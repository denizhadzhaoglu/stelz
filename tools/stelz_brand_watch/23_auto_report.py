#!/usr/bin/env python3
"""Auto-report: weekly/monthly insight report per brand.

Generates a markdown + JSON report covering:
- Hit volumes per period
- Top creators (by hit count, by relevance)
- Product-line distribution
- Source signal breakdown (brand-owned / hashtag / mention / visual-only)
- Trend vs previous period
- Top hits with image links (Supabase Storage)
- Auto-archived / promoted creators in period

Stores in `reports` table and (optional) uploads PDF to Supabase Storage.

Usage:
    python3 tools/stelz_brand_watch/23_auto_report.py --brand stelz --period weekly
    python3 tools/stelz_brand_watch/23_auto_report.py --brand stelz --period monthly --output stdout
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

PERIODS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


def gather_data(sb, brand_id: str, start: datetime, end: datetime) -> dict:
    """Pull detections + creators within the period."""
    res = (sb.table("v_detections_full")
           .select("*")
           .eq("brand_id", brand_id)
           .eq("detected", True)
           .eq("is_false_positive", False)
           .gte("posted_at", start.isoformat())
           .lt("posted_at", end.isoformat())
           .order("confidence", desc=True)
           .limit(2000)
           .execute())
    detections = res.data or []

    # Previous period for trend
    prev_start = start - (end - start)
    prev_res = (sb.table("v_detections_full")
                .select("detection_id")
                .eq("brand_id", brand_id)
                .eq("detected", True)
                .eq("is_false_positive", False)
                .gte("posted_at", prev_start.isoformat())
                .lt("posted_at", start.isoformat())
                .limit(2000)
                .execute())
    prev_count = len(prev_res.data or [])

    return {"detections": detections, "prev_count": prev_count}


def classify_signal(d: dict) -> str:
    BRAND_OWNED = {"drinkstelz", "stelz_suriname", "bullseyedistribution", "stanbev_international", "bavaria.bierkoerier", "stelzofficial"}
    handle = (d.get("creator_handle") or "").lower()
    if handle in BRAND_OWNED:
        return "brand_owned"
    tags = [(t or "").lower() for t in (d.get("post_hashtags") or [])]
    if any(t in {"stelz", "drinkstelz", "stelzhardseltzer", "stelzhardlemonade", "stelzhardicedtea"} for t in tags):
        return "hashtag"
    if "@drinkstelz" in (d.get("post_caption") or "").lower():
        return "mention"
    return "visual_only"


def build_report(brand_slug: str, period_name: str, start: datetime, end: datetime, data: dict) -> dict:
    detections = data["detections"]
    prev_count = data["prev_count"]

    n = len(detections)
    delta = n - prev_count
    delta_pct = round((delta / prev_count) * 100) if prev_count > 0 else None

    by_creator = Counter(d["creator_handle"] for d in detections if d.get("creator_handle"))
    top_creators = by_creator.most_common(15)

    by_line = Counter(d.get("product_line") or "none" for d in detections)
    by_signal = Counter(classify_signal(d) for d in detections)

    clear_hits = [d for d in detections
                  if d.get("product_line") in {"hard_lemonade", "hard_seltzer", "hard_iced_tea", "mixed_classics"}
                  and (d.get("is_primary_subject") or d.get("size_in_frame") in {"medium", "large", "dominant"})]

    top_hits = sorted(detections, key=lambda d: (d.get("confidence") or 0), reverse=True)[:10]

    return {
        "brand": brand_slug,
        "period": period_name,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_detections": n,
            "clear_visibility_hits": len(clear_hits),
            "prev_period": prev_count,
            "delta": delta,
            "delta_pct": delta_pct,
            "unique_creators": len(set(by_creator.keys())),
        },
        "by_product_line": dict(by_line),
        "by_source_signal": dict(by_signal),
        "top_creators": [{"handle": h, "hits": c} for h, c in top_creators],
        "top_hits": [{
            "handle": d.get("creator_handle"),
            "post_url": d.get("post_url"),
            "product_line": d.get("product_line"),
            "confidence": d.get("confidence"),
            "context": d.get("context"),
            "posted_at": d.get("posted_at"),
        } for d in top_hits],
    }


def render_markdown(r: dict) -> str:
    s = r["summary"]
    out = [
        f"# {r['brand'].upper()} brand watch — {r['period']} report",
        "",
        f"**Period:** {r['period_start'][:10]} → {r['period_end'][:10]}",
        f"**Generated:** {r['generated_at'][:19].replace('T', ' ')} UTC",
        "",
        "## Summary",
        "",
        f"- **Total detections:** {s['total_detections']}",
        f"- **Clear product hits:** {s['clear_visibility_hits']}",
        f"- **Unique creators:** {s['unique_creators']}",
        f"- **vs previous period:** {'+' if s['delta'] >= 0 else ''}{s['delta']} ({'+' if s['delta_pct'] and s['delta_pct'] >= 0 else ''}{s['delta_pct']}%)" if s.get("delta_pct") is not None else f"- **vs previous period:** new period",
        "",
        "## Source signal breakdown",
        "",
    ]
    for sig, cnt in sorted(r["by_source_signal"].items(), key=lambda x: -x[1]):
        out.append(f"- {sig.replace('_', ' ').title()}: {cnt}")
    out.extend(["", "## Product line distribution", ""])
    for line, cnt in sorted(r["by_product_line"].items(), key=lambda x: -x[1]):
        out.append(f"- {line}: {cnt}")
    out.extend(["", "## Top 15 creators this period", ""])
    for c in r["top_creators"]:
        out.append(f"- **@{c['handle']}** — {c['hits']} hits")
    out.extend(["", "## Top 10 hits by confidence", ""])
    for h in r["top_hits"]:
        out.append(f"- **@{h['handle']}** [{h['product_line']}, conf {h['confidence']}] {h['context'][:120] if h.get('context') else ''}")
        out.append(f"  - [Post link]({h['post_url']})")
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", default="stelz")
    p.add_argument("--period", choices=list(PERIODS.keys()), default="weekly")
    p.add_argument("--output", choices=["db", "stdout", "both"], default="both")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand = sb.table("brands").select("id, slug, name").eq("slug", args.brand).execute().data
    if not brand:
        sys.exit(f"Brand {args.brand} not found")
    brand_id = brand[0]["id"]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=PERIODS[args.period])
    print(f"Generating {args.period} report for {args.brand} ({start.date()} - {end.date()})", file=sys.stderr)

    data = gather_data(sb, brand_id, start, end)
    report = build_report(args.brand, args.period, start, end, data)
    md = render_markdown(report)

    if args.output in ("db", "both"):
        sb.table("reports").insert({
            "brand_id": brand_id,
            "period_type": args.period,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "format": "markdown",
            "content": report,
            "status": "generated",
        }).execute()
        print(f"Stored report in DB", file=sys.stderr)

    if args.output in ("stdout", "both"):
        print(md)


if __name__ == "__main__":
    main()
