"""Brand identity matching: name variants, typo generation, safe fuzzy matching.

Deliberately dependency-free — no Firestore, no network, no third-party fuzzy
library. That keeps it unit-testable offline (see tests/test_identity.py) and
keeps Cloud Function cold starts down; Damerau-Levenshtein is 20 lines and does
not justify pulling in rapidfuzz.

THE CENTRAL SAFETY RULE
-----------------------
Loose variants are for FINDING candidate content. Strict variants are for
ACCEPTING a detection. They are never the same list.

A bad loose variant costs one wasted scrape, and vision still filters the
result. A bad strict variant creates a permanent false positive in the client's
feed. This split is what makes aggressive typo expansion safe.

The regression that shaped this: German "Stelzlager"/"Stelzlagern" (a terrace
pedestal) matched a naive substring check and scored instant 95% confidence.
See detect_image._has_brand_word. Three independent guards prevent it here —
word boundaries, an explicit denylist, and a common-word filter — and
test_identity.py asserts all three.
"""
from __future__ import annotations

import re
import unicodedata

# Words that contain a plausible brand root but are ordinary vocabulary. Anything
# here can never be a variant, in either mode. Seeded with the real Stelz
# regression plus its Dutch/German neighbours.
COMMON_WORD_DENYLIST: frozenset[str] = frozenset({
    # German — the actual false positive that removed OCR from the pipeline
    "stelzlager", "stelzlagern", "stelzen", "stelze", "stelzenlaufer",
    "stelzenläufer", "stelzvogel", "stelzer", "stelzl",
    # Dutch near-neighbours
    "stelt", "stelten", "stellen", "stelling", "stel", "steel", "stelsel",
    "stelselmatig", "stelregel",
    # English
    "steel", "stealth", "stelae",
})

_QWERTY_NEIGHBOURS = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn",
    "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp",
    "p": "ol", "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy",
    "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu",
    "z": "asx",
}

_LEET = {"e": "3", "l": "1", "s": "5", "o": "0", "i": "1", "a": "4"}
_VOWEL_ACCENTS = {
    "a": "àáâãäå", "e": "èéêë", "i": "ìíîï", "o": "òóôõö", "u": "ùúûü",
}


def normalize(s: str) -> str:
    """Lowercase + strip diacritics. STËLZ -> stelz.

    The SQL caption matcher (db/04_caption_signal.sql) lacks this, which is why
    a caption reading "STËLZ" is currently invisible to it.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def damerau_levenshtein(a: str, b: str) -> int:
    """Edit distance including adjacent transposition (so 'setlz' vs 'stelz'
    is distance 1, not 2). Iterative, O(len(a) * len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + cost)
        prev2, prev = prev, cur
    return prev[len(b)]


def _doublings(c: str) -> set[str]:
    return {c[:i] + c[i] + c[i:] for i in range(len(c))}


def _omissions(c: str) -> set[str]:
    return {c[:i] + c[i + 1:] for i in range(len(c))}


def _transpositions(c: str) -> set[str]:
    return {c[:i] + c[i + 1] + c[i] + c[i + 2:] for i in range(len(c) - 1)}


def _keyboard_subs(c: str) -> set[str]:
    out = set()
    for i, ch in enumerate(c):
        for n in _QWERTY_NEIGHBOURS.get(ch, ""):
            out.add(c[:i] + n + c[i + 1:])
    return out


def _leet_subs(c: str) -> set[str]:
    """Single-character leet substitutions only. Multi-substitution forms like
    'st3lz' with two swaps get unreadable fast and are pure noise."""
    out = set()
    for i, ch in enumerate(c):
        if ch in _LEET:
            out.add(c[:i] + _LEET[ch] + c[i + 1:])
    return out


def _accent_forms(c: str) -> set[str]:
    out = set()
    for i, ch in enumerate(c):
        for acc in _VOWEL_ACCENTS.get(ch, ""):
            out.add(c[:i] + acc + c[i + 1:])
    return out


