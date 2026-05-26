#!/usr/bin/env python3
"""Per-brand credit budget alerts.

For each brand on a paid plan, computes month-to-date credit burn vs
monthly allotment. Fires Slack + email at three thresholds:
  80%  -> heads up
  95%  -> almost out
  100% -> over budget (additional spend pulls from top-up bucket)

Idempotent: each threshold alerts once per calendar month per brand
(tracked via brand_notification_prefs.last_budget_alert_threshold).

Usage:
    python3 tools/stelz_brand_watch/43_budget_alerts.py
    python3 tools/stelz_brand_watch/43_budget_alerts.py --brand stelz --dry-run
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM = os.getenv("RESEND_FROM", "Spot the Brand <reports@jackandai.com>")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://spotyourbrand.com")

THRESHOLDS = [80, 95, 100]


def month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def slack_post(webhook_url: str, blocks: list, fallback: str) -> bool:
    try:
        r = requests.post(webhook_url, json={"text": fallback, "blocks": blocks}, timeout=10)
        return r.status_code < 300
    except Exception:
        return False


def send_email(to: list[str], subject: str, html: str) -> bool:
    if not RESEND_API_KEY or not to: return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": to, "subject": subject, "html": html},
            timeout=15,
        )
        return r.status_code < 300
    except Exception:
        return False


def build_messages(brand_name: str, brand_slug: str, pct: int, used: int, plan_credits: int) -> tuple:
    headline = {
        80:  f"{brand_name}: 80% of monthly credits used",
        95:  f"{brand_name}: 95% of monthly credits used — top-up soon",
        100: f"{brand_name}: monthly budget exceeded — pulling from top-up",
    }[pct]
    sub = f"{used:,} / {plan_credits:,} credits this month."
    link = f"{DASHBOARD_URL}/account.html?brand={brand_slug}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": headline}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{sub}*"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{link}|Open Account & credits>"}]},
    ]
    html = f"""<!doctype html><html><body style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:32px;color:#222;">
      <h2 style="margin:0 0 12px;">{headline}</h2>
      <p style="color:#444;font-size:15px;">{sub}</p>
      <p style="margin:24px 0;"><a href="{link}" style="background:#FF1300;color:white;padding:12px 22px;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;">Manage credits</a></p>
      <p style="font-size:12px;color:#888;">You're getting this because credit-budget alerts are on. Toggle in Account &gt; Notifications.</p>
    </body></html>"""
    subject = f"[Spot the Brand] {headline}"
    return blocks, headline, subject, html


def compute_pct_used(sb, brand_id: str) -> tuple[int, int, int]:
    """Returns (pct, used_this_month, plan_credits_per_month)."""
    sub = sb.table("subscriptions").select("plan:plans(credits_per_month)").eq("brand_id", brand_id).eq("status", "active").maybe_single().execute().data
    if not sub or not sub.get("plan"):
        return 0, 0, 0
    plan_credits = sub["plan"].get("credits_per_month") or 0
    if plan_credits <= 0:
        return 0, 0, 0
    # Sum debits this month (negative amounts)
    txns = (sb.table("credit_transactions")
            .select("amount")
            .eq("brand_id", brand_id)
            .lt("amount", 0)
            .gte("created_at", month_start_iso())
            .limit(5000).execute().data) or []
    used = sum(-(t.get("amount") or 0) for t in txns)
    pct = int(round(100 * used / plan_credits))
    return pct, used, plan_credits


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    q = sb.table("brand_notification_prefs").select(
        "brand_id, slack_webhook_url, email_recipients, last_budget_alert_at, last_budget_alert_threshold, "
        "brand:brands!inner(id, slug, name)"
    )
    if args.brand:
        prefs = (q.eq("brand.slug", args.brand).execute().data) or []
    else:
        prefs = (q.execute().data) or []
    if not prefs:
        print("No brand_notification_prefs to evaluate.", file=sys.stderr)
        return

    now = datetime.now(timezone.utc)
    this_month = (now.year, now.month)
    alerts_fired = 0

    for row in prefs:
        b = row.get("brand") or {}
        if not b.get("id"):
            continue
        pct, used, plan_credits = compute_pct_used(sb, b["id"])
        if plan_credits == 0:
            continue
        # Which threshold (if any) crossed?
        crossed = None
        for t in THRESHOLDS:
            if pct >= t:
                crossed = t
        if crossed is None:
            continue
        # Idempotency: don't re-alert same threshold within same month
        last_at = row.get("last_budget_alert_at")
        last_thresh = row.get("last_budget_alert_threshold") or 0
        if last_at:
            try:
                last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
                if (last_dt.year, last_dt.month) == this_month and last_thresh >= crossed:
                    continue  # already alerted this band this month
            except Exception:
                pass

        slack_url = (row.get("slack_webhook_url") or "").strip()
        email_recipients = row.get("email_recipients") or []
        if not slack_url and not email_recipients:
            continue  # nowhere to send

        blocks, fallback, subject, html = build_messages(
            b.get("name") or b["slug"], b["slug"], crossed, used, plan_credits,
        )
        print(f"  {b['slug']}: {pct}% used ({used:,}/{plan_credits:,}) -> threshold {crossed}%", file=sys.stderr)
        if args.dry_run:
            continue
        if slack_url:
            slack_post(slack_url, blocks, fallback)
        if email_recipients:
            send_email(email_recipients, subject, html)
        sb.table("brand_notification_prefs").update({
            "last_budget_alert_at": now.isoformat(),
            "last_budget_alert_threshold": crossed,
            "updated_at": now.isoformat(),
        }).eq("brand_id", b["id"]).execute()
        alerts_fired += 1

    print(f"\n=== BUDGET ALERTS: fired {alerts_fired} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
