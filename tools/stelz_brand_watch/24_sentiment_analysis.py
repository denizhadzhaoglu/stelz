#!/usr/bin/env python3
"""Sentiment analysis on STELZ hits.

For each detection (detected=true, not is_false_positive) without a sentiment
yet, classify the post sentiment using Gemini Flash on caption + creator type.

Output:
  sentiment: 'positive' | 'neutral' | 'negative' | 'promotional'
  sentiment_score: -1.0 (negative) to +1.0 (positive)
  sentiment_rationale: one-sentence reasoning

Stores back into detections row.

Usage:
    python3 tools/stelz_brand_watch/24_sentiment_analysis.py
    python3 tools/stelz_brand_watch/24_sentiment_analysis.py --limit 100
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv, dotenv_values
from google import genai
from google.genai import types as genai_types
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

MODEL = "gemini-2.5-flash"

PROMPT = """You're an analyst evaluating consumer sentiment around STËLZ, a Dutch alcoholic beverage brand.

Given a post that mentions or shows STËLZ, classify the sentiment in ONE of:
- "positive"     : user expresses enjoyment, love, recommendation, excitement
- "neutral"      : casual mention, factual ("had a stelz tonight"), product placement without opinion
- "negative"     : complaint, dislike, bad experience, criticism
- "promotional"  : the account is selling, advertising, or promoting STELZ commercially (bar, retailer, sponsor)

Also return:
- sentiment_score: -1.0 (very negative) to +1.0 (very positive). neutral ~ 0. promotional ~ 0.2.
- sentiment_rationale: 1 short sentence explaining your call.

Return ONLY this JSON:
{
  "sentiment": "positive" | "neutral" | "negative" | "promotional",
  "sentiment_score": -1.0 to 1.0,
  "sentiment_rationale": "short explanation"
}

Be precise. A bar that just lists STELZ on a menu is promotional, not positive. A "going out, life is good" post with a STELZ in hand is positive.
"""


def _get_gemini_key():
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"): return env_key
    for p in [PA_ROOT.parent / "dl-orchestrator" / ".env",
              Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env")]:
        if p.exists():
            for k, v in dotenv_values(p).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                    return v.strip()
    raise RuntimeError("no AIza key")


def parse_json(text):
    cleaned = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None


async def analyze(client, summary, semaphore):
    async with semaphore:
        contents = [PROMPT, summary]
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                return parse_json(resp.text or "")
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                return None
        return None


def build_summary(row):
    return (
        f"Creator: @{row['creator_handle']} (category: {row.get('creator_category') or '?'})\n"
        f"Detection: {row.get('product_line')} ({row.get('size_in_frame')}, conf {row.get('confidence')})\n"
        f"Visual context: {row.get('context') or ''}\n"
        f"Post caption: {(row.get('post_caption') or '')[:500]}\n"
        f"Hashtags: {','.join((row.get('post_hashtags') or [])[:10])}"
    )


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Get detections without sentiment yet (only confirmed hits)
    q = (sb.table("v_detections_full")
         .select("detection_id, creator_handle, creator_category, product_line, size_in_frame, confidence, context, post_caption, post_hashtags")
         .eq("brand_id", brand_id)
         .eq("detected", True)
         .eq("is_false_positive", False)
         .is_("sentiment", "null"))
    if args.limit:
        q = q.limit(args.limit)
    rows = q.execute().data or []
    print(f"{len(rows)} detections to score for sentiment", file=sys.stderr)
    if not rows: return

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    semaphore = asyncio.Semaphore(args.concurrency)

    async def process(r):
        result = await analyze(client, build_summary(r), semaphore)
        return r["detection_id"], result

    t0 = time.time()
    results = await asyncio.gather(*[process(r) for r in rows])
    print(f"analyze: {time.time()-t0:.1f}s for {len(rows)}", file=sys.stderr)

    updated = 0
    counts = {}
    for det_id, result in results:
        if not result: continue
        sb.table("detections").update({
            "sentiment": result.get("sentiment"),
            "sentiment_score": result.get("sentiment_score"),
            "sentiment_rationale": result.get("sentiment_rationale"),
        }).eq("id", det_id).execute()
        updated += 1
        counts[result.get("sentiment", "?")] = counts.get(result.get("sentiment", "?"), 0) + 1

    print(f"\n=== SENTIMENT SUMMARY ===", file=sys.stderr)
    print(f"Analyzed: {updated}", file=sys.stderr)
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
