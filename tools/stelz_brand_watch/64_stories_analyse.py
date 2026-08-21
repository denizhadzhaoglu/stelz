#!/usr/bin/env python3
"""Run the real Stëlz detection over the archived stories, without a deploy.

Detection normally runs in a Cloud Function this machine cannot deploy to. It
does not have to: gemini.detect_image() takes image bytes directly (the path the
eval harness already uses), the reference photos live in the repo, and the
archive holds the media. The cascade itself lives in _local_detect.py and is
imported from the handlers, so the judgement here is the judgement there.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/64_stories_analyse.py            # analyse new
        ... --limit 5                                            # try a few first
        ... --covers-only                                        # skip video frames
        ... --redo-videos                                        # re-judge videos
        ... --redo                                               # re-judge everything

Resumable: verdicts land in .tmp/stories-archive/verdicts.jsonl and an
already-judged story is never paid for twice unless you ask for it.

WHY --redo-videos EXISTS. The first version of this script took
gemini.detect_frames_batch() as the final word on a video. In production that
call is only a screen; every frame it flags then gets a full detect_image at
full resolution (handlers/detect_video.py). Judging on the screen alone misses
a can that is small in one frame out of twelve — so every video judged by that
version is under-analysed and worth re-running.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_local_detect", Path(__file__).with_name("_local_detect.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

ARCHIVE = ROOT / ".tmp" / "stories-archive"
INDEX = ARCHIVE / "index.jsonl"
MEDIA = ARCHIVE / "media"
VERDICTS = ARCHIVE / "verdicts.jsonl"


def load_verdicts() -> dict[str, dict]:
    if not VERDICTS.exists():
        return {}
    out: dict[str, dict] = {}
    for line in VERDICTS.read_text().splitlines():
        if line.strip():
            try:
                v = json.loads(line)
                out[v.get("item_id") or v["story_id"]] = v
            except Exception:
                continue
    return out


def write_verdicts(rows: dict[str, dict]) -> None:
    """Whole file, ordered by id, so a re-judged row REPLACES the old one.

    Appending would leave both versions in the file and load_verdicts would
    resolve to whichever came last — which works, but leaves a file that
    disagrees with itself and is impossible to read by hand.
    """
    tmp = VERDICTS.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k]) + "\n")
    tmp.replace(VERDICTS)


def analyse(entry: dict, refs: list[bytes], covers_only: bool, stats: dict) -> dict:
    results: list[dict] = []
    frames_extracted = 0

    img_file = entry.get("image_file")
    if img_file and (MEDIA / img_file).exists():
        results.append(D.judge_image((MEDIA / img_file).read_bytes(), refs, stats))

    vid_file = entry.get("video_file")
    if vid_file and not covers_only and (MEDIA / vid_file).exists():
        before = stats["frames_extracted"]
        results.extend(D.judge_video((MEDIA / vid_file).read_bytes(), refs, stats))
        frames_extracted = stats["frames_extracted"] - before

    return D.verdict_record(entry["story_id"], entry["handle"], results,
                            frames_extracted=frames_extracted)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="analyse at most N stories")
    ap.add_argument("--covers-only", action="store_true", help="skip video frames")
    ap.add_argument("--redo", action="store_true", help="re-judge every story")
    ap.add_argument("--redo-videos", action="store_true",
                    help="re-judge stories that have a video (see the docstring)")
    args = ap.parse_args()

    D.load_env()
    if not D.have_key():
        print("No Gemini key (GOOGLE_AI_API_KEY / GEMINI_API_KEY)")
        return 2
    if not INDEX.exists():
        print(f"No archive at {ARCHIVE.relative_to(ROOT)} — run 62_stories_archive.py first")
        return 2

    entries = [json.loads(l) for l in INDEX.read_text().splitlines() if l.strip()]
    verdicts = load_verdicts()

    def wanted(e: dict) -> bool:
        if args.redo:
            return True
        sid = e["story_id"]
        if sid not in verdicts:
            return True
        return bool(args.redo_videos and e.get("video_file"))

    todo = [e for e in entries if wanted(e)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(entries)} archived · {len(verdicts)} already judged · {len(todo)} to analyse")
    if not todo:
        print("Nothing to do. Run 61_stories_preview_fixture.py to see the verdicts.")
        return 0

    D.warm()
    refs = D.load_references()
    print(f"{len(refs)} reference images, logo first: "
          f"{', '.join(p.name for p in D.reference_files())}")
    est = sum(D.COST_IMAGE + (D.COST_VIDEO + 2 * D.COST_IMAGE
                              if e.get("video_file") and not args.covers_only else 0)
              for e in todo)
    print(f"Estimated Gemini spend: ~${est:.2f} (screen + a full look at each flagged frame)\n")

    stats = D.new_stats()
    hits = near = changed = 0
    for i, e in enumerate(todo, 1):
        kind = "video" if (e.get("video_file") and not args.covers_only) else "photo"
        print(f"[{i}/{len(todo)}] @{e['handle']} {kind}", end=" ", flush=True)
        try:
            v = analyse(e, refs, args.covers_only, stats)
        except Exception as exc:
            # Never write a verdict we did not obtain: an unanalysed story is
            # honest, a fabricated miss is not. Left out so the next run retries.
            print(f"→ FAILED ({str(exc)[:60]})")
            continue
        was = verdicts.get(e["story_id"])
        if was and bool(was.get("detected")) != v["detected"]:
            changed += 1
        verdicts[e["story_id"]] = v
        write_verdicts(verdicts)   # flush per story: a crash keeps what it paid for
        if v["detected"]:
            hits += 1
            print(f"→ STËLZ {int((v['confidence'] or 0) * 100)}% "
                  f"({v.get('size_in_frame') or '?'}, {v.get('judged_from')})")
        elif v["near_miss"]:
            near += 1
            print(f"→ bijna ({(v.get('near_miss_reason') or '?')[:50]})")
        else:
            print("→ no")

    print(f"\n{hits} of {len(todo)} contained Stëlz · {near} near miss"
          f"{'' if near == 1 else 'es'}")
    if changed:
        print(f"{changed} verdict{'' if changed == 1 else 's'} CHANGED versus the previous run")
    print(f"Gemini: {stats['image_calls']} image · {stats['video_calls']} screen · "
          f"{stats['verify_calls']} verify  =  ~${D.spend(stats):.2f}")
    if stats["frames_extracted"]:
        print(f"Frames: {stats['frames_extracted']} sampled · {stats['frames_flagged']} flagged "
              f"by the screen · {stats['frames_analysed']} given a full look")
    print("\nNow run 61_stories_preview_fixture.py and open")
    print("http://localhost:5180/stories?preview=stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
