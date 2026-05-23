"""One-shot diff: depth-28 vs depth-32 on the 56 shared FENs in the two
順包 books. Run after the d32 schtask completes to see which verdicts
moved when we deepened by 4 plies."""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output" / "site"


def load_cache(path, var):
    m = re.search(rf'window\.{var}\s*=\s*(\{{.*\}});\s*$',
                  Path(path).read_text(encoding='utf-8'), re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def main():
    vd = load_cache(OUT_DIR / 'positions_very_deep.js', 'POSITIONS_VERY_DEEP')
    d32 = load_cache(OUT_DIR / 'positions_d32.js', 'POSITIONS_D32')
    games = json.loads((OUT_DIR / 'data' / 'games.json').read_text(encoding='utf-8'))

    targets = ['順包直車3兵對橫車邊馬', '順包兩頭蛇對雙橫車']
    loc = {}
    for g in games:
        rel = g.get('rel_path', '')
        hit = next((t for t in targets if t in rel), None)
        if not hit:
            continue
        for vi, plies in enumerate(g['variations']):
            for pi, p in enumerate(plies):
                f = p.get('fen')
                if f and f not in loc:
                    loc[f] = (hit, vi + 1, pi + 1, p.get('iccs', ''), p.get('chinese', ''))

    common = [f for f in d32 if f in vd]
    print(f'Comparable FENs: {len(common)}')

    rows = []
    for f in common:
        s28 = vd[f].get('score')
        s32 = d32[f].get('score')
        bm28 = vd[f].get('best_iccs')
        bm32 = d32[f].get('best_iccs')
        if s28 is None or s32 is None:
            continue
        delta = s32 - s28
        bm_changed = bm28 != bm32
        if abs(delta) >= 30 or bm_changed:
            rows.append((abs(delta), delta, s28, s32, bm28, bm32, loc.get(f, ('?', 0, 0, '', '')), bm_changed))

    rows.sort(reverse=True)
    bm_count = sum(1 for r in rows if r[7])
    print(f'FENs that moved (|Δ|>=30 OR best-move change): {len(rows)} / {len(common)}')
    print(f'  of which best-move changed: {bm_count}')
    print()
    hdr = f'{"檔":24} {"變·步":>9}  {"走法":<10} {"d28":>5} {"d32":>5} {"Δ":>5}  best d28→d32'
    print(hdr)
    print('-' * len(hdr))
    for absd, d, s28, s32, bm28, bm32, info, bm_changed in rows:
        name, vi, pi, iccs, chinese = info
        bm_note = '' if not bm_changed else f'  {bm28}→{bm32}'
        chinese = (chinese or iccs)[:8]
        print(f'{name:24} v{vi:>3}·p{pi:<3}  {chinese:<10} {s28:>5} {s32:>5} {d:>+5}{bm_note}')


if __name__ == '__main__':
    main()
