"""The event definition, read from the same file the dashboard reads.

    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location(
        "_events", pathlib.Path(__file__).with_name("_events.py"))
    E = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(E)

    ev = E.load("lowlands-2026")
    E.roster_ig(ev)        # ['stefandevries', 'heymalith', ...]
    E.roster_tt(ev)        # TikTok column, people without one left out
    E.archive_dir(ev, "stories")

WHAT THIS REPLACED
------------------
Five copies of the same eight lines. 62, 70, 71, 72 and 73 each opened
web/src/data/lowlandsSeed.ts, split it on backticks to get at the template
literal, split THAT on tabs, and each separately remembered that the string
"Geen" in column three means "this person has no TikTok". 73 additionally
carried the hashtag list hard-coded, because a TSV has nowhere to put one.

That arrangement has one failure mode and it is silent: add a creator to the
seed and every script picks her up, change the shape of the seed and every
script breaks differently. Now there is one JSON file, one parser per language,
and the event's dates and hashtags live next to its roster instead of in a
sixth place.

WHY THE FILE LIVES UNDER web/src
--------------------------------
Because the dashboard imports it directly (Vite resolves JSON natively) and
Python can reach anywhere. The other direction — config in tools/, TypeScript
reading it — would need the bundler to reach outside its own root, which Vite
refuses by default and which would need a symlink or a build step to fix.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = ROOT / "projects" / "stelz-brand-watch" / "web" / "src" / "data" / "events"

# The four archives an event collects. The names are also the directory names
# under .tmp/events/<event-id>/ and the --archive choices in 74_analyse.py, so
# adding a surface means adding it here and nowhere else.
KINDS = ("stories", "ig-posts", "tiktok", "discovery")


def available() -> list[str]:
    """Event ids with a definition on disk."""
    if not EVENTS_DIR.exists():
        return []
    return sorted(p.stem for p in EVENTS_DIR.glob("*.json"))


def load(event_id: str) -> dict:
    path = EVENTS_DIR / f"{event_id}.json"
    if not path.exists():
        raise SystemExit(
            f"No event {event_id!r} at {path.relative_to(ROOT)}. "
            f"Known: {', '.join(available()) or '(none)'}")
    return json.loads(path.read_text())


def _clean(handle: str | None) -> str | None:
    """A handle as the platforms spell it: lowercase, no leading @.

    None stays None. That is the whole reason the JSON uses null instead of the
    string "Geen": three people on the Lowlands roster have no TikTok, and a
    scraper that asks Apify for a profile called "geen" spends money to be told
    it does not exist.
    """
    if not handle:
        return None
    h = handle.strip().lstrip("@").lower()
    return h or None


def roster_ig(ev: dict) -> list[str]:
    """Instagram handles, in roster order, duplicates removed."""
    return _dedupe(_clean(m.get("instagram")) for m in ev.get("roster", []))


def roster_tt(ev: dict) -> list[str]:
    """TikTok handles. Shorter than roster_ig by however many people have none."""
    return _dedupe(_clean(m.get("tiktok")) for m in ev.get("roster", []))


def roster_accounts(ev: dict) -> set[str]:
    """Every handle on the roster, both platforms, as one set.

    For the "is this account being paid" question, which does not care which
    platform a post came from. A discovery hit is dropped if EITHER handle
    matches: Rein is @rvdofficial on Instagram and @rinnavandoffoe on TikTok,
    and a hashtag search returns whichever one the post was made from.
    """
    return {h for h in (roster_ig(ev) + roster_tt(ev)) if h}


def identity_map(ev: dict) -> dict[str, str]:
    """TikTok handle -> that person's Instagram handle.

    Keyed on the raw handle, the campaign table shows Rein twice and reports 42
    creators for a roster of 28 — which makes "who delivered nothing"
    unanswerable, and that column is the reason the page exists. Instagram wins
    because creator ids and project rosters are already built from it
    (splitCreatorId in lib/projects.ts).
    """
    out: dict[str, str] = {}
    for m in ev.get("roster", []):
        ig, tt = _clean(m.get("instagram")), _clean(m.get("tiktok"))
        if ig and tt:
            out[tt] = ig
    return out


def name_map(ev: dict) -> dict[str, str]:
    """Any handle, either platform -> the person's real name."""
    out: dict[str, str] = {}
    for m in ev.get("roster", []):
        name = (m.get("name") or "").strip()
        if not name:
            continue
        for h in (_clean(m.get("instagram")), _clean(m.get("tiktok"))):
            if h:
                out[h] = name
    return out


