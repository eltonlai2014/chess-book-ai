"""Inverse of find_trap_plies: list plies where the deep eval says the
played move was BETTER than the engine's first choice (mover-gained cp).
Use sparingly — short PVs and depth-22 quirks make some of these spurious.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SKIP = 15


def main():
    games = json.loads((REPO / 'output/site/data/games.json').read_text(encoding='utf-8'))
    shallow = load_positions(REPO / 'output/site/positions.js')
    deep = load_positions(REPO / 'output/site/positions_deep.js')

    brilliants = []
    seen = set()
    for g in games:
        for vi, plies in enumerate(g['variations']):
            for pi in range(SKIP, len(plies) - 1):
                fa = plies[pi].get('fen')
                fb = plies[pi + 1].get('fen')
                if not (fa and fb and fa in deep and fb in deep
                        and fa in shallow and fb in shallow):
                    continue
                d_loss = score_cp(deep[fa]) + score_cp(deep[fb])
                if d_loss >= -50:           # only mover-gained 50cp+
                    continue
                if abs(d_loss) >= 2000:     # mate-zone noise
                    continue
                s_loss = score_cp(shallow[fa]) + score_cp(shallow[fb])
                if fa in seen:
                    continue
                seen.add(fa)
                brilliants.append({
                    'file': g['file'], 'vi': vi + 1, 'pi': pi + 1,
                    'side': plies[pi]['side'], 'chinese': plies[pi]['chinese'],
                    'iccs': plies[pi]['iccs'],
                    'deep_gain': -d_loss,
                    'shallow_delta': -s_loss,
                })

    brilliants.sort(key=lambda x: -x['deep_gain'])
    print(f"共 {len(brilliants)} 個 unique 妙手候選（深算-mover gain >=50cp，排除 mate-zone）")
    print()
    header = f"{'排名':<5}{'gain':>6}  {'淺Δ':>7}  方  走法        步           檔案"
    print(header)
    print('-' * len(header) * 2)
    for i, b in enumerate(brilliants[:20], 1):
        side = '紅' if b['side'] == 'red' else '黑'
        fname = b['file'][:32]
        print(f"{i:<5}+{b['deep_gain']:>5}  {b['shallow_delta']:+6d}    {side}  "
              f"{b['chinese']:<10}  v{b['vi']:>3} ply{b['pi']:<3}  {fname}")

    hidden = [b for b in brilliants if abs(b['shallow_delta']) < 50]
    print(f"\n其中淺算看不出（|淺Δ|<50）的「隱形妙手」：{len(hidden)} 個")
    if hidden:
        print()
        for i, b in enumerate(hidden[:10], 1):
            side = '紅' if b['side'] == 'red' else '黑'
            fname = b['file'][:32]
            print(f"  {i:<3}+{b['deep_gain']:>5}  淺{b['shallow_delta']:+5d}  {side}  "
                  f"{b['chinese']:<10}  v{b['vi']:>3} ply{b['pi']:<3}  {fname}")


if __name__ == '__main__':
    main()
