#!/usr/bin/env python3
"""Fast-lane alerts for new tier_1 creator hits.

Runs every N minutes (Railway cron). For each brand with notification prefs
enabled, finds detections that:
  - belong to a tier_1 creator
  - are detected=true, confidence >= 0.7
  - are not flagged is_false_positive
  - landed since the brand's last_tier1_alert_at

If any new hits found, posts a Slack message to the configured webhook and
sends a heads-up email to email_recipients. Then bumps last_tier1_alert_at
so the same hits don't alert twice.

Idempotent: re-running within seconds is a no-op if nothing new landed.

Usage:
    python3 tools/stelz_brand_watch/37_alert_tier1_hits.py
    python3 tools/stelz_brand_watch/37_alert_tier1_hits.py --brand stelz
    python3 tools/stelz_brand_watch/37_alert_tier1_hits.py --dry-run
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
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://spotyourbrand.com")
MIN_CONFIDENCE = 0.7
FALLBACK_LOOKBACK_HOURS = 24  # first-ever run: how far back to consider


def slack_post(webhook_url: str, blocks: list, fallback_text: str) -> bool:
    try:
        r = requests.post(webhook_url, json={"text": fallback_text, "blocks": blocks}, timeout=10)
        if r.status_code >= 300:
            print(f"  slack err {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  slack exc: {e}", file=sys.stderr)
        return False


def send_email(to: list[str], subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        print("  no RESEND_API_KEY; skipping email send", file=sys.stderr)
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": to, "subject": subject, "html": html},
            timeout=15,
        )
        if r.status_code >= 300:
            print(f"  resend err {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"  resend exc: {e}", file=sys.stderr)
        return False


def build_slack_blocks(brand_name: str, brand_slug: str, hits: list) -> tuple[list, str]:
    n = len(hits)
    header = f"{n} new tier 1 hit{'s' if n != 1 else ''} for {brand_name}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"<{DASHBOARD_URL}/?brand={brand_slug}|Open dashboard>"}
        ]},
    ]
    for h in hits[:10]:
        line = f"*@{h['creator_handle']}* ({h['platform']}) - {h.get('product_line') or 'unspecified'} - conf {round(h['confidence'] or 0, 2)}"
        if h.get("post_url"):
            line += f" - <{h['post_url']}|post>"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    if n > 10:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"+{n-10} more in dashboard"}
        ]})
    return blocks, header


def build_email_html(brand_name: str, brand_slug: str, hits: list) -> tuple[str, str]:
    n = len(hits)
    subject = f"[Spot the Brand] {n} new tier 1 hit{'s' if n != 1 else ''} for {brand_name}"
    rows = ""
    for h in hits[:25]:
        product = h.get("product_line") or "unspecified"
        rows += (
            f"<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;'>@{h['creator_handle']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;color:#888;'>{h['platform']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;'>{product}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;'>{round(h['confidence'] or 0, 2)}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;'><a href='{h.get('post_url') or '#'}'>view</a></td>"
            f"</tr>"
        )
    html = f"""
<!doctype html><html><body style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;padding:24px;">
  <h2 style="margin:0 0 4px;">{n} new tier 1 hit{'s' if n != 1 else ''}</h2>
  <p style="color:#666;margin:0 0 18px;">Detections from your tier 1 creators for <b>{brand_name}</b>.</p>
  <table style="width:100%;border-collapse:collapse;font-size:14px;">
    <thead><tr style="text-align:left;color:#888;font-size:12px;">
      <th style="padding:8px;">Creator</th><th style="padding:8px;">Platform</th>
      <th style="padding:8px;">Product</th><th style="padding:8px;">Conf</th><th style="padding:8px;">Link</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="margin-top:24px;"><a href="{DASHBOARD_URL}/?brand={brand_slug}" style="background:#FF1300;color:white;padding:10px 18px;text-decoration:none;border-radius:6px;display:inline-block;">Open dashboard</a></p>
</body></html>"""
    return subject, html


def process_brand(sb, brand_id: str, brand_name: str, brand_slug: str, prefs: dict, dry_run: bool) -> int:
    """Returns count of new tier 1 hits alerted on."""
    slack_url = (prefs.get("slack_webhook_url") or "").strip()
    email_recipients = prefs.get("email_recipients") or []
    slack_on = bool(prefs.get("slack_alerts_tier1")) and bool(slack_url)
    email_on = bool(email_recipients)

    if not slack_on and not email_on:
        return 0  # nothing to send to

    last_at = prefs.get("last_tier1_alert_at")
    if not last_at:
        last_at = (datetime.now(timezone.utc) - timedelta(hours=FALLBACK_LOOKBACK_HOURS)).isoformat()

    # Pull recent detections via the rich view
    res = (sb.table("v_detections_full")
           .select("detection_id, creator_handle, platform, product_line, confidence, detected_at, post_url, image_url, creator_tier, is_false_positive, detected")
           .eq("brand_id", brand_id)
           .eq("detected", True)
           .eq("creator_tier", "tier_1")
           .gte("detected_at", last_at)
           .gte("confidence", MIN_CONFIDENCE)
           .order("detected_at", desc=True)
           .limit(200).execute()).data or []

    hits = [r for r in res if not r.get("is_false_positive")]
    if not hits:
        return 0

    print(f"  {brand_slug}: {len(hits)} new tier 1 hits since {last_at}", file=sys.stderr)

    if dry_run:
        for h in hits[:5]:
            print(f"    DRY: @{h['creator_handle']} - {h.get('product_line')} - {h.get('detected_at')}", file=sys.stderr)
        return len(hits)

    if slack_on:
        blocks, fallback = build_slack_blocks(brand_name, brand_slug, hits)
        slack_post(slack_url, blocks, fallback)
    if email_on:
        subject, html = build_email_html(brand_name, brand_slug, hits)
        send_email(email_recipients, subject, html)

    newest = max(h["detected_at"] for h in hits if h.get("detected_at"))
    sb.table("brand_notification_prefs").update({
        "last_tier1_alert_at": newest, "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("brand_id", brand_id).execute()

    return len(hits)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to a single brand slug")
    p.add_argument("--dry-run", action="store_true", help="Compute hits but don't send")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    q = sb.table("brand_notification_prefs").select(
        "brand_id, slack_webhook_url, slack_alerts_tier1, email_recipients, last_tier1_alert_at, "
        "brand:brands!inner(id, slug, name)"
    )
    if args.brand:
        prefs_rows = (q.eq("brand.slug", args.brand).execute().data) or []
    else:
        prefs_rows = (q.execute().data) or []

    if not prefs_rows:
        print("No brand_notification_prefs rows found; nothing to alert on.", file=sys.stderr)
        return

    total = 0
    for row in prefs_rows:
        b = row.get("brand") or {}
        if not b.get("id"):
            continue
        n = process_brand(sb, b["id"], b.get("name") or b["slug"], b["slug"], row, args.dry_run)
        total += n

    print(f"\n=== ALERT RUN: {total} tier_1 hits across {len(prefs_rows)} brands ===", file=sys.stderr)


if __name__ == "__main__":
    main()
