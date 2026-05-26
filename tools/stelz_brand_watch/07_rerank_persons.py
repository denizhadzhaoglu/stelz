#!/usr/bin/env python3
"""Re-rank discovery v2 output to prioritize individual persons over businesses.

Goal: surface real consumers and creators, not bars/cafes/horeca accounts.
Persons are valuable as STELZ activation targets; businesses are not.

Heuristics (combined into person_score):
- handle matches firstname.lastname / firstname_lastname pattern -> +
- full_name is 2-3 capitalized words -> +
- engagement per post is high (creators have higher eng than businesses) -> +
- business keywords in handle/name -> reject

Output: lifestyle_persons.csv ranked by person_score.

Usage:
    python3 tools/stelz_brand_watch/07_rerank_persons.py
"""

import csv
import re
import sys
from pathlib import Path

PA_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"

# Business keywords -> reject as person
BUSINESS_RE = re.compile(
    r"(cafe|caf[eé]|restaurant|bar |bar$|club|hotel|hostel|inn|pizza|sushi|frietzaak|"
    r"snackbar|grand cafe|stadscafe|borrelbar|schenkerij|slijterij|wijnhuis|"
    r"markt|winkel|supermarkt|albert heijn|jumbo|lidl|dirk|plus |spar|aldi|"
    r"b\.v\.|\bbv\b|n\.v\.|\bnv\b|\.nl|\.com|"
    r"vereniging|stichting|kerk|gemeente|agency|studio|productions|"
    r"festival|event|kermis|tentfeest|tractorpulling|partyplace|"
    r"introweek|universiteit|university|hogeschool|college|"
    r"news|nieuws|krant|magazine|blog|"
    r"verhuur|maklaardij|makelaardij|sport|toernooi|toernooi)",
    re.IGNORECASE,
)

# Person-like handle patterns
HANDLE_PERSON_RE = re.compile(
    r"^[a-z]+[._][a-z]+[0-9]*$|"  # firstname.lastname or firstname_lastname
    r"^[a-z]+[._][a-z]+[._][a-z]+$|"  # 3 word
    r"^[a-z]+[0-9]+$",  # firstname123
    re.IGNORECASE,
)

# Indicators in full_name
PERSON_FULLNAME_RE = re.compile(r"^[A-Z][a-z]+\s[A-Z][a-z]+(\s[A-Z][a-z]+)?$")
DUTCH_FIRSTNAMES = {
    "anne","anna","sanne","jan","piet","kees","maria","sophie","emma","julia",
    "lisa","lieke","femke","sofie","saar","tessa","fleur","noa","mila","luna",
    "daan","sem","luuk","finn","milan","levi","liam","noah","lars","jesse",
    "tim","tom","max","bram","stijn","ruben","sven","koen","thomas","mark",
    "luca","lucas","julian","matthijs","tijn","gijs","willem","robin","floris",
    "demi","mette","esmee","puck","floor","yara","lara","linde","jara","maud",
    "kim","kimberly","laura","ellen","liesbeth","marieke","carolien","esther",
    "iris","ilona","ilse","melenie","melanie","mariska","yvonne","monique",
    "natalya","liselotte","pascal","tristan","hugo","john","ilke","aejin",
    "merel","birgit","mirjam","kris","krisje","yan","yannick","annemiek",
}


def looks_like_person(handle: str, full_name: str | None) -> tuple[bool, int]:
    """Returns (is_person, score). is_person False means business/event."""
    handle_l = handle.lower()
    full_l = (full_name or "").lower()
    combined = f"{handle_l} {full_l}"

    if BUSINESS_RE.search(combined):
        return False, -10

    score = 0
    handle_clean = handle_l.replace(".", "").replace("_", "").replace("-", "")
    handle_tokens = re.split(r"[._-]", handle_l)

    if HANDLE_PERSON_RE.match(handle_l):
        score += 8
    if any(tok in DUTCH_FIRSTNAMES for tok in handle_tokens):
        score += 10
    if full_name and PERSON_FULLNAME_RE.match(full_name):
        score += 6
    if full_name:
        first_token = full_name.split()[0].lower() if full_name.split() else ""
        if first_token in DUTCH_FIRSTNAMES:
            score += 8
    if "official" in combined or "the_" in handle_l:
        score -= 5
    if any(emoji in (full_name or "") for emoji in ["🏆","🚀","💼","®","™"]):
        score -= 5
    if len(handle_l) > 25:
        score -= 3

    return score > 0, score


def main():
    csv_in = OUTPUT_DIR / "lifestyle_creators.csv"
    if not csv_in.exists():
        sys.exit(f"Missing {csv_in}")

    rows = list(csv.DictReader(open(csv_in)))
    print(f"Loaded {len(rows)} candidates from v2 discovery", file=sys.stderr)

    persons = []
    for r in rows:
        is_person, person_score = looks_like_person(r["handle"], r["full_name"])
        if not is_person:
            continue
        avg_eng = float(r["avg_engagement"])
        nl = int(r["nl_signal_score"])
        groups = int(r["groups_count"])
        # Re-rank: heavier on engagement (persons have higher eng per post), person_score, NL signal
        composite = (
            person_score * 1.5
            + min(avg_eng / 30, 15)
            + min(nl, 8)
            + groups * 2
        )
        persons.append({
            "handle": r["handle"],
            "full_name": r["full_name"],
            "person_score": person_score,
            "composite": round(composite, 1),
            "avg_engagement": avg_eng,
            "post_count": r["post_count"],
            "groups_count": groups,
            "nl_signal_score": nl,
            "groups_seen": r["groups_seen"],
            "sample_url_1": r["sample_url_1"],
            "sample_caption": r["sample_caption"][:140],
        })

    persons.sort(key=lambda x: x["composite"], reverse=True)

    out = OUTPUT_DIR / "lifestyle_persons.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(persons[0].keys()))
        w.writeheader()
        w.writerows(persons)

    print(f"\nFiltered to {len(persons)} likely-persons (of {len(rows)} candidates)", file=sys.stderr)
    print(f"\nTop 30 persons (by composite):", file=sys.stderr)
    for r in persons[:30]:
        print(f"  @{r['handle']:<28} {r['full_name'][:30]:<30} comp={r['composite']:<5} eng={r['avg_engagement']} pscore={r['person_score']}", file=sys.stderr)
    print(f"\nWrote: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
