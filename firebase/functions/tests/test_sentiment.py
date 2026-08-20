"""Tests for lib/sentiment.py — prompt inputs and verdict parsing.

The parsing half is where the risk sits. Sentiment is a four-way label that
the dashboard groups by, so anything this module lets through becomes a bucket
on a chart shown to the brand. Two failure modes matter more than the rest:

  * a label outside the fixed set (a typo, a translated word, an invented
    fifth category) silently becoming its own slice;
  * an unusable answer being rounded to "neutral", which is indistinguishable
    from a real neutral once written and can never be retried.

Both are rejections here, not repairs.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import sentiment  # noqa: E402


class TestParseVerdict(unittest.TestCase):
    def test_plain_json(self):
        got = sentiment.parse_verdict(
            '{"sentiment": "positive", "sentiment_score": 0.8, "sentiment_rationale": "loves it"}'
        )
        self.assertEqual(got["sentiment"], "positive")
        self.assertEqual(got["sentiment_score"], 0.8)
        self.assertEqual(got["sentiment_rationale"], "loves it")

    def test_markdown_fenced_json(self):
        got = sentiment.parse_verdict(
            '```json\n{"sentiment": "negative", "sentiment_score": -0.7}\n```'
        )
        self.assertEqual(got["sentiment"], "negative")

    def test_json_wrapped_in_prose(self):
        got = sentiment.parse_verdict(
            'Here is my answer:\n{"sentiment": "neutral", "sentiment_score": 0.0}\nHope that helps.'
        )
        self.assertEqual(got["sentiment"], "neutral")

    def test_unknown_label_is_rejected(self):
        """An off-set label must not reach Firestore. 'mixed' is not one of the
        four the UI knows how to render, and writing it would put an unlabelled
        slice on the dashboard."""
        self.assertIsNone(sentiment.parse_verdict('{"sentiment": "mixed", "sentiment_score": 0.1}'))

    def test_dutch_label_is_rejected(self):
        """Captions are Dutch and the model occasionally answers in kind."""
        self.assertIsNone(sentiment.parse_verdict('{"sentiment": "positief", "sentiment_score": 0.8}'))

    def test_label_is_case_and_space_insensitive(self):
        got = sentiment.parse_verdict('{"sentiment": " Promotional ", "sentiment_score": 0.2}')
        self.assertEqual(got["sentiment"], "promotional")

    def test_empty_and_garbage_return_none(self):
        for bad in ("", "   ", "no json here at all", "{not json}", "null", "[]"):
            with self.subTest(bad=bad):
                self.assertIsNone(sentiment.parse_verdict(bad))

    def test_missing_score_falls_back_to_label_midpoint(self):
        """The label is what the UI groups by; losing the whole verdict over a
        missing number would throw away the useful half."""
        got = sentiment.parse_verdict('{"sentiment": "positive"}')
        self.assertEqual(got["sentiment"], "positive")
        self.assertEqual(got["sentiment_score"], 0.6)

    def test_unparseable_score_falls_back_too(self):
        got = sentiment.parse_verdict('{"sentiment": "negative", "sentiment_score": "very bad"}')
        self.assertEqual(got["sentiment_score"], -0.6)

    def test_out_of_range_score_is_clamped(self):
        self.assertEqual(
            sentiment.parse_verdict('{"sentiment": "positive", "sentiment_score": 4.2}')["sentiment_score"],
            1.0,
        )
        self.assertEqual(
            sentiment.parse_verdict('{"sentiment": "negative", "sentiment_score": -9}')["sentiment_score"],
            -1.0,
        )

    def test_rationale_is_optional_and_bounded(self):
        got = sentiment.parse_verdict('{"sentiment": "neutral", "sentiment_score": 0}')
        self.assertIsNone(got["sentiment_rationale"])
        long = sentiment.parse_verdict(
            '{"sentiment": "neutral", "sentiment_score": 0, "sentiment_rationale": "%s"}' % ("x" * 500)
        )
        self.assertEqual(len(long["sentiment_rationale"]), 300)


class TestBuildSummary(unittest.TestCase):
    def test_empty_caption_is_stated_not_omitted(self):
        """A missing caption is information — rule 2 of the prompt turns it into
        'neutral'. Dropping the line entirely would leave the model guessing
        whether a caption existed at all."""
        s = sentiment.build_summary(caption=None)
        self.assertIn("(empty)", s)

    def test_whitespace_caption_counts_as_empty(self):
        self.assertIn("(empty)", sentiment.build_summary(caption="   \n  "))

    def test_includes_context_and_creator(self):
        s = sentiment.build_summary(
            caption="lekker weekend",
            hashtags=["#vrijmibo", "festival"],
            creator_handle="anna",
            creator_category="lifestyle",
            context="friends toasting on a terrace",
        )
        self.assertIn("@anna", s)
        self.assertIn("lifestyle", s)
        self.assertIn("friends toasting", s)
        self.assertIn("vrijmibo", s)

    def test_hashtags_are_capped(self):
        s = sentiment.build_summary(caption="x", hashtags=[f"t{i}" for i in range(40)])
        self.assertEqual(s.count(","), 11)  # 12 tags → 11 separators


class TestPrompt(unittest.TestCase):
    def test_brand_name_is_interpolated(self):
        self.assertIn("Stelz", sentiment.build_prompt("Stelz"))

    def test_prompt_has_no_stray_format_placeholders(self):
        """The JSON block is escaped with {{ }}; a slip there raises at runtime
        on the first real call rather than here."""
        p = sentiment.build_prompt("Stelz")
        self.assertIn('"sentiment":', p)
        self.assertNotIn("{{", p)


if __name__ == "__main__":
    unittest.main()
