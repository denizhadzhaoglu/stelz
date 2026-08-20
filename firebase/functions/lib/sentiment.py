"""Post sentiment: how a hit talks about the brand, not whether it shows it.

Prompt + parsing only. The Gemini call lives in lib/gemini.analyze_sentiment,
the batch driver in handlers/analyze_sentiment.py.

WHY THIS IS A SEPARATE CALL FROM DETECTION
------------------------------------------
The obvious saving would be to add these fields to DETECT_PROMPT_V8 and get
sentiment for free on a call we already make. That is exactly the mistake v8
was written to undo. Sentiment needs the CAPTION; detection is deliberately
pixels-only, and the prompt says so in as many words ("You have NOT been told
what the label text says"). Feeding a caption reading "stelz avond 🍻" into the
detection call gives the model the answer to the question it is being asked —
it starts reporting a readable wordmark on cans it cannot resolve. The comment
above detect_image() records that this already happened once with brand
identity text.

So: detection stays blind, sentiment runs afterwards over the caption of hits
that survived. Text-only, no images, which is also why it is cheap.

SCOPE
-----
Scored only for detected, non-rejected hits. Sentiment on a false positive is
sentiment about someone else's drink.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Stored on the detection doc as `sentiment`. Anything outside this set is
# dropped rather than written — a typo'd label would silently become its own
# bucket in the dashboard's group-by.
LABELS = ("positive", "neutral", "negative", "promotional")

PROMPT = """You are an analyst evaluating consumer sentiment around {brand_name}.

You are given the CAPTION and metadata of a social post that shows the brand.
You cannot see the image. Judge only what the text supports.

Classify the post as ONE of:
- "positive"    : enjoyment, love, recommendation, excitement
- "neutral"     : casual or factual mention, brand present without opinion
- "negative"    : complaint, dislike, bad experience, criticism
- "promotional" : the account is selling or advertising commercially — a bar,
                  retailer, sponsor, or a paid partnership

Also return:
- sentiment_score: -1.0 (very negative) to +1.0 (very positive). neutral ~ 0,
  promotional ~ 0.2.
- sentiment_rationale: ONE short sentence, quoting or naming the words that
  decided it.

Return STRICT JSON ONLY (no prose, no markdown fences):
{{
  "sentiment": "positive" | "neutral" | "negative" | "promotional",
  "sentiment_score": -1.0 to 1.0,
  "sentiment_rationale": "short explanation"
}}

RULES:
1. A venue listing the product on a menu or in a promo is "promotional", not
   "positive". Paid-partnership and ad markers outrank enthusiasm.
2. An empty, emoji-only, or non-committal caption is "neutral". Do not read
   warmth into a caption that carries none — a can in a party photo with the
   caption "zaterdag" is neutral, not positive.
3. Enthusiasm aimed at the night, the festival or the friends is NOT brand
   sentiment. Only credit "positive" when the good feeling attaches to the
   product or to drinking it.
4. Captions are usually Dutch. Judge them in Dutch; do not translate first.
"""


def build_prompt(brand_name: str) -> str:
    return PROMPT.format(brand_name=brand_name)


def build_summary(
    caption: str | None,
    hashtags: list[str] | None = None,
    creator_handle: str | None = None,
    creator_category: str | None = None,
    context: str | None = None,
) -> str:
    """The per-post half of the request.

    `context` is the detector's own one-line description of the scene. It is
    the only visual information in an otherwise text-only call, and it is
    included because "can on a bar counter" vs "friends toasting" changes the
    promotional/neutral call more than anything in the caption does.
    """
    lines = []
    if creator_handle:
        who = f"Creator: @{creator_handle}"
        if creator_category:
            who += f" (category: {creator_category})"
        lines.append(who)
    if context:
        lines.append(f"What the image shows: {context}")
    lines.append(f"Caption: {(caption or '').strip() or '(empty)'}")
    if hashtags:
        lines.append("Hashtags: " + ", ".join(h.lstrip('#') for h in hashtags[:12]))
    return "\n".join(lines)


def parse_verdict(text: str) -> dict[str, Any] | None:
    """Parse the model's JSON. Returns None when the answer is unusable.

    None is a real outcome, not an error path: the caller must leave the field
    unset so the post is retried later, rather than writing a fabricated
    "neutral" that can never be told apart from a genuine one.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", (text or "").strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Model wrapped the object in prose despite the instruction.
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None

    label = str(parsed.get("sentiment") or "").strip().lower()
    if label not in LABELS:
        return None

    score = parsed.get("sentiment_score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        # A missing or unparseable score shouldn't cost us the label, which is
        # what the UI actually groups by. Fall back to the label's midpoint.
        score = {"positive": 0.6, "neutral": 0.0, "negative": -0.6, "promotional": 0.2}[label]
    score = max(-1.0, min(1.0, score))

    rationale = parsed.get("sentiment_rationale")
    rationale = str(rationale).strip()[:300] if rationale else None

    return {
        "sentiment": label,
        "sentiment_score": score,
        "sentiment_rationale": rationale,
    }
