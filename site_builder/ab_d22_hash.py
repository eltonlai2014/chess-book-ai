"""Hash-isolation A/B: hold ORDER fixed (DFS), vary only Hash (16MB vs 1024MB).

The order A/B (ab_d22_order.py) showed FEN order is ~accuracy-neutral. This
isolates the OTHER variable that changed in the d12 recompute — TT Hash size —
to test whether THAT is the real accuracy lever (D12_TT_SWEEP.md says 16MB gave
"zero TT reuse").

Reuses the identical 300-FEN DFS-ordered set from ab_d22_order.py. The Hash=1024
arm is loaded from the saved output/_ab_d22_D.json (DFS order, Hash 1024, T1, d22)
— same conditions — so we only run ONE new arm here: Hash=16, same order.

  py site_builder/ab_d22_hash.py
"""
import json, math, time, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions  # noqa: E402
from enrich_decisive import collect_fens_to_eval, PUBLIC_EXCLUDE_KEYWORDS  # noqa: E402
from build_data import collect_fens_dfs  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT = REPO / "output" / "site"
CAP = 300
DEPTH = 22


def load(path):
    txt = path.read_text(encoding="utf-8")
    txt = txt[txt.index("{"):].rstrip().rstrip(";")
    return json.loads(txt)


def select_order():
    """Reproduce the EXACT 300-FEN DFS order from ab_d22_order.py (deterministic)."""
    games = json.loads((OUT / "data" / "games.json").read_text(encoding='utf-8'))
    shallow = load_positions(OUT / "positions.js")
    d28 = load(OUT / "positions_very_deep.js")
    public = [g for g in games
              if not any(k in (g.get('rel_path') or '') for k in PUBLIC_EXCLUDE_KEYWORDS)]
    scored = []
    for g in public:
        cand = collect_fens_to_eval([g], shallow)
        ref = sum(1 for f in cand if f in d28 and d28[f].get('mate') is None)
        if cand:
            scored.append((ref, len(cand), g))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    sel, cand_all = [], set()
    for ref, ncand, g in scored:
        sel.append(g)
        cand_all |= collect_fens_to_eval([g], shallow)
        if len(cand_all) >= CAP:
            break
    order_dfs = [f for f in collect_fens_dfs(sel) if f in cand_all][:CAP]
    scorable = [f for f in order_dfs if f in d28 and d28[f].get('mate') is None]
    return order_dfs, scorable, d28


def run_arm(order, hash_mb):
    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', '1')
    eng.set_option('Hash', str(hash_mb))
    eng.isready()
    res = {}
    t0 = time.time()
    try:
        for i, f in enumerate(order, 1):
            a = eng.go(f, DEPTH)
            res[f] = {'best': a.get('move'),
                      'score': a.get('score') if isinstance(a.get('score'), int) else None,
                      'mate': a.get('mate')}
            if i % 25 == 0:
                el = time.time() - t0
                print(f"   [H{hash_mb} {i}/{len(order)}] {el:.0f}s ({i/el:.2f}/s)", flush=True)
    finally:
        eng.quit()
    return res, time.time() - t0


def stats(res, scorable, d28):
    errs, sign, mv, xs, ys = [], 0, 0, [], []
    for f in scorable:
        if res[f]['mate'] is not None or res[f]['score'] is None or d28[f]['score'] is None:
            continue
        s, ref = res[f]['score'], d28[f]['score']
        errs.append(abs(s - ref))
        if (s > 0) == (ref > 0) or (s == 0 and ref == 0): sign += 1
        if res[f]['best'] == d28[f].get('best_iccs'): mv += 1
        xs.append(s); ys.append(ref)
    n = len(errs); e = sorted(errs)
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((a-mx)*(b-my) for a, b in zip(xs, ys))
    vx = math.sqrt(sum((a-mx)**2 for a in xs)); vy = math.sqrt(sum((b-my)**2 for b in ys))
    return dict(n=n, mean=sum(errs)/n, med=e[n//2], p90=e[min(n-1, int(n*0.9))],
                sign=sign/n, mv=mv/n, r=cov/(vx*vy) if vx and vy else float('nan'))


def main():
    order, scorable, d28 = select_order()
    print(f"[set] {len(order)} FENs (DFS order, same as arm D), {len(scorable)} scorable vs d28")

    # Hash=1024 arm: reuse saved arm D (identical conditions)
    saved = json.loads((REPO / "output" / "_ab_d22_D.json").read_text(encoding='utf-8'))
    r1024, w1024 = saved['res'], saved['wall']
    assert all(f in r1024 for f in order), "saved arm D doesn't cover this FEN set"
    print(f"[H1024] reused from _ab_d22_D.json (wall {w1024:.0f}s)")

    print("\n=== new arm: Hash=16MB, DFS order ===")
    r16, w16 = run_arm(order, 16)
    (REPO / "output" / "_ab_d22_H16.json").write_text(
        json.dumps({'wall': w16, 'res': r16}, ensure_ascii=False))

    s16, s1024 = stats(r16, scorable, d28), stats(r1024, scorable, d28)
    closer16 = closer1024 = tie = 0
    for f in scorable:
        if r16[f]['score'] is None or r1024[f]['score'] is None or d28[f]['score'] is None:
            continue
        if r16[f]['mate'] is not None or r1024[f]['mate'] is not None:
            continue
        e16 = abs(r16[f]['score'] - d28[f]['score'])
        e1024 = abs(r1024[f]['score'] - d28[f]['score'])
        if e1024 < e16: closer1024 += 1
        elif e16 < e1024: closer16 += 1
        else: tie += 1

    print(f"\n==== vs d28 (n={s16['n']}), ORDER fixed=DFS, only Hash varies ====")
    print(f"{'metric':<22}{'Hash 16MB':>13}{'Hash 1024MB':>14}   winner")
    def row(name, a, b, lower=True, pct=False, r=False):
        f = (lambda v: f'{v*100:.1f}%') if pct else (lambda v: f'{v:.3f}') if r else (lambda v: f'{v:.1f}')
        w = ('1024' if b < a else '16' if a < b else '=') if lower else ('1024' if b > a else '16' if a > b else '=')
        print(f"{name:<22}{f(a):>13}{f(b):>14}   {w}")
    row('|err vs d28| mean', s16['mean'], s1024['mean'])
    row('|err vs d28| median', s16['med'], s1024['med'])
    row('|err vs d28| p90', s16['p90'], s1024['p90'])
    row('sign agreement', s16['sign'], s1024['sign'], lower=False, pct=True)
    row('bestmove == d28', s16['mv'], s1024['mv'], lower=False, pct=True)
    row('Pearson r vs d28', s16['r'], s1024['r'], lower=False, r=True)
    print(f"\nhead-to-head closer to d28: H1024 {closer1024} / H16 {closer16} / tie {tie}")
    print(f"wall: H16 {w16:.0f}s  H1024 {w1024:.0f}s")


if __name__ == '__main__':
    main()