def _phonetic_nl(c: str) -> set[str]:
    """Dutch-flavoured respellings: z<->s, z->ts/sz, diminutive -je/-jes."""
    out = set()
    if "z" in c:
        out.add(c.replace("z", "s"))
        out.add(c.replace("z", "ts"))
        out.add(c.replace("z", "sz"))
    if c.endswith(("z", "s")):
        out.add(c + "je")
        out.add(c + "jes")
    return out


def generate_variants(
    canonical: str,
    extra_denylist: list[str] | None = None,
    min_len: int = 4,
) -> dict[str, list[str]]:
    """Produce name variants for a brand, split by how much we trust them.

    Returns {"strict": [...], "loose": [...]}.

      strict — visually unambiguous (accents, doublings, single leet swap).
               Safe to ACCEPT a detection on.
      loose  — everything else. Discovery only; must never accept a detection.

    Deterministic: same input always yields the same output, so it can be
    generated once at bootstrap and frozen rather than recomputed at runtime
    (a generator change would otherwise silently alter detection behaviour on
    historical data).
    """
    c = normalize(canonical)
    if not c:
        return {"strict": [], "loose": []}

    deny = set(COMMON_WORD_DENYLIST)
    deny.update(normalize(d) for d in (extra_denylist or []))

    # Accented forms (stélz, stëlz) are deliberately NOT generated: normalize()
    # strips diacritics on both the variant list and the text being matched, so
    # "STËLZ" in a caption already matches the canonical. Generating them would
    # produce entries that normalize back to `c` and get dropped as duplicates.
    strict_raw = _doublings(c) | _leet_subs(c)
    loose_raw = (
        _omissions(c) | _transpositions(c) | _keyboard_subs(c) | _phonetic_nl(c)
    )

    # Short brand names tolerate less distortion before they collide with real
    # words, so scale the allowed edit distance with length.
    max_dist = 1 if len(c) <= 5 else 2

    def _keep(v: str) -> bool:
        n = normalize(v)
        if len(n) < min_len or n == c:
            return False
        if n in deny:
            return False
        return damerau_levenshtein(n, c) <= max_dist

    strict = sorted({v for v in strict_raw if _keep(v)})
    loose = sorted({v for v in loose_raw if _keep(v)} - set(strict))
    return {"strict": strict, "loose": loose}


def build_word_pattern(variants: list[str]) -> re.Pattern[str]:
    """Word-boundary alternation over the variants, longest-first so 'stelzz'
    wins over 'stelz'.

    The lookarounds are what stop 'Stelzlagern' matching 'stelz' — a plain
    substring check is exactly the bug that removed OCR from the pipeline.
    """
    cleaned = sorted(
        {normalize(v) for v in variants if normalize(v)}, key=len, reverse=True
    )
    if not cleaned:
        return re.compile(r"(?!)")  # never matches
    alt = "|".join(re.escape(v) for v in cleaned)
    return re.compile(rf"(?<![a-z0-9])({alt})(?![a-z0-9])")


def has_brand_word(
    text: str,
    variants: list[str],
    denylist: list[str] | None = None,
) -> tuple[bool, str | None]:
    """(matched, which_variant) for a brand mention in free text.

    Guard order matters: the denylist is checked against whole tokens BEFORE
    the pattern runs, so a denied word can never be rescued by a shorter
    variant matching inside it.
    """
    n = normalize(text)
    if not n:
        return False, None

    deny = set(COMMON_WORD_DENYLIST)
    deny.update(normalize(d) for d in (denylist or []))
    tokens = set(re.findall(r"[a-z0-9]+", n))
    # A text made up solely of denied tokens can never be a brand mention.
    if tokens and tokens <= deny:
        return False, None

    m = build_word_pattern(variants).search(n)
    if not m:
        return False, None
    return True, m.group(1)


