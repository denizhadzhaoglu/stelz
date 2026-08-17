"""Tests for lib/hashtags.py — pool generation and cost discipline.

The pool went from 9 Instagram tags to 82. The risk in that is not the tag
count — Apify bills per RESULT, so a hashtag nobody uses is free — it is that
a high-volume, zero-yield lifestyle tag inherits the same 500-result cap as the
brand's own tag. These tests pin the caps that prevent that, and pin the
strict/loose split that makes wide typo coverage safe.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import hashtags, identity  # noqa: E402


class TestBuildPool(unittest.TestCase):
    def setUp(self):
        self.pool = hashtags.stelz_pool("instagram")
        self.tags = {t["tag"] for t in self.pool}

    def test_keeps_every_previously_seeded_tag(self):
        # Regenerating the pool must never silently drop a tag the client is
        # already relying on.
        for t in ("stelz", "drinkstelz", "stelzhardseltzer", "stelzhardlemonade",
                  "stelzhardicedtea", "vrijmibo", "huisfeest", "koningsdag",
                  "studentenleven"):
            self.assertIn(t, self.tags, f"dropped previously-seeded tag {t}")

    def test_adds_the_misspellings_that_were_entirely_absent(self):
        for t in ("stelzz", "stels", "stellz", "steelz", "sstelz"):
            self.assertIn(t, self.tags, f"missing typo tag {t}")

    def test_adds_flavour_and_event_tags(self):
        for t in ("stelzcassis", "stelzpeach", "casastelz", "stelzfest"):
            self.assertIn(t, self.tags)

    def test_no_duplicates(self):
        names = [t["tag"] for t in self.pool]
        self.assertEqual(len(names), len(set(names)))

    def test_deterministic(self):
        self.assertEqual(hashtags.stelz_pool("instagram"), self.pool)

    def test_sorted_by_priority_descending(self):
        prios = [t["priority"] for t in self.pool]
        self.assertEqual(prios, sorted(prios, reverse=True))

    def test_brand_tags_outrank_lifestyle(self):
        # publish_tags() truncates to max_tags by priority, so if this inverts,
        # a sweep spends its budget on #koningsdag and never reaches #stelz.
        core = min(t["priority"] for t in self.pool if t["family"] == "brand_core")
        life = max(t["priority"] for t in self.pool if t["family"] == "lifestyle")
        self.assertGreater(core, life)

    def test_no_degenerate_tags(self):
        for t in self.pool:
            self.assertGreaterEqual(len(t["tag"]), 3)
            self.assertNotIn("#", t["tag"])
            self.assertNotIn(" ", t["tag"])
            self.assertEqual(t["tag"], t["tag"].lower())

    def test_internal_product_keys_are_not_hashtags(self):
        # logo_only / zero_zero are UI classification keys, not things a human
        # would ever type after the brand name.
        self.assertNotIn("stelzlogoonly", self.tags)
        self.assertNotIn("stelzzerozero", self.tags)


class TestCostDiscipline(unittest.TestCase):
    def setUp(self):
        self.pool = hashtags.stelz_pool("instagram")

    def test_lifestyle_is_capped_far_below_brand(self):
        life = [t for t in self.pool if t["family"] == "lifestyle"]
        core = [t for t in self.pool if t["family"] == "brand_core"]
        self.assertTrue(life and core)
        self.assertTrue(all(t["maxResults"] and t["maxResults"] <= 100 for t in life),
                        "lifestyle tags convert at ~0% and must stay cheap")
        self.assertTrue(all(t["maxResults"] is None for t in core),
                        "the brand's own tags should take everything available")

    def test_every_low_yield_family_has_a_cap(self):
        for t in self.pool:
            if t["family"] in ("brand_core", "product_line"):
                continue
            self.assertIsNotNone(t["maxResults"], f"{t['tag']} ({t['family']}) uncapped")

    def test_capped_families_cost_less_than_a_flat_sweep(self):
        flat = sum(500 for _ in self.pool)
        capped = sum(min(500, t["maxResults"] or 500) for t in self.pool)
        self.assertLess(capped, flat * 0.6,
                        "per-family caps should roughly halve worst-case sweep cost")


class TestStrictLooseSafety(unittest.TestCase):
    """Wide typo coverage in the POOL is only safe because those same loose
    variants can never accept a DETECTION. If this ever inverts, every junk
    post found via #stelx becomes a candidate false positive."""

    def test_pool_uses_loose_variants(self):
        tags = {t["tag"] for t in hashtags.stelz_pool("instagram")}
        loose = set(identity.generate_variants("stelz")["loose"])
        self.assertTrue(loose & tags, "discovery should exploit loose variants")

    def test_detection_does_not_accept_loose_variants(self):
        from handlers.detect_image import _accept_variants
        accept = set(_accept_variants({"slug": "stelz", "wordmarkAliases": []}))
        loose = set(identity.generate_variants("stelz")["loose"])
        self.assertEqual(accept & loose, set(),
                         "a loose variant must never accept a detection")

    def test_denylisted_words_never_become_tags(self):
        tags = {t["tag"] for t in hashtags.stelz_pool("instagram")}
        for banned in ("stelzlager", "stelzen", "steel", "stelt"):
            self.assertNotIn(banned, tags)


class TestPlatformDifferences(unittest.TestCase):
    def test_tiktok_skips_typos(self):
        # TikTok search is fuzzy and tag-poor; misspelled tags return noise
        # there while still costing an actor run each.
        tt = {t["tag"] for t in hashtags.stelz_pool("tiktok")}
        self.assertNotIn("stelzz", tt)
        self.assertIn("stelz", tt)

    def test_tiktok_pool_is_smaller(self):
        self.assertLess(len(hashtags.stelz_pool("tiktok")),
                        len(hashtags.stelz_pool("instagram")))


class TestBrandAgnostic(unittest.TestCase):
    def test_works_for_another_tenant_with_no_code_change(self):
        pool = hashtags.build_pool("kever", product_lines={"hard_seltzer": ""})
        tags = {t["tag"] for t in pool}
        self.assertIn("kever", tags)
        self.assertIn("drinkkever", tags)
        self.assertIn("keverhardseltzer", tags)
        self.assertNotIn("stelz", tags)

    def test_empty_slug_yields_nothing(self):
        self.assertEqual(hashtags.build_pool(""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
