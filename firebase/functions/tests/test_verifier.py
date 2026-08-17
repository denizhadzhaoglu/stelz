"""Tests for the second-look verifier.

The dangerous direction here is DELETION. This pass is the only thing in the
pipeline that can turn an accepted detection back into detected=False, and it
does so on the word of one model call. So most of these tests pin the cases
where it must NOT act: an unreadable label, a failed call, a garbled response,
an empty verdict. A verifier that treats "I can't tell" as "it isn't there"
quietly destroys the true positives this whole feature exists to rescue.

The Gemini call itself is not covered — it needs the network. decide(),
should_verify(), needs_crop(), crop_to_box() and parse_verdict() are pure.
"""
from __future__ import annotations

import io
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stub(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if "." in name:
        parent, _, child = name.rpartition(".")
        setattr(_stub(parent), child, mod)
    return mod


for _n in (
    "firebase_admin", "firebase_admin.firestore", "firebase_admin.storage",
    "google.cloud", "google.cloud.firestore", "google.cloud.pubsub_v1",
):
    _stub(_n)
_stub("firebase_admin").initialize_app = lambda *a, **k: None
_stub("firebase_admin").get_app = lambda *a, **k: None
_stub("firebase_admin").credentials = types.SimpleNamespace(ApplicationDefault=lambda: None)
_stub("google.cloud.firestore").SERVER_TIMESTAMP = object()

from lib import verifier  # noqa: E402
from PIL import Image  # noqa: E402


def _img(w: int = 800, h: int = 1000) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (120, 140, 160)).save(out, format="JPEG")
    return out.getvalue()


class TestShouldVerify(unittest.TestCase):
    def test_capped_small_object_is_verified(self):
        # The whole point: this is the ~1-in-3-wrong band.
        self.assertTrue(verifier.should_verify(
            {"detected": True, "confidence": 0.70, "gate": "capped_small_object"}))

    def test_partial_wordmark_is_verified(self):
        self.assertTrue(verifier.should_verify(
            {"detected": True, "confidence": 0.75, "gate": "accepted_partial_wordmark"}))

    def test_clean_high_confidence_hit_is_not_verified(self):
        # Measured 8/8 correct on the golden set. Verifying it is pure cost.
        self.assertFalse(verifier.should_verify(
            {"detected": True, "confidence": 0.95, "gate": None}))

    def test_non_detection_is_not_verified(self):
        # This pass removes false positives and rescues capped true ones; it does
        # not re-open everything the gate rejected.
        self.assertFalse(verifier.should_verify(
            {"detected": False, "confidence": 0.0, "gate": "rejected_no_brand_text"}))

    def test_low_confidence_hit_without_a_gate_label_is_verified(self):
        self.assertTrue(verifier.should_verify({"detected": True, "confidence": 0.80}))

    def test_missing_confidence_is_treated_as_low(self):
        self.assertTrue(verifier.should_verify({"detected": True}))


