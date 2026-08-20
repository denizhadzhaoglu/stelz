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

    def test_not_a_container_rejects_when_the_brand_is_nowhere(self):
        # The microphone / thermos / deodorant class: no container, and the
        # wordmark is not on anything else either.
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


class TestNeedsReverify(unittest.TestCase):
    """Cache hits short-circuit detection, so before this the verifier only ever
    touched images the pipeline had never seen. The whole existing catalogue —
    which is what the operator looks at — kept its pre-verifier verdicts."""

    DEMOTED = {"detected": True, "confidence": 0.70, "gate": "capped_small_object"}

    def test_old_cached_hit_with_no_verdict_is_reverified(self):
        self.assertTrue(verifier.needs_reverify(self.DEMOTED))

    def test_already_verified_at_current_version_is_left_alone(self):
        # The guard against re-billing the same image on every scan.
        r = {**self.DEMOTED, "verify_version": verifier.VERIFY_VERSION,
             "verify_verdict": "confirmed"}
        self.assertFalse(verifier.needs_reverify(r))

    def test_stale_version_is_reverified(self):
        r = {**self.DEMOTED, "verify_version": verifier.VERIFY_VERSION - 1}
        self.assertTrue(verifier.needs_reverify(r))

    def test_inconclusive_is_not_retried_forever(self):
        # "I could not tell" is an answer. Retrying it every scan would bill
        # repeatedly for the same non-result.
        r = {**self.DEMOTED, "verify_version": verifier.VERIFY_VERSION,
             "verify_verdict": "inconclusive"}
        self.assertFalse(verifier.needs_reverify(r))

    def test_clean_high_confidence_cached_hit_is_never_reverified(self):
        # Not in the population the verifier exists for, so re-verifying the
        # whole cached catalogue would be pure cost.
        self.assertFalse(verifier.needs_reverify(
            {"detected": True, "confidence": 0.95, "gate": None}))

    def test_cached_non_detection_is_never_reverified(self):
        self.assertFalse(verifier.needs_reverify(
            {"detected": False, "confidence": 0.0, "gate": "rejected_no_brand_text"}))

    def test_a_verdict_carried_without_a_version_still_reverifies(self):
        # Defensive: a verdict with no version cannot be placed against the
        # current rules, so treat it as unverified rather than trusting it.
        r = {**self.DEMOTED, "verify_verdict": "confirmed"}
        self.assertTrue(verifier.needs_reverify(r))

    def test_garbage_version_does_not_crash(self):
        for bad in (None, "", "v1", [], {}):
            r = {**self.DEMOTED, "verify_version": bad}
            try:
                verifier.needs_reverify(r)
            except (TypeError, ValueError):
                self.fail(f"crashed on verify_version={bad!r}")


