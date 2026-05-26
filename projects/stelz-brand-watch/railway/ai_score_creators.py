#!/usr/bin/env python3
"""AI relevance scoring for creators in the seed list.

For each creator without a recent relevance_score, send their bio + 5 sample
captions to Gemini Flash and ask: is this account a real STELZ-relevant
creator (high) or noise (low)?

Score 0-10:
- 9-10: confirmed STELZ promoter or staff
- 7-8: NL party/student/lifestyle creator with high fit
- 4-6: mixed signals, monitor
- 1-3: business/horeca/distributor (still valuable but not UGC creator)
- 0:   irrelevant (gym account, food blog, kids content, etc)

Stores result in creators.ai_summary as JSON and creators.relevance_score as numeric.

Usage:
    python3 tools/stelz_brand_watch/21_ai_score_creators.py
    python3 tools/stelz_brand_watch/21_ai_score_creators.py --limit 50
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

PROMPT = """You are evaluating the relevance of an Instagram or TikTok creator for STËLZ, a Dutch alcoholic beverage brand (hard seltzer, hard lemonade, hard iced tea, mixed classics, 0.0).

Target audience for STËLZ: Dutch 18-30 year olds, party/student/festival/lifestyle.

Given the creator's bio, recent captions and hashtags, score 0-10:
- 9-10: confirmed STELZ promoter, staff, or directly brand-affiliated creator
- 7-8: NL lifestyle/party/student creator with strong product-target fit
- 4-6: NL creator with some fit (food, drink, going out content)
- 2-3: NL business/horeca/distributor (valuable for sales tracking, not UGC)
- 0-1: irrelevant (kids, religion, business outside hospitality, gym, foreign language not NL)

Also classify creator_type as: "ugc_creator" | "horeca" | "retail" | "festival" | "student_org" | "media" | "brand_owned" | "irrelevant"

Return ONLY this JSON:
{
  "relevance_score": 0-10 (number),
  "creator_type": "...",
  "is_dutch_speaker": true|false,
  "primary_content_theme": "short label",
  "audience_fit_rationale": "one sentence why",
  "recommended_action": "promote_tier_1" | "keep_monitoring" | "demote" | "archive"
}
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


async def score_creator(client, summary_text, semaphore):
    async with semaphore:
        contents = [PROMPT, summary_text]
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


def build_summary(creator, content_items):
    parts = [f"Handle: @{creator['handle']}"]
    if creator.get("full_name"): parts.append(f"Full name: {creator['full_name']}")
    if creator.get("bio"): parts.append(f"Bio: {creator['bio'][:300]}")
    if creator.get("follower_count"): parts.append(f"Followers: {creator['follower_count']:,}")
    parts.append(f"Platform: {creator.get('platform','?')}")
    parts.append(f"Category guess: {creator.get('category','?')}")
    if content_items:
        parts.append("\nRecent posts:")
        for ci in content_items[:5]:
            cap = (ci.get("caption") or "")[:200]
            tags = ",".join(ci.get("hashtags") or [])[:120]
            parts.append(f"- {cap} [tags: {tags}]")
    return "\n".join(parts)


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Fetch creators without a score (or stale)
    q = sb.table("creators").select("*").eq("brand_id", brand_id).is_("archived_at", "null")
    if not args.rescore:
        q = q.is_("relevance_score", "null")
    if args.limit:
        q = q.limit(args.limit)
    creators = q.execute().data or []
    print(f"{len(creators)} creators to score", file=sys.stderr)
    if not creators:
        return

    # For each creator, get up to 5 recent content_items
    ids = [c["id"] for c in creators]
    items_by_creator = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i+100]
        r = sb.table("content_items").select("creator_id, caption, hashtags").in_("creator_id", chunk).order("posted_at", desc=True).limit(500).execute()
        for it in (r.data or []):
            items_by_creator.setdefault(it["creator_id"], []).append(it)

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    semaphore = asyncio.Semaphore(args.concurrency)

    async def process(c):
        text = build_summary(c, items_by_creator.get(c["id"], []))
        score_obj = await score_creator(client, text, semaphore)
        return c, score_obj

    t0 = time.time()
    results = await asyncio.gather(*[process(c) for c in creators])
    print(f"scoring: {time.time()-t0:.1f}s for {len(results)} creators", file=sys.stderr)

    updates = 0
    auto_archive = 0
    for c, score_obj in results:
        if not score_obj: continue
        update = {
            "ai_summary": score_obj,
            "relevance_score": score_obj.get("relevance_score"),
            "last_evaluated_at": "now()",
        }
        # Apply recommended action softly (only on creators not manually promoted)
        if c.get("status") != "promoted":
            action = score_obj.get("recommended_action")
            if action == "archive" and score_obj.get("relevance_score", 5) <= 1:
                update["archived_at"] = "now()"
                update["archived_reason"] = f"AI score {score_obj.get('relevance_score')}: {score_obj.get('audience_fit_rationale','')}"
                auto_archive += 1
        sb.table("creators").update(update).eq("id", c["id"]).execute()
        updates += 1

    print(f"\n=== AI SCORING SUMMARY ===", file=sys.stderr)
    print(f"Scored: {updates}", file=sys.stderr)
    print(f"Auto-archived (score<=1): {auto_archive}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=15)
    parser.add_argument("--rescore", action="store_true", help="Re-score all, not just unscored")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
