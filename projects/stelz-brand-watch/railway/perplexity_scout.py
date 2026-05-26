#!/usr/bin/env python3
"""Perplexity scout: weekly intelligence on STELZ-related news, activations, creators.

Uses Perplexity API to surface things our scrapers don't see:
- Brand activations (Ibiza trip, festival sponsorships, etc)
- New ambassadors/creator partnerships
- Press coverage of STELZ
- Competitive landscape signals

Output goes to discovery_queue (potential creators) and writes a summary
note that the dashboard can show as a "weekly intelligence" panel.

Usage:
    python3 tools/stelz_brand_watch/22_perplexity_scout.py
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY")

QUERIES = [
    "What recent STËLZ Hard Seltzer activations, campaigns or sponsorships happened in the Netherlands in the last 30 days?",
    "Which Dutch Instagram or TikTok creators have recently partnered with STËLZ Hard Seltzer? Give specific handles if possible.",
    "What are the top trending Dutch festivals, student events, or party brands where STËLZ Hard Seltzer is being served or sponsored?",
    "Any news about STËLZ Hard Seltzer expansion (Suriname, Belgium, Germany) or new product launches in 2026?",
]


def perplexity_query(prompt: str) -> dict:
    if not PERPLEXITY_KEY:
        return {"error": "PERPLEXITY_API_KEY not set"}
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
        json={
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "You are a brand intelligence analyst. Answer concisely with facts and sources. If you mention a creator, prefix their handle with @."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60,
    )
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return r.json()


def extract_handles(text: str) -> list[str]:
    import re
    return list(set(re.findall(r"@([a-zA-Z0-9._]+)", text)))


def main():
    p = argparse.ArgumentParser()
    args = p.parse_args()

    if not PERPLEXITY_KEY:
        sys.exit("PERPLEXITY_API_KEY not in .env -- skipping scout.")

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    all_findings = []
    all_handles = set()
    for q in QUERIES:
        print(f"Querying: {q[:80]}...", file=sys.stderr)
        result = perplexity_query(q)
        if "error" in result:
            print(f"  err: {result['error']}", file=sys.stderr)
            continue
        try:
            content = result["choices"][0]["message"]["content"]
            citations = result.get("citations", [])
        except (KeyError, IndexError):
            print(f"  unexpected response shape", file=sys.stderr)
            continue
        handles = extract_handles(content)
        all_handles.update(handles)
        all_findings.append({
            "question": q,
            "answer": content,
            "handles_mentioned": handles,
            "citations": citations,
        })
        print(f"  found {len(handles)} handles, {len(citations)} citations", file=sys.stderr)

    # Add handles to discovery_queue (cross-platform, default IG)
    for handle in all_handles:
        try:
            sb.table("discovery_queue").upsert({
                "brand_id": brand_id,
                "platform": "instagram",
                "handle": handle,
                "source": "perplexity_scout",
                "signal_count": 3,  # Perplexity surface = high-trust signal, auto-add threshold
            }, on_conflict="brand_id,platform,handle").execute()
        except Exception as e:
            print(f"  queue upsert err {handle}: {e}", file=sys.stderr)

    # Store findings as discovery_runs row for audit
    sb.table("discovery_runs").insert({
        "brand_id": brand_id,
        "source_type": "perplexity_scout",
        "source_value": json.dumps([f["question"] for f in all_findings])[:1000],
        "status": "completed",
        "results_count": len(all_handles),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": json.dumps(all_findings)[:5000] if all_findings else None,  # Stash findings in error col (no better place yet)
    }).execute()

    print(f"\n=== PERPLEXITY SCOUT SUMMARY ===", file=sys.stderr)
    print(f"Queries: {len(QUERIES)}", file=sys.stderr)
    print(f"Unique handles surfaced: {len(all_handles)}", file=sys.stderr)
    print(f"Findings dumped to discovery_runs", file=sys.stderr)
    for f in all_findings:
        print(f"\n>>> {f['question'][:80]}", file=sys.stderr)
        print(f["answer"][:400], file=sys.stderr)


if __name__ == "__main__":
    main()
