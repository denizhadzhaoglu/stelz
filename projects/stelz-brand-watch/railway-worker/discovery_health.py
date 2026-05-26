#!/usr/bin/env python3
"""Discovery health report — per-source funnel + conversion metrics.

Answers the central operational question: which discovery sources are
actually finding relevant creators? Which channels are noise?

Reports per brand:
  - Total creators added per source
  - How many are still active (not archived)
  - How many yielded at least 1 verified brand-hit
  - Median days from add → first hit
  - Avg AI relevance score per source

Output formats:
  --output stdout      (default) pretty terminal table
  --output md          markdown table for paste into docs
  --output json        structured for piping

Usage:
    python3 tools/stelz_brand_watch/49_discovery_health.py --brand stelz
    python3 tools/stelz_brand_watch/49_discovery_health.py --brand stelz --output md > report.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def fetch_report(sb, brand_id: str) -> list[dict]:
    """Returns one row per discovery source."""
    sql = """
    WITH creator_stats AS (
      SELECT
        c.id,
        coalesce(c.auto_added_via, '(unknown)') AS source,
        c.created_at,
        c.archived_at,
        c.tier,
        c.relevance_score,
        c.posts_seen,
        c.hits_seen,
        c.last_hit_at
      FROM creators c
      WHERE c.brand_id = %(brand_id)s
    )
    SELECT
      source,
      count(*)                                                       AS total,
      count(*) FILTER (WHERE archived_at IS NULL)                    AS active,
      count(*) FILTER (WHERE archived_at IS NOT NULL)                AS archived,
      count(*) FILTER (WHERE hits_seen > 0)                          AS yielded_hit,
      count(*) FILTER (WHERE tier = 'tier_1' AND archived_at IS NULL) AS tier1_active,
      count(*) FILTER (WHERE tier = 'tier_2' AND archived_at IS NULL) AS tier2_active,
      count(*) FILTER (WHERE relevance_score >= 6)                    AS high_ai_score,
      round(avg(relevance_score) FILTER (WHERE relevance_score IS NOT NULL)::numeric, 1) AS avg_relevance,
      sum(hits_seen)                                                  AS total_hits,
      round(avg(hits_seen) FILTER (WHERE hits_seen > 0)::numeric, 1)  AS avg_hits_when_yielding,
      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from (last_hit_at - created_at)) / 86400.0)
            FILTER (WHERE last_hit_at IS NOT NULL)::numeric, 1)        AS median_days_to_first_hit
    FROM creator_stats
    GROUP BY source
    ORDER BY total DESC;
    """
    # Use rpc via execute_sql isn't available; use direct query via REST is complex.
    # Easier: use individual table queries + python aggregation. But for one-off
    # we can lean on existing supabase rpc if defined, OR use the rest endpoint.
    # Simplest path: pull creators + aggregate in Python (sub-second for 100k rows).
    rows = []
    offset = 0
    while True:
        r = (sb.table("creators")
             .select("id, auto_added_via, archived_at, tier, relevance_score, posts_seen, hits_seen, last_hit_at, created_at")
             .eq("brand_id", brand_id)
             .range(offset, offset + 999).execute().data) or []
        rows.extend(r)
        if len(r) < 1000: break
        offset += 1000

    # Aggregate by source
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        buckets[r.get("auto_added_via") or "(unknown)"].append(r)

    report = []
    for source, items in buckets.items():
        total = len(items)
        active = sum(1 for r in items if not r.get("archived_at"))
        archived = total - active
        yielded = sum(1 for r in items if (r.get("hits_seen") or 0) > 0)
        tier1 = sum(1 for r in items if r.get("tier") == "tier_1" and not r.get("archived_at"))
        tier2 = sum(1 for r in items if r.get("tier") == "tier_2" and not r.get("archived_at"))
        high_ai = sum(1 for r in items if (r.get("relevance_score") or 0) >= 6)
        rel_scores = [float(r["relevance_score"]) for r in items if r.get("relevance_score") is not None]
        avg_rel = round(sum(rel_scores) / len(rel_scores), 1) if rel_scores else None
        total_hits = sum(r.get("hits_seen") or 0 for r in items)
        yielding_hits = [r.get("hits_seen") or 0 for r in items if (r.get("hits_seen") or 0) > 0]
        avg_hits = round(sum(yielding_hits) / len(yielding_hits), 1) if yielding_hits else None
        report.append({
            "source": source,
            "total": total,
            "active": active,
            "archived": archived,
            "yielded_hit": yielded,
            "hit_rate_pct": round(100.0 * yielded / total, 1) if total else 0,
            "tier1_active": tier1,
            "tier2_active": tier2,
            "high_ai_score": high_ai,
            "avg_relevance": avg_rel,
            "total_hits": total_hits,
            "avg_hits_when_yielding": avg_hits,
        })
    report.sort(key=lambda x: -x["total"])
    return report


def render_stdout(report: list[dict], brand_slug: str):
    print(f"\n=== DISCOVERY HEALTH · {brand_slug} ===\n")
    cols = [
        ("source", 36), ("total", 7), ("active", 7), ("archived", 9),
        ("hit %", 7), ("tier1", 6), ("tier2", 6), ("avg AI", 7),
        ("Σhits", 8), ("hits/winner", 12),
    ]
    header = "  ".join(f"{name:>{w}}" if name not in ("source",) else f"{name:<{w}}" for name, w in cols)
    print(header)
    print("-" * len(header))
    for row in report:
        line = "  ".join([
            f"{row['source']:<36}",
            f"{row['total']:>7}",
            f"{row['active']:>7}",
            f"{row['archived']:>9}",
            f"{str(row['hit_rate_pct']) + '%':>7}",
            f"{row['tier1_active']:>6}",
            f"{row['tier2_active']:>6}",
            f"{str(row['avg_relevance'] or '-'):>7}",
            f"{row['total_hits']:>8}",
            f"{str(row['avg_hits_when_yielding'] or '-'):>12}",
        ])
        print(line)
    print("")


def render_markdown(report: list[dict], brand_slug: str) -> str:
    out = [f"# Discovery health · {brand_slug}\n"]
    out.append("| Source | Total | Active | Archived | Hit % | Tier 1 | Tier 2 | Avg AI | Σ hits | Hits/winner |")
    out.append("|--------|------:|------:|--------:|------:|------:|------:|------:|------:|------------:|")
    for row in report:
        out.append(
            f"| `{row['source']}` "
            f"| {row['total']} "
            f"| {row['active']} "
            f"| {row['archived']} "
            f"| {row['hit_rate_pct']}% "
            f"| {row['tier1_active']} "
            f"| {row['tier2_active']} "
            f"| {row['avg_relevance'] or '-'} "
            f"| {row['total_hits']} "
            f"| {row['avg_hits_when_yielding'] or '-'} |"
        )
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", required=True)
    p.add_argument("--output", choices=["stdout", "md", "json"], default="stdout")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_row = sb.table("brands").select("id").eq("slug", args.brand).execute().data
    if not brand_row:
        sys.exit(f"No brand {args.brand}")
    brand_id = brand_row[0]["id"]

    report = fetch_report(sb, brand_id)
    if args.output == "stdout":
        render_stdout(report, args.brand)
    elif args.output == "md":
        print(render_markdown(report, args.brand))
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
