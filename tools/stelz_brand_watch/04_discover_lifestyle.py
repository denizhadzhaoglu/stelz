#!/usr/bin/env python3
"""Discovery v2: build a broad pool of Dutch lifestyle creators.

Strategy: instead of scraping #stelz (which mostly returns retail/horeca),
scrape Dutch lifestyle hashtags where STELZ's actual target audience posts:
students, young adults, house parties, work drinks, friends, festivals.

The output is a ranked pool of candidate creators. A later step runs visual
detection on their recent content to identify who actually shows STELZ.

Usage:
    python3 tools/stelz_brand_watch/04_discover_lifestyle.py
    python3 tools/stelz_brand_watch/04_discover_lifestyle.py --posts-per-tag 100
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_HASHTAG = "apify/instagram-hashtag-scraper"

# NL-specific lifestyle hashtags where STELZ's target audience posts.
# Chosen to be NL-only or NL-dominant so we don't drown in international content.
HASHTAG_GROUPS = {
    "student_life": ["studentenleven", "studentlife", "introweek", "studentenstad"],
    "house_parties": ["huisfeest", "thuisfeest", "huisfeestje", "feestje"],
    "drinks_borrel": ["vrijmibo", "vrijdagmiddagborrel", "borrel", "werkborrel", "afterwork", "kerstborrel"],
    "friends": ["vriendinnenuitje", "vriendengroep", "vrouwenuitje", "ladiesnight", "meidenavond"],
    "festivals_season": ["koningsdag", "kingsday", "zomerfeest", "festivalseizoen"],
    "going_out": ["nachtleven", "uitgaansleven", "gezelligheid"],
}

# Heuristics
BUSINESS_RE = re.compile(
    r"\b(cafe|caf[eé]|restaurant|brasserie|bistro|club|disco|bar |hotel|hostel|inn|"
    r"pizza|sushi|frietzaak|snackbar|grand cafe|stadscafe|schenkerij|slijterij|wijnhuis|"
    r"markt|winkel|supermarkt|albert heijn|jumbo|lidl|dirk|plus |spar|aldi|"
    r"b\.v\.|\bbv\b|n\.v\.|\bnv\b|holding|company|brand|official|"
    r"vereniging|\bvv\b|wvf|stichting|kerk|gemeente|"
    r"agency|studio|productions|media|news|nieuws|krant|magazine|"
    r"festival|event|kermis|tentfeest|tractorpulling|muziekweekend|partyplace)",
    re.IGNORECASE,
)

NL_BIO_HINTS = [
    "amsterdam", "rotterdam", "utrecht", "den haag", "the hague", "eindhoven",
    "groningen", "tilburg", "breda", "nijmegen", "maastricht", "leiden", "delft",
    "haarlem", "alkmaar", "zwolle", "arnhem", "enschede", "wageningen",
    "nederland", "holland", "🇳🇱", "ned", "dutch",
]

NL_CAPTION_WORDS = [
    "gezellig", "lekker", "borrel", "feestje", "weekend", "vrijdag", "zaterdag",
    "vriend", "vriendin", "kroeg", "ijskoud", "proost", "blik", "feest",
    "uitje", "stappen", "dansen", "morgen", "vandaag", "studenten", "hbo", "uni",
]


def apify_run_sync(actor_id: str, run_input: dict, timeout: int = 240) -> list:
    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN not set")
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()


def looks_like_business(handle: str, full_name: str | None) -> bool:
    text = " ".join(filter(None, [handle, full_name])).lower()
    return bool(BUSINESS_RE.search(text))


def nl_signal_score(caption: str, full_name: str | None) -> int:
    text = " ".join(filter(None, [caption, full_name])).lower()
    score = 0
    for w in NL_BIO_HINTS:
        if w in text:
            score += 2
            break
    for w in NL_CAPTION_WORDS:
        if w in text:
            score += 1
    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--posts-per-tag", type=int, default=100)
    parser.add_argument("--groups", nargs="*", default=list(HASHTAG_GROUPS.keys()),
                        help="Which hashtag groups to run")
    args = parser.parse_args()

    hashtags_to_run = []
    for g in args.groups:
        if g in HASHTAG_GROUPS:
            for tag in HASHTAG_GROUPS[g]:
                hashtags_to_run.append((g, tag))

    print(f"Scraping {len(hashtags_to_run)} hashtags @ {args.posts_per_tag} posts each", file=sys.stderr)
    print(f"Estimated cost: ~${len(hashtags_to_run) * args.posts_per_tag * 0.0023:.2f}", file=sys.stderr)

    all_posts = []
    for group, tag in hashtags_to_run:
        print(f"  [{group}] #{tag}...", file=sys.stderr)
        try:
            items = apify_run_sync(ACTOR_HASHTAG, {
                "hashtags": [tag],
                "resultsLimit": args.posts_per_tag,
            })
            print(f"    {len(items)} posts", file=sys.stderr)
            for it in items:
                it["_hashtag"] = tag
                it["_group"] = group
            all_posts.extend(items)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)

    raw_file = OUTPUT_DIR / "lifestyle_raw_posts.json"
    raw_file.write_text(json.dumps(all_posts, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(all_posts)} raw posts -> {raw_file}", file=sys.stderr)

    # Aggregate per creator
    creators: dict = defaultdict(lambda: {
        "handle": None,
        "full_name": None,
        "post_count": 0,
        "hashtags_seen": set(),
        "groups_seen": set(),
        "total_likes": 0,
        "total_comments": 0,
        "sample_urls": [],
        "captions": [],
        "first_seen": None,
        "last_seen": None,
        "nl_score_total": 0,
    })

    for p in all_posts:
        handle = p.get("ownerUsername")
        if not handle:
            continue
        c = creators[handle]
        c["handle"] = handle
        c["full_name"] = c["full_name"] or p.get("ownerFullName")
        c["post_count"] += 1
        c["hashtags_seen"].add(p["_hashtag"])
        c["groups_seen"].add(p["_group"])
        c["total_likes"] += p.get("likesCount") or 0
        c["total_comments"] += p.get("commentsCount") or 0
        if len(c["sample_urls"]) < 3 and p.get("url"):
            c["sample_urls"].append(p["url"])
        cap = (p.get("caption") or "")[:200]
        if cap:
            c["captions"].append(cap)
            c["nl_score_total"] += nl_signal_score(cap, c["full_name"])
        ts = p.get("timestamp")
        if ts:
            if not c["first_seen"] or ts < c["first_seen"]:
                c["first_seen"] = ts
            if not c["last_seen"] or ts > c["last_seen"]:
                c["last_seen"] = ts

    print(f"Unique creators: {len(creators)}", file=sys.stderr)

    # Score and filter
    rows = []
    for handle, c in creators.items():
        is_business = looks_like_business(handle, c["full_name"])
        avg_eng = (c["total_likes"] + c["total_comments"]) / max(c["post_count"], 1)
        nl_score = c["nl_score_total"]
        # Composite score: prefer real creators, diverse hashtag presence, NL signal, engagement
        composite = (
            (0 if is_business else 5)
            + len(c["groups_seen"]) * 3
            + min(c["post_count"], 5)
            + min(nl_score, 10)
            + min(avg_eng / 50, 5)
        )
        rows.append({
            "handle": handle,
            "full_name": c["full_name"] or "",
            "is_business_guess": is_business,
            "composite_score": round(composite, 1),
            "post_count": c["post_count"],
            "groups_count": len(c["groups_seen"]),
            "hashtags_count": len(c["hashtags_seen"]),
            "groups_seen": ",".join(sorted(c["groups_seen"])),
            "hashtags_seen": ",".join(sorted(c["hashtags_seen"])),
            "total_likes": c["total_likes"],
            "total_comments": c["total_comments"],
            "avg_engagement": round(avg_eng, 1),
            "nl_signal_score": nl_score,
            "first_seen": c["first_seen"],
            "last_seen": c["last_seen"],
            "sample_url_1": c["sample_urls"][0] if c["sample_urls"] else "",
            "sample_url_2": c["sample_urls"][1] if len(c["sample_urls"]) > 1 else "",
            "sample_caption": (c["captions"][0] if c["captions"] else "")[:200],
        })

    rows.sort(key=lambda r: r["composite_score"], reverse=True)

    csv_file = OUTPUT_DIR / "lifestyle_creators.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    individuals = [r for r in rows if not r["is_business_guess"]]
    high_signal = [r for r in individuals if r["nl_signal_score"] >= 2 and r["avg_engagement"] >= 50]

    print(f"\n=== DISCOVERY v2 SUMMARY ===", file=sys.stderr)
    print(f"Total creators: {len(rows)}", file=sys.stderr)
    print(f"Individual (not business guess): {len(individuals)}", file=sys.stderr)
    print(f"High signal (NL>=2, eng>=50): {len(high_signal)}", file=sys.stderr)
    print(f"\nTop 20 individual creators by composite score:", file=sys.stderr)
    shown = 0
    for r in rows:
        if r["is_business_guess"]:
            continue
        print(f"  @{r['handle']:<28} {r['full_name'][:30]:<30} score={r['composite_score']:<5} groups={r['groups_count']} posts={r['post_count']} eng={r['avg_engagement']} NL={r['nl_signal_score']}", file=sys.stderr)
        shown += 1
        if shown >= 20:
            break
    print(f"\nWrote: {csv_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
