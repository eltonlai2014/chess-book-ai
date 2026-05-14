"""Check how shallow vs deep diverge in opening plies."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp

REPO = Path(__file__).resolve().parent.parent
games = json.loads((REPO / "output/site/data/games.json").read_text(encoding='utf-8'))
shallow = load_positions(REPO / "output/site/positions.js")
deep = load_positions(REPO / "output/site/positions_deep.js")

# For each variation that has deep data in plies 1-15, compute shallow vs deep loss
flagged = []
for g in games:
    for vi, plies in enumerate(g['variations']):
        for pi in range(min(15, len(plies) - 1)):
            a, b = plies[pi], plies[pi+1]
            fa, fb = a.get('fen'), b.get('fen')
            if not fa or not fb: continue
            if fa not in deep or fb not in deep: continue
            if fa not in shallow or fb not in shallow: continue
            sh = score_cp(shallow[fa]) + score_cp(shallow[fb])
            dp = score_cp(deep[fa]) + score_cp(deep[fb])
            if sh < 50 and dp > 100:
                flagged.append({
                    'file': g['file'][:18], 'vi': vi+1, 'pi': pi+1,
                    'side': a['side'], 'cn': a['chinese'], 'sh': sh, 'dp': dp,
                })

print(f"Early-ply (pi<=15) flagged as trap: {len(flagged)}")
for f in sorted(flagged, key=lambda x: -x['dp'])[:15]:
    print(f"  {f['file']:<18} v{f['vi']:>3} ply{f['pi']:>3} {f['side']:>5} {f['cn']:<6} 淺={f['sh']:+4} 深={f['dp']:+4}")
