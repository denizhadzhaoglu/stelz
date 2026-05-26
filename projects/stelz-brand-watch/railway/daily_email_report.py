#!/usr/bin/env python3
"""Daily email report per active brand.

For every brand with status=active subscription:
1. Aggregate yesterday's detections (posted_at in last 24h, not FP).
2. Aggregate this-week-vs-last-week deltas.
3. Pull top 5 creators ranked by new hits.
4. Send a HTML email via Resend to every brand_users.role=owner|editor.

Sends are throttled to one email per brand per calendar day (via a row in
the reports table) so re-running is idempotent.

Usage:
    python3 tools/stelz_brand_watch/34_daily_email_report.py            # send to all brands
    python3 tools/stelz_brand_watch/34_daily_email_report.py --brand stelz
    python3 tools/stelz_brand_watch/34_daily_email_report.py --dry-run  # build but don't send
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM = os.getenv("RESEND_FROM", "Spot the Brand <reports@jackandai.com>")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://stelz-brand-watch.vercel.app")


def fetch_emails_for_brand(sb, brand_id: str) -> list[str]:
    """Return all brand_users emails (owners + editors) via auth.users.

    auth.users is not exposed through PostgREST by default; we use the
    Supabase admin API endpoint to look up emails per user_id.
    """
    bu = sb.table("brand_users").select("user_id, role").eq("brand_id", brand_id).in_("role", ["owner", "editor"]).execute().data or []
    if not bu:
        return []
    emails = []
    base = os.getenv("SUPABASE_URL").rstrip("/")
    headers = {
        "Authorization": f"Bearer {os.getenv('SUPABASE_SECRET_KEY')}",
        "apikey": os.getenv("SUPABASE_SECRET_KEY"),
    }
    for row in bu:
        try:
            r = requests.get(f"{base}/auth/v1/admin/users/{row['user_id']}", headers=headers, timeout=10)
            if r.status_code == 200:
                em = (r.json() or {}).get("email")
                if em:
                    emails.append(em)
        except Exception as e:
            print(f"  email lookup err for {row['user_id']}: {e}", file=sys.stderr)
    return emails


def build_report(sb, brand) -> dict:
    """Compute yesterday + week metrics for the brand."""
    now = datetime.now(timezone.utc)
    yest_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yest_end   = yest_start + timedelta(days=1)
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    dets = (sb.table("v_detections_full")
            .select("creator_handle, posted_at, detected_at, product_line, image_url, post_url, is_false_positive")
            .eq("brand_id", brand["id"]).eq("detected", True)
            .gte("posted_at", prev_week_start.isoformat())
            .limit(2000).execute().data) or []

    valid = [d for d in dets if not d.get("is_false_positive")]
    yest = [d for d in valid if d.get("posted_at") and yest_start.isoformat() <= d["posted_at"] < yest_end.isoformat()]
    this_wk = [d for d in valid if d.get("posted_at") and d["posted_at"] >= week_start.isoformat()]
    prev_wk = [d for d in valid if d.get("posted_at")
               and prev_week_start.isoformat() <= d["posted_at"] < week_start.isoformat()]

    from collections import Counter
    top_creators = Counter(d["creator_handle"] for d in yest if d.get("creator_handle")).most_common(5)

    return {
        "brand_name": brand["name"],
        "brand_slug": brand["slug"],
        "yesterday_count": len(yest),
        "yesterday_creators": top_creators,
        "yesterday_sample": yest[:3],
        "week_count": len(this_wk),
        "week_delta": len(this_wk) - len(prev_wk),
        "week_delta_pct": (round((len(this_wk)/len(prev_wk) - 1) * 100) if prev_wk else None),
        "date": yest_start.date().isoformat(),
    }


def render_html(report: dict) -> str:
    creators_html = "".join(
        f'<li style="padding:6px 0;color:#444;"><b style="color:#000;">@{h}</b> · {n} hit{"s" if n > 1 else ""}</li>'
        for h, n in report["yesterday_creators"]
    ) or '<li style="color:#888;">No new hits in the last 24h.</li>'
    samples_html = ""
    if report["yesterday_sample"]:
        samples_html = '<div style="margin-top:24px;"><b>Sample hits:</b></div><div style="display:flex;gap:8px;margin-top:8px;">' + \
            "".join(
                f'<a href="{d.get("post_url") or "#"}" style="display:block;"><img src="{d.get("image_url") or ""}" style="width:120px;height:120px;object-fit:cover;border-radius:6px;border:1px solid #ddd;"></a>'
                for d in report["yesterday_sample"][:3]
            ) + '</div>'
    delta_html = ""
    if report["week_delta_pct"] is not None:
        sign = "+" if report["week_delta"] >= 0 else ""
        color = "#22c55e" if report["week_delta"] >= 0 else "#f59e0b"
        delta_html = f'<span style="color:{color};font-size:13px;margin-left:8px;">{sign}{report["week_delta"]} ({sign}{report["week_delta_pct"]}%) vs prev week</span>'
    return f"""\