def partial_wordmark_match(
    transcript: str,
    variants: list[str],
    min_resolved: int = 3,
) -> tuple[bool, str | None, int]:
    """Match an OCR transcript containing '?' wildcards against brand variants.

    Returns (matched, variant, resolved_char_count).

    DETECT_PROMPT_V8 explicitly instructs the model to emit partial reads like
    "ST??Z" or "..ELZ" and assign them confidence 0.70-0.84. The gate then
    rejected every one of them, because its regex needed the literal contiguous
    string — so the entire partial-read tier the prompt was designed to produce
    was unreachable. This makes it reachable.

    A wildcard may stand for any character. Every RESOLVED character must align
    exactly, so "STOLZ" never matches "stelz" (O conflicts with E) while
    "ST??Z" does. min_resolved keeps "?????" from matching everything.
    """
    n = normalize(transcript)
    if not n:
        return False, None, 0
    # '?' survives normalize (it is not a combining mark), but the tokenizer
    # must keep it.
    tokens = re.findall(r"[a-z0-9?]+", n)

    # Dedupe while PRESERVING caller order, and never iterate a set here.
    # A wildcard read is ambiguous by nature — "ST??Z" aligns to both "stelz"
    # and the leet variant "st3lz" with the same 3 resolved characters — and
    # iterating a set made the winner depend on PYTHONHASHSEED. That surfaced
    # as a test failing on some runs and passing on others, but the real cost
    # was in production: matched_variant exists so a variant that starts
    # showing up on rejected detections can be traced and demoted, and a value
    # that changes run to run for identical input makes that impossible.
    #
    # Callers pass canonical first (see detect_image._accept_variants), and
    # ties keep the earlier entry, so the canonical spelling wins.
    seen: set[str] = set()
    ordered: list[str] = []
    for x in variants:
        nx = normalize(x)
        if nx and nx not in seen:
            seen.add(nx)
            ordered.append(nx)

    best: tuple[str, int] | None = None
    for tok in tokens:
        if "?" not in tok:
            continue  # exact matches are has_brand_word's job
        for v in ordered:
            if len(tok) != len(v):
                continue
            resolved = 0
            ok = True
            for ct, cv in zip(tok, v):
                if ct == "?":
                    continue
                if ct != cv:
                    ok = False
                    break
                resolved += 1
            if ok and resolved >= min_resolved:
                if best is None or resolved > best[1]:
                    best = (v, resolved)
    if best:
        return True, best[0], best[1]
    return False, None, 0


def is_brand_specific_tag(
    tag: str, canonical: str, aliases: list[str] | None = None
) -> bool:
    """True when a hashtag is brand-specific rather than generic lifestyle.

    #stelz / #drinkstelz / #stelzhardseltzer qualify; #vrijmibo does not.
    Substring (not word-boundary) matching is correct here and safe: hashtags
    are single tokens, and the cost of a false positive is one extra promoted
    creator, not a bogus detection.
    """
    t = normalize(tag).lstrip("#")
    if not t:
        return False
    needles = {normalize(canonical)}
    needles.update(normalize(a) for a in (aliases or []))
    needles.discard("")
    if not needles:
        return False
    if t in COMMON_WORD_DENYLIST:
        return False
    return any(n in t for n in needles)


def is_real_handle(handle: str) -> bool:
    """Filter junk parsed out of captions — emails, domains, bare numbers.

    Ported from tools/stelz_brand_watch/51_build_edges.py, which the Firebase
    rewrite dropped; without it 'gmail.com' becomes a tracked creator.
    """
    h = (handle or "").strip().lstrip("@").lower()
    if not h or len(h) < 2 or len(h) > 30:
        return False
    if not re.fullmatch(r"[a-z0-9._]+", h):
        return False
    if h.isdigit():
        return False
    if h.count(".") >= 2:
        return False
    if re.search(r"\.(com|nl|org|net|io|be|de|co|uk)$", h):
        return False
    return True
