"""Tests for which hashtags actually get scanned.

The bug these pin: publish_tags took `sorted(pool, key=priority)[:max_tags]`,
and with the shipped 117-tag pool at the shipped max_tags=50 that removed all 45
typo tags, all 12 lifestyle tags and all 6 category tags — every time, silently.
Lifestyle tags are the creator-prospecting surface, which lib/hashtags.py calls
"the only route to untagged content", and untagged content is the product.

A regression here is invisible in production: the scan still runs, still returns
posts, and nobody sees that a whole discovery surface stopped being queried. So
the coverage guarantee is asserted directly against the real shipped pool.
"""
from __future__ import annotations

import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import hashtags  # noqa: E402


def _pool(spec: dict[str, int]) -> list[dict]:
    """Build a pool from {family: count} using real family priorities."""
    out = []
    for fam, n in spec.items():
        prio, cap, _ = hashtags.FAMILIES[fam]
        for i in range(n):
            out.append({"tag": f"{fam}{i}", "family": fam, "priority": prio, "maxResults": cap})
    return out


class TestSelectTags(unittest.TestCase):
    def test_no_family_is_wiped_out(self):
        # The actual bug, on the actual shipped pool.
        pool = hashtags.stelz_pool("instagram") + hashtags.stelz_pool("tiktok")
        picked = Counter(d["family"] for d in hashtags.select_tags(pool, 50))
        for fam in {d["family"] for d in pool}:
            self.assertGreater(picked[fam], 0, f"{fam} was cut entirely — the original bug")

    def test_lifestyle_survives_the_real_cut(self):
        pool = hashtags.stelz_pool("instagram") + hashtags.stelz_pool("tiktok")
        picked = [d for d in hashtags.select_tags(pool, 50) if d["family"] == "lifestyle"]
        self.assertGreaterEqual(len(picked), 1)

    def test_the_old_behaviour_really_did_drop_them(self):
        # Guards the premise. If this ever fails, the fix is aimed at nothing.
        pool = hashtags.stelz_pool("instagram") + hashtags.stelz_pool("tiktok")
        old = sorted(pool, key=lambda d: d.get("priority", 0), reverse=True)[:50]
        self.assertEqual(sum(1 for d in old if d["family"] == "lifestyle"), 0)

    def test_high_priority_families_still_dominate(self):
        # Fairness must not become equality — brand tags are where the hits are.
        pool = hashtags.stelz_pool("instagram") + hashtags.stelz_pool("tiktok")
        picked = Counter(d["family"] for d in hashtags.select_tags(pool, 50))
        self.assertGreater(picked["brand_core"], picked["lifestyle"])

    def test_respects_max_tags(self):
        pool = _pool({"brand_core": 20, "lifestyle": 20, "brand_typo": 20})
        for n in (1, 5, 12, 50, 60):
            self.assertLessEqual(len(hashtags.select_tags(pool, n)), n)

    def test_returns_everything_when_capacity_exceeds_the_pool(self):
        pool = _pool({"brand_core": 3, "lifestyle": 2})
        self.assertEqual(len(hashtags.select_tags(pool, 99)), 5)

    def test_tiny_budget_spends_on_the_best_families_first(self):
        # With room for 3, the floor cannot cover everything — the squeezed-out
        # families must be the low-priority ones, not arbitrary.
        pool = _pool({"brand_core": 5, "lifestyle": 5})
        picked = hashtags.select_tags(pool, 3)
        self.assertTrue(all(d["family"] == "brand_core" for d in picked))

    def test_is_deterministic(self):
        # Two runs must enqueue the same tags or week-on-week yield comparisons
        # are meaningless.
        pool = hashtags.stelz_pool("instagram")
        first = [d["tag"] for d in hashtags.select_tags(pool, 40)]
        for _ in range(5):
            self.assertEqual([d["tag"] for d in hashtags.select_tags(pool, 40)], first)

    def test_handles_empty_and_zero(self):
        self.assertEqual(hashtags.select_tags([], 50), [])
        self.assertEqual(hashtags.select_tags(_pool({"brand_core": 5}), 0), [])

    def test_survives_a_pool_entry_with_no_family_or_priority(self):
        # Firestore docs are user-editable; a missing field must not crash a scan.
        pool = [{"tag": "orphan"}, *_pool({"brand_core": 2})]
        self.assertEqual(len(hashtags.select_tags(pool, 3)), 3)


class TestProjectedResults(unittest.TestCase):
    def test_uses_the_per_family_cap_when_it_is_lower(self):
        # lifestyle is capped at 60/tag, so 500 must not be charged for it.
        lifestyle = _pool({"lifestyle": 1})
        self.assertEqual(hashtags.projected_results(lifestyle, 500), 60)

    def test_uncapped_family_uses_the_caller_number(self):
        self.assertEqual(hashtags.projected_results(_pool({"brand_core": 1}), 500), 500)

    def test_never_raises_the_caller_number(self):
        self.assertEqual(hashtags.projected_results(_pool({"brand_event": 1}), 100), 100)

    def test_the_fix_is_not_more_expensive(self):
        # The restored families carry caps, so they displace uncapped tags and
        # the selection actually gets cheaper. If this inverts, the change needs
        # a budget conversation before it ships.
        pool = hashtags.stelz_pool("instagram") + hashtags.stelz_pool("tiktok")
        old = sorted(pool, key=lambda d: d.get("priority", 0), reverse=True)[:50]
        new = hashtags.select_tags(pool, 50)
        self.assertLessEqual(
            hashtags.projected_results(new, 500),
            hashtags.projected_results(old, 500),
        )

    def test_empty_selection_costs_nothing(self):
        self.assertEqual(hashtags.projected_results([], 500), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
