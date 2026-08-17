"""Unit tests for lib/identity.py — runs offline, no Firestore, no API keys.

    cd firebase/functions && python3 -m unittest discover -s tests -v

The tests that matter most are TestStelzlagerRegression. That German word
("terrace pedestal") matched a naive substring check and scored instant 95%
confidence, which is why OCR was ripped out of the detection pipeline entirely
(see the comment at handlers/detect_image.py:238-241). Any future loosening of
brand matching has to keep these green.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import identity  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_strips_diacritics_and_lowercases(self):
        self.assertEqual(identity.normalize("STËLZ"), "stelz")
        self.assertEqual(identity.normalize("Stélz"), "stelz")
        self.assertEqual(identity.normalize("stèlz"), "stelz")

    def test_handles_empty(self):
        self.assertEqual(identity.normalize(""), "")
        self.assertEqual(identity.normalize(None), "")


class TestDamerauLevenshtein(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(identity.damerau_levenshtein("stelz", "stelz"), 0)

    def test_transposition_is_one(self):
        # A plain Levenshtein would score this 2.
        self.assertEqual(identity.damerau_levenshtein("setlz", "stelz"), 1)

    def test_substitution_and_insertion(self):
        self.assertEqual(identity.damerau_levenshtein("stelx", "stelz"), 1)
        self.assertEqual(identity.damerau_levenshtein("stelzz", "stelz"), 1)


class TestGenerateVariants(unittest.TestCase):
    def setUp(self):
        self.v = identity.generate_variants("stelz")

    def test_produces_the_typos_the_client_asked_for(self):
        both = set(self.v["strict"]) | set(self.v["loose"])
        for expected in ("stelzz", "stellz", "steelz", "sstelz"):
            self.assertIn(expected, both, f"missing typo variant {expected}")

    def test_accents_are_handled_by_normalization_not_generation(self):
        # Accented spellings are NOT generated as variants — normalize() strips
        # diacritics on both sides, so the canonical entry already matches them.
        # What matters is that the accented text matches, not that it is listed.
        both = set(self.v["strict"]) | set(self.v["loose"])
        self.assertNotIn("stélz", both)
        for text in ("STËLZ", "Stélz", "stèlz"):
            ok, _ = identity.has_brand_word(text, ["stelz"])
            self.assertTrue(ok, f"accented form {text} should match canonical")

    def test_canonical_itself_is_not_a_variant(self):
        self.assertNotIn("stelz", self.v["strict"])
        self.assertNotIn("stelz", self.v["loose"])

    def test_strict_and_loose_are_disjoint(self):
        self.assertEqual(set(self.v["strict"]) & set(self.v["loose"]), set())

    def test_denylisted_words_never_appear(self):
        both = set(self.v["strict"]) | set(self.v["loose"])
        for banned in ("stelt", "stel", "steel", "stelen"):
            self.assertNotIn(banned, both, f"denylisted word {banned} leaked in")

    def test_respects_min_length(self):
        both = set(self.v["strict"]) | set(self.v["loose"])
        self.assertTrue(all(len(x) >= 4 for x in both))

    def test_deterministic(self):
        self.assertEqual(identity.generate_variants("stelz"), self.v)

    def test_works_for_another_brand(self):
        # Brand-agnostic: a second tenant must work with no code change.
        v = identity.generate_variants("kever")
        both = set(v["strict"]) | set(v["loose"])
        self.assertIn("keverr", both)
        self.assertNotIn("kever", both)


class TestStelzlagerRegression(unittest.TestCase):
    """The false positive that removed OCR from the pipeline. Must stay dead."""

    def setUp(self):
        v = identity.generate_variants("stelz")
        self.variants = ["stelz"] + v["strict"]

    def test_stelzlager_does_not_match(self):
        ok, m = identity.has_brand_word("Stelzlager 20mm", self.variants)
        self.assertFalse(ok, f"Stelzlager matched as {m!r} — the 2026 bug is back")

    def test_stelzlagern_does_not_match(self):
        ok, _ = identity.has_brand_word("Wir bauen Stelzlagern", self.variants)
        self.assertFalse(ok)

    def test_other_german_neighbours_do_not_match(self):
        for word in ("Stelzen", "Stelzenläufer", "Stelzvogel"):
            ok, m = identity.has_brand_word(word, self.variants)
            self.assertFalse(ok, f"{word} matched as {m!r}")

    def test_real_brand_still_matches(self):
        # The guard must not be so tight that it kills true positives.
        for text in ("drinking a STELZ", "STËLZ hard seltzer", "love stelz!"):
            ok, _ = identity.has_brand_word(text, self.variants)
            self.assertTrue(ok, f"failed to match genuine mention: {text}")

    def test_punctuation_boundaries_still_match(self):
        for text in ("stelz.", "(stelz)", "#stelz ", "stelz,"):
            ok, _ = identity.has_brand_word(text, self.variants)
            self.assertTrue(ok, f"failed on {text!r}")


class TestStrictLooseSeparation(unittest.TestCase):
    """The safety contract that makes aggressive typo expansion viable.

    Detection accepts on canonical + STRICT variants only. LOOSE variants exist
    to find candidate content via hashtag search and must never, on their own,
    turn an image into a confirmed detection — otherwise every 'stels' or
    'setlz' the model hallucinates off a blurry can becomes a false positive in
    the client's feed.

    Mirrors detect_image._accept_variants().
    """

    def setUp(self):
        self.v = identity.generate_variants("stelz")
        self.accept = ["stelz"] + self.v["strict"]

    def test_strict_variants_are_accepted(self):
        for s in self.v["strict"]:
            ok, _ = identity.has_brand_word(f"can reads {s}", self.accept)
            self.assertTrue(ok, f"strict variant {s} should accept")

    def test_loose_variants_are_not_accepted(self):
        for s in self.v["loose"]:
            ok, m = identity.has_brand_word(f"can reads {s}", self.accept)
            self.assertFalse(
                ok, f"loose variant {s} must NOT accept a detection (matched {m!r})"
            )

    def test_loose_list_is_non_empty(self):
        # Guards against the test above passing vacuously.
        self.assertGreater(len(self.v["loose"]), 5)


class TestPartialWordmarkMatch(unittest.TestCase):
    """DETECT_PROMPT_V8 asks the model for partial reads like 'ST??Z'; the
    exact-match gate then rejected all of them, so that tier was dead. These
    lock in the wildcard alignment that revives it.

    Measured on the golden set: this converts fewshot_pos_07 from a miss into a
    hit, taking recall from 0.917 to 1.000.
    """

    def setUp(self):
        self.variants = ["stelz"] + identity.generate_variants("stelz")["strict"]

    def test_accepts_genuine_partial_reads(self):
        for t in ("ST??Z", "ST?LZ", "S?ELZ", "STEL?"):
            ok, var, _ = identity.partial_wordmark_match(t, self.variants)
            self.assertTrue(ok, f"{t} should align to a variant")
            self.assertEqual(var, "stelz")

    def test_rejects_conflicting_characters(self):
        # A resolved character that disagrees kills the match — 'O' is not 'E'.
        for t in ("STOLZ", "ST?LX", "AT??Z"):
            ok, _, _ = identity.partial_wordmark_match(t, self.variants)
            self.assertFalse(ok, f"{t} has a conflicting character and must not match")

    def test_rejects_too_few_resolved_characters(self):
        # "?????" would otherwise match literally any 5-letter brand.
        ok, _, _ = identity.partial_wordmark_match("?????", self.variants)
        self.assertFalse(ok)
        ok, _, _ = identity.partial_wordmark_match("S???Z", self.variants, min_resolved=3)
        self.assertFalse(ok, "only 2 resolved chars should fail min_resolved=3")

    def test_length_must_match(self):
        # This is what keeps the Stelzlager family out of the partial path too.
        for t in ("ST??ZLAGER", "ST?", "ST??ZZZZ"):
            ok, _, _ = identity.partial_wordmark_match(t, self.variants)
            self.assertFalse(ok, f"{t} is the wrong length and must not match")

    def test_exact_reads_are_not_handled_here(self):
        # has_brand_word owns exact matching; this path is wildcards only.
        ok, _, _ = identity.partial_wordmark_match("STELZ", self.variants)
        self.assertFalse(ok)

    def test_reports_resolved_count(self):
        _, _, n = identity.partial_wordmark_match("ST??Z", self.variants)
        self.assertEqual(n, 3)
        _, _, n = identity.partial_wordmark_match("ST?LZ", self.variants)
        self.assertEqual(n, 4)

    def test_finds_partial_inside_a_longer_transcript(self):
        ok, var, _ = identity.partial_wordmark_match(
            "holding a ST??Z can at the festival", self.variants
        )
        self.assertTrue(ok)
        self.assertEqual(var, "stelz")


    def test_tie_break_is_deterministic_and_prefers_canonical(self):
        """"ST??Z" aligns equally well to `stelz` and to the leet variant
        `st3lz` — 3 resolved characters each. This used to iterate a set, so
        the winner depended on PYTHONHASHSEED: the test failed on some runs and
        passed on others, and `matchedVariant` (whose whole job is letting a bad
        variant be traced and demoted) varied run to run for identical input."""
        for _ in range(50):
            ok, var, _n = identity.partial_wordmark_match("ST??Z", self.variants)
            self.assertTrue(ok)
            self.assertEqual(var, "stelz", "tie-break must prefer the canonical spelling")

    def test_tie_break_follows_caller_order(self):
        # Position in the list is the documented preference order, so a caller
        # that puts an alias first gets that alias back.
        ok, var, _n = identity.partial_wordmark_match("ST??Z", ["st3lz", "stelz"])
        self.assertTrue(ok)
        self.assertEqual(var, "st3lz")


class TestIsBrandSpecificTag(unittest.TestCase):
    def test_brand_tags(self):
        for tag in ("stelz", "drinkstelz", "stelzhardseltzer", "casastelz", "#stelzfest"):
            self.assertTrue(
                identity.is_brand_specific_tag(tag, "stelz"), f"{tag} should be brand-specific"
            )

    def test_lifestyle_tags(self):
        for tag in ("vrijmibo", "koningsdag", "huisfeest", "studentenleven", "nederland"):
            self.assertFalse(
                identity.is_brand_specific_tag(tag, "stelz"), f"{tag} should be generic"
            )

    def test_denylisted_tag_is_not_brand_specific(self):
        self.assertFalse(identity.is_brand_specific_tag("stelzlager", "stelz"))

    def test_accented_tag(self):
        self.assertTrue(identity.is_brand_specific_tag("stëlz", "stelz"))


class TestIsRealHandle(unittest.TestCase):
    def test_accepts_real_handles(self):
        for h in ("drinkstelz", "monica.geuze", "stelz_int", "@fatimawn"):
            self.assertTrue(identity.is_real_handle(h), f"{h} should be valid")

    def test_rejects_junk_parsed_from_captions(self):
        for h in ("gmail.com", "stuff.nl", "12345", "a", "", "x.y.z"):
            self.assertFalse(identity.is_real_handle(h), f"{h} should be rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
