"""Time-probe depth 28 (or any target depth) on a small sample of trap FENs
so we can estimate how long a full verification run would take. Reads the
trap list straight from games.json + positions{,_deep}.js so the sample
matches reality. Prints per-FEN timing and a rough projection.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_eval import CleanUciEngine  # noqa: E402
from enrich_depth import load_positions, score_cp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
SKIP_OPENING_PLIES = 15


def collect_trap_fens(games, shallow, deep, n_sample=5):
    """Return a list of (fen_before, fen_after) pairs for sampled traps."""
    pairs = []
    seen = set()
    for g in games:
        for plies in g['variations']:
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                fa = plies[pi].get('fen')
                fb = plies[pi + 1].get('fen')
                if not fa or not fb:
                    continue
                if fa not in deep or fb not in deep:
                    continue
                if fa not in shallow or fb not in shallow:
                    continue
                d_loss = score_cp(deep[fa]) + score_cp(deep[fb])
                s_loss = score_cp(shallow[fa]) + score_cp(shallow[fb])
                if d_loss <= 100 or d_loss >= 2000 or s_loss >= 50:
                    continue
                if fa in seen:
                    continue
                seen.add(fa)
                pairs.append((fa, fb))
                if len(pairs) >= n_sample:
                    return pairs
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=28)
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--hash-mb', type=int, default=512)
    ap.add_argument('--samples', type=int, default=5)
    args = ap.parse_args()

    import json
    games = json.loads((REPO / 'output/site/data/games.json').read_text(encoding='utf-8'))
    shallow = load_positions(REPO / 'output/site/positions.js')
    deep = load_positions(REPO / 'output/site/positions_deep.js')
    print(f"[load] {len(games)} games, {len(shallow)} shallow, {len(deep)} deep", file=sys.stderr)

    pairs = collect_trap_fens(games, shallow, deep, n_sample=args.samples)
    fens = []
    for fa, fb in pairs:
        if fa not in fens: fens.append(fa)
        if fb not in fens: fens.append(fb)
    print(f"[sample] {len(pairs)} trap pairs -> {len(fens)} unique FENs", file=sys.stderr)

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(args.threads))
    eng.set_option('Hash', str(args.hash_mb))
    eng.isready()

    times = []
    for i, fen in enumerate(fens, 1):
        t0 = time.time()
        res = eng.go(fen, args.depth)
        dt = time.time() - t0
        times.append(dt)
        print(f"  [{i}/{len(fens)}] {dt:6.1f}s  depth={res.get('depth')}  "
              f"score={res.get('score')}  best={res.get('move')}  fen={fen[:30]}...",
              file=sys.stderr)

    eng._send('quit')

    avg = sum(times) / len(times)
    # full verification = ~ all trap FENs (before + after), deduped.
    # Estimate using a rough trap-count proxy: count unique trap fens in full dataset.
    seen = set()
    n_full_pairs = 0
    for g in games:
        for plies in g['variations']:
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                fa = plies[pi].get('fen')
                fb = plies[pi + 1].get('fen')
                if not (fa and fb and fa in deep and fb in deep
                        and fa in shallow and fb in shallow):
                    continue
                d_loss = score_cp(deep[fa]) + score_cp(deep[fb])
                s_loss = score_cp(shallow[fa]) + score_cp(shallow[fb])
                if d_loss <= 100 or d_loss >= 2000 or s_loss >= 50:
                    continue
                if fa in seen:
                    continue
                seen.add(fa)
                n_full_pairs += 1

    full_fens = set()
    seen2 = set()
    for g in games:
        for plies in g['variations']:
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                fa = plies[pi].get('fen')
                fb = plies[pi + 1].get('fen')
                if not (fa and fb and fa in deep and fb in deep
                        and fa in shallow and fb in shallow):
                    continue
                d_loss = score_cp(deep[fa]) + score_cp(deep[fb])
                s_loss = score_cp(shallow[fa]) + score_cp(shallow[fb])
                if d_loss <= 100 or d_loss >= 2000 or s_loss >= 50:
                    continue
                if fa in seen2:
                    continue
                seen2.add(fa)
                full_fens.add(fa)
                full_fens.add(fb)

    eta = len(full_fens) * avg
    print()
    print(f"=== summary at depth {args.depth} (threads={args.threads}, hash={args.hash_mb}MB) ===")
    print(f"  avg per FEN: {avg:.1f}s  (min {min(times):.1f}, max {max(times):.1f})")
    print(f"  full set:    {n_full_pairs} unique traps  -> {len(full_fens)} unique FENs")
    print(f"  projected:   {eta:.0f}s = {eta/60:.1f} min = {eta/3600:.2f} h")


if __name__ == '__main__':
    main()
