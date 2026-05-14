"""Re-evaluate suspicious positions at higher depth.

Strategy: walk every variation in games.json, compute centipawn-loss using the
shallow depth-12 cache (positions.js). Any ply whose loss > THRESHOLD is a
candidate for a deeper search — the shallow engine may have mis-judged either
the position before or after the move, so we deep-search BOTH FENs.

Output: output/site/positions_deep.js — same shape as positions.js but only
for the FENs we re-evaluated. UI can overlay this on top of the shallow cache.

Usage:
  py site_builder/enrich_depth.py --depth 22 --threshold 100
  py site_builder/enrich_depth.py --depth 22 --threshold 100 --limit 3
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from cchess import UciEngine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import run_engine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT_DIR = REPO / "output" / "site"
GAMES_JSON = OUT_DIR / "data" / "games.json"
POSITIONS_JS = OUT_DIR / "positions.js"
DEEP_JS = OUT_DIR / "positions_deep.js"


def load_positions(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(r'window\.\w+\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def save_deep(path: Path, deep: dict):
    payload = json.dumps(deep, ensure_ascii=False, separators=(',', ':'))
    path.write_text(f"window.POSITIONS_DEEP = {payload};\n", encoding='utf-8')


def score_cp(entry):
    """Return centipawn score from side-to-move POV; mate becomes ±30000-ish."""
    if entry is None:
        return None
    if entry.get('mate') is not None:
        m = entry['mate']
        return 30000 - abs(m) if m > 0 else -(30000 - abs(m))
    s = entry.get('score')
    return s if isinstance(s, int) else None


def find_candidates(games: list, shallow: dict, threshold: int):
    """Return list of (fen, reason_str) for FENs whose ply has loss > threshold.

    Loss for ply i (side X to move at fen[i]): score(fen[i]) + score(fen[i+1]).
    Both POV-relative scores, so adding them gives X's centipawn loss.
    """
    candidates = {}  # fen -> list of reasons
    for g in games:
        for vi, plies in enumerate(g['variations']):
            for pi in range(len(plies) - 1):
                a = plies[pi]
                b = plies[pi + 1]
                fa = a.get('fen')
                fb = b.get('fen')
                if not fa or not fb:
                    continue
                ea = shallow.get(fa)
                eb = shallow.get(fb)
                if not ea or not eb:
                    continue
                sa = score_cp(ea)
                sb = score_cp(eb)
                if sa is None or sb is None:
                    continue
                loss = sa + sb
                if loss > threshold:
                    tag = f"{g['file']} v{vi+1} ply{pi+1} loss={loss}"
                    for fen in (fa, fb):
                        candidates.setdefault(fen, []).append(tag)
    return candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--threshold', type=int, default=100,
                    help='Centipawn loss threshold; ply with loss above this triggers deep eval')
    ap.add_argument('--limit', type=int, default=None,
                    help='Process only first N games (for testing)')
    ap.add_argument('--force', action='store_true',
                    help='Re-evaluate even FENs already in positions_deep.js')
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    if args.limit:
        games = games[:args.limit]
        print(f"[limit] using first {len(games)} games", file=sys.stderr)

    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)
    print(f"[load] shallow={len(shallow)}  deep={len(deep)}", file=sys.stderr)

    candidates = find_candidates(games, shallow, args.threshold)
    print(f"[scan] {len(candidates)} candidate FENs with loss > {args.threshold} cp", file=sys.stderr)

    todo = [f for f in candidates if args.force or f not in deep or deep[f].get('depth', 0) < args.depth]
    print(f"[plan] {len(todo)} FENs need deep eval at depth {args.depth}", file=sys.stderr)
    if not todo:
        print("[done] nothing to do", file=sys.stderr)
        return

    eng = UciEngine()
    eng.load(str(EXE))
    if not eng.wait_for_ready(timeout=15):
        raise RuntimeError("engine not ready")

    t0 = time.time()
    flipped = 0
    try:
        for idx, fen in enumerate(todo, 1):
            act = run_engine(eng, fen, args.depth)
            entry = {
                'best_iccs': act.get('move'),
                'score': act.get('score') if isinstance(act.get('score'), int) else None,
                'mate': act.get('mate'),
                'pv': act.get('moves', [])[:8],
                'depth': args.depth,
            }
            deep[fen] = entry

            # Compare against shallow
            sh = shallow.get(fen, {})
            sh_score = score_cp(sh)
            dp_score = score_cp(entry)
            sh_move = sh.get('best_iccs')
            dp_move = entry['best_iccs']
            tag = ''
            if sh_move != dp_move:
                tag += ' MOVE-CHANGED'
                flipped += 1
            if sh_score is not None and dp_score is not None and abs(sh_score - dp_score) > 100:
                tag += f' SCORE-SHIFT({sh_score:+d}->{dp_score:+d})'

            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(todo) - idx) / rate if rate > 0 else 0
            print(f"  [{idx}/{len(todo)}] {fen[:40]}... "
                  f"shallow={sh_move}/{sh_score} deep={dp_move}/{dp_score}{tag} "
                  f"({elapsed:.0f}s, eta {eta:.0f}s)", file=sys.stderr)

            if idx % 10 == 0:
                save_deep(DEEP_JS, deep)
    finally:
        try:
            eng.quit()
        except Exception:
            pass

    save_deep(DEEP_JS, deep)
    print(f"[write] {DEEP_JS} ({len(deep)} positions, {flipped} move-flips this run)", file=sys.stderr)


if __name__ == '__main__':
    main()
