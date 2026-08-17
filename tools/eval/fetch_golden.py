#!/usr/bin/env python3
"""Source hard NEGATIVE images for the detector's golden set.

Why only negatives: the shipped golden set (24 moderator-labelled images) has
12 positives but its negatives barely cover the failure mode that actually
matters in production — a competitor's slim can, or a can-shaped object, in a
party/sports scene. The manifest's own worst case is exactly that: a generic
pastel can at a US baseball game reported as "STELZ Mixed Classics" at
confidence 1.0.

Why the labels are trustworthy without a human moderator: STELZ is a small
Dutch brand with no presence in openly-licensed stock photography. Anything
returned by Wikimedia Commons or Openverse is therefore not-STELZ with very
high confidence. A negative label here is near-certain by construction. That
asymmetry is the whole reason this script only fetches negatives — sourcing
positives the same way would NOT be sound.

Consequence worth stating plainly: adding negatives can only lower or hold
precision, and cannot move recall at all. This is a precision stress test.

LICENSING. Images are openly licensed but are NOT redistributed — they are
written to tools/eval/golden/, which is gitignored. What gets committed is
golden_sources.json (URL, license, attribution, sha256). Re-run this script to
rebuild the set; a sha256 mismatch means the upstream file changed.

    python3 tools/eval/fetch_golden.py            # fetch new candidates
    python3 tools/eval/fetch_golden.py --verify   # re-download, check checksums
    python3 tools/eval/fetch_golden.py --sheet    # build contact sheets to review
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
SOURCES = HERE / "golden_sources.json"
SHEETS = HERE / "sheets"

UA = "stelz-brand-watch-eval/1.0 (offline detector evaluation; contact via repo)"
MAX_EDGE = 1024

# Each class targets a specific documented failure mode. `why` is carried into
# the manifest so a future reader knows what the slice is testing.
QUERIES: list[dict] = [
    {
        "cls": "competitor_seltzer",
        "why": "Same product category, same slim-can format. Prompt rule 2 names "
               "White Claw / Truly / Bavaria / Viper / Kokanee as explicit non-matches.",
        "openverse": ["hard seltzer can", "white claw seltzer", "truly hard seltzer",
                      "canned cocktail", "spiked seltzer"],
        "commons": ["White Claw hard seltzer can", "hard seltzer"],
    },
    {
        "cls": "generic_can",
        "why": "Unbranded or other-branded slim cans — tests whether can SHAPE "
               "alone triggers a detection, which prompt rule 1 forbids.",
        "openverse": ["sparkling water can", "aluminium drink can", "energy drink can",
                      "soda can close up"],
        "commons": ["sparkling water can", "beverage can"],
    },
    {
        "cls": "party_scene",
        "why": "The production archetype: cans at medium/small size in crowded, "
               "badly-lit party, festival and sports footage where the label is "
               "unreadable. This is where a hallucinated read costs the most.",
        "openverse": ["music festival crowd drinks", "party drinking beer",
                      "baseball game beer", "beach party drinks", "bar patio drinks"],
        "commons": ["music festival crowd", "beer garden people"],
    },
    {
        "cls": "beer_can",
        "why": "Dutch/EU market neighbours (Heineken, Bavaria, Grolsch). Same "
               "shelf, same fridge, same hand.",
        "openverse": ["heineken can", "beer can hand", "dutch beer"],
        "commons": ["Heineken can", "Bavaria beer", "Grolsch"],
    },
    {
        "cls": "nonproduct_cylinder",
        "why": "Prompt rule 3 lists microphones, deodorant, thermoses, vapes and "
               "shakers as can-confusable in dark footage — and nothing has ever "
               "tested that rule.",
        "openverse": ["handheld microphone", "deodorant spray can", "thermos flask",
                      "protein shaker bottle", "vape device"],
        "commons": ["handheld microphone", "thermos flask"],
    },
]

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search_openverse(q: str, n: int = 6) -> list[dict]:
    """Openverse aggregates CC-licensed photography (Flickr et al). Better than
    Commons for real-world scenes — Commons skews to clean product shots."""
    url = ("https://api.openverse.org/v1/images/?"
           + urllib.parse.urlencode({"q": q, "page_size": n, "license_type": "all"}))
    try:
        d = json.loads(_get(url))
    except Exception as e:
        print(f"    ! openverse {q!r}: {e}", file=sys.stderr)
        return []
    out = []
    for r in d.get("results") or []:
        if not r.get("url"):
            continue
        out.append({
            "url": r["url"],
            "source": "openverse",
            "title": (r.get("title") or "")[:120],
            "license": r.get("license"),
            "attribution": (r.get("creator") or "")[:80],
            "foreign_url": r.get("foreign_landing_url"),
            "query": q,
        })
    return out


def search_commons(q: str, n: int = 6) -> list[dict]:
    """Wikimedia Commons. iiurlwidth gives a thumbnail URL — the originals run
    to 8000px and we downscale to 1024 anyway."""
    url = ("https://commons.wikimedia.org/w/api.php?"
           + urllib.parse.urlencode({
               "action": "query", "generator": "search", "gsrsearch": q,
               "gsrnamespace": 6, "gsrlimit": n, "prop": "imageinfo",
               "iiprop": "url|mime|extmetadata", "iiurlwidth": MAX_EDGE,
               "format": "json",
           }))
    try:
        d = json.loads(_get(url))
    except Exception as e:
        print(f"    ! commons {q!r}: {e}", file=sys.stderr)
        return []
    out = []
    for p in ((d.get("query") or {}).get("pages") or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in IMAGE_MIMES:
            continue
        ex = ii.get("extmetadata") or {}
        out.append({
            "url": ii.get("thumburl") or ii.get("url"),
            "source": "commons",
            "title": p.get("title", "")[:120],
            "license": (ex.get("LicenseShortName") or {}).get("value"),
            "attribution": ((ex.get("Artist") or {}).get("value") or "")[:80],
            "foreign_url": ii.get("descriptionurl"),
            "query": q,
        })
    return [c for c in out if c["url"]]


def normalize_image(raw: bytes) -> bytes | None:
    """Downscale to MAX_EDGE and re-encode as JPEG, so the eval set is uniform
    and every entry costs the same ~258 image tokens at the model."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return None
    if min(img.size) < 200:          # thumbnails/icons carry no visual evidence
        return None
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        s = MAX_EDGE / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def load_manifest() -> dict:
    if SOURCES.exists():
        return json.loads(SOURCES.read_text())
    return {"note": "Hard negatives for the Stelz detector eval. Images are "
                    "gitignored; re-fetch with tools/eval/fetch_golden.py.",
            "items": []}


