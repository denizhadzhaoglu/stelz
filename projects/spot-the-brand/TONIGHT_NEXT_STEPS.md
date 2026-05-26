# Tonight + tomorrow morning · @spotyourbrand + Stripe + monitoring tool

Status snapshot at 21:35 CET, 17 May 2026.

---

## 1. Tool optimization — DONE on local, NEEDS DEPLOY

**Problem you flagged:** "mis veel postings van de laatste paar dagen, het blijft wel een monitoring tool he."

**Root cause:** the scan worker (`32_process_scan_queue.py` on Railway) was spending 91% of today's scan budget on subculture exploration (vrijmibo, house_parties, student_life, foodies). Known hit-producing creators were only being touched every 9-15h, and `hashtag:stelz` (our best source at 55.6% hit rate) ran only 2 scans today.

**What I changed:**
- `tools/stelz_brand_watch/18_daily_scan.py` — added `--prioritize-hits` flag (orders creators by `hits_seen DESC, last_scraped_at ASC`).
- `tools/stelz_brand_watch/32_process_scan_queue.py` — new aux schedule:
  - **every 2h** — priority sweep: top 60 hit-producers, `--skip-recent-hours 2`. Means new posts from known fans caught within ~2h instead of 9-15h.
  - **every 4h** — broad sweep: 400 oldest creators, `--skip-recent-hours 4`. Full base of 2020 rotates every ~10h.
  - **every 6h** — hashtag harvest (`12_full_stelz_harvest.py`, 300 posts per tag).
  - **every 4h** — stories harvest (unchanged).
  - **every 24h** — perplexity scout (unchanged).
- Synced changes to `projects/stelz-brand-watch/railway-worker/`:
  - `daily_scan.py` + `process_scan_queue.py` updated.
  - `full_stelz_harvest.py` added (was missing from docker image).
  - `Dockerfile` updated with COPY + symlink for `12_full_stelz_harvest.py`.

**Catch-up scans I fired tonight (local):**
- Top 120 hit-producers re-scraped → 24 new posts, 2 hits (most creators were already up-to-date on local rotation).
- Hashtag harvest running in background.

**What you still need to do — DEPLOY:**
```bash
cd projects/stelz-brand-watch/railway-worker
git add -A
git commit -m "Rebalance scan cron: prioritize monitoring over exploration"
git push   # Railway auto-deploys
```
Railway will restart the worker. After ~5 min you'll see the new aux schedule kick in.

---

## 2. First IG feed posts live tomorrow morning

**The chain to fully automate posting is not complete tonight** (needs FB Page link + Graph API token), so for tomorrow morning we go pragmatic.

**Fastest path tonight (5 min on phone):**
1. On your phone, open the Supabase storage URL: `https://menaatbeoeutywulcdvv.supabase.co/storage/v1/object/public/brand-watch-thumbnails/spot-the-brand-ig/organic/grid-manifesto.png`
2. Tap+hold → Save to Photos.
3. Repeat for `grid-stat-split.png` (same URL pattern).
4. Open IG app as @spotyourbrand → new post → pick the saved image → paste caption from `assets/ig-week1/organic/CAPTIONS.md`.

Recommended drops tonight (in order):
- `grid-manifesto.png` — strongest brand statement, great first post on grid
- `grid-stat-split.png` — strong hook, sets up the rest

Schedule for the rest of the week: see `assets/ig-week1/organic/CAPTIONS.md`.

**Full automation path (later this week):**
- Finish MBS chain: FB Page "Spot the Brand" → link @spotyourbrand → 15 min in MBS.
- Generate IG Graph API token: Meta developer portal → 15 min.
- Add `IG_USER_ID` + `IG_ACCESS_TOKEN` to `.env`.
- Run `python tools/ig_publish_organic_week1.py --publish` → all 7 remaining posts go live in sequence.

---

## 3. Stripe Live mode

**What I cannot do for you (Anthropic safety):**
- Enter bank account (IBAN), KvK number, BTW, or identity verification in Stripe activation flow.

**What you need to do (~10 min in Stripe dashboard):**
1. Open https://dashboard.stripe.com
2. Top right: toggle **"Test mode"** OFF
3. Stripe prompts "Activate payments" → fill:
   - Business type: BV / Eenmanszaak
   - KvK number
   - Business address
   - IBAN for payouts
   - BTW number (if applicable)
   - Personal identity check
4. Click submit. Most NL accounts get instant approval.

**What I do once you say "live":**
1. You give me the new `sk_live_xxx` key (paste in chat or update `.env`).
2. I run `python tools/stelz_brand_watch/26_setup_stripe.py --live` → creates products + prices in live mode, backfills `plans.stripe_price_id` to live IDs.
3. You create a new webhook in Stripe dashboard (live mode) → endpoint `https://menaatbeoeutywulcdvv.supabase.co/functions/v1/stripe-webhook` → events: `checkout.session.completed`, `customer.subscription.*`, `invoice.payment_failed` → copy the new `whsec_xxx`.
4. I update Supabase Edge Function secrets via Chrome MCP: `STRIPE_SECRET_KEY=sk_live_xxx`, `STRIPE_WEBHOOK_SECRET=whsec_xxx`.
5. Test a real checkout on landing → first €0.50 test transaction.

Total: ~15 min after your 10-min activation.

---

## 4. Other still-pending (lower priority)

- Meta Ads MCP: switch OAuth dropdown from @spotyourbrand to your personal FB → connects. (For future ads boosting.)
- MBS: create FB Page "Spot the Brand" + link @spotyourbrand (needed for IG Graph publishing).
- IG account: profile pic ✓, website field needs phone, action button needs phone, 2FA needs phone.
- 5 IG Stories: must be uploaded from phone (Graph API doesn't support poll/link stickers).

---

## TL;DR for tomorrow morning

You wake up to:
- ✅ Scanner running on new monitoring-priority cron (top creators every 2h, not every 12h)
- ✅ Hashtag harvest catching new STELZ-tagged posts every 6h instead of "when I remember"
- ✅ 2 posts live on @spotyourbrand (if you spend 5 min tonight)
- ⏳ Stripe live mode (waiting on your 10-min KvK/IBAN flow)
- ⏳ Full IG automation (waiting on FB Page link + token, can do later this week)
