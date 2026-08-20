#!/usr/bin/env python3
"""Run the Stëlz detection over an archive — TikTok or Instagram feed posts.

Same cascade as the stories analyser (64), same module (_local_detect), so the
three surfaces cannot drift into three different opinions about what counts as
a sighting.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/74_analyse.py --archive tiktok
        ... --archive ig-posts
        ... --limit 5            # try a few first
        ... --covers-only        # skip video frames (cheap, and says so)
        ... --redo               # re-judge everything

Resumable per item id. Cost is printed as an estimate before the run and as an
actual after it.

ON COVER-ONLY VERDICTS: an item whose video could not be downloaded is judged
on its cover and the verdict records `cover_only: true`. That is not the same
claim as "we watched the clip and saw nothing", and the UI has to be able to
tell the difference — a thumbnail is a chosen frame, and nobody chooses the one
where they are drinking.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_local_detect", Path(__file__).with_name("_local_detect.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

ARCHIVES = {
    "tiktok": (ROOT / ".tmp" / "tiktok-archive", "video_id"),
    "ig-posts": (ROOT / ".tmp" / "ig-posts-archive", "item_id"),
    "stories": (ROOT / ".tmp" / "stories-archive", "story_id"),
}


def load_verdicts(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                v = json.loads(line)
                out[v.get("item_id") or v.get("story_id")] = v
            except Exception:
                continue
    return out


def write_verdicts(path: Path, rows: dict[str, dict]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k]) + "\n")
    tmp.replace(path)


def analyse(entry: dict, media: Path, refs: list[bytes], covers_only: bool,
            stats: dict) -> tuple[list[dict], int]:
    results: list[dict] = []
    frames_extracted = 0

    img = entry.get("image_file")
    if img and (media / img).exists():
        results.append(D.judge_image((media / img).read_bytes(), refs, stats))

    vid = entry.get("video_file")
    if vid and not covers_only and (media / vid).exists():
        before = stats["frames_extracted"]
        results.extend(D.judge_video((media / vid).read_bytes(), refs, stats))
        frames_extracted = stats["frames_extracted"] - before

    return results, frames_extracted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, choices=sorted(ARCHIVES))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--covers-only", action="store_true")
    ap.add_argument("--redo", action="store_true")
    # Re-judge only the rows a verifier change can move: the ones the second
    # look already touched, plus the one hard rejection it is now allowed to
    # re-open (verifier.REOPENABLE_GATE). That is a few dozen out of fifteen
    # hundred — re-running the whole archive would re-bill the ~97% no verifier
    # rule can reach.
    ap.add_argument("--redo-verified", action="store_true",
                    help="re-judge items the second-look pass can change its mind about")
    # Re-judge everything the archive currently CLAIMS. Used to check that a
    # finding survives a change to the detection path without re-billing the
    # ~97% of an archive that says "nothing here" — those rows are only at risk
    # from a change that makes the pass see MORE, and this flag exists for the
    # opposite case.
    ap.add_argument("--redo-found", action="store_true",
                    help="re-judge every hit and near miss")
    # What the first pass sees. The default matches the deployed function, so a
    # local number means the same thing as a deployed one. 0 sends the archived
    # bytes as-is, which finds more and costs more — see _local_detect.
    ap.add_argument("--max-dim", type=int, default=D.PROD_MAX_DIM,
                    help=f"first-pass long edge in px (default {D.PROD_MAX_DIM}, "
                         f"as production; 0 = no downscale)")
    # Frame extraction is CPU-bound and the Gemini calls are almost all waiting
    # on the network, so one item at a time leaves both idle. 288 TikToks at
    # ~30s each is two and a half hours serial; the work is embarrassingly
    # parallel and the only shared state is the verdict file, which is written
    # under a lock.
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    base, id_field = ARCHIVES[args.archive]
    index, media, vpath = base / "index.jsonl", base / "media", base / "verdicts.jsonl"

    D.load_env()
    if not D.have_key():
        print("No Gemini key (GOOGLE_AI_API_KEY / GEMINI_API_KEY)")
        return 2
    if not index.exists():
        print(f"No archive at {base.relative_to(ROOT)} — harvest it first")
        return 2

    entries = [json.loads(l) for l in index.read_text().splitlines() if l.strip()]
    verdicts = load_verdicts(vpath)
    def wanted(e: dict) -> bool:
        if args.redo:
            return True
        if args.redo_found:
            v = verdicts.get(e[id_field]) or {}
            return bool(v.get("detected")) or bool(v.get("near_miss"))
        if args.redo_verified:
            v = verdicts.get(e[id_field]) or {}
            return bool(v.get("verify_verdict")) or v.get("gate") == D.REOPENABLE_GATE
        return e[id_field] not in verdicts

    todo = [e for e in entries if wanted(e)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(entries)} archived · {len(verdicts)} already judged · {len(todo)} to analyse")
    print("First pass at "
          + (f"{args.max_dim}px (as production)" if args.max_dim == D.PROD_MAX_DIM
             else f"{args.max_dim}px" if args.max_dim > 0
             else "the archived resolution — MORE than production sees"))
    if not todo:
        print("Nothing to do.")
        return 0

    D.set_max_dim(args.max_dim)
    D.warm()
    refs = D.load_references()
    print(f"{len(refs)} reference images, logo first")
    est = sum(D.COST_IMAGE + (D.COST_VIDEO + 2 * D.COST_IMAGE
                              if e.get("video_file") and not args.covers_only else 0)
              for e in todo)
    print(f"Estimated Gemini spend: ~${est:.2f}\n")

    stats = D.new_stats()
    counts = {"hits": 0, "near": 0, "cover_only": 0, "done": 0}
    lock = threading.Lock()

    def work(e: dict) -> None:
        iid = e[id_field]
        try:
            results, frames = analyse(e, media, refs, args.covers_only, stats)
        except Exception as exc:
            with lock:
                counts["done"] += 1
                print(f"[{counts['done']}/{len(todo)}] @{e['handle']} → FAILED ({str(exc)[:60]})")
            return
        if not results:
            with lock:
                counts["done"] += 1
                print(f"[{counts['done']}/{len(todo)}] @{e['handle']} → no media")
            return
        v = D.verdict_record(iid, e["handle"], results,
                             frames_extracted=frames, duration_s=e.get("duration"))
        # A verdict with no description is not a verdict. The model returned
        # nothing usable — a malformed response, a safety block, a truncated
        # call — and writing it stores "no Stëlz" for an image nothing ever
        # actually read, which is indistinguishable on screen from a real
        # negative. Leaving it out keeps the item in the todo list so the next
        # run retries it, exactly as detect_image refuses to cache a failed call
        # ("Never cache a failed call ... not evidence the brand is absent").
        if not v["detected"] and not (v.get("context") or "").strip():
            with lock:
                counts["done"] += 1
                print(f"[{counts['done']}/{len(todo)}] @{e['handle']} → LEEG antwoord, "
                      f"niet opgeslagen (blijft ongeanalyseerd)")
            return
        # A clip we never obtained is judged on a thumbnail. Say so in the row
        # rather than letting it read like a full viewing.
        v["cover_only"] = bool(e.get("video_unavailable")) or (
            args.covers_only and bool(e.get("video_file") or e.get("video_unavailable")))
        with lock:
            counts["done"] += 1
            if v["cover_only"]:
                counts["cover_only"] += 1
            verdicts[iid] = v
            # Under the lock and after every item: a crash keeps everything it
            # already paid Gemini for.
            write_verdicts(vpath, verdicts)
            head = f"[{counts['done']}/{len(todo)}] @{e['handle']}"
            if v["detected"]:
                counts["hits"] += 1
                print(f"{head} → STËLZ {int((v['confidence'] or 0) * 100)}% "
                      f"({v.get('size_in_frame') or '?'}, {v.get('judged_from')})")
            elif v["near_miss"]:
                counts["near"] += 1
                print(f"{head} → bijna ({(v.get('near_miss_reason') or '?')[:50]})")
            else:
                print(f"{head} → no")

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        for fut in as_completed([ex.submit(work, e) for e in todo]):
            fut.result()
    hits, near, cover_only = counts["hits"], counts["near"], counts["cover_only"]

    print(f"\n{hits} of {len(todo)} contained Stëlz · {near} near miss"
          f"{'' if near == 1 else 'es'}")
    if cover_only:
        print(f"{cover_only} judged on the cover alone (video unavailable) — "
              f"weaker evidence, marked as such")
    print(f"Gemini: {stats['image_calls']} image · {stats['video_calls']} screen · "
          f"{stats['verify_calls']} verify  =  ~${D.spend(stats):.2f}")
    if stats["frames_extracted"]:
        print(f"Frames: {stats['frames_extracted']} sampled · {stats['frames_flagged']} flagged "
              f"· {stats['frames_analysed']} given a full look")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
