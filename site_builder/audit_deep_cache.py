"""Audit positions_deep.js: for each entry, check whether the stored
best_iccs is a legal move from the position's FEN. Report what fraction
are corrupted, and sample a few to re-evaluate with a fresh engine call.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import run_engine  # noqa: E402

from cchess import ChessBoard, UciEngine

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
DEEP_JS = REPO / "output" / "site" / "positions_deep.js"
SHALLOW_JS = REPO / "output" / "site" / "positions.js"


def load_positions(path, varname):
    text = path.read_text(encoding='utf-8')
    m = re.search(rf'window\.{varname}\s*=\s*(\{{.*\}});\s*$', text, re.DOTALL)
    return json.loads(m.group(1))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'deep'
    if which == 'shallow':
        deep = load_positions(SHALLOW_JS, 'POSITIONS')
    else:
        deep = load_positions(DEEP_JS, 'POSITIONS_DEEP')
    print(f"[load] {len(deep)} {which} entries", file=sys.stderr)

    invalid_best = []
    valid_best = []
    for fen, e in deep.items():
        best = e.get('best_iccs')
        if not best:
            continue
        b = ChessBoard(fen)
        if b.move_iccs(best) is None:
            invalid_best.append(fen)
        else:
            valid_best.append(fen)
    print(f"  valid best_iccs:   {len(valid_best)}")
    print(f"  invalid best_iccs: {len(invalid_best)}  <-- corrupted entries")
    print()

    # Re-evaluate 10 random invalid entries to see what the engine ACTUALLY says
    import random
    random.seed(42)
    sample = random.sample(invalid_best, min(10, len(invalid_best)))

    if which == 'shallow':
        print("[note] shallow audit done, skipping engine re-eval", file=sys.stderr)
        return
    eng = UciEngine()
    eng.load(str(EXE))
    if not eng.wait_for_ready(timeout=15):
        print("engine not ready", file=sys.stderr)
        return
    eng.set_option('Threads', '4')
    eng.set_option('Hash', '256')

    print(f"=== re-evaluating {len(sample)} corrupted entries @ depth 22 ===")
    print(f"{'fen[:50]':<52} {'cached':>12} {'fresh':>12} {'score_cache':>11} {'score_fresh':>11}")
    for fen in sample:
        cached = deep[fen]
        t0 = time.time()
        act = run_engine(eng, fen, 22)
        elapsed = time.time() - t0
        print(f"{fen[:50]:<52} "
              f"{cached.get('best_iccs') or '?':>12} "
              f"{act.get('move') or '?':>12} "
              f"{str(cached.get('score') or cached.get('mate') or '?'):>11} "
              f"{str(act.get('score') or act.get('mate') or '?'):>11}  "
              f"({elapsed:.1f}s)")
    eng.quit()


if __name__ == '__main__':
    main()
