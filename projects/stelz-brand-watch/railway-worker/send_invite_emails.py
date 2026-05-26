#!/usr/bin/env python3
"""Send pending team-invite emails.

Polls brand_invites for rows that:
  - have status='pending'
  - have email_sent_at IS NULL
  - haven't expired

For each, sends a "you've been invited to {brand}" email via Resend with the
accept-invite deep link. Marks email_sent_at on success so re-runs don't
double-send.

Resending a copy of the invite is handled by the dashboard UI (the inviter
clicks "Copy link" which surfaces the same token).

Usage:
    python3 tools/stelz_brand_watch/39_send_invite_emails.py
    python3 tools/stelz_brand_watch/39_send_invite_emails.py --dry-run
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


def build_email(brand_name: str, role: str, token: str, inviter_email: str | None) -> tuple[str, str]:
    link = f"{DASHBOARD_URL}/accept-invite.html?token={token}"
    subject = f"You're invited to {brand_name} on Spot the Brand"
    inviter_line = f" by {inviter_email}" if inviter_email else ""
    html = f"""
<!doctype html><html><body style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:32px;color:#222;">
  <h2 style="margin:0 0 12px;">You've been invited{inviter_line}</h2>
  <p style="font-size:15px;line-height:1.6;color:#444;">
    Join the <b>{brand_name}</b> workspace on Spot the Brand as a <b>{role}</b>.
    You'll get access to brand detection dashboards, creator tiers and alerts.
  </p>
  <p style="margin:28px 0;">
    <a href="{link}" style="background:#FF1300;color:white;padding:12px 22px;text-decoration:none;border-radius:8px;font-weight:600;display:inline-block;">Accept invite</a>
  </p>
  <p style="font-size:12px;color:#888;">Or paste this link into your browser:<br>{link}</p>
  <p style="font-size:11px;color:#aaa;margin-top:32px;">This invite expires in 7 days. If you weren't expecting this, you can ignore the email.</p>
</body></html>"""
    return subject, html


def send_email(to: str, subject: str, html: str) -> tuple[bool, str | None]:
    if not RESEND_API_KEY:
        return False, "no RESEND_API_KEY set"
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": [to], "subject": subject, "html": html},
            timeout=15,
        )
        if r.status_code >= 300:
            return False, f"resend {r.status_code}: {r.text[:200]}"
        return True, None
    except Exception as e:
        return False, str(e)


def lookup_inviter_email(sb, user_id: str) -> str | None:
    if not user_id:
        return None
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    headers = {
        "Authorization": f"Bearer {os.getenv('SUPABASE_SECRET_KEY')}",
        "apikey": os.getenv("SUPABASE_SECRET_KEY"),
    }
    try:
        r = requests.get(f"{base}/auth/v1/admin/users/{user_id}", headers=headers, timeout=10)
        if r.status_code == 200:
            return (r.json() or {}).get("email")
    except Exception:
        pass
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    now_iso = datetime.now(timezone.utc).isoformat()
    rows = (sb.table("brand_invites").select(
        "id, email, role, token, invited_by, expires_at, status, email_sent_at, "
        "brand:brands!inner(name, slug)"
    )
    .eq("status", "pending")
    .is_("email_sent_at", "null")
    .gt("expires_at", now_iso)
    .order("created_at", desc=False)
    .limit(args.limit)
    .execute().data) or []

    if not rows:
        print("No invites pending email.", file=sys.stderr)
        return

    print(f"{len(rows)} invite(s) need an email", file=sys.stderr)
    sent = 0
    failed = 0
    for inv in rows:
        brand = inv.get("brand") or {}
        inviter_email = lookup_inviter_email(sb, inv.get("invited_by"))
        subject, html = build_email(brand.get("name") or brand.get("slug") or "your brand",
                                    inv["role"], inv["token"], inviter_email)
        if args.dry_run:
            print(f"  DRY: would send to {inv['email']} ({brand.get('slug')}, {inv['role']})", file=sys.stderr)
            continue
        ok, err = send_email(inv["email"], subject, html)
        if ok:
            sb.table("brand_invites").update({
                "email_sent_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", inv["id"]).execute()
            sent += 1
            print(f"  ✓ {inv['email']}", file=sys.stderr)
        else:
            failed += 1
            print(f"  ✗ {inv['email']}: {err}", file=sys.stderr)

    print(f"\n=== INVITE EMAILS: sent {sent}, failed {failed} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