class TestBrandAwayFromTheContainer(unittest.TestCase):
    """A drinks brand at a festival is not only on cans.

    This class exists because of a measured failure, not a hypothetical. On the
    Lowlands archive 22 of 41 verifier rejections came back "not_a_container",
    and the first three checked by eye were: a STELZ-branded swim ring on a
    yacht, a STELZ festival bar with the wordmark across the front and cans on
    the shelf, and a man raising a can to his mouth. All three were deleted from
    the client's results while the client could see them with their own eyes.

    The cause was structural. Steps 1-3 of VERIFY_PROMPT ask which brand is on
    the CONTAINER, so a placement that is not a container has no honest answer
    except "not_a_container" — and that fell through into the rejection branch.
    """
    BASE = {"detected": True, "confidence": 0.70, "gate": "capped_small_object"}

    def test_the_swim_ring_survives(self):
        # No beverage container in frame at all; the wordmark is on an inflatable.
        out = verifier.decide(self.BASE, {
            "brand": "not_a_container",
            "brand_elsewhere": "merchandise",
            "visible_text": "STELZ HARD LEMONADE",
            "confidence": 0.9,
        })
        self.assertTrue(out["detected"])
        self.assertEqual(out["verify_verdict"], "confirmed")
        self.assertEqual(out["gate"], "verified_off_container")
        self.assertEqual(out["verify_placement"], "merchandise")

    def test_the_festival_bar_survives(self):
        out = verifier.decide(self.BASE, {
            "brand": "not_a_container",
            "brand_elsewhere": "signage",
            "visible_text": "STELZ HARD DRINKS 4.5% ALC.",
            "confidence": 0.85,
        })
        self.assertTrue(out["detected"])
        self.assertEqual(out["verify_placement"], "signage")

    def test_our_branding_next_to_a_rivals_can_still_counts(self):
        # A Heineken can in someone's hand in front of a STELZ bar is a STELZ
        # placement. Reading the rival correctly must not delete ours.
        out = verifier.decide(self.BASE, {
            "brand": "Heineken",
            "brand_elsewhere": "signage",
            "visible_text": "STELZ",
            "confidence": 0.9,
        })
        self.assertTrue(out["detected"])
        self.assertEqual(out["verify_placement"], "signage")

    def test_a_placement_with_nothing_read_is_not_evidence(self):
        # "There is orange merchandise" is not "I read the wordmark". Without a
        # transcript this claim is exactly the hallucination the module exists
        # to catch, so it must not rescue anything.
        out = verifier.decide(self.BASE, {
            "brand": "not_a_container",
            "brand_elsewhere": "merchandise",
            "visible_text": None,
            "confidence": 0.9,
        })
        self.assertFalse(out["detected"])
        self.assertEqual(out["verify_verdict"], "rejected")

    def test_a_clean_can_read_still_upgrades(self):
        # The container branch stays ahead of this one: reading the wordmark on
        # the can itself is the stronger evidence and must keep its promotion.
        out = verifier.decide(self.BASE, {
            "brand": "STELZ", "brand_elsewhere": "signage",
            "visible_text": "STELZ HARD LEMONADE", "confidence": 0.95,
        })
        self.assertEqual(out["verify_verdict"], "upgraded")
        self.assertGreaterEqual(out["confidence"], 0.90)

    def test_the_prompt_actually_asks_for_it(self):
        # The decision rule is unreachable unless the prompt requests the field.
        p = verifier.build_prompt("STELZ")
        self.assertIn("brand_elsewhere", p)
        for placement in verifier.PLACEMENTS:
            self.assertIn(placement, p, placement)

    def test_placement_normalizes_junk_without_discarding_the_claim(self):
        self.assertEqual(verifier.placement_of({"brand_elsewhere": "a parasol"}), "other")
        self.assertEqual(verifier.placement_of({"brand_elsewhere": "SIGNAGE"}), "signage")
        for empty in (None, "", "null", "none", 0, [], {"x": 1}):
            self.assertIsNone(verifier.placement_of({"brand_elsewhere": empty}), repr(empty))

    def test_verdicts_are_versioned_apart_from_v1(self):
        # v1 rejected every one of the cases above. A stored v1 verdict is not
        # comparable to a v2 one, and needs_reverify is what re-opens them.
        self.assertGreaterEqual(verifier.VERIFY_VERSION, 2)
        self.assertTrue(verifier.needs_reverify(
            {"detected": True, "confidence": 0.70, "verify_version": 1}))


class TestCropCannotVetoTheFullFrame(unittest.TestCase):
    """The crop is taken from a box the model chose for itself.

    When that box is wrong the second call is looking at sky, and its "no
    container here" is a statement about the crop rather than about the photo.
    Production guarded against `no_readable_brand` and not against
    `not_a_container`; the local analyser had no guard at all and overwrote the
    full-frame verdict unconditionally.
    """
    def test_a_resolved_brand_supersedes(self):
        self.assertTrue(verifier.crop_supersedes({"brand": "STELZ"}))
        self.assertTrue(verifier.crop_supersedes({"brand": "White Claw"}))

    def test_an_empty_crop_does_not(self):
        for brand in (None, "", "no_readable_brand", "not_a_container"):
            self.assertFalse(verifier.crop_supersedes({"brand": brand}), repr(brand))

    def test_a_crop_that_found_the_brand_off_container_does(self):
        self.assertTrue(verifier.crop_supersedes(
            {"brand": "not_a_container", "brand_elsewhere": "signage"}))

    def test_both_call_sites_use_the_shared_guard(self):
        # Two copies of this rule drifted apart once already — production had
        # half of it and the local analyser had none. Assert they share one.
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[3]
        for rel in ("firebase/functions/handlers/detect_image.py",
                    "tools/stelz_brand_watch/_local_detect.py"):
            src = (root / rel).read_text()
            self.assertIn("crop_supersedes", src, rel)


