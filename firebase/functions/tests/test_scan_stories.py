"""Stories capture — the filter, the TTL, and the money.

Three things here are load-bearing:

1. THE LEAK FILTER. Stories endpoints return reels and feed posts mixed into
   their output. A reel filed as a story would make the product's central claim
   ("we caught it before it disappeared") false, so anything shaped like a feed
   item is rejected.

2. expiresAt IS COMPUTED. Two prototypes promised this field in their header
   and neither wrote it; without it nothing can say how long a story has left.

3. THE RUN FEE IS REAL. This actor charges per run AND per username, breaking
   the "runs are free" assumption baked into the rest of the cost table. If the
   run fee is not recorded, story scraping is invisible to the budget ladder —
   the exact bug that already shipped once in scan_creators.
"""
from __future__ import annotations

import datetime as dt
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
_fsmod = _stub("google.cloud.firestore")
if not hasattr(_fsmod, "SERVER_TIMESTAMP"):
    _fsmod.SERVER_TIMESTAMP = "TS"
for _attr, _val in (("Increment", lambda *a, **k: None), ("ArrayUnion", lambda v: v), ("ArrayRemove", lambda v: v)):
    if not hasattr(_fsmod, _attr):
        setattr(_fsmod, _attr, _val)

from handlers import scan_stories  # noqa: E402


# ── In-memory doubles ───────────────────────────────────────────────────

class FakeSnap:
    def __init__(self, doc_id, data, exists=True):
        self.id = doc_id
        self._d = dict(data or {})
        self.exists = exists
        self.reference = types.SimpleNamespace(path=f"creators/{doc_id}")

    def to_dict(self):
        return dict(self._d)


class FakeDoc:
    def __init__(self, store, key):
        self._store, self._key = store, key
        self.subs: dict[str, dict] = {}

    def get(self):
        return FakeSnap(self._key, self._store.get(self._key), self._key in self._store)

    def set(self, data, merge=False):
        cur = dict(self._store.get(self._key) or {}) if merge else {}
        cur.update(data)
        self._store[self._key] = cur

    def collection(self, name):
        return FakeCol(self.subs.setdefault(name, {}))


