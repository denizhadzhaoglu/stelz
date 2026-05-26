"""Smoke test the spot-api endpoints via Vercel CLI bypass.

Uses `vercel curl` to handle Deployment Protection. Each test asserts the
response is valid JSON of the expected shape (array, object, or error). On
failure, prints the actual response for debugging.

Run from project root:
    python3 tests/test_spot_api.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "projects" / "spot-the-brand" / "cli" / ".local-token"
API_DIR = ROOT / "projects" / "spot-the-brand" / "api"


def _token() -> str:
    raw = TOKEN_FILE.read_text().strip()
    return raw.split("=", 1)[1] if "=" in raw else raw


def _curl(path: str, *, token: str | None = None, method: str = "GET", body: dict | None = None) -> tuple[int | None, dict | list | str | None]:
    """Invoke `vercel curl` and parse the JSON response.

    Returns (status_or_None, parsed_body_or_None).
    """
    args = ["vercel", "curl", path, "--", "-s", "-i"]
    if token:
        args += ["-H", f"Authorization: Bearer {token}"]
    if method != "GET":
        args += ["-X", method]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(args, cwd=str(API_DIR), capture_output=True, text=True, timeout=60)
    # Only parse stdout. `vercel curl` writes "Retrieving project…" to stderr
    # which would otherwise be appended after the JSON body and confuse the
    # blank-line-separates-headers heuristic.
    out = r.stdout or ""
    # Parse status from the LAST HTTP/x.x line (in case of redirects)
    status = None
    body_text = ""
    in_body = False
    blank_seen = False
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("HTTP/"):
            try:
                status = int(stripped.split()[1])
            except Exception:
                pass
            blank_seen = False
            in_body = False
            body_text = ""
            continue
        if not in_body:
            if stripped == "":
                blank_seen = True
                in_body = True
                continue
            # header line, skip
            continue
        body_text += line + "\n"
    body_text = body_text.strip()
    json_body: dict | list | str | None = None
    if body_text:
        try:
            json_body = json.loads(body_text)
        except Exception:
            # Last resort: find first { or [ and try
            for i, ch in enumerate(body_text):
                if ch in "[{":
                    try:
                        json_body = json.loads(body_text[i:])
                        break
                    except Exception:
                        continue
    return status, json_body


def assert_(cond: bool, msg: str) -> bool:
    print(("  ✓ " if cond else "  ✗ ") + msg)
    return cond


def test_all() -> tuple[int, int]:
    token = _token()
    passed, failed = 0, 0

    cases = [
        # path, method, body, expected_status, validate_fn(body) -> bool
        ("/api/v1/brands", "GET", None, 200, lambda b: isinstance(b, list) and len(b) >= 1),
        ("/api/v1/brands/stelz", "GET", None, 200, lambda b: isinstance(b, dict) and b.get("slug") == "stelz"),
        ("/api/v1/brands/stelz/health", "GET", None, 200, lambda b: isinstance(b, dict) and "creators_total" in b),
        ("/api/v1/brands/stelz/hits", "GET", None, 200, lambda b: isinstance(b, list)),
        ("/api/v1/brands/stelz/top-creators", "GET", None, 200, lambda b: isinstance(b, list) and len(b) >= 1),
        ("/api/v1/brands/stelz/creators/drinkstelz", "GET", None, 200, lambda b: isinstance(b, dict) and b.get("handle") == "drinkstelz"),
        ("/api/v1/brands/stelz/fp-analysis", "GET", None, 200, lambda b: isinstance(b, list) and len(b) >= 1),
        ("/api/v1/brands/stelz/subcultures", "GET", None, 200, lambda b: isinstance(b, list)),
        ("/api/v1/brands/stelz/hashtags", "GET", None, 200, lambda b: isinstance(b, list) and len(b) >= 1),
        ("/api/v1/brands/does-not-exist", "GET", None, 404, lambda b: isinstance(b, dict) and "error" in b),
        ("/api/v1/brands/stelz/creators/does-not-exist", "GET", None, 404, lambda b: isinstance(b, dict) and "error" in b),
        # Auth check
        ("/api/v1/brands", "GET", None, 401, lambda b: isinstance(b, dict) and "error" in b),
    ]

    print("=== Spot API endpoint matrix ===")
    for path, method, body, want_status, validator in cases:
        use_token = token if want_status != 401 else None
        try:
            status, parsed = _curl(path, token=use_token, method=method, body=body)
        except Exception as e:
            print(f"  ✗ {path:<52} EXCEPTION: {e}")
            failed += 1
            continue
        status_ok = (status == want_status) if status is not None else (want_status in (200, 404))
        body_ok = validator(parsed) if parsed is not None else False
        if status_ok and body_ok:
            passed += 1
            print(f"  ✓ {path:<52} HTTP {status or '?'} body-ok")
        else:
            failed += 1
            print(f"  ✗ {path:<52} HTTP {status} body={str(parsed)[:120]}")

    return passed, failed


if __name__ == "__main__":
    p, f = test_all()
    print(f"\n{p} passed, {f} failed")
    sys.exit(0 if f == 0 else 1)
