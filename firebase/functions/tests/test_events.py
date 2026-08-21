"""The event definition, and the two things that go wrong around it.

1. THE RESOLUTION TRAP. 74_analyse.py's --max-dim defaults to 512, the size the
   deployed function downscales to. The three roster archives were judged at the
   archived resolution (max_dim 0); re-running one at the default turns 37
   Instagram hits into 27 and 8 TikTok hits into 5. Nothing about the brand
   changed — the pass just saw fewer pixels. An archive holding both kinds of
   verdict cannot be read at all, so the analyser refuses to mix them and this
   test holds it to that.

2. THE PRICE TABLES. Money is priced in lib/usage.COST_PER_UNIT, measured
   against a real invoice, and the local tools carry their own copies so they
   can print an estimate before spending anything. test_cost_parity.py already
   guards the Python/TypeScript pair; these are the third and fourth copies.

Runs with no third-party imports: _events.py is plain json + pathlib, and the
price checks read the other files as text.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
TOOLS = ROOT / "tools" / "stelz_brand_watch"

_spec = importlib.util.spec_from_file_location("_events", TOOLS / "_events.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)


class TestDefinition(unittest.TestCase):
    def test_at_least_one_event_exists(self):
        self.assertIn("lowlands-2026", E.available())

    def test_every_definition_is_complete(self):
        for eid in E.available():
            ev = E.load(eid)
            for key in ("id", "name", "projectId", "venue", "window", "roster",
                        "hashtags", "discovery"):
                self.assertIn(key, ev, f"{eid} has no {key}")
            self.assertEqual(ev["id"], eid, "id must match the filename")

    def test_an_event_never_ends_before_it_starts(self):
        for eid in E.available():
            start, end = E.window(E.load(eid))
            self.assertLessEqual(start, end, eid)

    def test_the_window_is_the_festival_plus_its_edges(self):
        ev = E.load("lowlands-2026")
        self.assertEqual(E.window(ev), ("2026-08-17", "2026-08-30"))
        self.assertTrue(E.in_window(ev, "2026-08-20T19:16:00+00:00"))
        # Fifteen of the fifty sightings on the real fixture were from July.
        # They are real detections and they are not Lowlands.
        self.assertFalse(E.in_window(ev, "2026-07-14T09:00:00Z"))
        self.assertFalse(E.in_window(ev, None))

    def test_no_tiktok_is_null_and_never_the_word_geen(self):
        # Three real people. A scraper that asks Apify for a profile called
        # "geen" spends money to be told it does not exist.
        ev = E.load("lowlands-2026")
        self.assertEqual(len(ev["roster"]), 28)
        self.assertEqual(len(E.roster_ig(ev)), 28)
        self.assertEqual(len(E.roster_tt(ev)), 25)
        for m in ev["roster"]:
            self.assertNotEqual(str(m.get("tiktok")).lower(), "geen")

    def test_both_platforms_resolve_to_one_person(self):
        ev = E.load("lowlands-2026")
        self.assertEqual(E.identity_map(ev).get("rinnavandoffoe"), "rvdofficial")
        self.assertEqual(E.name_map(ev).get("rinnavandoffoe"), "Rein van Duivenboden")
        self.assertIn("rvdofficial", E.roster_accounts(ev))
        self.assertIn("rinnavandoffoe", E.roster_accounts(ev))

    def test_tags_are_split_into_the_two_families(self):
        ev = E.load("lowlands-2026")
        self.assertTrue(E.tags(ev, "brand"))
        self.assertTrue(E.tags(ev, "event"))
        self.assertEqual(len(E.tags(ev)), len(ev["hashtags"]))
        for tag, _ in E.tags(ev):
            self.assertFalse(tag.startswith("#"))
            self.assertEqual(tag, tag.lower())

    def test_archive_paths_are_per_event_and_named(self):
        ev = E.load("lowlands-2026")
        for kind in E.KINDS:
            p = E.archive_dir(ev, kind)
            self.assertEqual(p.name, kind)
            self.assertEqual(p.parent.name, "lowlands-2026")
        with self.assertRaises(ValueError):
            E.archive_dir(ev, "verzonnen")

    def test_the_paste_format_round_trips(self):
        # The import screen takes text. This is the only place the roster is
        # rendered back to it, and importList.test.ts asserts the result parses
        # to 28 rows and 53 platform ids.
        ev = E.load("lowlands-2026")
        lines = E.seed_tsv(ev).splitlines()
        self.assertEqual(len(lines), 29)                     # header + 28
        self.assertEqual(lines[0].split("\t"), ["Gasten", "Tag Instagram", "Tag TikTok"])
        ids = sum(len([c for c in l.split("\t")[1:] if c and c != "Geen"])
                  for l in lines[1:])
        self.assertEqual(ids, 53)


class TestVerdictResolution(unittest.TestCase):
    """One archive, one resolution. Skips where an archive has not been built."""

    def _verdicts(self, ev: dict, kind: str) -> list[dict]:
        path = E.archive_dir(ev, kind) / "verdicts.jsonl"
        if not path.exists():
            self.skipTest(f"{kind} not analysed yet")
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_no_archive_mixes_two_resolutions(self):
        for eid in E.available():
            ev = E.load(eid)
            for kind in E.KINDS:
                path = E.archive_dir(ev, kind) / "verdicts.jsonl"
                if not path.exists():
                    continue
                seen = {json.loads(l).get("max_dim")
                        for l in path.read_text().splitlines() if l.strip()}
                self.assertEqual(
                    len(seen), 1,
                    f"{eid}/{kind} holds verdicts at {sorted(map(str, seen))} — "
                    f"the totals over it cannot mean anything. Re-run with "
                    f"--redo at one resolution.")

    def test_the_analyser_defaults_to_what_production_sees(self):
        # Not a preference — a local number has to mean the same thing as a
        # deployed one, so the default matches MAX_IMAGE_DIM and anything else
        # has to be asked for out loud.
        src = (TOOLS / "74_analyse.py").read_text()
        self.assertIn("default=D.PROD_MAX_DIM", src)
        detect = (ROOT / "firebase" / "functions" / "handlers" / "detect_image.py").read_text()
        m = re.search(r"^MAX_IMAGE_DIM\s*=\s*(\d+)", detect, re.M)
        self.assertIsNotNone(m, "detect_image.py no longer declares MAX_IMAGE_DIM")
        local = re.search(r"^PROD_MAX_DIM\s*=\s*(\S+)", (TOOLS / "_local_detect.py").read_text(), re.M)
        self.assertIsNotNone(local)
        self.assertIn("MAX_IMAGE_DIM", local.group(1),
                      "PROD_MAX_DIM must be MAX_IMAGE_DIM itself, not a copy of its value")

    def test_the_analyser_refuses_to_mix(self):
        src = (TOOLS / "74_analyse.py").read_text()
        self.assertIn("REFUSED", src,
                      "74_analyse.py no longer refuses to add rows at a second resolution")


class TestLocalPriceParity(unittest.TestCase):
    """The local tools' price copies, against the invoice-measured table."""

    def setUp(self):
        usage = (ROOT / "firebase" / "functions" / "lib" / "usage.py").read_text()
        block = usage.split("COST_PER_UNIT", 1)[1]
        self.prices = {
            k: float(v)
            for k, v in re.findall(r'"([a-z0-9_]+)"\s*:\s*([0-9.]+)', block)
        }

    def _const(self, path: Path, name: str) -> float:
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", path.read_text(), re.M)
        self.assertIsNotNone(m, f"{path.name} no longer declares {name}")
        return float(m.group(1))

    def test_gemini_calls_are_priced_as_the_backend_prices_them(self):
        d = TOOLS / "_local_detect.py"
        self.assertEqual(self._const(d, "COST_IMAGE"), self.prices["gemini_flash_calls"])
        self.assertEqual(self._const(d, "COST_VIDEO"), self.prices["gemini_video_calls"])
        self.assertEqual(self._const(d, "COST_VERIFY"), self.prices["gemini_verify_calls"])

    def test_instagram_results_are_priced_the_same_in_both_harvesters(self):
        ig = self.prices["apify_ig_results"]
        self.assertEqual(self._const(TOOLS / "71_ig_posts_archive.py", "COST_PER_RESULT"), ig)
        self.assertEqual(self._const(TOOLS / "73_lowlands_discovery.py", "IG_COST_PER_RESULT"), ig)

    def test_tiktok_is_still_free_and_still_says_so(self):
        # clockworks/free-tiktok-scraper. If this ever stops being 0, every
        # "gratis" in the discovery script becomes a lie about spend.
        self.assertEqual(self.prices["apify_tt_results"], 0.0)

    def test_the_per_video_estimate_is_built_from_the_priced_calls(self):
        src = (TOOLS / "73_lowlands_discovery.py").read_text()
        m = re.search(r"^ANALYSIS_PER_VIDEO\s*=\s*(.+)$", src, re.M)
        self.assertIsNotNone(m)
        got = _arith(m.group(1))
        want = self.prices["gemini_video_calls"] + 2 * self.prices["gemini_flash_calls"]
        self.assertAlmostEqual(got, want, places=6)


def _arith(expr: str) -> float:
    """Evaluate a numeric literal expression — numbers, + and * and nothing else.

    Not eval(). This reads a line out of a source file, and eval() on file
    contents is arbitrary code execution however trustworthy the file looks
    today; a test that runs in CI is exactly where that stops being true.
    ast.literal_eval would be safe but rejects arithmetic, and the constant
    under test IS arithmetic ("one screen call plus a full look at two frames")
    — which is the part worth checking, because a bare 0.00638 would say
    nothing about where it came from.
    """
    import ast

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            a, b = walk(node.left), walk(node.right)
            return a + b if isinstance(node.op, ast.Add) else a * b
        raise AssertionError(f"ANALYSIS_PER_VIDEO is not plain arithmetic: {expr!r}")

    return walk(ast.parse(expr.strip(), mode="eval").body)


if __name__ == "__main__":
    unittest.main()