class FakeCol:
    def __init__(self, store):
        self.store = store
        self.docs: dict[str, FakeDoc] = {}
        self.added: list[dict] = []

    def document(self, doc_id):
        return self.docs.setdefault(doc_id, FakeDoc(self.store, doc_id))

    def add(self, data):
        self.added.append(data)

    def where(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def stream(self):
        return [FakeSnap(k, v) for k, v in self.store.items()]


class StoriesBase(unittest.TestCase):
    def setUp(self):
        self.creators = {
            "instagram_anna": {"handle": "anna", "platform": "instagram", "tier": "tier_2"},
        }
        self.posts: dict = {}
        self.recorded: list[dict] = []
        self.runs_col = FakeCol({})

        self.posts_col = FakeCol(self.posts)
        self.brand = mock.Mock(get=lambda: mock.Mock(exists=True))
        fake_fs = types.SimpleNamespace(
            brand_doc=lambda bid: self.brand,
            creators_col=lambda bid: FakeCol(self.creators),
            posts_col=lambda bid: self.posts_col,
            scan_runs_col=lambda bid: self.runs_col,
            composite_id=lambda *parts: "_".join(p.lower() for p in parts if p),
        )
        self.usage = types.SimpleNamespace(
            budget_exhausted=lambda bid: False,
            scraping_allowed=lambda bid: True,
            record=lambda bid, **kw: self.recorded.append(kw),
        )
        self.apify = mock.Mock()
        self.apify.run_sync = mock.Mock(return_value=[])
        for p in (
            mock.patch.object(scan_stories, "fs", fake_fs),
            mock.patch.object(scan_stories, "usage", self.usage),
            mock.patch.object(scan_stories, "apify", self.apify),
        ):
            p.start()
            self.addCleanup(p.stop)

    def run_stories(self, **kw):
        return scan_stories.run("stelz", dry_run=True, **kw)

    def stamp(self) -> dict:
        """The `stories` map last written to the brand doc, or {}."""
        for call in reversed(self.brand.set.call_args_list):
            payload = call.args[0] if call.args else {}
            if "stories" in payload:
                return payload["stories"]
        return {}


# Shaped from a real actor response (Lowlands roster, 20 Aug 2026), not from
# the API docs and not from imagination. The previous fixture in this file was
# invented — camelCase feed-post fields that no vendor has ever returned — so
# sixteen passing tests proved nothing, and a live run rejected 69 of 69 real
# stories. URLs and ids are stand-ins; every KEY is what the vendor sends.
STORY = {
    "product_type": "story",
    # "{media_id}_{user_id}" — this is what broke the old str.isdigit() check.
    "id": "31415926535_314162194",
    # 64-bit id mangled by JSON's float: deliberately wrong here, and unread.
    "pk": 31415926500,
    "code": "DcOVs-KMRoO",          # stories DO have a shortcode
    "media_type": 1,                 # 1 = image, 2 = video
    "username": "anna",
    "user": {"username": "anna"},
    "taken_at": 1755680000,
    "expiring_at": 1755680000 + 86400,
    "image_versions2": {"candidates": [
        {"url": "https://cdn/story-1320.jpg", "width": 1320, "height": 2346},
        {"url": "https://cdn/story-750.jpg", "width": 750, "height": 1333},
    ]},
    "caption": None,
}

VIDEO_STORY = {
    **STORY,
    "media_type": 2,
    "video_versions": [
        {"url": "https://cdn/story-720.mp4", "width": 720, "height": 1280},
        {"url": "https://cdn/story-360.mp4", "width": 360, "height": 640},
    ],
}


class TestLeakFilter(StoriesBase):
    def test_product_type_is_the_discriminator(self):
        # Stories endpoints leak reels and feed posts. Instagram labels the
        # media itself, so this reads the label instead of guessing from shape.
        for leak in (
            {**STORY, "product_type": "clips"},
            {**STORY, "product_type": "feed"},
            {**STORY, "product_type": "igtv"},
            {k: v for k, v in STORY.items() if k != "product_type"},
        ):
            self.assertIsNone(scan_stories._normalize_item(leak))

    def test_a_shortcode_does_not_make_it_a_post(self):
        # The old filter rejected anything carrying a shortCode. Every one of
        # the 69 real stories in the live run had a `code`, so that heuristic
        # alone would have thrown the entire feature away.
        self.assertIsNotNone(scan_stories._normalize_item({**STORY, "code": "DcOVs-KMRoO"}))

    def test_accepts_the_real_composite_id(self):
        # "{media_id}_{user_id}" — str.isdigit() on the whole string is what
        # rejected 69 of 69 genuine stories.
        out = scan_stories._normalize_item(STORY)
        self.assertEqual(out["story_id"], "31415926535")
        self.assertEqual(out["handle"], "anna")

    def test_rejects_ids_that_are_not_ids(self):
        for bad in ("abc", "", None, "_314162194"):
            self.assertIsNone(scan_stories._normalize_item({**STORY, "id": bad}), bad)

    def test_takes_the_widest_image_and_best_video(self):
        # Candidates arrive widest-first; the detector should see full res.
        self.assertEqual(scan_stories._normalize_item(STORY)["image_url"],
                         "https://cdn/story-1320.jpg")
        self.assertEqual(scan_stories._normalize_item(VIDEO_STORY)["video_url"],
                         "https://cdn/story-720.mp4")

    def test_falls_back_to_nested_username(self):
        out = scan_stories._normalize_item({k: v for k, v in STORY.items() if k != "username"})
        self.assertEqual(out["handle"], "anna")

    def test_leaked_items_are_counted_not_silently_dropped(self):
        self.apify.run_sync.return_value = [
            STORY, {**STORY, "id": "999_1", "product_type": "clips"},
        ]
        out = self.run_stories()
        self.assertEqual(out["storiesFound"], 1)
        self.assertEqual(out["skippedNonStory"], 1)

    def test_foreign_handle_is_skipped(self):
        # An account we never asked about must not enter the corpus.
        self.apify.run_sync.return_value = [
            {**STORY, "username": "vreemde", "user": {"username": "vreemde"}},
        ]
        out = self.run_stories()
        self.assertEqual(out["storiesFound"], 0)
        self.assertEqual(out["skippedNonStory"], 1)


class TestStoryMetadata(StoriesBase):
    def test_mentions_and_hashtags_are_carried(self):
        # A story that @-mentions the brand is a hit whether or not a can is in
        # frame. These were being written as empty lists while the payload
        # carried them.
        item = {**STORY,
                "reel_mentions": [{"user": {"username": "Stelz"}},
                                  {"user": {"username": "lowlands"}}],
                "story_hashtags": [{"hashtag": {"name": "Vrijmibo"}}]}
        self.apify.run_sync.return_value = [item]
        self.run_stories()
        doc = self.posts["instagram_story31415926535"]
        self.assertEqual(doc["mentions"], ["stelz", "lowlands"])
        self.assertEqual(doc["hashtags"], ["vrijmibo"])

    def test_malformed_mention_entries_are_dropped_not_fatal(self):
        item = {**STORY, "reel_mentions": [{}, {"user": {}}, {"user": {"username": "ok"}}]}
        self.apify.run_sync.return_value = [item]
        self.run_stories()
        self.assertEqual(self.posts["instagram_story31415926535"]["mentions"], ["ok"])


class TestPersistence(StoriesBase):
    def test_uses_instagrams_own_expiry_when_given(self):
        # The payload states expiring_at. Preferring it over our arithmetic
        # gives the true countdown for a story near the boundary.
        self.apify.run_sync.return_value = [{**STORY, "expiring_at": STORY["taken_at"] + 3600}]
        self.run_stories()
        doc = self.posts["instagram_story31415926535"]
        self.assertEqual(doc["expiresAt"] - doc["postedAt"], dt.timedelta(hours=1))

    def test_falls_back_to_posted_at_plus_24h(self):
        self.apify.run_sync.return_value = [
            {k: v for k, v in STORY.items() if k != "expiring_at"},
        ]
        self.run_stories()
        doc = self.posts["instagram_story31415926535"]
        self.assertEqual(doc["expiresAt"] - doc["postedAt"], dt.timedelta(hours=24))

    def test_doc_id_and_permalink_shape(self):
        self.apify.run_sync.return_value = [STORY]
        self.run_stories()
        self.assertIn("instagram_story31415926535", self.posts)
        doc = self.posts["instagram_story31415926535"]
        # A story permalink, not the raw CDN jpeg — "open original" must look
        # like a story rather than a stray image.
        self.assertEqual(doc["url"], "https://www.instagram.com/stories/anna/31415926535/")
        self.assertEqual(doc["contentType"], "story")
        self.assertEqual(doc["caption"], "")
        self.assertEqual(doc["hashtags"], [])
        self.assertEqual(doc["creatorTier"], "tier_2")

    def test_post_id_has_exactly_two_segments(self):
        # The frontend groups frames and carousel slots by the first TWO
        # underscore-separated parts of the post id (lib/types.parentPostKey).
        # An id like "instagram_story_123" parses as post "story", so every
        # story in the corpus would collapse into one feed row — the whole
        # feature, invisible. Two stories from the same creator must stay two.
        self.apify.run_sync.return_value = [STORY, {**STORY, "id": "27182818284_314162194"}]
        self.run_stories()
        ids = [k for k in self.posts if k.startswith("instagram_story")]
        self.assertEqual(len(ids), 2, ids)
        for post_id in ids:
            head = "_".join(post_id.split("_")[:2])
            self.assertEqual(head, post_id, f"{post_id} would dedupe into {head}")

    def test_missing_timestamp_is_flagged_as_estimated(self):
        self.apify.run_sync.return_value = [
            {k: v for k, v in STORY.items() if k not in ("taken_at", "expiring_at")},
        ]
        self.run_stories()
        doc = self.posts["instagram_story31415926535"]
        self.assertTrue(doc["postedAtEstimated"])
        self.assertIsNotNone(doc["expiresAt"])

    def test_video_story_enqueues_video_and_its_cover(self):
        # Story video URLs are short-lived signed links that routinely expire in
        # the queue; the cover is the pass that reliably succeeds.
        self.apify.run_sync.return_value = [VIDEO_STORY]
        out = self.run_stories()
        self.assertEqual(out["videosEnqueued"], 1)
        self.assertEqual(out["imagesEnqueued"], 1)

    def test_image_story_enqueues_one_image(self):
        self.apify.run_sync.return_value = [STORY]
        out = self.run_stories()
        self.assertEqual(out["imagesEnqueued"], 1)
        self.assertEqual(out["videosEnqueued"], 0)


class TestCostAndGates(StoriesBase):
    def test_one_run_for_all_handles(self):
        self.creators.update({
            f"instagram_c{i}": {"handle": f"c{i}", "platform": "instagram", "tier": "tier_2"}
            for i in range(20)
        })
        self.run_stories()
        # The run fee dwarfs the per-username price: 21 separate runs would cost
        # roughly sixteen times one batched run.
        self.assertEqual(self.apify.run_sync.call_count, 1)
        actor, payload = self.apify.run_sync.call_args[0][:2]
        self.assertEqual(actor, scan_stories.STORIES_ACTOR)
        self.assertEqual(len(payload["usernames"]), 21)

    def test_records_both_billed_units(self):
        self.run_stories()
        self.assertEqual(self.recorded[0]["apify_story_runs"], 1)
        self.assertEqual(self.recorded[0]["apify_story_usernames"], 1)

    def test_spend_is_recorded_even_when_the_actor_throws(self):
        # The actor start is billed whether or not items come back.
        self.apify.run_sync.side_effect = RuntimeError("actor exploded")
        out = self.run_stories()
        self.assertEqual(out["storiesFound"], 0)
        self.assertEqual(self.recorded[0]["apify_story_runs"], 1)

    def test_budget_gates_refuse_before_spending(self):
        for gate in ("budget_exhausted", "scraping_allowed"):
            with self.subTest(gate=gate):
                self.apify.run_sync.reset_mock()
                self.recorded.clear()
                setattr(self.usage, gate, (lambda bid: True) if gate == "budget_exhausted" else (lambda bid: False))
                out = self.run_stories()
                self.assertIn("skipped", out)
                self.apify.run_sync.assert_not_called()
                self.assertEqual(self.recorded, [])
                # restore
                self.usage.budget_exhausted = lambda bid: False
                self.usage.scraping_allowed = lambda bid: True

    def test_no_tracked_creators_skips_without_spending(self):
        self.creators.clear()
        out = self.run_stories()
        self.assertEqual(out["skipped"], "no_creators")
        self.apify.run_sync.assert_not_called()


class TestEmptyIsNormal(StoriesBase):
    def test_zero_stories_is_a_success_not_an_error(self):
        # Most creators have no active story at any given moment. If this ever
        # reads as a failure, the UI will cry wolf four times a day.
        self.apify.run_sync.return_value = []
        out = self.run_stories()
        self.assertEqual(out["storiesFound"], 0)
        self.assertNotIn("skipped", out)
        self.assertEqual(self.runs_col.added[0]["status"], "ok")


class TestLastRunStamp(StoriesBase):
    """`brands/{id}.stories` is how the panel answers "when did this last look?".

    Three quarters of these sweeps come from the 6-hourly scheduler, which runs
    outside any scan session and therefore writes no step state. Without this
    stamp an empty strip looks identical whether the scheduler ran ten minutes
    ago and found nothing, or stopped firing a week ago.
    """

    def test_success_records_when_and_how_many(self):
        self.apify.run_sync.return_value = [STORY]
        self.run_stories()
        s = self.stamp()
        self.assertEqual(s["lastFound"], 1)
        self.assertEqual(s["lastChecked"], 1)
        self.assertIsNone(s["lastSkipped"])
        self.assertIsNotNone(s["lastRunAt"])

    def test_empty_sweep_still_records(self):
        # The distinction the UI depends on: looked and found nothing.
        self.apify.run_sync.return_value = []
        self.run_stories()
        self.assertEqual(self.stamp()["lastFound"], 0)
        self.assertIsNone(self.stamp()["lastSkipped"])

    def test_skips_record_their_reason(self):
        self.creators.clear()
        self.run_stories()
        self.assertEqual(self.stamp()["lastSkipped"], "no_creators")

    def test_stamping_can_never_fail_the_sweep(self):
        self.brand.set.side_effect = RuntimeError("firestore down")
        self.apify.run_sync.return_value = [STORY]
        out = self.run_stories()
        self.assertEqual(out["storiesFound"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
