"""Tests for reference-image selection in lib/refs.py.

refs.py transitively imports firebase_admin, which isn't installed locally, so
we stub the Firestore layer before import. The function under test is pure.

Why this matters: the previous loader took the first 8 docs from an UNORDERED
Firestore query. Firestore returns document-name ascending, and reference doc
IDs are `${Date.now()}_${filename}` (web/src/lib/firestore.ts:268) — so it was
deterministically the 8 OLDEST uploads, forever. Every packshot uploaded after
the first 8 was invisible to the detector while still appearing in the Settings
"Training" UI as if it were in use.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub the firebase/google modules refs.py pulls in transitively.
for name in (
    "firebase_admin",
    "firebase_admin.firestore",
    "firebase_admin.storage",
    "google",
    "google.cloud",
    "google.cloud.firestore",
):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["firebase_admin"].initialize_app = lambda *a, **k: None
sys.modules["firebase_admin"].get_app = lambda *a, **k: None
sys.modules["firebase_admin"].credentials = types.SimpleNamespace(
    ApplicationDefault=lambda: None
)
sys.modules["google.cloud.firestore"].SERVER_TIMESTAMP = object()
sys.modules["google.cloud.firestore"].Increment = lambda *a, **k: None
sys.modules["google.cloud.firestore"].ArrayUnion = lambda *a, **k: None

from lib.refs import _select_reference_docs  # noqa: E402


def _docs():
    """8 old Hard Seltzer packshots, then 3 newer shots of other product lines."""
    old = [
        {"url": f"old_seltzer_{i}", "productLine": "hard_seltzer", "uploadedAt": i}
        for i in range(1, 9)
    ]
    new = [
        {"url": "new_iced_tea", "productLine": "hard_iced_tea", "uploadedAt": 20},
        {"url": "new_mixed", "productLine": "mixed_classics", "uploadedAt": 21},
        {"url": "new_lemonade", "productLine": "hard_lemonade", "uploadedAt": 22},
    ]
    return old + new


class TestReferenceSelection(unittest.TestCase):
    def test_covers_every_product_line(self):
        picked = _select_reference_docs(_docs(), 8)
        lines = {d["productLine"] for d in picked}
        self.assertEqual(
            lines,
            {"hard_seltzer", "hard_iced_tea", "mixed_classics", "hard_lemonade"},
            "every product line must be represented or the model never learns "
            "what the other cans look like",
        )

    def test_newer_uploads_are_not_starved(self):
        picked = {d["url"] for d in _select_reference_docs(_docs(), 8)}
        for u in ("new_iced_tea", "new_mixed", "new_lemonade"):
            self.assertIn(u, picked, f"{u} was uploaded later and must still be seen")

    def test_respects_max_count(self):
        self.assertEqual(len(_select_reference_docs(_docs(), 8)), 8)
        self.assertEqual(len(_select_reference_docs(_docs(), 3)), 3)

    def test_handles_fewer_docs_than_max(self):
        self.assertEqual(len(_select_reference_docs(_docs()[:2], 8)), 2)

    def test_handles_empty(self):
        self.assertEqual(_select_reference_docs([], 8), [])

    def test_missing_uploadedAt_does_not_exclude(self):
        # A server-seeded doc with no uploadedAt must still be selectable —
        # this is why we sort in Python rather than with Firestore order_by,
        # which silently drops documents missing the sort field.
        docs = [{"url": "seeded", "productLine": "logo_only"}] + _docs()
        picked = {d["url"] for d in _select_reference_docs(docs, 8)}
        self.assertIn("seeded", picked)

    def test_no_duplicates(self):
        picked = _select_reference_docs(_docs(), 8)
        urls = [d["url"] for d in picked]
        self.assertEqual(len(urls), len(set(urls)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
