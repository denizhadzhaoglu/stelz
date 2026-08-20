"""Who gets to be a member of a brand — bootstrap_brand step 2.

This is the gate the whole read-only story rests on. Every write path in
main.py calls _require_brand_member, and firestore.rules gates reference-image
writes on the same membership doc. None of that means anything if the enrolment
path hands out membership on request.

It did. bootstrap_brand.run() added the caller as `owner` unconditionally, and
the UI calls it as the first step of "Run scan" (web/src/pages/Home.tsx) — so
any tester with any Google account who pressed the button became an owner of
the live Stelz brand, with the right to reject detections and delete the
reference images the detector is trained on.

The rule now: an unclaimed brand (no members) goes to its first caller, which
is what makes self-serve onboarding work; a claimed brand never grants
membership here.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
sys.modules["google.cloud.firestore"].SERVER_TIMESTAMP = "TS"
sys.modules["google.cloud.firestore"].Increment = lambda *a, **k: None
sys.modules["google.cloud.firestore"].ArrayUnion = lambda *a, **k: None

from handlers import bootstrap_brand  # noqa: E402


# ── Minimal in-memory Firestore double ──────────────────────────────────

class FakeSnap:
    def __init__(self, exists: bool, data: dict | None = None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return dict(self._data)


class FakeDoc:
    def __init__(self, store: dict, key: str):
        self._store = store
        self._key = key

    def get(self):
        return FakeSnap(self._key in self._store, self._store.get(self._key))

    def set(self, data, merge=False):
        if merge and self._key in self._store:
            self._store[self._key].update(data)
        else:
            self._store[self._key] = dict(data)


class FakeCol:
    """One collection. `docs` is the shared dict this collection reads/writes."""

    def __init__(self, docs: dict):
        self.docs = docs

    def document(self, doc_id):
        return FakeDoc(self.docs, doc_id)

    def limit(self, n):
        self._limit = n
        return self

    def stream(self):
        n = getattr(self, "_limit", None)
        items = [FakeSnap(True, v) for v in self.docs.values()]
        return iter(items[:n] if n else items)

    def where(self, *a, **k):
        return self

    def __iter__(self):
        return self.stream()


class FakeBrandRef:
    def __init__(self, brands: dict, brand_id: str, subcols: dict):
        self._brands = brands
        self._id = brand_id
        self._subcols = subcols

    def get(self):
        return FakeSnap(self._id in self._brands, self._brands.get(self._id))

    def set(self, data, merge=False):
        if merge and self._id in self._brands:
            self._brands[self._id].update(data)
        else:
            self._brands[self._id] = dict(data)

    def collection(self, name):
        return FakeCol(self._subcols.setdefault(name, {}))


class MembershipTestBase(unittest.TestCase):
    def setUp(self):
        self.brands = {"stelz": {"name": "Stelz", "productLines": {"x": "X"}}}
        self.subcols: dict[str, dict] = {"members": {}}

        brand_ref = FakeBrandRef(self.brands, "stelz", self.subcols)
        self._orig_brand_doc = bootstrap_brand.fs.brand_doc
        self._orig_pool = bootstrap_brand.fs.hashtag_pool_col
        bootstrap_brand.fs.brand_doc = lambda _bid: brand_ref
        # Hashtag seeding is irrelevant here and would otherwise write hundreds
        # of docs per test; point it at a throwaway collection.
        bootstrap_brand.fs.hashtag_pool_col = lambda _bid: FakeCol({})

    def tearDown(self):
        bootstrap_brand.fs.brand_doc = self._orig_brand_doc
        bootstrap_brand.fs.hashtag_pool_col = self._orig_pool

    @property
    def members(self):
        return self.subcols["members"]


class TestFirstClaim(MembershipTestBase):
    def test_first_caller_on_an_unclaimed_brand_becomes_owner(self):
        """Self-serve onboarding must keep working — this is the path that
        makes a brand usable at all after bootstrap creates it."""
        result = bootstrap_brand.run("stelz", "Stelz", uid="alice", user_email="a@x.nl")
        self.assertTrue(result["added_member"])
        self.assertEqual(self.members["alice"]["role"], "owner")


class TestClaimedBrand(MembershipTestBase):
    def setUp(self):
        super().setUp()
        self.members["alice"] = {"role": "owner", "email": "a@x.nl"}

    def test_second_caller_does_not_become_a_member(self):
        """The regression that mattered: a tester pressing Run scan.

        The UI calls bootstrap first, so this exact call happened for every
        tester handed a link. It must not grant anything.
        """
        result = bootstrap_brand.run("stelz", "Stelz", uid="tester", user_email="t@x.nl")
        self.assertFalse(result["added_member"])
        self.assertNotIn("tester", self.members)

    def test_second_caller_is_not_an_error(self):
        """Bootstrap still has to succeed for a non-member — the UI calls it on
        the way to a scan, and a raised error there would surface as a broken
        page rather than as a refused permission. The refusal belongs to the
        scan step (main.py._require_brand_member), not to this one."""
        result = bootstrap_brand.run("stelz", "Stelz", uid="tester")
        self.assertEqual(result["brand_id"], "stelz")

    def test_existing_member_calling_again_is_idempotent(self):
        result = bootstrap_brand.run("stelz", "Stelz", uid="alice", user_email="a@x.nl")
        self.assertFalse(result["added_member"])
        self.assertEqual(self.members["alice"]["role"], "owner")
        self.assertEqual(len(self.members), 1)


if __name__ == "__main__":
    unittest.main()