<!doctype html><html><body style="font-family:-apple-system,system-ui,sans-serif;background:#fafafa;margin:0;padding:24px;color:#222;">
<div style="max-width:580px;margin:0 auto;background:white;border-radius:12px;padding:32px;border:1px solid #eee;">
  <div style="font-size:13px;color:#888;margin-bottom:8px;">Spot the Brand daily · {report["date"]}</div>
  <h1 style="font-size:22px;margin:0 0 18px;">{report["brand_name"]}</h1>
  <div style="display:flex;gap:20px;margin-bottom:24px;">
    <div><div style="font-size:32px;font-weight:700;">{report["yesterday_count"]}</div>
         <div style="font-size:12px;color:#888;text-transform:uppercase;">hits yesterday</div></div>
    <div><div style="font-size:32px;font-weight:700;">{report["week_count"]}</div>
         <div style="font-size:12px;color:#888;text-transform:uppercase;">last 7 days{delta_html}</div></div>
  </div>
  <h3 style="font-size:14px;text-transform:uppercase;letter-spacing:0.06em;color:#888;margin:0 0 8px;">Top creators yesterday</h3>
  <ul style="list-style:none;padding:0;margin:0;">{creators_html}</ul>
  {samples_html}
  <div style="margin-top:32px;text-align:center;">
    <a href="{DASHBOARD_URL}" style="display:inline-block;padding:12px 24px;background:#FF1300;color:white;text-decoration:none;border-radius:8px;font-weight:500;">Open dashboard →</a>
  </div>
  <div style="margin-top:32px;font-size:11px;color:#aaa;text-align:center;">
    Spot the Brand by JackandAI · <a href="mailto:hello@jackandai.com" style="color:#aaa;">support</a> · <a href="{DASHBOARD_URL}/account.html" style="color:#aaa;">unsubscribe</a>
  </div>
</div>
</body></html>"""


def send_via_resend(to: list[str], subject: str, html: str) -> tuple[bool, str]:
    if not RESEND_API_KEY:
        return False, "RESEND_API_KEY not set"
    r = requests.post("https://api.resend.com/emails",
                      headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                      json={"from": RESEND_FROM, "to": to, "subject": subject, "html": html},
                      timeout=20)
    if r.status_code >= 400:
        return False, r.text[:300]
    return True, r.json().get("id", "")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Only run for this brand slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    q = sb.table("brands").select("id, slug, name").eq("active", True)
    if args.brand:
        q = q.eq("slug", args.brand)
    brands = q.execute().data or []
    print(f"Processing {len(brands)} brand(s)", file=sys.stderr)

    sent = 0
    skipped = 0
    today = datetime.now(timezone.utc).date().isoformat()

    for brand in brands:
        # Idempotency: already sent today?
        existing = (sb.table("reports").select("id")
                    .eq("brand_id", brand["id"]).eq("period_type", "daily_email")
                    .gte("created_at", today).limit(1).execute().data)
        if existing and not args.dry_run:
            print(f"  {brand['slug']}: already sent today, skip", file=sys.stderr)
            skipped += 1
            continue

        report = build_report(sb, brand)
        html = render_html(report)
        subject = f"Spot the Brand · {report['yesterday_count']} new hit{'' if report['yesterday_count'] == 1 else 's'} for {brand['name']}"

        recipients = fetch_emails_for_brand(sb, brand["id"])
        if not recipients:
            print(f"  {brand['slug']}: no recipients, skip", file=sys.stderr)
            skipped += 1
            continue

        if args.dry_run:
            print(f"  {brand['slug']}: would send '{subject}' to {recipients}", file=sys.stderr)
            sent += 1
            continue

        ok, msg = send_via_resend(recipients, subject, html)
        if ok:
            yest_start = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sb.table("reports").insert({
                "brand_id": brand["id"],
                "period_type": "daily_email",
                "period_start": yest_start.isoformat(),
                "period_end": (yest_start + timedelta(days=1)).isoformat(),
                "format": "html",
                "content": subject,
                "sent_to": ", ".join(recipients),
                "status": "sent",
            }).execute()
            sent += 1
            print(f"  {brand['slug']}: sent to {len(recipients)} recipient(s)", file=sys.stderr)
        else:
            print(f"  {brand['slug']}: send failed: {msg}", file=sys.stderr)

    print(f"\n=== DAILY EMAIL SUMMARY: sent={sent} skipped={skipped} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
