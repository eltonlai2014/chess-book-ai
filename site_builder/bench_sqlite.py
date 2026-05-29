"""Sanity-check + benchmark the migrated SQLite vs raw JS lookup."""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "output" / "positions.db"
JS = ROOT / "output" / "site" / "positions.js"

def t(label, fn, *a):
    t0 = time.perf_counter()
    out = fn(*a)
    print(f"  {label:50s} {(time.perf_counter()-t0)*1000:7.2f} ms")
    return out

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# pick a known FEN to query
sample_fen = con.execute("SELECT fen FROM evals WHERE depth=12 LIMIT 1").fetchone()["fen"]
print(f"sample fen: {sample_fen}\n")

print("[A] Single-FEN lookup (cold cache)")
con.close()
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
t("SELECT score,best_iccs WHERE fen=? AND depth=12",
  lambda: con.execute("SELECT score,best_iccs FROM evals WHERE fen=? AND depth=12", (sample_fen,)).fetchone())
t("SELECT all depths for one fen",
  lambda: con.execute("SELECT depth,score,best_iccs FROM evals WHERE fen=?", (sample_fen,)).fetchall())

print("\n[B] Bulk operations (typical editor session = look up ~100 FENs)")
fens = [r["fen"] for r in con.execute("SELECT fen FROM evals WHERE depth=12 LIMIT 100").fetchall()]
t("100x single SELECT (sequential)",
  lambda: [con.execute("SELECT score FROM evals WHERE fen=? AND depth=12",(f,)).fetchone() for f in fens])
t("1x SELECT ... WHERE fen IN (100)",
  lambda: con.execute(f"SELECT fen,score FROM evals WHERE depth=12 AND fen IN ({','.join('?'*len(fens))})", fens).fetchall())

print("\n[C] Analytical queries (what was painful with .js files)")
t("count FENs at each depth",
  lambda: con.execute("SELECT depth, COUNT(*) FROM evals GROUP BY depth").fetchall())
t("FENs missing depth 28 (resume target)",
  lambda: con.execute("SELECT COUNT(*) FROM evals WHERE depth=22 AND fen NOT IN (SELECT fen FROM evals WHERE depth=28)").fetchone())
t("biggest depth-12 vs depth-28 swings (top 10)",
  lambda: con.execute("""
    SELECT s.fen, s.score AS d12, d.score AS d28, ABS(s.score-d.score) AS swing
    FROM evals s JOIN evals d ON s.fen=d.fen AND s.depth=12 AND d.depth=28
    WHERE s.score IS NOT NULL AND d.score IS NOT NULL
    ORDER BY swing DESC LIMIT 10
  """).fetchall())

print("\n[D] Raw JS load (for comparison)")
def load_js():
    text = JS.read_text(encoding="utf-8")
    body = text[text.index("=")+1:].strip().rstrip(";")
    return json.loads(body)
data = t("read+parse positions.js (full file, 7.6 MB)", load_js)
t("dict lookup after load (100x)",
  lambda: [data[f] for f in fens])

con.close()
print("\ndone.")
