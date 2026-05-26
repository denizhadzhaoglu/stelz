"""Upload all @spotyourbrand IG assets to Supabase Storage public bucket.

Result: each PNG gets a public URL like
  https://menaatbeoeutywulcdvv.supabase.co/storage/v1/object/public/brand-watch-thumbnails/spot-the-brand-ig/<file>.png

Why: the Instagram Graph API requires `image_url` (public HTTP URL) for every
media upload. Once @spotyourbrand is linked to a FB Page in Business Manager,
`ig_publish_organic_week1.py` can fire off the entire week-1 + grid-filler set
without any browser interaction.

Also handy for: copy-pasting into MBS Composer, Buffer, Later, or just sharing
links with Lukas.
"""
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SB_URL = os.environ["SUPABASE_URL"]
SB_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SECRET_KEY")
    or os.environ.get("SUPABASE_KEY")
)
if not SB_KEY:
    raise SystemExit("Set SUPABASE_SECRET_KEY (or SERVICE_ROLE_KEY) in .env")

BUCKET = "brand-watch-thumbnails"
PREFIX = "spot-the-brand-ig"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "projects" / "spot-the-brand" / "assets" / "ig-week1"

sb = create_client(SB_URL, SB_KEY)


def public_url(path: str) -> str:
    return f"{SB_URL}/storage/v1/object/public/{BUCKET}/{path}"


def upload(local_path: Path, remote_path: str) -> str:
    print(f"  uploading {local_path.name} -> {remote_path}", file=sys.stderr)
    data = local_path.read_bytes()
    try:
        sb.storage.from_(BUCKET).upload(
            path=remote_path,
            file=data,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
    except Exception as e:
        # supabase-py raises on duplicate; try update
        msg = str(e).lower()
        if "duplicate" in msg or "exists" in msg or "already" in msg:
            sb.storage.from_(BUCKET).update(
                path=remote_path,
                file=data,
                file_options={"content-type": "image/png", "upsert": "true"},
            )
        else:
            raise
    return public_url(remote_path)


def main():
    pngs = sorted(list(ASSETS_DIR.glob("*.png")) + list((ASSETS_DIR / "organic").glob("*.png")))
    print(f"Found {len(pngs)} PNGs to upload", file=sys.stderr)

    manifest = {}
    for p in pngs:
        subfolder = "organic" if p.parent.name == "organic" else "reels"
        remote = f"{PREFIX}/{subfolder}/{p.name}"
        url = upload(p, remote)
        manifest[p.name] = url

    out = ASSETS_DIR / "organic" / "PUBLIC_URLS.json"
    out.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {out}", file=sys.stderr)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
