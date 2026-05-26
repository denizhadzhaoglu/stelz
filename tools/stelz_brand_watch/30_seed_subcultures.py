#!/usr/bin/env python3
"""Seed initial subcultures for STELZ + classify existing creators.

The seed list is hand-curated for STELZ based on its target audience:
Dutch hard seltzer drinkers in their 20s/30s, with strong student-life,
festival, and house-party signals. New brands later get their own seed.

Classification approach (cheap, deterministic, no Gemini needed for seed):
1. For each creator, gather all their post hashtags from content_items.
2. For each subculture, check if any of its signature_hashtags appear in
   the creator's hashtag history. If yes, link with hashtag_match.
3. Also link by creator.category mapping (horeca -> horeca subculture etc).
4. Confidence scales with number of matching signals.

Run repeatedly: it's idempotent (uses upsert).

Usage:
    python3 tools/stelz_brand_watch/30_seed_subcultures.py
    python3 tools/stelz_brand_watch/30_seed_subcultures.py --reclassify  # also re-run on already-classified creators
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


# Brand-specific seed. New brands plug in their own list here later.
STELZ_SUBCULTURES = [
    {
        "slug": "student_life",
        "name": "Student life",
        "description": "Dutch student culture: dorms, study breaks, week-night drinks, gradutation parties.",
        "signature_hashtags": [
            "studentenleven", "studenten", "studentlife", "studentehuis",
            "huisfeest", "borrel", "studentenstad", "leiden", "groningen",
            "utrechtstudent", "amsterdamstudent", "rotterdamstudent",
        ],
        "signature_keywords": ["student", "studeren", "huisfeest", "borrel", "dorm", "studentenkamer"],
        "category_match": ["student_org"],
        "color": "#60a5fa",
        "emoji": "🎓",
    },
    {
        "slug": "vrijmibo",
        "name": "Vrijdagmiddagborrel",
        "description": "The Dutch Friday-afternoon-drink ritual: colleagues winding down, terraces, after-work drinks.",
        "signature_hashtags": [
            "vrijmibo", "vrijdagmiddagborrel", "vrijdagborrel", "borrel", "happyhour",
            "vrijdag", "weekend", "afterwork",
        ],
        "signature_keywords": ["vrijmibo", "vrijdagmiddag", "happy hour", "afterwork"],
        "category_match": [],
        "color": "#fb923c",
        "emoji": "🍻",
    },
    {
        "slug": "festivals_events",
        "name": "Festivals & events",
        "description": "Dutch festival scene: Koningsdag, summer festivals, music events, outdoor party culture.",
        "signature_hashtags": [
            "festival", "koningsdag", "kingsday", "amsterdamdance", "lowlands",
            "awakenings", "intothenight", "extrema", "pinkpop", "dgtl",
            "ade", "pride", "queensday",
        ],
        "signature_keywords": ["festival", "koningsdag", "summer", "outdoor"],
        "category_match": ["festival"],
        "color": "#f472b6",
        "emoji": "🎉",
    },
    {
        "slug": "house_parties",
        "name": "House parties & pregames",
        "description": "Pre-going-out at someone's place, group gatherings, intimate party content.",
        "signature_hashtags": [
            "huisfeest", "preparty", "voorfeest", "feestje", "drinks",
            "feest", "party", "girlsnight", "boysnight",
        ],
        "signature_keywords": ["huisfeest", "feestje", "preparty", "house party"],
        "category_match": [],
        "color": "#a78bfa",
        "emoji": "🏠",
    },
    {
        "slug": "horeca_nightlife",
        "name": "Horeca & nightlife",
        "description": "Cafes, bars, clubs and restaurants stocking and serving STELZ.",
        "signature_hashtags": [
            "cafe", "bar", "nachtleven", "uitgaan", "club", "horeca",
            "amsterdamnightlife", "rotterdamcafe", "denhaagbar",
        ],
        "signature_keywords": ["cafe", "bar", "restaurant", "horeca", "nightlife", "uitgaan"],
        "category_match": ["horeca"],
        "color": "#fbbf24",
        "emoji": "🍸",
    },
    {
        "slug": "foodies_lifestyle",
        "name": "Foodies & lifestyle",
        "description": "Influencers around food, cocktails, drinks pairing, lifestyle aesthetic.",
        "signature_hashtags": [
            "foodie", "cocktails", "drinks", "lifestyle", "drinkstagram",
            "drinkrecipes", "summerdrinks", "mocktail",
        ],
        "signature_keywords": ["foodie", "cocktail", "lifestyle", "recipe"],
        "category_match": [],
        "color": "#34d399",
        "emoji": "🥂",
    },
    {
        "slug": "retail_promo",
        "name": "Retail & supermarket promo",
        "description": "Supermarkets (Albert Heijn, Jumbo, Plus) and liquor stores promoting STELZ deals.",
        "signature_hashtags": [
            "albertheijn", "jumbo", "plus", "aanbieding", "deal", "korting",
            "folder", "weekaanbieding",
        ],
        "signature_keywords": ["albert heijn", "jumbo", "aanbieding", "supermarkt", "korting"],
        "category_match": ["retail"],
        "color": "#ef4444",
        "emoji": "🛒",
    },
    {
        "slug": "fitness_wellness",
        "name": "Fitness & wellness (0.0 angle)",
        "description": "Sports, gym, run clubs — non-alc STELZ 0.0 angle. Health-conscious consumers.",
        "signature_hashtags": [
            "fitness", "gym", "run", "running", "hardlopen", "yoga",
            "padel", "padelnederland", "fitfam",
        ],
        "signature_keywords": ["fitness", "gym", "running", "padel", "yoga", "0.0"],
        "category_match": [],
        "color": "#22d3ee",
        "emoji": "🏃",
    },
    {
        "slug": "expats_internationals",
        "name": "Expats & internationals",
        "description": "English-speaking expat community in NL; international students, professionals.",
        "signature_hashtags": [
            "expat", "expatlife", "amsterdamexpat", "internationalstudents",
            "thehague", "english",
        ],
        "signature_keywords": ["expat", "international", "english"],
        "category_match": [],
        "color": "#c084fc",
        "emoji": "🌍",
    },
    {
        "slug": "media_press",
        "name": "Media & press",
        "description": "Drinks media, business press, marketing publications writing about STELZ.",
        "signature_hashtags": ["marketingtribune", "adformatie", "fmt", "fmt_marketing"],
        "signature_keywords": ["marketing", "media", "press"],
        "category_match": ["media"],
        "color": "#94a3b8",
        "emoji": "📰",
    },
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reclassify", action="store_true",
                   help="Re-classify all creators, not just unclassified ones")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # 1. Upsert the subcultures themselves.
    print(f"Seeding {len(STELZ_SUBCULTURES)} subcultures for STELZ...", file=sys.stderr)
    subc_by_slug = {}
    for sc in STELZ_SUBCULTURES:
        row = {
            "brand_id": brand_id,
            "slug": sc["slug"],
            "name": sc["name"],
            "description": sc["description"],
            "signature_hashtags": sc["signature_hashtags"],
            "signature_keywords": sc["signature_keywords"],
            "color": sc.get("color"),
            "emoji": sc.get("emoji"),
            "status": "active",
        }
        res = sb.table("subcultures").upsert(row, on_conflict="brand_id,slug").execute()
        subc_by_slug[sc["slug"]] = {"id": res.data[0]["id"], "spec": sc}
    print(f"  ✓ {len(subc_by_slug)} subcultures in DB", file=sys.stderr)

    # 2. Pull creators + their hashtag history.
    print("Loading creators + their post hashtags...", file=sys.stderr)
    creators = []
    offset = 0
    while True:
        r = (sb.table("creators")
             .select("id, handle, category")
             .eq("brand_id", brand_id)
             .range(offset, offset+999)
             .execute())
        if not r.data: break
        creators.extend(r.data)
        if len(r.data) < 1000: break
        offset += 1000
    print(f"  {len(creators)} creators", file=sys.stderr)

    # Get hashtags per creator (aggregate over their posts).
    print("Fetching hashtags per creator...", file=sys.stderr)
    creator_hashtags = defaultdict(set)
    offset = 0
    while True:
        r = (sb.table("content_items")
             .select("creator_id, hashtags, caption")
             .eq("brand_id", brand_id)
             .range(offset, offset+999)
             .execute())
        if not r.data: break
        for ci in r.data:
            tags = ci.get("hashtags") or []
            for t in tags:
                if t: creator_hashtags[ci["creator_id"]].add(t.lower())
        if len(r.data) < 1000: break
        offset += 1000
    print(f"  hashtags collected for {len(creator_hashtags)} creators", file=sys.stderr)

    # 3. Classify each creator against each subculture.
    print("Classifying...", file=sys.stderr)
    new_links = 0
    creator_score = defaultdict(lambda: defaultdict(int))  # creator_id -> subc_id -> match_count

    for c in creators:
        c_tags = creator_hashtags.get(c["id"], set())
        for slug, info in subc_by_slug.items():
            spec = info["spec"]
            score = 0
            # Hashtag matches
            tags_lower = {t.lower() for t in spec["signature_hashtags"]}
            score += len(c_tags & tags_lower) * 2
            # Category match
            if c.get("category") in spec.get("category_match", []):
                score += 3
            if score > 0:
                creator_score[c["id"]][info["id"]] = score

    # Build the link rows
    rows = []
    for cid, scores in creator_score.items():
        for sid, score in scores.items():
            conf = min(1.0, score / 6.0)
            rows.append({
                "creator_id": cid,
                "subculture_id": sid,
                "confidence": round(conf, 2),
                "classified_by": "hashtag_match",
            })

    if rows:
        for i in range(0, len(rows), 500):
            sb.table("creator_subcultures").upsert(rows[i:i+500], on_conflict="creator_id,subculture_id").execute()
        new_links = len(rows)

    print(f"\n=== SEED COMPLETE ===", file=sys.stderr)
    print(f"  Subcultures created/updated: {len(subc_by_slug)}", file=sys.stderr)
    print(f"  Creator-subculture links:    {new_links}", file=sys.stderr)
    # Show distribution
    by_subc = defaultdict(int)
    for cid, scores in creator_score.items():
        for sid in scores:
            by_subc[sid] += 1
    print(f"\nCoverage per subculture:", file=sys.stderr)
    for slug, info in subc_by_slug.items():
        print(f"  {info['spec']['emoji']} {slug:<25} {by_subc[info['id']]:>4} creators", file=sys.stderr)


if __name__ == "__main__":
    main()
