"""Quick stats: how effective is the loss>100 threshold at catching plies whose
shallow-depth judgement differs from depth-22?"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp

REPO = Path(__file__).resolve().parent.parent
games = json.loads((REPO / "output/site/data/games.json").read_text(encoding='utf-8'))
shallow = load_positions(REPO / "output/site/positions.js")
deep = load_positions(REPO / "output/site/positions_deep.js")

samples = {'gone': [], 'worse': [], 'shrunk': []}
for g in games:
    for vi, plies in enumerate(g['variations']):
        for pi in range(len(plies) - 1):
            a, b = plies[pi], plies[pi + 1]
            fa, fb = a.get('fen'), b.get('fen')
            if not fa or not fb or fa not in shallow or fb not in shallow:
                continue
            ssa, ssb = score_cp(shallow[fa]), score_cp(shallow[fb])
            if ssa is None or ssb is None:
                continue
            sloss = ssa + ssb
            if sloss <= 100:
                continue
            if fa not in deep or fb not in deep:
                continue
            dsa, dsb = score_cp(deep[fa]), score_cp(deep[fb])
            if dsa is None or dsb is None:
                continue
            dloss = dsa + dsb
            tag = f"{g['file'][:20]} v{vi+1:>2} ply{pi+1:>2} {a['chinese']}"
            if dloss <= 50:
                samples['gone'].append((sloss, dloss, tag))
            elif dloss < sloss - 50:
                samples['shrunk'].append((sloss, dloss, tag))
            elif dloss > sloss + 50:
                samples['worse'].append((sloss, dloss, tag))

print('=== gone (shallow 冤枉了書譜步) top 8 ===')
for sloss, dloss, tag in sorted(samples['gone'])[:8]:
    print(f'  淺={sloss:+5d}  深={dloss:+5d}    {tag}')
print()
print('=== worse (淺算還低估失分) top 8 ===')
for sloss, dloss, tag in sorted(samples['worse'], key=lambda x: -x[1])[:8]:
    print(f'  淺={sloss:+5d}  深={dloss:+5d}    {tag}')
print()
print('=== shrunk (失分縮水) top 5 ===')
for sloss, dloss, tag in sorted(samples['shrunk'])[:5]:
    print(f'  淺={sloss:+5d}  深={dloss:+5d}    {tag}')