class TestDecide(unittest.TestCase):
    BASE = {"detected": True, "confidence": 0.70, "gate": "capped_small_object"}

    def test_confident_brand_read_upgrades_and_raises_confidence(self):
        out = verifier.decide(self.BASE, {"brand": "STELZ", "confidence": 0.95})
        self.assertEqual(out["verify_verdict"], "upgraded")
        self.assertGreaterEqual(out["confidence"], 0.90)
        self.assertTrue(out["detected"])

    def test_upgrade_lifts_it_out_of_the_review_band(self):
        # >=0.85 is what the frontend uses to separate the clean tier from
        # "Worth a check" (web/src/lib/quality.ts).
        out = verifier.decide(self.BASE, {"brand": "STELZ", "confidence": 0.95})
        self.assertGreaterEqual(out["confidence"], 0.85)

    def test_hesitant_brand_read_confirms_without_promoting(self):
        out = verifier.decide(self.BASE, {"brand": "STELZ", "confidence": 0.6})
        self.assertEqual(out["verify_verdict"], "confirmed")
        self.assertEqual(out["confidence"], 0.70)
        self.assertTrue(out["detected"])

    def test_a_rival_brand_rejects(self):
        out = verifier.decide(self.BASE, {"brand": "White Claw", "confidence": 0.9})
        self.assertFalse(out["detected"])
        self.assertEqual(out["verify_verdict"], "rejected")
        self.assertEqual(out["gate"], "rejected_by_verifier")

    def test_every_named_rival_rejects(self):
        for b in ("Truly", "Bavaria", "Heineken", "Red Bull", "Coca-Cola", "other_brand"):
            out = verifier.decide(self.BASE, {"brand": b, "confidence": 0.9})
            self.assertFalse(out["detected"], f"{b} should reject")

    def test_not_a_container_rejects(self):
        # The microphone / thermos / deodorant class.
        out = verifier.decide(self.BASE, {"brand": "not_a_container", "confidence": 0.9})
        self.assertFalse(out["detected"])

    def test_unreadable_label_does_NOT_reject_when_the_passes_agree(self):
        # The most important test in this file. "I can't read it" is not
        # evidence of absence — the first pass may have had a better crop — so
        # long as the first pass also admitted it could not read the label.
        for legibility in ("partial", "unreadable", None):
            out = verifier.decide(
                {**self.BASE, "text_legibility": legibility},
                {"brand": "no_readable_brand", "confidence": 0.9},
            )
            self.assertTrue(out["detected"], legibility)
            self.assertEqual(out["verify_verdict"], "inconclusive", legibility)

    def test_unreadable_label_DOES_reject_a_claimed_clear_read(self):
        # The legibility contradiction: the first pass said it read the label
        # clearly, 4x the pixels found nothing readable. Added resolution cannot
        # make text harder to read, so the first read was fabricated. This is the
        # golden-set case (fewshot_neg_00) that fooled both the original model
        # and the legacy Pro verify chain.
        out = verifier.decide(
            {**self.BASE, "text_legibility": "clear"},
            {"brand": "no_readable_brand", "confidence": 0.9},
        )
        self.assertFalse(out["detected"])
        self.assertEqual(out["gate"], "rejected_legibility_contradiction")

    def test_a_FAILED_call_never_rejects_even_on_a_clear_read(self):
        # An empty verdict means the call failed. That is not evidence of
        # anything, and must not be confused with an explicit "I looked and
        # could not read a brand".
        out = verifier.decide({**self.BASE, "text_legibility": "clear"}, {})
        self.assertTrue(out["detected"])
        self.assertEqual(out["verify_verdict"], "inconclusive")

    def test_empty_verdict_does_NOT_reject(self):
        out = verifier.decide(self.BASE, {})
        self.assertTrue(out["detected"])
        self.assertEqual(out["verify_verdict"], "inconclusive")

    def test_garbled_brand_value_does_NOT_silently_pass_as_stelz(self):
        out = verifier.decide(self.BASE, {"brand": "STELZZZ ish?", "confidence": 0.9})
        self.assertFalse(out["detected"])

    def test_case_insensitive_brand_match(self):
        for spelling in ("stelz", "STELZ", "Stelz"):
            out = verifier.decide(self.BASE, {"brand": spelling, "confidence": 0.95})
            self.assertTrue(out["detected"], spelling)

    def test_version_is_always_stamped(self):
        # Without it a stale verdict cannot be told from a fresh one, and lazy
        # re-verification has nothing to key on.
        for v in ({"brand": "STELZ", "confidence": 0.9}, {"brand": "Truly"}, {}):
            self.assertEqual(verifier.decide(self.BASE, v)["verify_version"], verifier.VERIFY_VERSION)

    def test_does_not_mutate_the_input(self):
        base = dict(self.BASE)
        verifier.decide(base, {"brand": "Truly", "confidence": 0.9})
        self.assertEqual(base, self.BASE)

    def test_reason_is_truncated(self):
        out = verifier.decide(self.BASE, {"brand": "STELZ", "confidence": 0.9, "reason": "x" * 900})
        self.assertLessEqual(len(out["verify_reason"]), 300)


class TestNeedsCrop(unittest.TestCase):
    def test_small_box_needs_a_crop(self):
        # 10% x 10% = 1% of frame — invisible even at 1024px.
        self.assertTrue(verifier.needs_crop([400, 400, 500, 500]))

    def test_large_box_does_not(self):
        self.assertFalse(verifier.needs_crop([0, 0, 900, 900]))

    def test_missing_or_malformed_box(self):
        self.assertFalse(verifier.needs_crop(None))
        self.assertFalse(verifier.needs_crop([]))
        self.assertFalse(verifier.needs_crop([1, 2, 3]))

    def test_degenerate_box_is_not_a_crop_candidate(self):
        self.assertFalse(verifier.needs_crop([500, 500, 500, 500]))


class TestCropToBox(unittest.TestCase):
    def test_crop_returns_a_smaller_image(self):
        src = _img(800, 1000)
        out = verifier.crop_to_box(src, [400, 400, 500, 500])
        self.assertIsNotNone(out)
        self.assertLess(Image.open(io.BytesIO(out)).size[0], 800)

    def test_padding_widens_the_box(self):
        # Context matters: a pixel-tight crop of a wordmark loses the can shape
        # and cap that separate a Stelz can from a rival's.
        out = verifier.crop_to_box(_img(1000, 1000), [400, 400, 500, 500], padding=0.5)
        self.assertGreater(Image.open(io.BytesIO(out)).size[0], 100)

    def test_box_at_the_frame_edge_is_clamped_not_crashed(self):
        self.assertIsNotNone(verifier.crop_to_box(_img(), [0, 0, 100, 100]))
        self.assertIsNotNone(verifier.crop_to_box(_img(), [900, 900, 1000, 1000]))

    def test_inverted_box_returns_none(self):
        # None means "no crop available" — callers must not fall back to the full
        # frame, or the second call is the first call again at extra cost.
        self.assertIsNone(verifier.crop_to_box(_img(), [500, 500, 100, 100]))

    def test_non_numeric_box_returns_none(self):
        self.assertIsNone(verifier.crop_to_box(_img(), ["a", "b", "c", "d"]))

    def test_corrupt_image_returns_none(self):
        self.assertIsNone(verifier.crop_to_box(b"not an image", [10, 10, 900, 900]))