def cmd_fetch() -> int:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    man = load_manifest()
    have_urls = {i["url"] for i in man["items"]}
    have_sha = {i["sha256"] for i in man["items"]}
    counts: dict[str, int] = {}
    for i in man["items"]:
        counts[i["cls"]] = counts.get(i["cls"], 0) + 1

    added = 0
    for spec in QUERIES:
        cls = spec["cls"]
        print(f"\n== {cls}")
        cands: list[dict] = []
        for q in spec.get("openverse", []):
            cands += search_openverse(q)
            time.sleep(0.4)          # be polite to an anonymous public API
        for q in spec.get("commons", []):
            cands += search_commons(q)
            time.sleep(0.4)

        for c in cands:
            if c["url"] in have_urls:
                continue
            try:
                raw = _get(c["url"])
            except Exception as e:
                print(f"    ! {c['title'][:40]}: {e}")
                continue
            norm = normalize_image(raw)
            if norm is None:
                continue
            sha = hashlib.sha256(norm).hexdigest()
            if sha in have_sha:       # same photo surfaced by two queries
                continue
            idx = counts.get(cls, 0)
            name = f"{cls}_{idx:02d}.jpg"
            (GOLDEN / name).write_bytes(norm)
            man["items"].append({
                "file": name,
                "cls": cls,
                "why": spec["why"],
                # Provisional. cmd_sheet() prints these for visual review and
                # review.py records the human decision; nothing enters the eval
                # until `reviewed` is true.
                "truth": False,
                "reviewed": False,
                "note": "",
                "url": c["url"],
                "source": c["source"],
                "title": c["title"],
                "license": c["license"],
                "attribution": c["attribution"],
                "foreign_url": c["foreign_url"],
                "query": c["query"],
                "sha256": sha,
            })
            have_urls.add(c["url"])
            have_sha.add(sha)
            counts[cls] = idx + 1
            added += 1
            print(f"    + {name:26} {c['license'] or '?':12} {c['title'][:44]}")

    SOURCES.write_text(json.dumps(man, indent=2) + "\n")
    print(f"\n{added} new images. total={len(man['items'])}  -> {SOURCES}")
    for cls, n in sorted(counts.items()):
        print(f"  {cls:22} {n}")
    return 0


def cmd_verify() -> int:
    """Re-download every source and confirm the bytes still hash the same."""
    man = load_manifest()
    bad = 0
    for i in man["items"]:
        try:
            norm = normalize_image(_get(i["url"]))
        except Exception as e:
            print(f"  GONE  {i['file']:26} {e}")
            bad += 1
            continue
        if norm is None or hashlib.sha256(norm).hexdigest() != i["sha256"]:
            print(f"  DRIFT {i['file']:26} upstream image changed")
            bad += 1
    print(f"\n{len(man['items']) - bad}/{len(man['items'])} sources intact")
    return 1 if bad else 0


def cmd_sheet(per_sheet: int = 12) -> int:
    """Contact sheets with index labels, so a human can review many at once."""
    from PIL import Image, ImageDraw
    man = load_manifest()
    SHEETS.mkdir(parents=True, exist_ok=True)
    items = [i for i in man["items"] if (GOLDEN / i["file"]).exists()]
    cell, cols = 320, 4
    made = 0
    for start in range(0, len(items), per_sheet):
        chunk = items[start:start + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell, rows * (cell + 26)), "white")
        d = ImageDraw.Draw(sheet)
        for k, it in enumerate(chunk):
            img = Image.open(GOLDEN / it["file"]).convert("RGB")
            img.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
            x = (k % cols) * cell + (cell - img.width) // 2
            y = (k // cols) * (cell + 26) + 22
            sheet.paste(img, (x, y))
            d.text(((k % cols) * cell + 6, (k // cols) * (cell + 26) + 6),
                   f"[{start + k}] {it['file']}", fill="black")
        out = SHEETS / f"sheet_{start // per_sheet:02d}.jpg"
        sheet.save(out, quality=85)
        print(f"  {out}  ({len(chunk)} images, indices {start}-{start + len(chunk) - 1})")
        made += 1
    print(f"\n{made} sheets covering {len(items)} images")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    if a.verify:
        return cmd_verify()
    if a.sheet:
        return cmd_sheet()
    return cmd_fetch()


if __name__ == "__main__":
    raise SystemExit(main())
