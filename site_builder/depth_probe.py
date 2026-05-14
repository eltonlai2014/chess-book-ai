"""Run Pikafish on one FEN at multiple depths and tabulate how score/move converge.

Two ways to supply the position:
  py depth_probe.py --fen "rnbakabnr/9/1c5c1/... w"  --depths 12,16,20,24
  py depth_probe.py --game 牛頭滾.xqf --variation 10 --ply 31  --depths 12,16,20,24

The "--game --variation --ply" form looks up the pre-move FEN of that ply in
output/site/data/games.json (1-based indices to match the UI's row numbers).
"""
import argparse
import json
import sys
import time
from pathlib import Path

from cchess import UciEngine

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
GAMES_JSON = REPO / "output" / "site" / "data" / "games.json"


def resolve_fen(game_name, variation_idx_1, ply_idx_1):
    data = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    needle = game_name.lower().replace('.xqf', '')
    for g in data:
        if needle in g['file'].lower():
            vi = variation_idx_1 - 1
            pi = ply_idx_1 - 1
            v = g['variations'][vi]
            return v[pi]['fen'], v[pi]
    raise SystemExit(f"game not found: {game_name}")


def run_one(eng, fen, depth):
    eng.go_from(fen, params={'depth': depth})
    t0 = time.time()
    last = None
    timeout = max(60, depth * depth)  # heuristic upper bound
    while time.time() - t0 < timeout:
        act = eng.get_action()
        if act is None:
            time.sleep(0.01)
            continue
        if act['action'] == 'info_move':
            last = act
        elif act['action'] == 'bestmove':
            last = act
            break
        elif act['action'] in ('dead', 'draw'):
            last = act
            break
    return last, time.time() - t0


def fmt_score(act):
    if not act:
        return '?'
    if 'mate' in act and act['mate'] is not None:
        m = act['mate']
        return f"M{m}" if m > 0 else f"-M{-m}"
    s = act.get('score')
    return f"{s:+d}" if isinstance(s, int) else '?'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fen', help='FEN string (overrides --game/--variation/--ply)')
    ap.add_argument('--game', help='Substring of game filename (used with --variation/--ply)')
    ap.add_argument('--variation', type=int, help='1-based variation index')
    ap.add_argument('--ply', type=int, help='1-based ply index within the variation')
    ap.add_argument('--depths', default='12,16,20,24',
                    help='Comma-separated depths to test (default: 12,16,20,24)')
    args = ap.parse_args()

    if args.fen:
        fen = args.fen
        ply = None
    else:
        if not (args.game and args.variation and args.ply):
            ap.error("must supply --fen, or --game --variation --ply")
        fen, ply = resolve_fen(args.game, args.variation, args.ply)
        print(f"# Resolved {args.game} var={args.variation} ply={args.ply}")
        print(f"#   side: {ply['side']}  book: {ply['chinese']} ({ply['iccs']})")

    depths = [int(x) for x in args.depths.split(',')]
    print(f"# FEN: {fen}")
    print()

    eng = UciEngine()
    eng.load(str(EXE))
    if not eng.wait_for_ready(timeout=15):
        raise RuntimeError("engine not ready")

    print(f"{'depth':>6}  {'best':>6}  {'score':>7}  {'time':>7}  pv (first 8)")
    print(f"{'-' * 6}  {'-' * 6}  {'-' * 7}  {'-' * 7}  ----")
    try:
        for d in depths:
            act, elapsed = run_one(eng, fen, d)
            best = act.get('move', '?') if act else '?'
            score = fmt_score(act)
            pv = ' '.join((act.get('moves') or [])[:8]) if act else ''
            print(f"{d:>6}  {best:>6}  {score:>7}  {elapsed:>6.1f}s  {pv}")
    finally:
        try:
            eng.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
