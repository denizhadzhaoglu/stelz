#!/usr/bin/env python3
"""Find Stëlz at Lowlands from people who are NOT on the roster.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/73_lowlands_discovery.py
        ... --per-tag 60            # how deep per event tag (default 40)
        ... --brand-only            # skip the wide event tags entirely
        ... --instagram             # add IG hashtags — BILLED, see below
        ... --since 2026-08-19      # only posts from the festival itself
        ... --dry-run               # show the tag plan and the bill, scrape nothing

WHY THIS EXISTS SEPARATELY FROM 70_tiktok_archive.py
----------------------------------------------------
70 scrapes the 25 roster HANDLES: the people Stëlz is paying. This scrapes
TAGS: everyone else at the same festival. They answer different questions and a
brand needs both — "did the people we paid deliver" is a contract question,
"is anyone else showing our can" is a marketing one — so they are kept in
separate archives and the dashboard labels which is which. A number that mixes
paid and organic reach is worse than either number alone.

Anything posted by a roster handle is dropped here, no matter which tag found
it. It is already in the roster archive and counting it twice would inflate the
organic number with content that was bought.

WHAT IT COSTS
-------------
TikTok is FREE. `clockworks/free-tiktok-scraper` is $0.0000 per result in both
cost tables (lib/usage.COST_PER_UNIT, web/src/lib/costs.ts) and takes hashtags
directly. Instagram is $0.0023 per result and is therefore opt-in, printed
before it runs, and never the default.

The real bill is the ANALYSIS afterwards (74_analyse.py --archive lowlands):
roughly $0.0064 per video, because a clip costs a screen call plus a full look
at each flagged frame. That is why the event tags are capped and the brand tags
are not — see below.

WHY BRAND TAGS ARE UNCAPPED AND EVENT TAGS ARE NOT
--------------------------------------------------
lib/hashtags.py already measured this on the real corpus: `hashtag:stelz`
converts at 55.6%, lifestyle and event tags at roughly 0%. #stelz has a small
pool and nearly every post in it is a can; #lowlands has an enormous pool and
almost none of it is. Taking all of the first and a bounded sample of the
second is not a compromise, it is what the conversion data says to do.

The cap is REPORTED, never silent. A tag that hit its ceiling says so and says
how many it left behind, because "40 of 40" and "40 of 4000" are the same line
on screen and completely different facts.

REPEATABLE
----------
Idempotent on video id, against BOTH this archive and the roster one. Re-running
during a festival adds only what is new, so this can be a cron entry or a button
rather than a one-off. `--since` bounds it to the festival window; without it
the event tags happily return last year's.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firebase" / "functions"))

# Reuse the roster harvester's normalisation and downloads rather than writing a
# second opinion about what a TikTok item is. Its module name starts with a
# digit, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location(
    "_tiktok_archive", Path(__file__).with_name("70_tiktok_archive.py"))
TT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TT)

_espec = importlib.util.spec_from_file_location(
    "_events", Path(__file__).with_name("_events.py"))
E = importlib.util.module_from_spec(_espec)
_espec.loader.exec_module(E)

# Assigned in main() from --event. See the note in 70_tiktok_archive.py.
P: "E.Paths" = None      # this event's discovery archive
ROSTER_INDEXES: list[Path] = []   # the same event's roster archives

APIFY = "https://api.apify.com/v2"
TT_ACTOR = "clockworks/free-tiktok-scraper"
IG_ACTOR = "apify/instagram-hashtag-scraper"
IG_COST_PER_RESULT = 0.0023   # lib/usage.COST_PER_UNIT["apify_ig_results"]

# The tags come from the event definition (web/src/data/events/*.json), where
# they sit next to the roster and the dates instead of in a sixth place. Two
# families, because the split is measured and not a guess: lib/hashtags.py puts
# `hashtag:stelz` at 55.6% post-level conversion and event tags at roughly 0%.
# Brand tags are therefore taken whole and event tags are sampled.
#
# The event list is deliberately short and specific. #festival or #summer2026
# would return a hundred thousand posts and roughly zero cans — that family is
# "creator PROSPECTING ONLY", and prospecting is not what this script is for.

# Per-video analysis cost, from lib/usage.COST_PER_UNIT: one screen call plus a
# full look at the frames it flags. Used only to print an estimate.
ANALYSIS_PER_VIDEO = 0.00288 + 2 * 0.00175


def known_ids() -> set[str]:
    """Ids already archived HERE or as roster content.

    Checking the roster archives too is the load-bearing half: #stelz will
    happily return a roster creator's video, and archiving it here would let it
    be counted as organic reach when it was paid for. Both roster surfaces are
    checked, not just TikTok — an Instagram brand tag returns IG posts, and the
    roster's IG posts live in their own index.
    """
    out: set[str] = set()
    for path in [P.index, *ROSTER_INDEXES]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            for key in ("video_id", "item_id"):
                if row.get(key):
                    out.add(str(row[key]))
            # The roster's Instagram rows are keyed "<shortcode>s<slot>" while a
            # hashtag find is keyed "ig<shortcode>". Same post, two spellings,
            # and without this line the same carousel is archived twice — once
            # as a delivery and once as organic pickup.
            if row.get("short_code"):
                out.add(f"ig{row['short_code']}")
    return out


def scrape_tag(tag: str, limit: int, tok: str) -> list[dict]:
    try:
        r = requests.post(
            f"{APIFY}/acts/{TT_ACTOR.replace('/', '~')}/run-sync-get-dataset-items",
            params={"token": tok, "timeout": 300, "memory": 1024},
            json={"hashtags": [tag], "resultsPerPage": limit,
                  "shouldDownloadVideos": False, "shouldDownloadCovers": False},
            timeout=330,
        )
        r.raise_for_status()
        items = r.json()
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  ✕ #{tag}: {str(e)[:90]}")
        return []


def scrape_tag_ig(tag: str, limit: int, tok: str) -> list[dict]:
    try:
        r = requests.post(
            f"{APIFY}/acts/{IG_ACTOR.replace('/', '~')}/run-sync-get-dataset-items",
            params={"token": tok, "timeout": 300, "memory": 1024},
            json={"hashtags": [tag], "resultsLimit": limit},
            timeout=330,
        )
        r.raise_for_status()
        items = r.json()
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  ✕ IG #{tag}: {str(e)[:90]}")
        return []


def normalise_ig(item: dict) -> list[dict]:
    """Instagram hashtag row -> one archive row per image or video to analyse.

    EVERY SLIDE, NOT JUST THE FIRST. This used to return a single row built from
    `displayUrl`, which is slide one of a carousel — so a ten-slide post was
    judged on its cover and the other nine were never looked at. That is exactly
    the failure 71_ig_posts_archive.py was written to avoid, reintroduced on the
    discovery side, where it bites harder: a stranger's festival dump is far
    more likely to be a carousel with the can somewhere in the middle than a
    booked creator's single hero shot.

    Field names mirror 71's so one analyser reads both archives.
    """
    code = item.get("shortCode") or item.get("code")
    if not code:
        return []
    base = {
        "handle": (item.get("ownerUsername") or "").lower(),
        "short_code": code,
        "url": item.get("url") or f"https://www.instagram.com/p/{code}/",
        "posted_at": item.get("timestamp"),
        "caption": item.get("caption") or "",
        "hashtags": item.get("hashtags") or [],
        "mentions": item.get("mentions") or [],
        # Instagram publishes no play count on a photo and none at all here for
        # a reel scraped by tag. None, never 0 — 0 would read as "nobody saw it".
        "play_count": item.get("videoViewCount"),
        "digg_count": item.get("likesCount"),
        "comment_count": item.get("commentsCount"),
        "share_count": None,
        "follower_count": None,
        "full_name": item.get("ownerFullName"),
        "avatar_url": None,
        "verified": None,
        "is_ad": bool(item.get("isSponsored")),
        "music": None,
        "platform": "instagram",
    }
    children = item.get("childPosts") or []

    def row(vid: str, cover: str | None, video: str | None,
            slot: int, slots: int) -> dict:
        return {
            **base,
            # No underscore in the id. The frontend's parentPostKey groups by
            # the first TWO underscore-separated segments of a post id, so
            # "instagram_post" + "ig_ABC" would parse as post "postig" and
            # collapse every Instagram discovery row into one. That bug has
            # shipped once already. The slot goes in a field, never in the id.
            "video_id": vid,
            "slot": slot,
            "slots": slots,
            "cover_url": cover,
            "download_url": video,
            "duration": item.get("videoDuration"),
            "is_slideshow": slots > 1,
            "media_type": "video" if video else "image",
        }

    if children:
        out = [row(f"ig{code}s{i}", ch.get("displayUrl"), ch.get("videoUrl"),
                   i, len(children))
               for i, ch in enumerate(children)]
    else:
        out = [row(f"ig{code}", item.get("displayUrl"), item.get("videoUrl"), 0, 1)]
    return [r for r in out if r["cover_url"] or r["download_url"]]


def after(entry: dict, since: dt.date | None) -> bool:
    if since is None:
        return True
    raw = entry.get("posted_at")
    if not raw:
        # No timestamp is not evidence it is old. Keep it and let the analysis
        # decide; dropping it here would silently lose festival content.
        return True
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date() >= since
    except Exception:
        return True


def main() -> int:
    global P, ROSTER_INDEXES
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", default="lowlands-2026", choices=E.available(),
                    help="which event's tags, roster and archive (default lowlands-2026)")
    ap.add_argument("--per-tag", type=int, default=None,
                    help="cap per EVENT tag (default: the event's discovery.perTag)")
    ap.add_argument("--per-brand-tag", type=int, default=None,
                    help="ceiling per brand tag (default: the event's "
                         "discovery.perBrandTag) — a pool this size is normally "
                         "exhausted well before it")
    ap.add_argument("--brand-only", action="store_true",
                    help="skip the wide event tags; brand tags convert ~55%%, event ~0%%")
    ap.add_argument("--instagram", action="store_true",
                    help="also scrape IG hashtags — BILLED at $0.0023/result")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="drop posts older than this (the festival window)")
    ap.add_argument("--no-video", action="store_true", help="archive covers only")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the bill, scrape nothing")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    since = None
    if args.since:
        try:
            since = dt.date.fromisoformat(args.since)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}")
            return 2

    ev = E.load(args.event)
    P = E.paths(ev, "discovery")
    ROSTER_INDEXES = [E.paths(ev, k).index for k in ("tiktok", "ig-posts", "stories")]
    per_tag = args.per_tag or int(ev["discovery"]["perTag"])
    per_brand = args.per_brand_tag or int(ev["discovery"]["perBrandTag"])
    plan = [(t, f, per_brand if f == "brand" else per_tag)
            for t, f in E.tags(ev) if not (args.brand_only and f == "event")]
    brand_n = sum(1 for _, f, _ in plan if f == "brand")
    ceiling = sum(lim for _, _, lim in plan)

    print(f"{ev['name']} · {len(plan)} hashtags · {brand_n} merk, "
          f"{len(plan) - brand_n} evenement")
    print(f"TikTok: {TT_ACTOR} — $0.00 per resultaat, {len(plan)} runs")
    if args.instagram:
        print(f"Instagram: {IG_ACTOR} — ${IG_COST_PER_RESULT}/resultaat, "
              f"maximaal ${ceiling * IG_COST_PER_RESULT:.2f}")
    print(f"Bovengrens {ceiling} video's → analyse hooguit "
          f"~${ceiling * ANALYSIS_PER_VIDEO:.2f} "
          f"(74_analyse.py --event {ev['id']} --archive discovery)")
    if since:
        print(f"Alleen posts vanaf {since}")
    print()
    for t, f, lim in plan:
        print(f"  #{t:<20} {f:<6} tot {lim}")
    if args.dry_run:
        print("\n--dry-run: niets gescrapet.")
        return 0

    tok = TT.token()
    if not tok:
        print("APIFY_API_TOKEN not set (and not in firebase/functions/.env)")
        return 2

    P.mkdirs()

    roster = E.roster_accounts(ev)
    print(f"\n{len(roster)} roster-handles worden overgeslagen — die staan al in "
          f"het roster-archief\n")

    # tag -> items, so a video can record which tag surfaced it.
    found: list[tuple[str, str, dict]] = []   # (tag, family, item)
    capped: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(scrape_tag, t, lim, tok): (t, f, lim) for t, f, lim in plan}
        for fut in as_completed(futs):
            t, f, lim = futs[fut]
            items = fut.result()
            # No silent caps: a full page back from the actor means there was
            # more behind it, and "40 of 40" must not read like "40 of all".
            hit_cap = len(items) >= lim
            if hit_cap:
                capped.append((t, lim))
            print(f"  #{t}: {len(items)} video's{' (plafond geraakt)' if hit_cap else ''}")
            found.extend((t, f, it) for it in items)

    if args.instagram:
        # Instagram bills per result and its event-tag pools are enormous with
        # near-zero conversion, so an event decides for itself whether they are
        # worth paying for. Brand tags always are.
        ig_plan = [(t, f, lim) for t, f, lim in plan
                   if f == "brand" or ev["discovery"].get("instagramEventTags")]
        skipped_ig = len(plan) - len(ig_plan)
        if skipped_ig:
            print(f"  IG: {skipped_ig} evenement-tags overgeslagen "
                  f"(discovery.instagramEventTags staat uit)")
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {ex.submit(scrape_tag_ig, t, lim, tok): (t, f, lim) for t, f, lim in ig_plan}
            for fut in as_completed(futs):
                t, f, lim = futs[fut]
                items = fut.result()
                print(f"  IG #{t}: {len(items)} posts")
                found.extend((t, f, {**it, "_ig": True}) for it in items)

    already = known_ids()
    added = dupe = roster_skip = old = no_media = no_video = 0
    seen_now: set[str] = set()
    with P.index.open("a") as idx:
        for tag, family, item in found:
            # One post can be several things to look at: an Instagram carousel
            # is one item with ten slides and the can is rarely on slide one.
            if item.get("_ig"):
                rows = normalise_ig(item)
            else:
                one = TT.normalise(item, "")
                rows = [one] if one else []
            if not rows:
                continue
            # Whole-post decisions, taken once: every slide shares a handle and
            # a timestamp, and skipping slide three of a roster creator's post
            # while keeping slide four would be nonsense.
            if (rows[0].get("handle") or "").lower() in roster:
                roster_skip += 1          # paid content is not organic content
                continue
            if not after(rows[0], since):
                old += 1
                continue
            raw_written = False
            for e in rows:
                vid = str(e["video_id"])
                if vid in already or vid in seen_now:
                    dupe += 1
                    continue
                seen_now.add(vid)

                if not raw_written:
                    (P.raw / f"{rows[0].get('short_code') or vid}.json").write_text(
                        json.dumps(item, indent=1))
                    raw_written = True
                e["raw_file"] = f"{rows[0].get('short_code') or vid}.json"
                # Which tag surfaced this, and how much that tag is worth. Kept
                # per item so a tag's real yield can be measured instead of
                # assumed — the number lib/hashtags.py's priority scheme rests on.
                e["found_via"] = tag
                e["found_via_family"] = family
                e["source"] = "discovery"
                e["event"] = ev["id"]

                e["image_file"] = None
                if e.get("cover_url"):
                    if TT.download(e["cover_url"], P.media / f"{vid}.jpg"):
                        e["image_file"] = f"{vid}.jpg"

                e["video_file"] = None
                e["video_unavailable"] = False
                want_video = not args.no_video and (
                    e.get("download_url") if item.get("_ig") else not e.get("is_slideshow"))
                if want_video:
                    if TT.download_video(e, P.media / f"{vid}.mp4"):
                        e["video_file"] = f"{vid}.mp4"
                    else:
                        e["video_unavailable"] = True
                        no_video += 1

                if not e["image_file"] and not e["video_file"]:
                    # Nothing to look at. A row here could never be analysed and
                    # would sit in the dashboard as a permanent "niet
                    # geanalyseerd".
                    no_media += 1
                    continue

                idx.write(json.dumps(e) + "\n")
                added += 1

    print(f"\n{added} nieuw · {dupe} al gearchiveerd · {roster_skip} van roster-creators "
          f"(overgeslagen) · {old} te oud · {no_media} zonder media")
    if no_video:
        print(f"{no_video} zonder video — alleen de cover, en dat staat in het oordeel")
    if capped:
        print("\nPLAFOND GERAAKT — hier is meer dan we hebben opgehaald:")
        for t, lim in sorted(capped):
            print(f"  #{t}: {lim} opgehaald, er is meer. Verhoog --per-tag om dieper te gaan.")
    total = sum(1 for _ in P.index.open()) if P.index.exists() else 0
    print(f"\nArchief: {total} items in {P.label()}")
    print(f"Analyseer met:\n  ./firebase/functions/venv/bin/python "
          f"tools/stelz_brand_watch/74_analyse.py --event {ev['id']} "
          f"--archive discovery --max-dim 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