class TestParseVerdict(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(verifier.parse_verdict('{"brand": "STELZ"}')["brand"], "STELZ")

    def test_markdown_fenced_json(self):
        self.assertEqual(
            verifier.parse_verdict('```json\n{"brand": "Truly"}\n```')["brand"], "Truly")

    def test_garbage_returns_empty_dict_not_an_exception(self):
        # Feeds decide(), which treats {} as inconclusive — never as a rejection.
        self.assertEqual(verifier.parse_verdict("sorry, I cannot help"), {})
        self.assertEqual(verifier.parse_verdict(""), {})

    def test_json_array_is_not_accepted_as_a_verdict(self):
        self.assertEqual(verifier.parse_verdict('[{"brand": "STELZ"}]'), {})


class TestPrompt(unittest.TestCase):
    def test_prompt_never_reveals_the_expected_answer(self):
        # The legacy verifier opened with "A previous less-precise model claimed
        # to detect STËLZ ... verify or reject that detection", and confidently
        # confirmed a hallucination. Nothing here may hint at a prior verdict.
        p = verifier.build_prompt("STELZ").lower()
        for leak in ("previous", "already", "claimed", "verify or reject", "confirm the detection"):
            self.assertNotIn(leak, p, f"prompt leaks the expected answer: {leak!r}")

    def test_prompt_offers_rivals_as_real_choices(self):
        p = verifier.build_prompt("STELZ")
        for rival in ("White Claw", "Truly", "Heineken"):
            self.assertIn(rival, p)

    def test_prompt_offers_an_i_cannot_tell_option(self):
        self.assertIn("no_readable_brand", verifier.build_prompt("STELZ"))

    def test_every_choice_is_rendered(self):
        p = verifier.build_prompt("STELZ")
        for c in verifier.BRAND_CHOICES:
            self.assertIn(c, p)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestNegativeExemplars(unittest.TestCase):
    """The legacy pipeline fed twelve moderator-REJECTED images to the detector
    as unlabelled POSITIVE references (18_daily_scan.py:139 and two others).
    These tests make that specific mistake impossible to repeat here."""

    def _rows(self, n=3, high=False):
        return [{"imageBytes": _img(), "visibleText": f"STELZ {i}", "highSignal": high}
                for i in range(n)]

    def test_every_exemplar_carries_a_label(self):
        # The load-bearing assertion. There is no API that returns bare bytes.
        for label, blob in verifier.build_negative_exemplars(self._rows()):
            self.assertTrue(label and isinstance(label, str))
            self.assertTrue(blob)

    def test_the_label_says_NEGATIVE_and_names_the_brand(self):
        label, _ = verifier.build_negative_exemplars(self._rows(1))[0]
        self.assertIn("NEGATIVE", label)
        self.assertIn("STELZ", label)
        self.assertIn("NOT", label)

    def test_the_label_never_reads_as_a_positive_reference(self):
        label, _ = verifier.build_negative_exemplars(self._rows(1))[0]
        for phrase in ("Reference", "what to look for", "the brand product"):
            self.assertNotIn(phrase, label)

    def test_the_hallucinated_text_is_quoted_back(self):
        rows = [{"imageBytes": _img(), "visibleText": "STËLZ HARD SELTZER"}]
        label, _ = verifier.build_negative_exemplars(rows)[0]
        self.assertIn("STËLZ HARD SELTZER", label)

    def test_high_signal_rejections_come_first(self):
        # A rejection of something the model was confident about teaches more
        # than a rejection of something it already doubted.
        rows = [
            {"imageBytes": _img(), "visibleText": "low", "highSignal": False},
            {"imageBytes": _img(), "visibleText": "HIGH", "highSignal": True},
        ]
        self.assertIn("HIGH", verifier.build_negative_exemplars(rows, limit=1)[0][0])

    def test_respects_the_limit(self):
        self.assertEqual(len(verifier.build_negative_exemplars(self._rows(10), limit=2)), 2)

    def test_rows_without_bytes_are_skipped_not_crashed(self):
        rows = [{"visibleText": "no image"}, {"imageBytes": _img()}]
        self.assertEqual(len(verifier.build_negative_exemplars(rows)), 1)

    def test_empty_input(self):
        self.assertEqual(verifier.build_negative_exemplars([]), [])

    def test_missing_visible_text_still_produces_a_usable_label(self):
        rows = [{"imageBytes": _img()}]
        label, _ = verifier.build_negative_exemplars(rows)[0]
        self.assertIn("NEGATIVE", label)
        self.assertNotIn('wrongly read ""', label)
