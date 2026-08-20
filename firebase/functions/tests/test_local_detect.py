"""The local analyser must judge the way production judges.

It exists so the dashboard can be filled without a deploy, which makes it very
easy for it to quietly become a SECOND, weaker detector — and that already
happened once: it treated gemini.detect_frames_batch() as a verdict when
production uses it only as a screen, and reported screen results for 22 video
stories as if a full analysis had run.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "tools" / "stelz_brand_watch" / "_local_detect.py"


def load_module():
    spec = importlib.util.spec_from_file_location("_local_detect_under_test", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = load_module()


class TestReferenceOrder(unittest.TestCase):
    """Defect: the wordmark was never sent to the model.

    load_references sorted filenames alphabetically and cut at 8.
    `web_stelz_logo.png` sorts to position 9 of the 27 files in refs/, so the
    detector was asked to recognise a brand while being shown every packshot
    EXCEPT its logo. Production does not have this bug — lib/refs stratifies by
    product line — which is exactly why the local copy could drift unnoticed.
    """

    def test_the_logo_is_sent(self):
        names = [p.name for p in D.reference_files()]
        self.assertIn("web_stelz_logo.png", names,
                      "the wordmark must be among the references the model sees")

    def test_the_logo_is_first(self):
        self.assertEqual(D.reference_files()[0].name, "web_stelz_logo.png")

    def test_it_still_stops_at_the_cap(self):
        self.assertLessEqual(len(D.reference_files()), 8)
        self.assertLessEqual(len(D.reference_files(3)), 3)

    def test_unlisted_files_do_not_displace_the_priority_list(self):
        # A new file dropped into refs/ must not push the logo out again.
        head = [p.name for p in D.reference_files(4)]
        self.assertEqual(head, D.REF_PRIORITY[:4])


class TestVideoIsTwoStage(unittest.TestCase):
    """The screen decides who gets LOOKED at; it does not decide the verdict."""

    def setUp(self):
        self.frames = [(i, b"jpeg-%d" % i) for i in range(4)]
        self.stats = D.new_stats()

    def _run(self, screen_verdicts, full_result):
        with mock.patch.object(D, "_extract_frames", return_value=(self.frames, {})), \
             mock.patch.object(D.gemini, "detect_frames_batch", return_value=screen_verdicts) as batch, \
             mock.patch.object(D, "judge_image", side_effect=lambda *a, **k: dict(full_result)) as judge:
            out = D.judge_video(b"video", [b"ref"], self.stats, on_note=lambda _m: None)
        return out, batch, judge

    def test_a_flagged_frame_gets_a_full_look(self):
        # Frame 2 carries brand text, so the screen flags it and a real
        # detect_image call must follow. Taking the screen's own answer is the
        # bug this test exists for.
        screen = [{"detected": False} for _ in self.frames]
        screen[2] = {"detected": False, "visible_text": "STELZ"}
        out, batch, judge = self._run(screen, {"detected": True, "confidence": 0.9})
        self.assertEqual(batch.call_count, 1, "the batch is the screen: exactly one call")
        self.assertEqual(judge.call_count, 1, "only the flagged frame is analysed")
        self.assertTrue(any(r.get("detected") for r in out))
        self.assertEqual(self.stats["frames_flagged"], 1)
        self.assertEqual(self.stats["frames_analysed"], 1)

    def test_a_cleared_frame_costs_nothing_more(self):
        out, _batch, judge = self._run([{"detected": False} for _ in self.frames], {})
        self.assertEqual(judge.call_count, 0)
        self.assertEqual(len(out), 4, "every frame is still reported, as a miss")
        self.assertTrue(all(r["screened_out"] for r in out))

    def test_a_screen_failure_analyses_everything(self):
        # Same policy as handlers/detect_video: the screen can only ever save
        # work, never lose a frame.
        with mock.patch.object(D, "_extract_frames", return_value=(self.frames, {})), \
             mock.patch.object(D.gemini, "detect_frames_batch", side_effect=RuntimeError("boom")), \
             mock.patch.object(D, "judge_image", side_effect=lambda *a, **k: {"detected": False}) as judge:
            D.judge_video(b"video", [b"ref"], self.stats, on_note=lambda _m: None)
        self.assertEqual(judge.call_count, 4)

    def test_screen_flags_frame_is_imported_not_reimplemented(self):
        from handlers import detect_video
        self.assertIs(D.screen_flags_frame, detect_video.screen_flags_frame)


class TestNearMissSurvives(unittest.TestCase):
    """An overturned hit must reach the UI as its own state."""

    def test_raw_hit_plus_final_miss_is_a_near_miss(self):
        rec = D.verdict_record("id1", "anna", [
            {"detected": False, "raw_detected": True, "confidence": 0.8,
             "verify_reason": "No beverage container is visible.",
             "gate": "rejected_by_verifier", "source": "cover"},
        ])
        self.assertFalse(rec["detected"])
        self.assertTrue(rec["near_miss"])
        self.assertEqual(rec["near_miss_reason"], "No beverage container is visible.")

    def test_a_plain_miss_is_not_a_near_miss(self):
        rec = D.verdict_record("id1", "anna", [
            {"detected": False, "raw_detected": False, "confidence": 0.0, "source": "cover"},
        ])
        self.assertFalse(rec["near_miss"])
        self.assertIsNone(rec["near_miss_reason"])

    def test_a_confirmed_hit_is_never_a_near_miss(self):
        rec = D.verdict_record("id1", "anna", [
            {"detected": True, "raw_detected": True, "confidence": 0.95, "source": "cover"},
        ])
        self.assertTrue(rec["detected"])
        self.assertFalse(rec["near_miss"])

    def test_the_argued_frame_represents_the_video(self):
        # Eleven frames of grass and one the model called a hit. Picking by
        # confidence alone would show the grass and lose the disagreement.
        rec = D.verdict_record("v1", "anna", [
            {"detected": False, "raw_detected": False, "confidence": 0.4, "source": "frame0"},
            {"detected": False, "raw_detected": True, "confidence": 0.2,
             "visible_text": "STELZ", "source": "frame1"},
        ])
        self.assertTrue(rec["near_miss"])
        self.assertEqual(rec["judged_from"], "frame1")

    def test_it_counts_full_looks_separately_from_frames_seen(self):
        # "13 beelden bekeken" would overstate the work if 12 of them only ever
        # passed through the screen.
        rec = D.verdict_record("v1", "anna", [
            {"detected": False, "raw_detected": False, "source": "cover"},
            {"detected": False, "screened_out": True, "source": "frame0"},
            {"detected": False, "screened_out": True, "source": "frame1"},
        ])
        self.assertEqual(rec["frames_judged"], 3)
        self.assertEqual(rec["frames_analysed"], 1)


class TestGeminiClientIsBuiltOnce(unittest.TestCase):
    """Unsynchronised lazy init closed a client out from under a live request.

    Two threads both saw None, both constructed a Client, one assignment won,
    and the loser was garbage-collected — taking its httpx connection pool with
    it. Symptom: "Cannot send a request, as the client has been closed", which
    is what two of the first three parallel items reported.
    """

    def test_concurrent_callers_share_one_client(self):
        from lib import gemini

        made: list[object] = []
        barrier = threading.Barrier(8)

        def fake_client(**_kwargs):
            obj = object()
            made.append(obj)
            return obj

        with mock.patch.object(gemini, "_client", None), \
             mock.patch.object(gemini, "_key", return_value="k"), \
             mock.patch.object(gemini.genai, "Client", side_effect=fake_client):
            got: list[object] = []

            def worker():
                barrier.wait()          # maximise the overlap
                got.append(gemini.client())

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(len(made), 1, "the client must be constructed exactly once")
        self.assertEqual(len(set(id(c) for c in got)), 1, "every caller gets the same client")


if __name__ == "__main__":
    sys.exit(unittest.main())


class TestTheLocalVerifierLearnsFromRejections(unittest.TestCase):
    """Production feeds moderator-rejected images back into the verify prompt.

    The local analyser used to pass negative_exemplars=[] — so a false positive
    confirmed by eye was re-made on every subsequent run, forever. The measured
    case: a mirror selfie of a white slim can reading SAVRY, which the detector
    transcribed as "STËLZ HARD ICED TEA" in an Instagram post AND, separately,
    in a story of the same scene.
    """

    def test_the_manifest_is_committed_and_the_images_are_not(self):
        # Same rule as tools/eval/golden_sources.json: the manifest is the
        # artefact, the pixels are other people's photographs.
        self.assertTrue(D.NEGATIVES_MANIFEST.exists(), "negatives.json is missing")
        self.assertIn(".tmp", str(D.NEGATIVES_DIR))

    def test_every_entry_names_what_the_detector_hallucinated(self):
        import json
        data = json.loads(D.NEGATIVES_MANIFEST.read_text())
        self.assertTrue(data.get("rejected"), "manifest has no entries")
        for e in data["rejected"]:
            self.assertTrue(e.get("file"), e)
            self.assertTrue(e.get("hallucinatedText"), e)
            self.assertTrue(e.get("whyItIsNotStelz"), e)

    def test_exemplars_are_labelled_pairs_never_bare_bytes(self):
        # The legacy stack emitted these as unlabelled "Reference {i}:" parts and
        # taught the detector that twelve confirmed false positives WERE the
        # brand. The label has to travel with the image.
        for label, blob in D.load_negatives():
            self.assertIsInstance(label, str)
            self.assertIn("NOT STELZ", label)
            self.assertIsInstance(blob, (bytes, bytearray))

    def test_a_missing_image_degrades_to_no_exemplars_not_a_crash(self):
        with mock.patch.object(D, "NEGATIVES_DIR", Path("/nonexistent-negatives")):
            self.assertEqual(D.load_negatives(), [])

    def test_a_missing_manifest_degrades_too(self):
        with mock.patch.object(D, "NEGATIVES_MANIFEST", Path("/nonexistent.json")):
            self.assertEqual(D.load_negatives(), [])

    def test_the_verifier_is_actually_given_them(self):
        # A loader nothing calls is decoration. Assert the wiring, not just the
        # helper — this is the bug that existed for the whole first analysis run.
        src = Path(D.__file__).read_text()
        self.assertNotIn("negative_exemplars=[]", src,
                         "the local verifier is still running blind")
        self.assertIn("negative_exemplars=negatives", src)


class TestTheFirstPassSeesWhatProductionSees(unittest.TestCase):
    """gemini.detect_image does not resize. detect_image.run does, at the call
    site, to MAX_IMAGE_DIM=512 — and this module passed the archived bytes
    straight through, so the local first pass was reading images at up to
    4096px while the deployed function reads them at 512.

    Two consequences, both bad. Local hit counts would flatter what a deploy
    actually finds, and lib/verifier's premise — "this pass looks at 4x the
    pixel area of the first" — silently inverts when the first pass had eight
    times the pixels of the second.

    It also broke outright: one 3072x4096 progressive JPEG returned an empty
    object on every attempt at full size and parsed cleanly at 512.
    """

    def _tiny_jpeg(self, w: int, h: int) -> bytes:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (200, 30, 30)).save(buf, format="JPEG")
        return buf.getvalue()

    def test_a_large_image_is_downscaled_before_the_model_sees_it(self):
        from PIL import Image
        import io
        big = self._tiny_jpeg(3072, 4096)
        seen: dict = {}

        def fake_detect(**kw):
            seen["bytes"] = kw["image_bytes"]
            return {"detected": False, "context": "nothing here"}

        with mock.patch.object(D.gemini, "detect_image", side_effect=fake_detect):
            D.judge_image(big, [], D.new_stats())

        w, h = Image.open(io.BytesIO(seen["bytes"])).size
        self.assertLessEqual(max(w, h), 512, f"first pass got {w}x{h}")

    def test_the_verifier_still_gets_more_pixels_than_the_first_pass(self):
        # The ordering the second look depends on. If these ever cross, the
        # legibility-contradiction rule starts deleting true positives.
        from handlers.detect_image import MAX_IMAGE_DIM
        self.assertGreater(D.verifier.VERIFY_MAX_DIM, MAX_IMAGE_DIM)
