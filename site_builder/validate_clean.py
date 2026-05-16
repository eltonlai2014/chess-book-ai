"""Sanity check the CleanUciEngine driver against 10 known-corrupted FENs
from the deep cache. If the driver produces legal bestmoves and consistent
scores across two runs, we can trust it for the full re-eval."""
import json
import random
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
    text = DEEP_JS.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS_DEEP\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    return json.loads(m.group(1))


def main():
    deep = load_deep()
    invalid = []
    for fen, e in deep.items():
        best = e.get('best_iccs')
        if best and ChessBoard(fen).move_iccs(best) is None:
            invalid.append(fen)
    random.seed(42)
    sample = random.sample(invalid, 10)

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', '4')
    eng.set_option('Hash', '512')
    eng.isready()

    print(f"{'fen[:46]':<48} {'cache_move':<10} {'clean_move':<10} "
          f"{'legal?':<7} {'cache_sc':>9} {'clean_sc':>9} {'t(s)':>6}")
    print('-' * 110)

    legal_count = 0
    runs = []
    for fen in sample:
        cached = deep[fen]
        t0 = time.time()
        result = eng.go(fen, 22)
        elapsed = time.time() - t0
        move = result.get('move')
        legal = move is not None and ChessBoard(fen).move_iccs(move) is not None
        if legal:
            legal_count += 1
        score_str = (f"{result['score']:+d}" if result.get('score') is not None
                     else (f"M{result['mate']}" if result.get('mate') is not None else '?'))
        cache_score_str = (f"{cached.get('score'):+d}" if cached.get('score') is not None
                           else (f"M{cached.get('mate')}" if cached.get('mate') is not None else '?'))
        print(f"{fen[:46]:<48} {cached.get('best_iccs') or '?':<10} "
              f"{move or '?':<10} {'YES' if legal else 'NO':<7} "
              f"{cache_score_str:>9} {score_str:>9} {elapsed:>6.1f}")
        runs.append((fen, result))

    print('-' * 110)
    print(f"legal moves: {legal_count}/{len(sample)}  "
          f"(target: {len(sample)}/{len(sample)} for the fix to be valid)")

    # Second pass: run the same FENs again, see if results are stable
    print("\n=== second pass (same FENs, same driver) — should match first ===")
    stable = 0
    for fen, prev in runs:
        result = eng.go(fen, 22)
        match = (result.get('move') == prev.get('move')
                 and result.get('score') == prev.get('score')
                 and result.get('mate') == prev.get('mate'))
        if match:
            stable += 1
        else:
            print(f"  DIFF {fen[:50]} prev={prev.get('move')}/{prev.get('score')} "
                  f"now={result.get('move')}/{result.get('score')}")
    print(f"stable across runs: {stable}/{len(sample)}")

    eng.quit()


if __name__ == '__main__':
    main()
