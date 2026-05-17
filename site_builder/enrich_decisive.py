"""Deep-evaluate every ply in variations that END in a decisive position.

Logic: if the final ply's shallow score is large (|score| > THRESHOLD), the
side that ended up losing made a mistake somewhere. Deep-evaluating every
position in such a variation lets us find the exact ply where the score
swung — that's where the human-trap lies.

Usage:
  py site_builder/enrich_decisive.py --depth 22 --threshold 300
  py site_builder/enrich_decisive.py --depth 22 --threshold 300 --dry-run
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, save_deep, score_cp  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT_DIR = REPO / "output" / "site"
GAMES_JSON = OUT_DIR / "data" / "games.json"
POSITIONS_JS = OUT_DIR / "positions.js"
DEEP_JS = OUT_DIR / "positions_deep.js"


SKIP_OPENING_PLIES = 15  # plies 1..15 = opening theory; comparing book vs engine here is misframed (avoiding all engine-preferred moves makes it a different opening). Skip for compute savings AND noise reduction; UI applies same cutoff.


def find_decisive_variations(games, shallow, threshold):
    """Return list of (game, vi, plies, final_score) for variations whose last
    valid ply has |shallow score| > threshold."""
    out = []
    for g in games:
        for vi, plies in enumerate(g['variations']):
            # Find last ply with cached score
            final_score = None
            for p in reversed(plies):
                fen = p.get('fen')
                if fen and fen in shallow:
                    sc = score_cp(shallow[fen])
                    if sc is not None:
                        final_score = sc
                        break
            if final_score is None:
                continue
            if abs(final_score) > threshold:
                out.append((g, vi, plies, final_score))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--threshold', type=int, default=300)
    ap.add_argument('--threads', type=int, default=4,
                    help='Pikafish search threads (i7-8700 has 6 cores; 4 leaves room for other work)')
    ap.add_argument('--hash-mb', type=int, default=512,
                    help='Pikafish transposition table size in MB (default 16 is way too small)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)
    print(f"[load] shallow={len(shallow)}  deep={len(deep)}", file=sys.stderr)

    decisive = find_decisive_variations(games, shallow, args.threshold)
    fens_in_variations = set()
    for _, _, plies, _ in decisive:
        # Skip opening theory — deep eval at pi<SKIP_OPENING_PLIES rarely reveals
        # real traps, mostly just depth artefacts. Saves a lot of compute and
        # matches the UI which won't flag those plies anyway.
        for pi, p in enumerate(plies):
            if pi < SKIP_OPENING_PLIES:
                continue
            fen = p.get('fen')
            if fen and fen in shallow:
                fens_in_variations.add(fen)

    todo = [f for f in fens_in_variations
            if f not in deep or deep[f].get('depth', 0) < args.depth]
    print(f"[scan] decisive variations: {len(decisive)} (|final|>{args.threshold})",
          file=sys.stderr)
    print(f"[scan] unique FENs in those variations: {len(fens_in_variations)}",
          file=sys.stderr)
    print(f"[plan] need deep eval at depth {args.depth}: {len(todo)} FENs",
          file=sys.stderr)
    eta_min = len(todo) * 5.5 / 60
    print(f"[plan] est. wall clock @ 5.5s/FEN: {eta_min:.0f} min", file=sys.stderr)

    if args.dry_run or not todo:
        return

    # CleanUciEngine instead of cchess.UciEngine — see clean_eval.py for why
    # (cchess thread race trashed 85% of depth-22 entries in earlier runs).
    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(args.threads))
    eng.set_option('Hash', str(args.hash_mb))
    eng.isready()
    print(f"[engine] Threads={args.threads}  Hash={args.hash_mb}MB (clean driver)",
          file=sys.stderr)

    t0 = time.time()
    try:
        for idx, fen in enumerate(todo, 1):
            act = eng.go(fen, args.depth)
            deep[fen] = {
                'best_iccs': act.get('move'),
                'score': act.get('score') if isinstance(act.get('score'), int) else None,
                'mate': act.get('mate'),
                'pv': act.get('pv') or [],
                'depth': args.depth,
            }
            sh = shallow.get(fen, {})
            sh_score = score_cp(sh)
            dp_score = score_cp(deep[fen])
            tag = ''
            if sh.get('best_iccs') != deep[fen]['best_iccs']:
                tag += ' MOVE-CHANGED'
            if sh_score is not None and dp_score is not None and abs(sh_score - dp_score) > 100:
                tag += f' SCORE-SHIFT({sh_score:+d}->{dp_score:+d})'

            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(todo) - idx) / rate if rate > 0 else 0
            print(f"  [{idx}/{len(todo)}] {fen[:40]}... "
                  f"shallow={sh.get('best_iccs')}/{sh_score} deep={deep[fen]['best_iccs']}/{dp_score}{tag} "
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
