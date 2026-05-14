"""For each variation ending in a decisive position, walk the deep-eval trajectory
and pinpoint the ply where the losing side actually blundered.

Output: top-N "human trap" plies sorted by swing magnitude. These are positions
where shallow analysis would not catch the mistake but deep search reveals it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
games = json.loads((REPO / "output/site/data/games.json").read_text(encoding='utf-8'))
shallow = load_positions(REPO / "output/site/positions.js")
deep = load_positions(REPO / "output/site/positions_deep.js")

# Skip plies 1..10 — opening theory is well-known; deep-vs-shallow drift there
# is mostly engine artefact (depth 22 can over-judge slow positions). The UI
# applies the same cutoff; keep them in sync.
SKIP_OPENING_PLIES = 15


def best_score(fen):
    """Prefer deep over shallow."""
    if fen in deep:
        return score_cp(deep[fen]), 'deep'
    if fen in shallow:
        return score_cp(shallow[fen]), 'shallow'
    return None, None


def main():
    swings = []

    for g in games:
        for vi, plies in enumerate(g['variations']):
            scores = []
            for p in plies:
                fen = p.get('fen')
                if not fen:
                    scores.append(None)
                    continue
                s, src = best_score(fen)
                scores.append(s)

            # Find biggest swing AGAINST the side that just moved
            # Loss for ply i (the side that moved at ply i): scores[i] + scores[i+1]
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                if scores[pi] is None or scores[pi+1] is None:
                    continue
                loss = scores[pi] + scores[pi+1]
                if loss < 100:
                    continue
                # Also need: was this NOT obvious at shallow depth?
                fa = plies[pi].get('fen')
                fb = plies[pi+1].get('fen')
                if fa not in shallow or fb not in shallow:
                    continue
                sh_loss = score_cp(shallow[fa]) + score_cp(shallow[fb])
                shallow_blind = sh_loss < 50  # shallow thought this move was fine
                swing_diff = loss - sh_loss
                p = plies[pi]
                swings.append({
                    'file': g['file'],
                    'vi': vi + 1,
                    'pi': pi + 1,
                    'side': p['side'],
                    'chinese': p['chinese'],
                    'iccs': p['iccs'],
                    'fen': fa,
                    'shallow_loss': sh_loss,
                    'deep_loss': loss,
                    'swing': swing_diff,
                    'shallow_blind': shallow_blind,
                    'annote': (p.get('annote') or '').strip()[:60],
                })

    # Filter out mate-saturated positions (|score| > 2000 = endgame mate sequence)
    real = [s for s in swings if abs(s['deep_loss']) < 2000]
    mate_zone = len(swings) - len(real)

    # Dedupe by FEN — same position reached via different variation prefixes
    # is conceptually the same blunder, not separate findings.
    seen_fens = set()
    unique = []
    for s in real:
        if s['fen'] in seen_fens:
            continue
        seen_fens.add(s['fen'])
        unique.append(s)

    blind = [s for s in unique if s['shallow_blind']]
    confirmed = [s for s in unique if not s['shallow_blind']]

    blind.sort(key=lambda s: -s['deep_loss'])
    confirmed.sort(key=lambda s: -s['deep_loss'])

    print(f"Total ply-blunders (deep_loss>100): {len(swings)}")
    print(f"  - mate-zone (deep_loss>2000, late tactical sequence): {mate_zone}")
    print(f"  - real opening/middle-game range (100-2000): {len(real)}")
    print(f"     of which shallow-blind: {len(blind)}  ← actual human traps")
    print(f"     of which shallow-saw-it: {len(confirmed)}\n")

    print("=== TOP 20 OPENING/MIDDLE-GAME HUMAN TRAPS ===")
    print("    (shallow said fine, deep says 100-2000 cp loss)\n")
    for s in blind[:20]:
        ann = f"  «{s['annote']}»" if s['annote'] else ''
        print(f"  {s['file'][:20]:<20} v{s['vi']:>3} ply{s['pi']:>3} {s['side']:>5} "
              f"{s['chinese']:<6}  深失={s['deep_loss']:>4}cp (淺={s['shallow_loss']:+4}){ann}")

    print("\n=== TOP 10 confirmed blunders ===")
    for s in confirmed[:10]:
        print(f"  {s['file'][:20]:<20} v{s['vi']:>3} ply{s['pi']:>3} {s['side']:>5} "
              f"{s['chinese']:<6}  深失={s['deep_loss']:>4}cp (淺={s['shallow_loss']:+4})")


if __name__ == '__main__':
    main()