class TestTheOneReopenedRejection(unittest.TestCase):
    """detect_image's fine-print rule deletes rows before the verifier runs.

    Measured case: booijagency's TikTok cover — the brand's OWN agency — showing
    a two-metre inflatable STELZ Hard Lemonade can across a yacht deck with
    "NATURAL FLAVOURING 63 CALORIES 250 ml e ALC. 4.5% VOL" printed a hand's
    width tall, four people each holding a can, and STELZ towels. size_in_frame
    said "medium", legibility said not clear, fine_print counted three, and the
    row was hard-rejected without a second look.

    The gate's premise is about APPARENT size and it is right about cans. It is
    wrong about the objects a drinks brand deploys at an event. So the rejection
    stands but stops being final.
    """
    REJECTED = {
        "detected": False, "confidence": 0.75,
        "gate": "rejected_fabricated_fine_print", "false_positive_risk": "high",
    }

    def test_the_fine_print_rejection_gets_a_second_look(self):
        self.assertTrue(verifier.should_verify(self.REJECTED))

    def test_no_other_rejection_is_re_opened(self):
        for gate in ("rejected_no_brand_text", "rejected_by_verifier",
                     "rejected_legibility_contradiction", None):
            self.assertFalse(
                verifier.should_verify({**self.REJECTED, "gate": gate}), repr(gate))

    def test_a_confident_read_restores_it(self):
        out = verifier.decide(self.REJECTED, {"brand": "STELZ", "confidence": 0.95})
        self.assertTrue(out["detected"])
        self.assertEqual(out["gate"], "verified_upgraded")

    def test_the_inflatable_read_off_container_restores_it(self):
        out = verifier.decide(self.REJECTED, {
            "brand": "not_a_container", "brand_elsewhere": "merchandise",
            "visible_text": "STELZ HARD LEMONADE ORANGE", "confidence": 0.9,
        })
        self.assertTrue(out["detected"])
        self.assertEqual(out["gate"], "verified_off_container")

    def test_a_hesitant_read_does_NOT_restore_it(self):
        # Re-opening a rejection must require positive evidence. "Probably
        # STELZ" is what the gate already disbelieved.
        out = verifier.decide(self.REJECTED, {"brand": "STELZ", "confidence": 0.6})
        self.assertFalse(out["detected"])
        self.assertEqual(out["verify_verdict"], "inconclusive")

    def test_silence_does_NOT_restore_it(self):
        for verdict in ({}, {"brand": "no_readable_brand", "confidence": 0.9},
                        {"brand": "not_a_container", "confidence": 0.9},
                        {"brand": "White Claw", "confidence": 0.9}):
            out = verifier.decide(self.REJECTED, verdict)
            self.assertFalse(out["detected"], repr(verdict))

    def test_a_demoted_hit_is_unaffected_by_the_re_open_rule(self):
        # The ordinary population still behaves exactly as before: a hesitant
        # STELZ read on a live detection confirms rather than going inconclusive.
        live = {"detected": True, "confidence": 0.70, "gate": "capped_small_object"}
        out = verifier.decide(live, {"brand": "STELZ", "confidence": 0.6})
        self.assertEqual(out["verify_verdict"], "confirmed")
        self.assertTrue(out["detected"])

    def test_a_placement_cannot_resurrect_an_unrelated_rejection(self):
        # decide() is public. A caller that skipped should_verify must not be
        # able to turn "rejected: the wordmark is not there" into a hit by way
        # of the off-container branch.
        out = verifier.decide(
            {"detected": False, "confidence": 0.0, "gate": "rejected_no_brand_text"},
            {"brand": "not_a_container", "brand_elsewhere": "signage",
             "visible_text": "STELZ", "confidence": 0.9},
        )
        self.assertFalse(out["detected"])
