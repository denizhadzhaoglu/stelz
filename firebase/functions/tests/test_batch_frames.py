"""Alignment tests for gemini.detect_frames_batch — offline, no API calls.

The batched call is a screen (see detect_video.run), so its failure modes are
about ATTRIBUTION, not detection quality. If a response misaligns, a can seen
in frame 5 gets recorded against frame 0 and the moderator opens the wrong
timestamp — a wrong answer that looks entirely plausible. These pin the
alignment and, just as importantly, pin that ambiguous responses RAISE rather
than guess, because detect_video treats an exception as "analyse every frame"
and only a silent mis-parse can actually lose data.
"""
from __future__ import annotations

import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import gemini  # noqa: E402


class _FakeResp:
    def __init__(self, text: str):
        self.text = text
        self.usage_metadata = types.SimpleNamespace(
            prompt_token_count=100, candidates_token_count=20,
            cached_content_token_count=0, total_token_count=120,
        )


class _FakeModels:
    def __init__(self, text: str):
        self._text = text
        self.last_contents = None

    def generate_content(self, model, contents, config):
        self.last_contents = contents
        return _FakeResp(self._text)


class _FakeClient:
    def __init__(self, text: str):
        self.models = _FakeModels(text)


class BatchTestCase(unittest.TestCase):
    def call(self, payload, n=3, **kw):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        fake = _FakeClient(text)
        orig = gemini.client
        gemini.client = lambda: fake
        try:
            frames = [(i * 10, b"\xff\xd8\xff" + bytes([i])) for i in range(n)]
            return gemini.detect_frames_batch(
                frames, "STELZ", {"hard_seltzer": "Hard Seltzer"}, **kw
            ), fake
        finally:
            gemini.client = orig


class TestAlignment(BatchTestCase):
    def test_returns_one_result_per_frame_in_order(self):
        out, _ = self.call([
            {"frame_index": 0, "detected": False},
            {"frame_index": 1, "detected": True, "visible_text": "STELZ"},
            {"frame_index": 2, "detected": False},
        ])
        self.assertEqual(len(out), 3)
        self.assertTrue(out[1]["detected"])
        self.assertFalse(out[0]["detected"])

    def test_frame_index_wins_over_position(self):
        # The model answered out of order. Honouring frame_index is the whole
        # point of asking for it.
        out, _ = self.call([
            {"frame_index": 2, "detected": True},
            {"frame_index": 0, "detected": False},
            {"frame_index": 1, "detected": False},
        ])
        self.assertTrue(out[2]["detected"])
        self.assertFalse(out[0]["detected"])

    def test_missing_frame_index_falls_back_to_position(self):
        out, _ = self.call([
            {"detected": False}, {"detected": True}, {"detected": False},
        ])
        self.assertTrue(out[1]["detected"])

    def test_unwraps_object_response(self):
        out, _ = self.call({"frames": [
            {"frame_index": 0, "detected": True},
            {"frame_index": 1, "detected": False},
            {"frame_index": 2, "detected": False},
        ]})
        self.assertTrue(out[0]["detected"])

    def test_strips_markdown_fences(self):
        out, _ = self.call(
            '```json\n[{"detected": false},{"detected": true},{"detected": false}]\n```'
        )
        self.assertTrue(out[1]["detected"])

    def test_tags_results_as_batched(self):
        out, _ = self.call([{"detected": False}] * 3)
        self.assertTrue(all(r["batched"] for r in out))
        self.assertTrue(all(r["model"] for r in out))

    def test_empty_frames_short_circuits(self):
        # Must not call the API at all for an empty video.
        self.assertEqual(gemini.detect_frames_batch([], "STELZ", {}), [])


class TestRejectsAmbiguity(BatchTestCase):
    """Every case here MUST raise. detect_video catches the exception and
    analyses all frames individually, so raising is the safe outcome; guessing
    is the one that silently corrupts data."""

    def test_wrong_count_raises(self):
        with self.assertRaises(ValueError):
            self.call([{"detected": False}, {"detected": True}], n=3)

    def test_duplicate_frame_index_raises(self):
        with self.assertRaises(ValueError):
            self.call([
                {"frame_index": 1, "detected": True},
                {"frame_index": 1, "detected": False},
                {"frame_index": 2, "detected": False},
            ])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            self.call({"detected": True})

    def test_non_dict_entry_raises(self):
        with self.assertRaises(ValueError):
            self.call([{"detected": False}, "nope", {"detected": False}])

    def test_out_of_range_index_does_not_crash(self):
        # A nonsense index falls back to position rather than raising — the
        # response is still complete and unambiguous.
        out, _ = self.call([
            {"frame_index": 99, "detected": True},
            {"frame_index": 1, "detected": False},
            {"frame_index": 2, "detected": False},
        ])
        self.assertTrue(out[0]["detected"])


class TestRequestShape(BatchTestCase):
    def test_prompt_precedes_frames_for_prefix_caching(self):
        """[references, prompt, frames] — the references+prompt prefix is
        identical for every video, which is what earns the cached-token
        discount. A frame placed before the prompt would break it."""
        _, fake = self.call([{"detected": False}] * 3,
                            reference_image_bytes=[b"\xff\xd8\xffref"])
        c = fake.models.last_contents
        texts = [i for i, x in enumerate(c) if isinstance(x, str)]
        prompt_at = next(i for i in texts if "STRICT visual brand detector" in c[i])
        first_frame_label = next(i for i in texts if c[i].startswith("FRAME "))
        self.assertLess(prompt_at, first_frame_label)

    def test_every_frame_is_labelled(self):
        _, fake = self.call([{"detected": False}] * 3)
        labels = [x for x in fake.models.last_contents
                  if isinstance(x, str) and x.startswith("FRAME ")]
        self.assertEqual(labels, ["FRAME 0:", "FRAME 1:", "FRAME 2:"])

    def test_prompt_states_the_frame_count(self):
        _, fake = self.call([{"detected": False}] * 3)
        prompt = next(x for x in fake.models.last_contents
                      if isinstance(x, str) and "MULTI-FRAME MODE" in x)
        self.assertIn("exactly 3 objects", prompt)
        self.assertIn("FRAME 0 ... FRAME 2", prompt)

    def test_usage_out_is_populated(self):
        u: dict = {}
        self.call([{"detected": False}] * 3, usage_out=u)
        self.assertEqual(u["prompt_tokens"], 100)
        self.assertEqual(u["frames"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
