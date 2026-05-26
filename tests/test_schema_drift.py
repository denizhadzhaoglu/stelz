"""Schema-drift test: every column referenced in dashboard HTML files must
exist in the DB. Catches the kinds of bugs where someone renames a column
in a migration and a `select("ai_score")` call starts returning 400.

Run from project root:
    python3 tests/test_schema_drift.py
"""
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

DASHBOARD_DIR = ROOT / "projects" / "stelz-brand-watch" / "dashboard"

# Match `sb.from("table_name").select("col_a, col_b, col_c")`
PATTERN_FROM = re.compile(r"sb\s*\.from\s*\(\s*['\"`]([a-zA-Z0-9_]+)['\"`]\s*\)")
PATTERN_SELECT = re.compile(r"\.select\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*\)")


def parse_columns(select_str: str) -> set[str]:
    cols: set[str] = set()
    depth = 0
    buf = ""
    for ch in select_str:
        if ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            cols.update(_extract_col_names(buf))
            buf = ""
        else:
            buf += ch
    if buf:
        cols.update(_extract_col_names(buf))
    return cols


def _extract_col_names(s: str) -> set[str]:
    s = s.strip()
    if not s or s == "*":
        return set()
    # Drop aliases like "alias:col" — keep col
    if ":" in s and "(" not in s.split(":")[0]:
        s = s.split(":", 1)[1].strip()
    # Drop subselect "rel(cola, colb)" — keep relationship name only (skip; that's a join)
    if "(" in s:
        return set()
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", s):
        return {s}
    return set()


def extract_table_column_pairs() -> dict[str, set[str]]:
    """Walk every HTML file, find `.from("X").select("a,b,c")` pairs."""
    pairs: dict[str, set[str]] = {}
    for f in sorted(DASHBOARD_DIR.glob("*.html")):
        text = f.read_text(errors="ignore")
        # Find all `.from("X").select("a,b,c")` adjacencies
        for m in re.finditer(r"sb\s*\.from\s*\(\s*['\"`]([a-zA-Z0-9_]+)['\"`]\s*\)\s*\.select\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*\)", text, re.DOTALL):
            table = m.group(1)
            cols = parse_columns(m.group(2))
            pairs.setdefault(table, set()).update(cols)
    return pairs


def list_real_columns() -> dict[str, set[str]]:
    # Uses a SECURITY DEFINER RPC to expose information_schema.columns
    # without granting anon/authenticated direct access.
    r = sb.rpc("list_public_columns", {}).execute()
    out: dict[str, set[str]] = {}
    for row in r.data or []:
        out.setdefault(row["table_name"], set()).add(row["column_name"])
    return out


def run() -> tuple[int, int]:
    passed = failed = 0
    print("=== Schema-drift test ===")
    pairs = extract_table_column_pairs()
    real = list_real_columns()

    # Some "tables" referenced in HTML are actually views, joins, or
    # PostgREST-relationship names. Skip names that look like joins
    # (containing "(") and known-virtual tables.
    skip_tables = {"information_schema"}

    for table, cols in sorted(pairs.items()):
        if table in skip_tables:
            continue
        real_cols = real.get(table)
        if real_cols is None:
            # We have no info on this table — might be a view we couldn't
            # introspect through PostgREST. Try a single-row SELECT to verify
            # it at least exists.
            try:
                sb.from_(table).select("*").limit(1).execute()
                # Table exists; we just can't enumerate columns.
                print(f"  ⚠ {table:<30} (could not list columns; skipped)")
                continue
            except Exception:
                print(f"  ✗ {table:<30} TABLE DOES NOT EXIST (referenced columns: {sorted(cols)})")
                failed += 1
                continue
        bad = [c for c in cols if c not in real_cols]
        if bad:
            print(f"  ✗ {table:<30} missing columns: {bad}")
            failed += 1
        else:
            print(f"  ✓ {table:<30} {len(cols)} columns OK")
            passed += 1
    return passed, failed


if __name__ == "__main__":
    p, f = run()
    print(f"\n{p} passed, {f} failed")
    sys.exit(0 if f == 0 else 1)