def tags(ev: dict, family: str | None = None) -> list[tuple[str, str]]:
    """(tag, family) pairs. `family` filters to 'brand' or 'event'."""
    pairs = [(t["tag"].lstrip("#").lower(), t.get("family") or "event")
             for t in ev.get("hashtags", [])]
    return [p for p in pairs if family is None or p[1] == family]


def window(ev: dict) -> tuple[str, str]:
    """The full period an item can belong to this event, as ISO dates.

    Not the festival — the festival plus its run-up and its tail. People post
    the packing video three days out and the recap a week later, and both are
    the event as far as the brand is concerned. Returned as 'YYYY-MM-DD'
    strings because every date comparison downstream is lexicographic on ISO
    text, and a festival day is a calendar day with no timezone of its own.
    """
    w = ev.get("window") or {}
    start = dt.date.fromisoformat(w["start"]) - dt.timedelta(days=int(w.get("preDays") or 0))
    end = dt.date.fromisoformat(w["end"]) + dt.timedelta(days=int(w.get("postDays") or 0))
    return start.isoformat(), end.isoformat()


def in_window(ev: dict, timestamp: str | None) -> bool:
    """Is this ISO timestamp inside the event's period?

    Compares the date part only. A post at 23:50 on the last day is in; the
    timezone the platform stamped it with is not worth a conversion, because
    the boundary already carries seven days of slack on one side and three on
    the other.
    """
    if not timestamp:
        return False
    start, end = window(ev)
    return start <= str(timestamp)[:10] <= end


def archive_dir(ev: dict, kind: str) -> Path:
    """.tmp/events/<event-id>/<kind> — created on demand by the caller.

    Per event, because the alternative is one .tmp/tiktok-archive shared by
    every festival Stëlz ever does, with no way to ask "what did Lowlands
    bring" except by date, and dates are exactly what the archives were missing.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown archive kind {kind!r}; expected one of {KINDS}")
    return ROOT / ".tmp" / "events" / ev["id"] / kind


class Paths:
    """Where one event's one archive lives, as four names instead of four joins.

    Each harvester keeps a module-level `P` that main() assigns once. The
    alternative — threading a directory through every function — is a bigger
    diff across five scripts for the same result, and the alternative to THAT
    is what was there before: `ARCHIVE = ROOT / ".tmp" / "tiktok-archive"` at
    import time, which is a global constant pretending an event is a singleton.
    """

    __slots__ = ("dir", "index", "media", "raw")

    def __init__(self, base: Path):
        self.dir = base
        self.index = base / "index.jsonl"
        self.media = base / "media"
        self.raw = base / "raw"

    def mkdirs(self) -> None:
        for d in (self.dir, self.media, self.raw):
            d.mkdir(parents=True, exist_ok=True)

    def label(self) -> str:
        try:
            return str(self.dir.relative_to(ROOT))
        except ValueError:
            return str(self.dir)


def paths(ev: dict, kind: str) -> Paths:
    return Paths(archive_dir(ev, kind))


def seed_tsv(ev: dict) -> str:
    """The roster in the paste format the import screen parses.

    PasteImport takes text, so the UI needs the roster as a TSV string. Built
    from the JSON rather than stored alongside it — two hand-maintained copies
    of one roster is the problem this module exists to remove. "Geen" comes
    back for the null TikToks because that is what the client's sheet says and
    what parseCreatorList already knows to skip.
    """
    lines = ["Gasten\tTag Instagram\tTag TikTok"]
    for m in ev.get("roster", []):
        lines.append(f"{m['name']}\t{m.get('instagram') or ''}\t{m.get('tiktok') or 'Geen'}")
    return "\n".join(lines)


def _dedupe(values) -> list[str]:
    seen, out = set(), []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out
