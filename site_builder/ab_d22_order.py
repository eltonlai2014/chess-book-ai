"""A/B test: does DFS preorder (warm TT) make d22 closer to d28 than lexical order?

Isolates ONE variable — FEN visit order — by evaluating the SAME candidate FEN
set twice at depth 22, Hash 1024, Threads 1, each arm in a FRESH engine process
(so the TT starts empty for both):

  arm L : sorted(FEN) order      (what enrich_decisive.py did before)
  arm D : collect_fens_dfs order (parent ply before children/siblings)

Reference = d28 (positions_very_deep.js), the deeper, more authoritative eval —
same role d22 played when we validated d12.

Writes nothing to the live caches. Sidecar results → output/_ab_d22_{L,D}.json.

  py site_builder/ab_d22_order.py --dry-run          # show selection + ETA
  py site_builder/ab_d22_order.py --cap 300          # run both arms
"""
import argparse, json, math, time, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp  # noqa: E402
from enrich_decisive import collect_fens_to_eval, PUBLIC_EXCLUDE_KEYWORDS  # noqa: E402
from build_data import collect_fens_dfs  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT = REPO / "output" / "site"
GAMES = OUT / "data" / "games.json"


def load(path):
    txt = path.read_text(encoding="utf-8")
    txt = txt[txt.index("{"):].rstrip().rstrip(";")
    return json.loads(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cap', type=int, default=300,
                    help='approx max candidate FENs across the selected games')
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    games = json.loads(GAMES.read_text(encoding='utf-8'))
    shallow = load_positions(OUT / "positions.js")
    d28 = load(OUT / "positions_very_deep.js")
    public = [g for g in games
              if not any(k in (g.get('rel_path') or '') for k in PUBLIC_EXCLUDE_KEYWORDS)]

    # Per-game candidate set; rank by how many candidates have a d28 reference
    # (only those are scorable), so the A/B has the most signal per engine-second.
    scored = []
    for g in public:
        cand = collect_fens_to_eval([g], shallow)
        ref = sum(1 for f in cand if f in d28 and d28[f].get('mate') is None)
        if cand:
            scored.append((ref, len(cand), g))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    # Take whole games (most d28-refs first) until we have enough candidates to
    # truncate from, then keep the first `cap` FENs in DFS preorder. A contiguous
    # DFS prefix preserves within-variation parent->child locality — exactly the
    # warm-TT effect we're testing. Both arms run on this identical FEN set.
    sel = []
    cand_all = set()
    for ref, ncand, g in scored:
        sel.append(g)
        cand_all |= collect_fens_to_eval([g], shallow)
        if len(cand_all) >= args.cap:
            break

    order_dfs_full = [f for f in collect_fens_dfs(sel) if f in cand_all]
    order_dfs = order_dfs_full[:args.cap]          # contiguous DFS prefix
    test_set = set(order_dfs)
    order_lex = sorted(test_set)                   # same FENs, lexical order
    scorable = [f for f in order_dfs if f in d28 and d28[f].get('mate') is None]

    print(f"[select] {len(sel)} games -> {len(cand_all)} candidates; "
          f"testing first {len(order_dfs)} in DFS order, {len(scorable)} with d28 reference")
    for ref, ncand, g in scored:
        if g in sel:
            print(f"   - {g['file']:<28} cand={ncand}  d28-ref={ref}")
    eta = len(order_dfs) * 2 * 10 / 60  # 2 arms, ~10s/FEN single-thread d22 guess
    print(f"[eta] ~{eta:.0f} min (2 arms x {len(order_dfs)} FENs @ ~10s, single-thread)")
    if args.dry_run:
        return

    def run_arm(label, order):
        eng = CleanUciEngine(str(EXE))
        eng.set_option('Threads', '1')
        eng.set_option('Hash', '1024')
        eng.isready()
        res = {}
        t0 = time.time()
        try:
            for i, f in enumerate(order, 1):
                a = eng.go(f, args.depth)
                res[f] = {'best': a.get('move'),
                          'score': a.get('score') if isinstance(a.get('score'), int) else None,
                          'mate': a.get('mate')}
                if i % 25 == 0:
                    el = time.time() - t0
                    print(f"   [{label} {i}/{len(order)}] {el:.0f}s ({i/el:.2f}/s)", flush=True)
        finally:
            eng.quit()
        wall = time.time() - t0
        print(f"[{label}] done {len(order)} FENs in {wall:.0f}s ({len(order)/wall:.2f}/s)")
        (REPO / "output" / f"_ab_d22_{label}.json").write_text(
            json.dumps({'wall': wall, 'res': res}, ensure_ascii=False))
        return res, wall

    print("\n=== arm D (DFS preorder, warm TT) ===")
    rd, wd = run_arm('D', order_dfs)
    print("\n=== arm L (lexical order) ===")
    rl, wl = run_arm('L', order_lex)

    # Score both against d28 on the scorable subset
    def stats(label, res):
        errs, sign, mv, xs, ys = [], 0, 0, [], []
        for f in scorable:
            if res[f]['mate'] is not None or res[f]['score'] is None:
                continue
            s = res[f]['score']; ref = d28[f]['score']
            if ref is None:
                continue
            errs.append(abs(s - ref))
            if (s > 0) == (ref > 0) or (s == 0 and ref == 0): sign += 1
            if res[f]['best'] == d28[f].get('best_iccs'): mv += 1
            xs.append(s); ys.append(ref)
        n = len(errs)
        errs_s = sorted(errs)
        mx, my = sum(xs)/n, sum(ys)/n
        cov = sum((a-mx)*(b-my) for a, b in zip(xs, ys))
        vx = math.sqrt(sum((a-mx)**2 for a in xs)); vy = math.sqrt(sum((b-my)**2 for b in ys))
        r = cov/(vx*vy) if vx and vy else float('nan')
        return dict(n=n, mean=sum(errs)/n, med=errs_s[n//2],
                    p90=errs_s[min(n-1, int(n*0.9))], sign=sign/n, mv=mv/n, r=r)

    sD, sL = stats('D', rd), stats('L', rl)
    dfs_closer = lex_closer = tie = 0
    for f in scorable:
        if rd[f]['score'] is None or rl[f]['score'] is None or d28[f]['score'] is None:
            continue
        if rd[f]['mate'] is not None or rl[f]['mate'] is not None:
            continue
        ed = abs(rd[f]['score'] - d28[f]['score']); el = abs(rl[f]['score'] - d28[f]['score'])
        if ed < el: dfs_closer += 1
        elif el < ed: lex_closer += 1
        else: tie += 1

    print(f"\n==== scored vs d28 (n={sD['n']}) ====")
    print(f"{'metric':<22}{'arm L (lex)':>14}{'arm D (DFS)':>14}   winner")
    def row(name, a, b, lower=True, pct=False, r=False):
        f = (lambda v: f'{v*100:.1f}%') if pct else (lambda v: f'{v:.3f}') if r else (lambda v: f'{v:.1f}')
        w = ('D' if b < a else 'L' if a < b else '=') if lower else ('D' if b > a else 'L' if a > b else '=')
        print(f"{name:<22}{f(a):>14}{f(b):>14}   {w}")
    row('|err vs d28| mean', sL['mean'], sD['mean'])
    row('|err vs d28| median', sL['med'], sD['med'])
    row('|err vs d28| p90', sL['p90'], sD['p90'])
    row('sign agreement', sL['sign'], sD['sign'], lower=False, pct=True)
    row('bestmove == d28', sL['mv'], sD['mv'], lower=False, pct=True)
    row('Pearson r vs d28', sL['r'], sD['r'], lower=False, r=True)
    print(f"\nhead-to-head closer to d28: DFS {dfs_closer} / LEX {lex_closer} / tie {tie}")
    print(f"wall clock: LEX {wl:.0f}s  DFS {wd:.0f}s  "
          f"({'DFS faster by ' + format((wl-wd)/wl*100, '.1f') + '%' if wd < wl else 'LEX faster'})  "
          f"<- speed gap = TT reuse evidence")


if __name__ == '__main__':
    main()
