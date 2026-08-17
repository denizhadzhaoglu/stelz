"""Tests for video frame sampling in handlers/detect_video.py.

detect_video imports cv2/yt_dlp/firebase transitively, so we stub those before
import. The functions under test are pure arithmetic.

The bug being fixed: FRAME_SAMPLE_POINTS was a fixed [0.0, 0.2, 0.4, 0.6, 0.8,
1.0]. On a Reel or TikTok, frame 0.0 is almost always a title/hook card and 1.0
an outro or CTA — so two of six samples were routinely spent on frames that
cannot contain product-in-use footage. The legacy pipeline already sampled
10%-90% (57_video_frame_detect.py:120-122); the Firebase rewrite lost it.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _stub(name: str) -> types.ModuleType:
    """Install a stub module, and attach it to its parent package so both
    `import a.b` and `from a import b` resolve. setdefault alone is not enough:
    `google` is a real namespace package here, so `from google import genai`
    would still hit the real (genai-less) one."""
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if "." in name:
        parent_name, _, child = name.rpartition(".")
        parent = _stub(parent_name)
        setattr(parent, child, mod)
    return mod


for _name in (
    "cv2",
    "yt_dlp",
    "requests",
    "PIL",
    "PIL.Image",
    "firebase_admin",
    "firebase_admin.firestore",
    "firebase_admin.storage",
    "google.cloud",
    "google.cloud.firestore",
    "google.cloud.pubsub_v1",
    "google.genai",
    "google.genai.types",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
):
    _stub(_name)

_stub("firebase_admin").initialize_app = lambda *a, **k: None
_stub("firebase_admin").get_app = lambda *a, **k: None
_stub("firebase_admin").credentials = types.SimpleNamespace(ApplicationDefault=lambda: None)
_stub("google.cloud.firestore").SERVER_TIMESTAMP = object()
_stub("google.cloud.firestore").Increment = lambda *a, **k: None
_stub("google.cloud.firestore").ArrayUnion = lambda *a, **k: None
_stub("google.genai").Client = object

from handlers.detect_video import (  # noqa: E402
    adaptive_frame_budget,
    frame_sample_points,
    screen_flags_frame,
    _SAMPLE_LO,
    _SAMPLE_HI,
)
from lib import identity  # noqa: E402

_ACCEPT = ["stelz"] + identity.generate_variants("stelz")["strict"]


class TestAdaptiveFrameBudget(unittest.TestCase):
    def test_scales_with_duration(self):
        self.assertEqual(adaptive_frame_budget(5), 6)
        self.assertEqual(adaptive_frame_budget(20), 9)
        self.assertEqual(adaptive_frame_budget(45), 12)
        self.assertEqual(adaptive_frame_budget(180), 15)

    def test_is_monotonic_in_duration(self):
        # A longer clip must never be sampled less densely than a shorter one —
        # easy to break when the thresholds are hand-edited.
        budgets = [adaptive_frame_budget(d) for d in (1, 5, 10, 11, 30, 31, 60, 61, 600)]
        self.assertEqual(budgets, sorted(budgets))

    def test_unknown_duration_gets_a_middling_budget(self):
        # TikTok frequently omits duration, so this is a common path, not an
        # edge case — it should not get the smallest grid.
        self.assertEqual(adaptive_frame_budget(0), 8)
        self.assertEqual(adaptive_frame_budget(-1), 8)

    def test_long_videos_are_capped(self):
        # Don't let a 30-minute livestream replay run away with the budget.
        self.assertEqual(adaptive_frame_budget(10_000), 15)

    def test_budget_stays_within_what_the_degrade_ladder_can_trim(self):
        # usage.frame_budget_cap drops to 4 / 3 under budget pressure; a raised
        # ceiling must still be reducible, not a floor that ignores the ladder.
        self.assertGreater(adaptive_frame_budget(180), 4)


class TestFrameSamplePoints(unittest.TestCase):
    def test_never_samples_the_title_card_or_outro(self):
        for duration in (5, 20, 45, 180, 0):
            pts = frame_sample_points(duration)
            self.assertGreater(min(pts), 0.0, f"sampled frame 0 at {duration}s")
            self.assertLess(max(pts), 1.0, f"sampled the final frame at {duration}s")

    def test_stays_inside_the_safe_window(self):
        for duration in (5, 20, 45, 180):
            pts = frame_sample_points(duration)
            self.assertGreaterEqual(min(pts), _SAMPLE_LO)
            self.assertLessEqual(max(pts), _SAMPLE_HI)

    def test_count_matches_budget(self):
        # Derived, not hardcoded: the budgets are a tuning decision that has
        # already changed once, and duplicating the numbers here just makes a
        # tuning change look like a regression.
        for duration in (5, 20, 45, 180, 0):
            self.assertEqual(len(frame_sample_points(duration)), adaptive_frame_budget(duration))

    def test_explicit_budget_overrides_duration(self):
        # This is how the budget guard shrinks sampling under cost pressure.
        self.assertEqual(len(frame_sample_points(180, budget=3)), 3)
        self.assertEqual(len(frame_sample_points(5, budget=8)), 8)

    def test_points_are_strictly_increasing(self):
        pts = frame_sample_points(45)
        self.assertEqual(pts, sorted(pts))
        self.assertEqual(len(pts), len(set(pts)))

    def test_evenly_spaced(self):
        pts = frame_sample_points(20)
        gaps = [round(b - a, 4) for a, b in zip(pts, pts[1:])]
        self.assertEqual(len(set(gaps)), 1, f"uneven spacing: {gaps}")

    def test_degenerate_budgets(self):
        self.assertEqual(len(frame_sample_points(20, budget=1)), 1)
        self.assertEqual(len(frame_sample_points(20, budget=0)), 1)
        self.assertEqual(len(frame_sample_points(20, budget=-5)), 1)
        # A single sample should land mid-clip, not at an edge.
        self.assertAlmostEqual(frame_sample_points(20, budget=1)[0], 0.5, places=1)

    def test_improves_on_the_old_fixed_points(self):
        # The property under test is that no sample is wasted on the title card
        # or the outro, which is independent of how many samples there are.
        # (It originally also asserted equal count against the old fixed spread;
        # that stopped being the point once the budgets were raised deliberately.)
        old = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        new = frame_sample_points(20)
        wasted_old = sum(1 for p in old if p <= 0.0 or p >= 1.0)
        wasted_new = sum(1 for p in new if p <= 0.0 or p >= 1.0)
        self.assertEqual(wasted_old, 2, "sanity: the old spread wasted 2 of 6")
        self.assertEqual(wasted_new, 0)
        self.assertGreaterEqual(len(new), len(old))

class TestScreenFlagsFrame(unittest.TestCase):
    """The batched screen decides which frames get a real analysis.

    Its one unacceptable failure is dropping a frame the real gate would have
    accepted, because nothing looks at that frame again. Measured over the
    72-image golden set the rule below flags 21% of frames, keeps 12/12 known
    positives, and drops nothing the gate would have accepted.
    """

    def flag(self, **kw):
        return screen_flags_frame(kw, _ACCEPT)

    def test_flags_anything_the_model_detected(self):
        self.assertTrue(self.flag(detected=True, visible_text=None))

    def test_flags_a_readable_brand_the_model_did_not_act_on(self):
        self.assertTrue(self.flag(detected=False, visible_text="STELZ"))
        self.assertTrue(self.flag(detected=False, visible_text="STËLZ HARD SELTZER"))

    def test_flags_partial_wordmark_reads(self):
        # The tier that measuring had to revive; screening it out would
        # silently re-kill it.
        for t in ("ST??Z", "ST?LZ", "S?ELZ"):
            self.assertTrue(self.flag(detected=False, visible_text=t), t)

    def test_does_not_flag_competitor_labels(self):
        # The whole point: the model reads these perfectly and none can ever
        # survive the real gate, so paying for a second call on them is waste.
        for t in ("HEINEKEN LAGER BEER", "TRULY", "Red Bull ENERGY DRINK 250 ml",
                  "LONE RIVER RANCH WATER HARD SELTZER", "THERMOS", "MONSTER Rehab"):
            self.assertFalse(self.flag(detected=False, visible_text=t), t)

    def test_does_not_flag_empty_transcripts(self):
        for t in (None, "", "   "):
            self.assertFalse(self.flag(detected=False, visible_text=t))

    def test_does_not_flag_the_stelzlager_regression(self):
        self.assertFalse(self.flag(detected=False, visible_text="Stelzlager 20mm"))

    def test_surface_type_alone_is_not_enough(self):
        # A can with no readable text cannot pass the gate (prompt rule 1), so
        # flagging on shape would just re-pay for a guaranteed rejection.
        self.assertFalse(self.flag(detected=False, visible_text=None, surface_type="can"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
