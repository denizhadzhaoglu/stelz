"""Tests for the SRS creator score — the parts that can be tested offline.

Context: the hashtag layer used to score a creator on how closely their tags
matched the brand's, using a brand_vec built from posts that ALREADY produced a
detection. Since discovery is hashtag-seeded, that corpus is dominated by posts
carrying #stelz — so 45% of the cold-start score was effectively "how findable
is this person WITHOUT us". Backwards for a tool whose whole value is finding
people you can't find for free.

The fix drops brand-specific tags from both vectors. Its dangerous failure mode
is that brand_vec becomes EMPTY (if every detected post carries only brand
tags), which would score the layer 0.0 for everyone and silently collapse the
ranking. redistribute_weight() handles that, and is what these tests pin.

run() itself needs Firestore and is not covered here.
"""
from __future__ import annotations

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
_stub("google.cloud.firestore").Increment = lambda *a, **k: None
_stub("google.cloud.firestore").ArrayUnion = lambda *a, **k: None

from handlers.compute_resonance import redistribute_weight, _cosine, SRS_VERSION  # noqa: E402
from lib import identity  # noqa: E402

COLD = {"graph": 5, "hashtag": 45, "comment": 20, "geo": 30, "visual": 0}
WARM = {"graph": 25, "hashtag": 30, "comment": 20, "geo": 15, "visual": 10}
HOT = {"graph": 35, "hashtag": 25, "comment": 20, "geo": 10, "visual": 10}


class TestRedistributeWeight(unittest.TestCase):
    def test_weights_still_sum_to_100(self):
        # The whole point: a dead layer must not shrink the total, or SRS stops
        # being comparable across brands and bootstrap modes.
        for name, w in (("cold", COLD), ("warm", WARM), ("hot", HOT)):
            out = redistribute_weight(w, "hashtag")
            self.assertEqual(sum(out.values()), 100, f"{name} mode drifted: {out}")

    def test_dead_layer_is_zeroed(self):
        self.assertEqual(redistribute_weight(COLD, "hashtag")["hashtag"], 0)

    def test_surviving_layers_all_grow(self):
        out = redistribute_weight(COLD, "hashtag")
        for k in ("graph", "comment", "geo"):
            self.assertGreater(out[k], COLD[k], f"{k} did not absorb any weight")

    def test_zero_weight_layers_stay_zero(self):
        # visual is 0 in cold mode; handing it weight would invent signal from a
        # layer that has none.
        self.assertEqual(redistribute_weight(COLD, "hashtag")["visual"], 0)

    def test_proportional_split(self):
        # geo (30) should absorb about six times what graph (5) does.
        out = redistribute_weight(COLD, "hashtag")
        self.assertGreater(out["geo"] - COLD["geo"], out["graph"] - COLD["graph"])

    def test_noop_when_layer_already_zero(self):
        self.assertEqual(redistribute_weight(COLD, "visual"), COLD)

    def test_does_not_mutate_the_input(self):
        before = dict(COLD)
        redistribute_weight(COLD, "hashtag")
        self.assertEqual(COLD, before)

    def test_survives_having_nothing_left(self):
        # Degenerate but must not crash or produce a negative weight.
        out = redistribute_weight({"hashtag": 100}, "hashtag")
        self.assertEqual(out["hashtag"], 0)


class TestBrandTagExclusion(unittest.TestCase):
    """The filter itself. is_brand_specific_tag is shared with the promotion
    logic, so these double as a guard on that."""

    def flt(self, tags):
        return [t for t in tags if not identity.is_brand_specific_tag(t, "stelz", ["stelz"])]

    def test_brand_tags_are_dropped(self):
        self.assertEqual(self.flt(['stelz', 'drinkstelz', 'stelzhardseltzer']), [])

    def test_lifestyle_tags_survive(self):
        keep = ['vrijmibo', 'huisfeest', 'koningsdag', 'studentenleven', 'festivalseizoen']
        self.assertEqual(self.flt(keep), keep)

    def test_the_stelzlager_regression_is_not_treated_as_a_brand_tag(self):
        # It must SURVIVE the filter (it is not a brand tag), which is the
        # opposite direction from the detection gate but the same denylist.
        self.assertIn('stelzlager', self.flt(['stelzlager']))

    def test_a_mixed_post_keeps_only_its_context(self):
        self.assertEqual(self.flt(['stelz', 'vrijmibo', 'drinkstelz', 'borrel']),
                         ['vrijmibo', 'borrel'])


class TestCosine(unittest.TestCase):
    def test_identical_vectors(self):
        v = {'vrijmibo': 0.5, 'huisfeest': 0.5}
        self.assertAlmostEqual(_cosine(v, v), 1.0, places=5)

    def test_disjoint_vectors(self):
        self.assertEqual(_cosine({'a': 1.0}, {'b': 1.0}), 0.0)

    def test_empty_vector_is_zero_not_a_crash(self):
        # This is the state the redistribute path exists for.
        self.assertEqual(_cosine({}, {'vrijmibo': 1.0}), 0.0)
        self.assertEqual(_cosine({}, {}), 0.0)


class TestVersioning(unittest.TestCase):
    def test_version_is_bumped_past_v1(self):
        # v1 scores are already in Firestore and on the client's screen; they
        # are not comparable with v2.
        self.assertGreaterEqual(SRS_VERSION, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
