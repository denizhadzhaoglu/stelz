#!/usr/bin/env python3
"""Render a brand insight report as a styled PDF and upload to Storage.

Builds on 23_auto_report.py: reuses its data gathering, then renders a
Spot the Brand themed HTML template and uses Playwright Chromium to
convert it to PDF. The PDF lands in Supabase Storage under
    reports/<brand_slug>/<period>-<YYYYMMDD>.pdf
and the public URL is also stored on the matching `reports` row.

This is meant to be called from the daily/weekly email cron OR ad-hoc:
    python3 tools/stelz_brand_watch/40_render_report_pdf.py --brand stelz --period weekly
    python3 tools/stelz_brand_watch/40_render_report_pdf.py --brand stelz --period monthly

Falls back gracefully when Playwright Chromium isn't available — it just
writes the HTML and leaves a TODO for the operator.
"""

import argparse
import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

REPORTS_BUCKET = "brand-watch-thumbnails"  # reuse existing bucket; folder=reports/
STORAGE_FOLDER = "reports"


def _import_auto_report():
    """Load 23_auto_report.py as a module (filename starts with a digit)."""
    spec = importlib.util.spec_from_file_location(
        "auto_report", PA_ROOT / "tools/stelz_brand_watch/23_auto_report.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render_html(report: dict, brand_name: str) -> str:
    s = report["summary"]
    period = report["period"]
    by_signal = sorted(report["by_source_signal"].items(), key=lambda x: -x[1])
    by_product = sorted(report["by_product_line"].items(), key=lambda x: -x[1])
    top_creators = report["top_creators"][:10]
    top_hits = report["top_hits"][:10]

    def safe(s, n=140):
        return (s or "").replace("<", "&lt;").replace(">", "&gt;")[:n]

    rows_creators = "".join(
        f'<tr><td>@{c["handle"]}</td><td style="text-align:right;font-variant-numeric:tabular-nums;">{c["hits"]}</td></tr>'
        for c in top_creators
    )
    rows_hits = "".join(
        f'<tr><td>@{h["handle"]}</td><td>{(h.get("product_line") or "").replace("_", " ")}</td><td style="text-align:right;">{round(h.get("confidence") or 0, 2)}</td><td><a href="{h.get("post_url") or "#"}">view</a></td></tr>'
        for h in top_hits
    )
    rows_signal = "".join(
        f'<tr><td>{sig.replace("_", " ").title()}</td><td style="text-align:right;font-variant-numeric:tabular-nums;">{cnt}</td></tr>'
        for sig, cnt in by_signal
    )
    rows_product = "".join(
        f'<tr><td>{(line or "logo only").replace("_", " ")}</td><td style="text-align:right;font-variant-numeric:tabular-nums;">{cnt}</td></tr>'
        for line, cnt in by_product
    )

    delta_line = ""
    if s.get("delta_pct") is not None:
        sign = "+" if s["delta"] >= 0 else ""
        delta_line = f'<span style="color:{"#16a34a" if s["delta"] >= 0 else "#dc2626"};font-weight:600;">{sign}{s["delta"]}</span> vs previous period ({sign}{s["delta_pct"]}%)'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{brand_name} report</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; color: #0a0a0a; font-size: 11pt; line-height: 1.5; margin: 0; }}
  .accent {{ color: #FF1300; }}
  header {{ border-bottom: 2px solid #0a0a0a; padding-bottom: 14px; margin-bottom: 22px; display: flex; justify-content: space-between; align-items: baseline; }}
  header h1 {{ font-size: 26pt; margin: 0; letter-spacing: -0.02em; font-weight: 800; }}
  header h1 span {{ color: #FF1300; }}
  header .period {{ font-size: 10pt; color: #555; }}
  h2 {{ font-size: 13pt; margin: 28px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #ddd; letter-spacing: -0.01em; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 18px 0 6px; }}
  .stat {{ background: #f8f8f8; border-left: 3px solid #FF1300; padding: 12px 14px; border-radius: 4px; }}
  .stat .num {{ font-size: 22pt; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }}
  .stat .lbl {{ font-size: 9pt; color: #555; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .delta {{ font-size: 10pt; color: #555; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10pt; }}
  th, td {{ padding: 7px 10px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }}
  th {{ font-size: 9pt; color: #555; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
  a {{ color: #FF1300; text-decoration: none; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  footer {{ margin-top: 36px; padding-top: 14px; border-top: 1px solid #eee; font-size: 9pt; color: #888; display: flex; justify-content: space-between; }}
  .brand-pill {{ display: inline-block; padding: 2px 8px; background: #0a0a0a; color: white; font-size: 8pt; font-weight: 700; letter-spacing: 0.08em; border-radius: 3px; }}
</style></head><body>
<header>
  <div>
    <h1>{brand_name} <span>·</span> {period} report</h1>
    <div class="period">{report["period_start"][:10]} → {report["period_end"][:10]}</div>
  </div>
  <div><span class="brand-pill">SPOT THE BRAND</span></div>
</header>

<div class="summary-grid">
  <div class="stat"><div class="num">{s["total_detections"]}</div><div class="lbl">Detections</div></div>
  <div class="stat"><div class="num">{s["clear_visibility_hits"]}</div><div class="lbl">Clear product hits</div></div>
  <div class="stat"><div class="num">{s["unique_creators"]}</div><div class="lbl">Unique creators</div></div>
  <div class="stat"><div class="num">{s.get("delta", 0)}</div><div class="lbl">Δ vs previous</div></div>
</div>
{f'<div class="delta">{delta_line}</div>' if delta_line else ''}

<div class="two-col">
  <div>
    <h2>Source signal mix</h2>
    <table><thead><tr><th>Signal</th><th style="text-align:right;">Count</th></tr></thead><tbody>{rows_signal}</tbody></table>
  </div>
  <div>
    <h2>Product line distribution</h2>
    <table><thead><tr><th>Product</th><th style="text-align:right;">Count</th></tr></thead><tbody>{rows_product}</tbody></table>
  </div>
</div>

<h2>Top 10 creators this period</h2>
<table><thead><tr><th>Creator</th><th style="text-align:right;">Hits</th></tr></thead><tbody>{rows_creators}</tbody></table>

<h2>Top 10 hits by confidence</h2>
<table><thead><tr><th>Creator</th><th>Product</th><th style="text-align:right;">Conf</th><th>Link</th></tr></thead><tbody>{rows_hits}</tbody></table>

<footer>
  <span>Generated {report["generated_at"][:10]} · spotyourbrand.com</span>
  <span>Spot the Brand by JackandAI</span>
</footer>
</body></html>"""


async def html_to_pdf(html: str, out_path: Path) -> bool:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return False
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.set_content(html, wait_until="networkidle")
        await page.pdf(path=str(out_path), format="A4",
                       margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                       print_background=True)
        await browser.close()
    return True


def upload_pdf(sb, brand_slug: str, period: str, pdf_bytes: bytes) -> str | None:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = f"{STORAGE_FOLDER}/{brand_slug}/{period}-{today}.pdf"
    try:
        sb.storage.from_(REPORTS_BUCKET).upload(
            path=path, file=pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
    except Exception as e:
        print(f"  storage upload err: {e}", file=sys.stderr)
        return None
    return f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{REPORTS_BUCKET}/{path}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", default="stelz")
    p.add_argument("--period", choices=["daily", "weekly", "monthly"], default="weekly")
    p.add_argument("--keep-html", action="store_true", help="Also write HTML alongside PDF (debug)")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_row = sb.table("brands").select("id, slug, name").eq("slug", args.brand).execute().data
    if not brand_row:
        sys.exit(f"Brand {args.brand} not found")
    brand_id = brand_row[0]["id"]
    brand_name = brand_row[0]["name"] or args.brand

    auto_report = _import_auto_report()
    PERIODS = {"daily": 1, "weekly": 7, "monthly": 30}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=PERIODS[args.period])
    print(f"Building {args.period} report for {args.brand}: {start.date()} - {end.date()}", file=sys.stderr)

    data = auto_report.gather_data(sb, brand_id, start, end)
    report = auto_report.build_report(args.brand, args.period, start, end, data)
    html = render_html(report, brand_name)

    out_dir = PA_ROOT / ".tmp" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pdf_path = out_dir / f"{args.brand}-{args.period}-{today}.pdf"
    html_path = out_dir / f"{args.brand}-{args.period}-{today}.html"

    if args.keep_html:
        html_path.write_text(html)
        print(f"  wrote HTML: {html_path}", file=sys.stderr)

    ok = asyncio.run(html_to_pdf(html, pdf_path))
    if not ok:
        html_path.write_text(html)
        print(f"  Playwright not available; wrote HTML only to {html_path}", file=sys.stderr)
        print(f"  run: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)

    pdf_bytes = pdf_path.read_bytes()
    print(f"  wrote PDF: {pdf_path} ({len(pdf_bytes)//1024} KB)", file=sys.stderr)

    public_url = upload_pdf(sb, args.brand, args.period, pdf_bytes)
    if public_url:
        print(f"  storage URL: {public_url}", file=sys.stderr)

    # Stamp the latest reports row of this brand+period with the URL.
    latest = (sb.table("reports").select("id")
              .eq("brand_id", brand_id).eq("period_type", args.period)
              .order("period_end", desc=True).limit(1).execute().data) or []
    if latest:
        sb.table("reports").update({"pdf_url": public_url}).eq("id", latest[0]["id"]).execute()
        print(f"  updated reports.pdf_url on {latest[0]['id']}", file=sys.stderr)

    print(public_url or pdf_path)


if __name__ == "__main__":
    main()
