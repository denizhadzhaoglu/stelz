"""Creator projects — the rules that guard spend and shared state.

Two behaviours here are load-bearing:

1. THE TRACKING CAP. Adding a creator to a project flips them to a 6h/12h scan
   cadence — up to 8x the default spend, drawn from the same $5/day budget as
   every hashtag scan. The cap on distinct tracked creators is the only thing
   between "enthusiastic account manager" and a silently multiplied Apify bill,
   so it must hold across projects, not per project.

2. ARRAYUNION, NOT READ-MODIFY-WRITE. Firestore merge=True REPLACES arrays; the
   promotion funnel was once severed by exactly that (scan_hashtags.py:58-64).
   Two teammates adding creators at the same moment must both land.
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


class FakeArrayUnion:
    """Real union semantics, so the tests exercise what production relies on."""

    def __init__(self, values):
        self.values = list(values)


class FakeArrayRemove:
    """Real remove semantics — the fix for the review-confirmed lost-update bug
    (a filtered-array overwrite clobbered concurrent adds)."""

    def __init__(self, values):
        self.values = list(values)


_fsmod = _stub("google.cloud.firestore")
_fsmod.ArrayUnion = FakeArrayUnion
_fsmod.ArrayRemove = FakeArrayRemove
if not hasattr(_fsmod, "SERVER_TIMESTAMP"):
    _fsmod.SERVER_TIMESTAMP = "TS"
if not hasattr(_fsmod, "Increment"):
    _fsmod.Increment = lambda *a, **k: None

from handlers import projects  # noqa: E402

# handlers.projects captured ArrayUnion at import; make sure it is OUR class,
# not a lambda left behind by an earlier test module in the same process.
projects.ArrayUnion = FakeArrayUnion
projects.ArrayRemove = FakeArrayRemove


# ── In-memory Firestore double ──────────────────────────────────────────

class FakeSnap:
    def __init__(self, doc_id, exists, data):
        self.id = doc_id
        self.exists = exists
        self._d = data or {}

    def to_dict(self):
        return dict(self._d)


class FakeDoc:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def get(self):
        return FakeSnap(self._key, self._key in self._store, self._store.get(self._key))

    def set(self, data, merge=False):
        cur = dict(self._store.get(self._key) or {}) if merge else {}
        for k, v in data.items():
            if isinstance(v, FakeArrayUnion):
                existing = list(cur.get(k) or [])
                cur[k] = existing + [x for x in v.values if x not in existing]
            elif isinstance(v, FakeArrayRemove):
                cur[k] = [x for x in (cur.get(k) or []) if x not in set(v.values)]
            else:
                cur[k] = v
        self._store[self._key] = cur


class FakeCol:
    def __init__(self, store):
        self.store = store

    def document(self, doc_id):
        return FakeDoc(self.store, doc_id)

    def stream(self):
        return [FakeSnap(k, True, v) for k, v in self.store.items()]


class ProjectsBase(unittest.TestCase):
    def setUp(self):
        self.projects_store: dict = {}
        self.creators_store: dict = {
            "instagram_anna": {"tier": "tier_3", "handle": "anna"},
            "instagram_bob": {"tier": "tier_3", "handle": "bob"},
            "tiktok_carla": {"tier": "tier_3", "handle": "carla"},
        }
        p1 = mock.patch.object(projects.fs, "projects_col", lambda bid: FakeCol(self.projects_store))
        p2 = mock.patch.object(projects.fs, "creators_col", lambda bid: FakeCol(self.creators_store))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def create(self, name="Zomer Campagne", **kw):
        return projects.run("stelz", "uid1", "create", {"name": name, **kw})


class TestCreate(ProjectsBase):
    def test_creates_with_defaults(self):
        out = self.create()
        self.assertTrue(out["ok"])
        self.assertEqual(out["project"]["trackingTier"], "tier_1")
        self.assertEqual(out["project"]["creatorIds"], [])
        self.assertFalse(out["project"]["archived"])

    def test_empty_name_rejected(self):
        with self.assertRaises(projects.ProjectError):
            self.create(name="   ")

    def test_duplicate_name_is_409(self):
        self.create()
        with self.assertRaises(projects.ProjectError) as cm:
            self.create()
        self.assertEqual(cm.exception.status, 409)

    def test_tier_3_tracking_rejected(self):
        # tier_3 is the default cadence — "tracking" at it would be a no-op
        # sold as a feature.
        with self.assertRaises(projects.ProjectError):
            self.create(trackingTier="tier_3")

    def test_note_is_truncated_not_rejected(self):
        out = self.create(note="x" * 2000)
        self.assertLessEqual(len(out["project"]["note"]), projects.MAX_NOTE_LEN)


class TestAddCreators(ProjectsBase):
    def test_add_patches_tier_and_next_scan(self):
        pid = self.create()["project"]["id"]
        out = projects.run("stelz", "uid1", "addCreators",
                           {"projectId": pid, "creatorIds": ["instagram_anna"]})
        self.assertIn("instagram_anna", out["project"]["creatorIds"])
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_1")
        # nextScanAt set to "now" → eligible on the very next creator-scan run.
        self.assertIn("nextScanAt", self.creators_store["instagram_anna"])

    def test_two_sequential_adds_accumulate(self):
        # The ArrayUnion semantics: second add must not replace the first.
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        out = projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_bob"]})
        self.assertEqual(sorted(out["project"]["creatorIds"]), ["instagram_anna", "instagram_bob"])

    def test_duplicate_add_does_not_double(self):
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        out = projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        self.assertEqual(out["project"]["creatorIds"].count("instagram_anna"), 1)

    def test_unknown_creator_gets_a_tracking_stub_not_a_404(self):
        # Review-confirmed: most FEED creators were never promoted (promotion
        # needs 2 distinct generic tags), so a 404 here broke "Track in
        # project" for exactly the found-someone-great moment it exists for.
        pid = self.create()["project"]["id"]
        out = projects.run("stelz", "uid1", "addCreators",
                           {"projectId": pid, "creatorIds": ["instagram_nieuwevondst"]})
        self.assertIn("instagram_nieuwevondst", out["project"]["creatorIds"])
        stub = self.creators_store["instagram_nieuwevondst"]
        self.assertEqual(stub["handle"], "nieuwevondst")
        self.assertEqual(stub["platform"], "instagram")
        self.assertEqual(stub["status"], "discovered")  # scan_creators selects this
        self.assertEqual(stub["tier"], "tier_1")

    def test_malformed_creator_id_is_still_rejected(self):
        # The stub-upsert must not turn a garbage id into a phantom doc.
        pid = self.create()["project"]["id"]
        with self.assertRaises(projects.ProjectError):
            projects.run("stelz", "uid1", "addCreators",
                         {"projectId": pid, "creatorIds": ["geenplatform"]})

    def test_archived_project_refuses_adds(self):
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "archive", {"projectId": pid})
        with self.assertRaises(projects.ProjectError) as cm:
            projects.run("stelz", "uid1", "addCreators",
                         {"projectId": pid, "creatorIds": ["instagram_anna"]})
        self.assertEqual(cm.exception.status, 409)

    def test_tier_2_project_sets_tier_2(self):
        pid = self.create(name="Rustig volgen", trackingTier="tier_2")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_bob"]})
        self.assertEqual(self.creators_store["instagram_bob"]["tier"], "tier_2")


class TestTrackingCap(ProjectsBase):
    def _seed_many(self, n):
        for i in range(n):
            self.creators_store[f"instagram_c{i}"] = {"tier": "tier_3", "handle": f"c{i}"}

    def test_cap_holds_within_one_project(self):
        self._seed_many(30)
        pid = self.create()["project"]["id"]
        ids = [f"instagram_c{i}" for i in range(projects.TRACKED_CREATOR_CAP)]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ids[:25]})
        with self.assertRaises(projects.ProjectError) as cm:
            projects.run("stelz", "uid1", "addCreators",
                         {"projectId": pid, "creatorIds": ["instagram_c25"]})
        self.assertEqual(cm.exception.status, 409)
        self.assertIn("budget", str(cm.exception).lower())

    def test_cap_holds_ACROSS_projects(self):
        # The whole point of the cap: a second project is not a fresh allowance.
        self._seed_many(30)
        p1 = self.create(name="Project een")["project"]["id"]
        p2 = self.create(name="Project twee")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators",
                     {"projectId": p1, "creatorIds": [f"instagram_c{i}" for i in range(25)]})
        with self.assertRaises(projects.ProjectError):
            projects.run("stelz", "uid1", "addCreators",
                         {"projectId": p2, "creatorIds": ["instagram_c25"]})

    def test_same_creator_in_two_projects_counts_once(self):
        pid1 = self.create(name="Een")["project"]["id"]
        pid2 = self.create(name="Twee")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid1, "creatorIds": ["instagram_anna"]})
        # Same creator again elsewhere — union, so this must not hit the cap
        # accounting twice, and must simply succeed.
        out = projects.run("stelz", "uid1", "addCreators", {"projectId": pid2, "creatorIds": ["instagram_anna"]})
        self.assertTrue(out["ok"])

    def test_archived_projects_free_their_slots(self):
        self._seed_many(30)
        p1 = self.create(name="Oud")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators",
                     {"projectId": p1, "creatorIds": [f"instagram_c{i}" for i in range(25)]})
        projects.run("stelz", "uid1", "archive", {"projectId": p1})
        p2 = self.create(name="Nieuw")["project"]["id"]
        out = projects.run("stelz", "uid1", "addCreators",
                           {"projectId": p2, "creatorIds": ["instagram_c25"]})
        self.assertTrue(out["ok"])


class TestRemoveAndArchive(ProjectsBase):
    def test_remove_reverts_tier_when_last_project(self):
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        out = projects.run("stelz", "uid1", "removeCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        self.assertEqual(out["reverted"], 1)
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_3")

    def test_remove_keeps_tier_when_still_in_another_project(self):
        p1 = self.create(name="Een")["project"]["id"]
        p2 = self.create(name="Twee")["project"]["id"]
        for pid in (p1, p2):
            projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        out = projects.run("stelz", "uid1", "removeCreators", {"projectId": p1, "creatorIds": ["instagram_anna"]})
        self.assertEqual(out["reverted"], 0)
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_1")

    def test_archive_reverts_all_unclaimed_members(self):
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators",
                     {"projectId": pid, "creatorIds": ["instagram_anna", "instagram_bob"]})
        out = projects.run("stelz", "uid1", "archive", {"projectId": pid})
        self.assertEqual(out["reverted"], 2)
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_3")
        self.assertTrue(out["project"]["archived"])

    def test_remove_from_missing_project_is_404(self):
        with self.assertRaises(projects.ProjectError) as cm:
            projects.run("stelz", "uid1", "removeCreators",
                         {"projectId": "nope", "creatorIds": ["instagram_anna"]})
        self.assertEqual(cm.exception.status, 404)


class TestRenameAndMisc(ProjectsBase):
    def test_rename_changes_name_and_note(self):
        pid = self.create()["project"]["id"]
        out = projects.run("stelz", "uid1", "rename",
                           {"projectId": pid, "name": "Herfst", "note": "Q4"})
        self.assertEqual(out["project"]["name"], "Herfst")
        self.assertEqual(out["project"]["note"], "Q4")

    def test_unknown_action_rejected(self):
        with self.assertRaises(projects.ProjectError):
            projects.run("stelz", "uid1", "explode", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestTierReconciliation(ProjectsBase):
    """Review-confirmed: a blind per-project tier stamp was wrong in both
    directions. The effective tier is the FASTEST cadence among the live
    projects that claim the creator, recomputed on every membership change."""

    def test_add_to_slower_project_does_not_downgrade(self):
        p1 = self.create(name="Snel", trackingTier="tier_1")["project"]["id"]
        p2 = self.create(name="Rustig", trackingTier="tier_2")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": p1, "creatorIds": ["instagram_anna"]})
        projects.run("stelz", "uid1", "addCreators", {"projectId": p2, "creatorIds": ["instagram_anna"]})
        # tier_1 project still claims anna — the tier_2 add must not slow her down.
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_1")

    def test_leaving_the_fast_project_drops_to_the_remaining_slower_tier(self):
        # The 2x cost leak: leaving tier_1 while a tier_2 project remains used
        # to keep the 6h cadence forever. Now it reconciles to tier_2.
        p1 = self.create(name="Snel", trackingTier="tier_1")["project"]["id"]
        p2 = self.create(name="Rustig", trackingTier="tier_2")["project"]["id"]
        for pid in (p1, p2):
            projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        out = projects.run("stelz", "uid1", "removeCreators", {"projectId": p1, "creatorIds": ["instagram_anna"]})
        self.assertEqual(out["reverted"], 0)  # still tracked, so not reverted...
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_2")  # ...but reconciled

    def test_archiving_the_fast_project_reconciles_too(self):
        p1 = self.create(name="Snel", trackingTier="tier_1")["project"]["id"]
        p2 = self.create(name="Rustig", trackingTier="tier_2")["project"]["id"]
        for pid in (p1, p2):
            projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        projects.run("stelz", "uid1", "archive", {"projectId": p1})
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_2")


class TestRemoveIsArrayRemove(ProjectsBase):
    def test_remove_does_not_clobber_a_concurrent_add(self):
        # The review-confirmed HIGH: removeCreators used to write back a
        # filtered snapshot of the whole array, erasing any creator a teammate
        # added between the read and the write. With ArrayRemove the write only
        # touches the ids being removed. Simulated by injecting the concurrent
        # add between run()'s snapshot read and its write — the fake applies
        # ArrayRemove against CURRENT state, exactly like Firestore.
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})

        real_run = projects.run
        store = self.projects_store

        # Inject bob directly into the stored array to model a write that lands
        # after removeCreators has read its snapshot.
        class SneakyCol(FakeCol):
            def document(self, doc_id):
                doc = super().document(doc_id)
                orig_get = doc.get
                def get_with_race():
                    snap = orig_get()
                    if snap.exists and "instagram_bob" not in (store[doc_id].get("creatorIds") or []):
                        store[doc_id]["creatorIds"] = list(store[doc_id].get("creatorIds") or []) + ["instagram_bob"]
                    return snap  # snapshot WITHOUT bob — the stale read
                doc.get = get_with_race
                return doc

        with mock.patch.object(projects.fs, "projects_col", lambda bid: SneakyCol(store)):
            out = real_run("stelz", "uid1", "removeCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        # bob survived the remove of anna — the old overwrite erased him.
        self.assertIn("instagram_bob", store[pid]["creatorIds"])
        self.assertNotIn("instagram_anna", store[pid]["creatorIds"])
        self.assertTrue(out["ok"])


class TestUnarchive(ProjectsBase):
    def test_unarchive_exists_and_restores_tracking(self):
        # The addCreators error says "unarchive it first" — so it has to exist.
        pid = self.create()["project"]["id"]
        projects.run("stelz", "uid1", "addCreators", {"projectId": pid, "creatorIds": ["instagram_anna"]})
        projects.run("stelz", "uid1", "archive", {"projectId": pid})
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_3")
        out = projects.run("stelz", "uid1", "unarchive", {"projectId": pid})
        self.assertFalse(out["project"]["archived"])
        self.assertEqual(self.creators_store["instagram_anna"]["tier"], "tier_1")

    def test_unarchive_respects_the_cap(self):
        for i in range(30):
            self.creators_store[f"instagram_c{i}"] = {"tier": "tier_3", "handle": f"c{i}"}
        p1 = self.create(name="Oud")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators",
                     {"projectId": p1, "creatorIds": [f"instagram_c{i}" for i in range(20)]})
        projects.run("stelz", "uid1", "archive", {"projectId": p1})
        p2 = self.create(name="Nieuw")["project"]["id"]
        projects.run("stelz", "uid1", "addCreators",
                     {"projectId": p2, "creatorIds": [f"instagram_c{i}" for i in range(20, 30)] + ["instagram_anna"]})
        # Reviving p1 would put 20 + 11 = 31 creators on tracked cadence.
        with self.assertRaises(projects.ProjectError) as cm:
            projects.run("stelz", "uid1", "unarchive", {"projectId": p1})
        self.assertEqual(cm.exception.status, 409)

    def test_unarchive_of_a_live_project_is_an_error(self):
        pid = self.create()["project"]["id"]
        with self.assertRaises(projects.ProjectError):
            projects.run("stelz", "uid1", "unarchive", {"projectId": pid})
