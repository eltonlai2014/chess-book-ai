"""Re-evaluate trap positions with a longer PV (up to PV_LEN moves).

The existing positions_deep.js caps PV at 8 moves, which often cuts off before
red's winning sequence is fully visible. This script finds plies where the deep
search reveals a significant swing (|mover-POV loss| > THRESHOLD, ply >= 15)
and re-runs the engine on those FENs + their immediate successors, overwriting
the cached entries with the longer PV.

Usage:
  py site_builder/extend_trap_pv.py --threshold 200 --pv-len 16
"""
import argparse
import json
import sys
import time
from pathlib import Path

from cchess import UciEngine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import run_engine  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, save_deep, score_cp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT_DIR = REPO / "output" / "site"
GAMES_JSON = OUT_DIR / "data" / "games.json"
DEEP_JS = OUT_DIR / "positions_deep.js"
SKIP_OPENING_PLIES = 15


def find_trap_fens(games, deep, threshold, top_per_variation):
    """Same trap selection as list_trap_plies.py: positive mover-POV loss
    >= threshold, ply >= SKIP_OPENING_PLIES, |loss| < 2000 (skip mate-zone),
    capped to top-N per (file, variation) by loss. Returns both the trap
    FENs and the immediate next ply's FEN (so the user can play through the
    refutation from either side of the blunder)."""
    # First: collect all trap rows
    raw = []
    for g in games:
        for vi, plies in enumerate(g['variations']):
            scores = [score_cp(deep[p['fen']]) if p.get('fen') in deep else None
                      for p in plies]
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                if scores[pi] is None or scores[pi + 1] is None:
                    continue
                loss = scores[pi] + scores[pi + 1]
                if loss < threshold or loss >= 2000:
                    continue
                raw.append({
                    'file': g['file'], 'vi': vi, 'pi': pi, 'loss': loss,
                    'fa': plies[pi].get('fen'),
                    'fb': plies[pi + 1].get('fen'),
                })

    # Dedupe by trap FEN (same position via different prefixes)
    seen = set()
    unique = []
    raw.sort(key=lambda r: (r['file'], r['vi'], r['pi']))
    for r in raw:
        if r['fa'] in seen:
            continue
        seen.add(r['fa'])
        unique.append(r)

    # Top-N per (file, variation) by loss
    from collections import defaultdict
    groups = defaultdict(list)
    for r in unique:
        groups[(r['file'], r['vi'])].append(r)
    capped = []
    for _, rows in groups.items():
        rows.sort(key=lambda r: -r['loss'])
        capped.extend(rows[:top_per_variation])

    targets = set()
    for r in capped:
        if r['fa']:
            targets.add(r['fa'])
        if r['fb']:
            targets.add(r['fb'])
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--threshold', type=int, default=200,
                    help='mover-POV loss threshold (cp) to call a ply a "trap"')
    ap.add_argument('--pv-len', type=int, default=16,
                    help='PV moves to keep (default 16; previous default was 8)')
    ap.add_argument('--top-per-variation', type=int, default=3,
                    help='per (file, variation), only extend top-N traps by loss '
                         '(matches list_trap_plies.py default)')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--hash-mb', type=int, default=512)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    deep = load_positions(DEEP_JS)
    print(f"[load] deep={len(deep)}", file=sys.stderr)

    fens = find_trap_fens(games, deep, args.threshold, args.top_per_variation)
    todo = sorted(f for f in fens if f in deep)
    print(f"[scan] trap FENs (|loss| > {args.threshold}, pi >= {SKIP_OPENING_PLIES}): "
          f"{len(fens)}; existing in deep cache: {len(todo)}", file=sys.stderr)
    eta_min = len(todo) * 6.0 / 60
    print(f"[plan] re-evaluate {len(todo)} FENs @ depth {args.depth}, PV[:{args.pv_len}] "
          f"— est. {eta_min:.0f} min", file=sys.stderr)

    if args.dry_run or not todo:
        return

    eng = UciEngine()
    eng.load(str(EXE))
    if not eng.wait_for_ready(timeout=15):
        raise RuntimeError("engine not ready")
    eng.set_option('Threads', str(args.threads))
    eng.set_option('Hash', str(args.hash_mb))
    print(f"[engine] Threads={args.threads}  Hash={args.hash_mb}MB", file=sys.stderr)

    t0 = time.time()
    try:
        for idx, fen in enumerate(todo, 1):
            act = run_engine(eng, fen, args.depth)
            old_pv_len = len(deep[fen].get('pv') or [])
            deep[fen] = {
                'best_iccs': act.get('move'),
                'score': act.get('score') if isinstance(act.get('score'), int) else None,
                'mate': act.get('mate'),
                'pv': act.get('moves', [])[:args.pv_len],
                'depth': args.depth,
            }
            new_pv_len = len(deep[fen]['pv'])
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(todo) - idx) / rate if rate > 0 else 0
            print(f"  [{idx}/{len(todo)}] {fen[:40]}... "
                  f"pv {old_pv_len} -> {new_pv_len} "
                  f"({elapsed:.0f}s, eta {eta:.0f}s)", file=sys.stderr)
            if idx % 20 == 0:
                save_deep(DEEP_JS, deep)
    finally:
        try:
            eng.quit()
        except Exception:
            pass

    save_deep(DEEP_JS, deep)
    print(f"[write] {DEEP_JS} ({len(deep)} positions total)", file=sys.stderr)


if __name__ == '__main__':
    main()
