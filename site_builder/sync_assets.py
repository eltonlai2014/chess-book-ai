"""Fast asset-only sync for UI iteration.

Copies site_builder/assets/{style.css, board.js} to:
  - output/site/   (local preview)
  - docs/          (GitHub Pages mirror)

Use this instead of render_site.py when only CSS or board.js changed —
takes <1s vs many minutes for the full enrich+render pipeline.

If you changed render_site.py templates, games.json, or any position data,
run the full pipeline (render_site.py) instead.
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"
OUT_SITE = REPO / "output" / "site"
DOCS = REPO / "docs"

ASSET_FILES = ["style.css", "board.js"]


def main() -> int:
    missing = [n for n in ASSET_FILES if not (ASSETS / n).exists()]
    if missing:
        print(f"[err] missing source assets: {missing}", file=sys.stderr)
        return 1

    targets = [d for d in (OUT_SITE, DOCS) if d.exists()]
    if not targets:
        print(f"[err] neither {OUT_SITE} nor {DOCS} exists — run render_site.py first", file=sys.stderr)
        return 1

    for name in ASSET_FILES:
        src = ASSETS / name
        for dst_dir in targets:
            dst = dst_dir / name
            shutil.copy2(src, dst)
            rel = dst.relative_to(REPO)
            print(f"[sync] {name}  ->  {rel}")
    print(f"[done] reload the page in browser — no HTML re-render needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
