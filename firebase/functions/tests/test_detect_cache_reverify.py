"""The cache path must reach the verifier.

This pins a wiring bug, not a logic bug. detect_image.run short-circuits on an
imageHashCache hit and returned before the verify pass ever ran, so the verifier
only improved images the pipeline had never seen. Every detection already in the
catalogue — i.e. the entire feed an operator looks at — kept its pre-verifier
verdict permanently, while the tests for verifier.decide() all passed.

needs_reverify() being correct is not enough; these tests exercise run() itself.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

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

# The google-genai SDK is a deploy-time dependency and is not installed locally.
# detect_image imports lib.gemini at module scope, so it has to be stubbed
# before the import below. Every genai call in these tests is patched anyway.
_stub("google.genai")
_stub("google.genai.types")
_stub("google").genai = sys.modules["google.genai"]
sys.modules["google.genai"].Client = lambda *a, **k: None

from handlers import detect_image  # noqa: E402
from lib import verifier  # noqa: E402

# A cached detection from before the verifier existed: demoted, no verdict.
UNVERIFIED_CACHED = {
    "detected": True,
    "confidence": 0.70,
    "gate": "capped_small_object",
    "text_legibility": "clear",
    "visible_text": "STELZ",
}


class _Snap:
    def __init__(self, data):
        self.exists = True
        self._d = data

    def to_dict(self):
        return self._d


class CachePathBase(unittest.TestCase):
    def setUp(self):
        self.persisted = []
        self.cache_saves = []

        patches = {
            "fs": mock.DEFAULT, "cache": mock.DEFAULT, "usage": mock.DEFAULT,
            "refs": mock.DEFAULT, "gemini": mock.DEFAULT, "requests": mock.DEFAULT,
            "_mirror_to_storage": mock.DEFAULT, "_persist": mock.DEFAULT,
            "_log_attempt": mock.DEFAULT,
        }
        self.p = mock.patch.multiple(detect_image, **patches)
        self.m = self.p.start()
        self.addCleanup(self.p.stop)

        self.m["fs"].brand_doc.return_value.get.return_value = _Snap(
            {"name": "STELZ", "productLines": {}, "slug": "stelz"})
        self.m["fs"].posts_col.return_value.document.return_value.get.return_value = _Snap({})
        self.m["fs"].composite_id.side_effect = lambda *a: "_".join(str(x) for x in a)
        self.m["requests"].get.return_value = mock.Mock(
            content=b"\xff\xd8\xffimagebytes", raise_for_status=lambda: None)
        self.m["cache"].sha256_of.return_value = "hash123"
        self.m["cache"].save_cached_detection.side_effect = \
            lambda *a, **k: self.cache_saves.append(a[3])
        self.m["_mirror_to_storage"].return_value = "https://stored/x.jpg"
        self.m["_persist"].side_effect = \
            lambda bid, pid, did, base, result, source: self.persisted.append(result)
        self.m["usage"].budget_exhausted.return_value = False
        self.m["usage"].degrade_level.return_value = 0
        self.m["usage"].DEGRADE_TRIM = 1
        self.m["refs"].load_references.return_value = [b"ref"]

    def run_with_cache(self, cached):
        self.m["cache"].get_cached_detection.return_value = dict(cached)
        return detect_image.run("stelz", "instagram_1", "https://cdn/x.jpg")


class TestCacheHitReverifies(CachePathBase):
    def test_an_unverified_cached_hit_reaches_the_verifier(self):
        # The regression. Before the fix this assertion failed: run() returned
        # from the cache branch without ever calling gemini.
        self.m["gemini"].verify_brand.return_value = {"brand": "STELZ", "confidence": 0.95}
        out = self.run_with_cache(UNVERIFIED_CACHED)
        self.assertTrue(self.m["gemini"].verify_brand.called)
        self.assertTrue(out["reverified"])

    def test_a_rival_brand_verdict_removes_the_hit_from_the_feed(self):
        # detected=False plus the detectedOnly feed query is what actually makes
        # a wrong can disappear for the operator.
        self.m["gemini"].verify_brand.return_value = {"brand": "Heineken", "confidence": 0.95}
        out = self.run_with_cache(UNVERIFIED_CACHED)
        self.assertFalse(out["detected"])
        self.assertFalse(self.persisted[0]["detected"])

    def test_an_upgraded_verdict_is_persisted(self):
        self.m["gemini"].verify_brand.return_value = {"brand": "STELZ", "confidence": 0.95}
        self.run_with_cache(UNVERIFIED_CACHED)
        self.assertEqual(self.persisted[0]["verify_verdict"], "upgraded")
        self.assertGreaterEqual(self.persisted[0]["confidence"], 0.85)

    def test_the_verdict_is_written_back_to_the_cache(self):
        # Without this the same image is re-verified — and re-billed — on every
        # scan that touches it.
        self.m["gemini"].verify_brand.return_value = {"brand": "STELZ", "confidence": 0.95}
        self.run_with_cache(UNVERIFIED_CACHED)
        self.assertEqual(len(self.cache_saves), 1)
        self.assertEqual(self.cache_saves[0]["verify_version"], verifier.VERIFY_VERSION)


class TestCacheHitDoesNotReverify(CachePathBase):
    def test_an_already_verified_hit_is_not_re_billed(self):
        already = {**UNVERIFIED_CACHED, "verify_version": verifier.VERIFY_VERSION,
                   "verify_verdict": "confirmed"}
        out = self.run_with_cache(already)
        self.assertFalse(self.m["gemini"].verify_brand.called)
        self.assertFalse(out["reverified"])

    def test_a_clean_high_confidence_hit_is_not_verified(self):
        self.run_with_cache({"detected": True, "confidence": 0.95, "gate": None})
        self.assertFalse(self.m["gemini"].verify_brand.called)

    def test_budget_pressure_skips_reverification_but_not_detection(self):
        # This pass is an improvement, not part of detecting anything, so it is
        # the first thing to stop when spend runs out.
        self.m["usage"].degrade_level.return_value = 1  # DEGRADE_TRIM
        out = self.run_with_cache(UNVERIFIED_CACHED)
        self.assertFalse(self.m["gemini"].verify_brand.called)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["detected"])

    def test_a_failed_verifier_call_leaves_the_detection_untouched(self):
        # And is NOT written to the cache, so it retries next time rather than
        # freezing a transient failure into the record forever.
        self.m["gemini"].verify_brand.side_effect = RuntimeError("429 rate limited")
        out = self.run_with_cache(UNVERIFIED_CACHED)
        self.assertTrue(out["detected"])
        self.assertFalse(out["reverified"])
        self.assertEqual(self.cache_saves, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
