"""Migrate existing JS / JSON eval sources into a single SQLite database.

Read-only over the existing data — does NOT modify positions*.js or chessdb_cache.json.
Writes to ``output/positions.db``. Re-running drops + rebuilds (idempotent).

Sources:
  output/site/positions.js            window.POSITIONS         depth 12
  output/site/positions_deep.js       window.POSITIONS_DEEP    depth 22
  output/site/positions_very_deep.js  window.POSITIONS_VERY_DEEP depth 28
  output/site/positions_d32.js        window.POSITIONS_D32     depth 32
  output/site/data/chessdb_cache.json (raw JSON, no window prefix)

Schema (long-table, see CLAUDE.md discussion):

  evals(fen, depth, score, mate, best_iccs, pv_json)   PK (fen, depth)
  chessdb(fen, status, moves_json)                     PK fen

best_chinese + pv_detail are intentionally NOT migrated — they're derived
in render_site.py from best_iccs + pv via cchess, not source-of-truth.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "output" / "site"
DB_PATH = ROOT / "output" / "positions.db"

# (source path, window-var prefix, depth label)
JS_SOURCES = [
    (SITE / "positions.js",            "window.POSITIONS",          12),
    (SITE / "positions_deep.js",       "window.POSITIONS_DEEP",     22),
    (SITE / "positions_very_deep.js",  "window.POSITIONS_VERY_DEEP", 28),
    (SITE / "positions_d32.js",        "window.POSITIONS_D32",      32),
]
CHESSDB_JSON = SITE / "data" / "chessdb_cache.json"


SCHEMA = """
CREATE TABLE evals (
  fen        TEXT NOT NULL,
  depth      INTEGER NOT NULL,
  score      INTEGER,
  mate       INTEGER,
  best_iccs  TEXT,
  pv_json    TEXT,
  PRIMARY KEY (fen, depth)
) WITHOUT ROWID;

CREATE INDEX evals_by_depth ON evals(depth);

CREATE TABLE chessdb (
  fen        TEXT PRIMARY KEY,
  status     TEXT,
  moves_json TEXT
) WITHOUT ROWID;
"""


def _strip_js_wrapper(text: str, prefix: str) -> str:
    """Strip ``window.X =`` prefix and any trailing semicolon, leaving raw JSON."""
    text = text.lstrip()
    if not text.startswith(prefix):
        raise ValueError(f"expected prefix {prefix!r}, got {text[:40]!r}")
    body = text[len(prefix):].lstrip()
    if body.startswith("="):
        body = body[1:].lstrip()
    body = body.rstrip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    return body


def _load_js_dict(path: Path, prefix: str) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(_strip_js_wrapper(text, prefix))


def _iter_eval_rows(data: dict, depth: int):
    for fen, entry in data.items():
        # `depth` from the file should match our label; trust the label, the
        # in-entry depth is informational
        yield (
            fen,
            depth,
            entry.get("score"),
            entry.get("mate"),
            entry.get("best_iccs"),
            json.dumps(entry.get("pv") or [], separators=(",", ":")),
        )


def _iter_chessdb_rows(data: dict):
    for fen, entry in data.items():
        yield (
            fen,
            entry.get("status"),
            json.dumps(entry.get("moves") or [], separators=(",", ":"), ensure_ascii=False),
        )


def main():
    if not SITE.exists():
        raise SystemExit(f"site dir not found: {SITE}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    print(f"[migrate] target: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    con.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    con.executescript(SCHEMA)

    totals: dict[str, int] = {}

    for src, prefix, depth in JS_SOURCES:
        if not src.exists():
            print(f"[migrate] skip (missing): {src.name}")
            continue
        t0 = time.perf_counter()
        data = _load_js_dict(src, prefix)
        rows = list(_iter_eval_rows(data, depth))
        con.executemany(
            "INSERT INTO evals (fen, depth, score, mate, best_iccs, pv_json) VALUES (?,?,?,?,?,?)",
            rows,
        )
        con.commit()
        dt = time.perf_counter() - t0
        totals[f"d{depth}"] = len(rows)
        print(f"[migrate] {src.name:32s} depth={depth:2d}  rows={len(rows):6d}  {dt:5.2f}s")

    if CHESSDB_JSON.exists():
        t0 = time.perf_counter()
        data = json.loads(CHESSDB_JSON.read_text(encoding="utf-8"))
        rows = list(_iter_chessdb_rows(data))
        con.executemany(
            "INSERT INTO chessdb (fen, status, moves_json) VALUES (?,?,?)", rows
        )
        con.commit()
        dt = time.perf_counter() - t0
        totals["chessdb"] = len(rows)
        print(f"[migrate] {CHESSDB_JSON.name:32s}            rows={len(rows):6d}  {dt:5.2f}s")
    else:
        print(f"[migrate] skip (missing): {CHESSDB_JSON.name}")

    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print()
    print(f"[migrate] done. {DB_PATH.name} = {size_mb:.1f} MB")
    for k, v in totals.items():
        print(f"           {k:10s} {v:6d} rows")


if __name__ == "__main__":
    main()
