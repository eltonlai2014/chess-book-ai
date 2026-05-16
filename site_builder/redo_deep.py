"""Re-evaluate every FEN in positions_deep.js using the CleanUciEngine
driver. The original enrich_decisive.py used cchess.UciEngine which has a
thread race that corrupts ~85% of deep entries at depth 22.

Output: overwrites positions_deep.js in place. Checkpoints every 50 FENs.
Resumable: if an entry is already at depth >= target AND its best_iccs is
a legal move from the FEN, it's skipped.

Usage:
  py site_builder/redo_deep.py --depth 22 --threads 4 --hash-mb 512
  py site_builder/redo_deep.py --depth 22 --limit 50    # quick test
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from cchess import ChessBoard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
DEEP_JS = REPO / "output" / "site" / "positions_deep.js"


def load_deep():
    if not DEEP_JS.exists():
        return {}
    text = DEEP_JS.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS_DEEP\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def save_deep(d):
    payload = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
    DEEP_JS.write_text(f"window.POSITIONS_DEEP = {payload};\n", encoding='utf-8')


def is_entry_valid(fen, entry, target_depth):
    """Trust an existing entry only if its depth meets the target AND the
    stored bestmove is actually a legal move from this position."""
    if not entry:
        return False
    if (entry.get('depth') or 0) < target_depth:
        return False
    best = entry.get('best_iccs')
    if not best:
        # Terminal positions (mate-in-N near 0) may have no bestmove — treat
        # those as valid only if explicit mate/draw signal is present.
        return entry.get('mate') is not None or entry.get('move') in ('draw',)
    try:
        return ChessBoard(fen).move_iccs(best) is not None
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--hash-mb', type=int, default=512)
    ap.add_argument('--limit', type=int, default=0,
                    help='process at most N FENs (0 = all)')
    args = ap.parse_args()

    deep = load_deep()
    print(f"[load] {len(deep)} existing entries", file=sys.stderr)

    # Compose todo: every FEN currently in cache (we want to redo them all
    # because most are corrupted). Filter out already-valid-and-deep entries.
    all_fens = list(deep.keys())
    todo = [f for f in all_fens if not is_entry_valid(f, deep.get(f), args.depth)]
    print(f"[plan] {len(todo)} FENs need re-evaluation at depth {args.depth}",
          file=sys.stderr)
    if args.limit:
        todo = todo[:args.limit]
        print(f"[plan] limited to first {len(todo)}", file=sys.stderr)

    if not todo:
        print("[done] nothing to do", file=sys.stderr)
        return

    eta_min = len(todo) * 5.5 / 60
    print(f"[plan] est. wall clock @ 5.5s/FEN: {eta_min:.0f} min", file=sys.stderr)

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(args.threads))
    eng.set_option('Hash', str(args.hash_mb))
    eng.isready()
    print(f"[engine] Threads={args.threads}  Hash={args.hash_mb}MB",
          file=sys.stderr)

    t0 = time.time()
    try:
        for idx, fen in enumerate(todo, 1):
            result = eng.go(fen, args.depth)
            # Validate the new result is legal before writing
            move = result.get('move')
            legal = move and ChessBoard(fen).move_iccs(move) is not None
            tag = '' if legal else '  ILLEGAL-MOVE'
            deep[fen] = {
                'best_iccs': move,
                'score': result.get('score') if isinstance(result.get('score'), int) else None,
                'mate': result.get('mate'),
                'pv': result.get('pv') or [],
                'depth': args.depth,
            }
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(todo) - idx) / rate if rate > 0 else 0
            score_str = (f"{result.get('score'):+d}" if result.get('score') is not None
                         else (f"M{result.get('mate')}" if result.get('mate') is not None else '?'))
            pv_len = len(result.get('pv') or [])
            print(f"  [{idx}/{len(todo)}] {fen[:40]}... "
                  f"move={move or '?'} sc={score_str} pv={pv_len}"
                  f"{tag} ({elapsed:.0f}s, eta {eta:.0f}s)",
                  file=sys.stderr)
            if idx % 50 == 0:
                save_deep(deep)
    finally:
        try:
            eng.quit()
        except Exception:
            pass

    save_deep(deep)
    print(f"[write] {DEEP_JS} ({len(deep)} positions total)", file=sys.stderr)


if __name__ == '__main__':
    main()
