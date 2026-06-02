"""Deep-evaluate plies in public games (non-中貴棋譜), up to the first ply
where the shallow score becomes decisive (|d12| > DECISIVE_CUTOFF).

Policy (2026-06-01):
  - Skip games whose rel_path matches PUBLIC_EXCLUDE_KEYWORDS — those get d12
    only (中貴棋譜/ corpus is real-game collections, kept local for the editor
    but not deep-evaluated).
  - For each remaining variation, walk plies and include each (subject to
    SKIP_OPENING_PLIES). Once |d12 score| > DECISIVE_CUTOFF at some ply N,
    include ply N (so trap detection at ply N-1 still has both neighbours)
    then stop the walk for this variation.
  - PV stored truncated to PV_KEEP entries — d22 PV is only trustworthy for
    the first ~10 plies (master's empirical observation).

Usage:
  py site_builder/enrich_decisive.py --depth 22
  py site_builder/enrich_decisive.py --depth 22 --dry-run
"""
import argparse
import json
import subprocess
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


SKIP_OPENING_PLIES = 15  # plies 1..15 = opening theory; comparing book vs engine here is misframed.
PUBLIC_EXCLUDE_KEYWORDS = ('中貴棋譜',)  # mirror render_site.PUBLIC_EXCLUDE_KEYWORDS — these get d12 only
DECISIVE_CUTOFF = 500  # |d12 score| > this → stop deepening further plies in the variation
PV_KEEP = 10           # d22 PV is reliable for ~first 10 plies; rest is engine drift


def collect_fens_to_eval(games, shallow):
    """Walk every public-game variation, include each ply ≥ SKIP_OPENING_PLIES,
    stop when |d12 score| first exceeds DECISIVE_CUTOFF (inclusive of that ply
    so the prior trap pair stays evaluable)."""
    out = set()
    for g in games:
        rel = g.get('rel_path', '') or ''
        if any(k in rel for k in PUBLIC_EXCLUDE_KEYWORDS):
            continue
        for plies in g['variations']:
            for pi, p in enumerate(plies):
                if pi < SKIP_OPENING_PLIES:
                    # Still need to honour the decisive cutoff even in the opening prefix,
                    # so peek at the score and break early if already past it.
                    fen = p.get('fen')
                    if fen and fen in shallow:
                        sc = score_cp(shallow[fen])
                        if sc is not None and abs(sc) > DECISIVE_CUTOFF:
                            break
                    continue
                fen = p.get('fen')
                if not fen or fen not in shallow:
                    continue
                out.add(fen)
                sc = score_cp(shallow[fen])
                if sc is not None and abs(sc) > DECISIVE_CUTOFF:
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=22)
    ap.add_argument('--threads', type=int, default=4,
                    help='Pikafish search threads (i7-8700 has 6 cores; 4 leaves room for other work)')
    ap.add_argument('--hash-mb', type=int, default=512,
                    help='Pikafish transposition table size in MB (default 16 is way too small)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-hours', type=float, default=None,
                    help='Self-deadline — save and exit cleanly when reached')
    ap.add_argument('--no-post', action='store_true',
                    help='Skip the auto render + migrate + commit + push at end')
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)
    print(f"[load] shallow={len(shallow)}  deep={len(deep)}", file=sys.stderr)
    n_public = sum(1 for g in games
                   if not any(k in (g.get('rel_path') or '') for k in PUBLIC_EXCLUDE_KEYWORDS))
    n_excl = len(games) - n_public
    print(f"[scope] {n_public} public games / {n_excl} excluded (中貴棋譜)", file=sys.stderr)

    candidates = collect_fens_to_eval(games, shallow)
    todo = [f for f in sorted(candidates)
            if f not in deep or deep[f].get('depth', 0) < args.depth]
    print(f"[scan] candidate FENs (public, ply≥{SKIP_OPENING_PLIES}, "
          f"|d12|≤{DECISIVE_CUTOFF} or decisive boundary): {len(candidates)}",
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
    deadline = (time.time() + args.max_hours * 3600) if args.max_hours else None
    hit_deadline = False
    try:
        for idx, fen in enumerate(todo, 1):
            if deadline and time.time() >= deadline:
                print(f"[deadline] reached at FEN {idx}/{len(todo)} — saving and exiting",
                      file=sys.stderr)
                save_deep(DEEP_JS, deep)
                hit_deadline = True
                break
            act = eng.go(fen, args.depth)
            deep[fen] = {
                'best_iccs': act.get('move'),
                'score': act.get('score') if isinstance(act.get('score'), int) else None,
                'mate': act.get('mate'),
                'pv': (act.get('pv') or [])[:PV_KEEP],
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

    if not args.no_post:
        post_render_and_push(hit_deadline)


def post_render_and_push(partial: bool):
    """Refresh public site, rebuild SQLite eval DB, commit + push."""
    print("[post] render_site.py", flush=True)
    subprocess.run([sys.executable, str(REPO / 'site_builder' / 'render_site.py')],
                   check=True, cwd=str(REPO))
    print("[post] migrate_to_sqlite.py", flush=True)
    subprocess.run([sys.executable, str(REPO / 'site_builder' / 'migrate_to_sqlite.py')],
                   check=True, cwd=str(REPO))
    print("[post] git add", flush=True)
    subprocess.run(['git', 'add', 'docs/', 'output/site/', 'DEEP_STATUS.md'],
                   check=True, cwd=str(REPO))
    msg = (
        "Enrich d22 nightly progress — public 42 books\n"
        "\n"
        "Resumable sweep over public-game positions (中貴棋譜/ excluded).\n"
        "Variation walk stops at first |d12|>500 ply per master policy.\n"
        + ("Partial batch (hit --max-hours deadline).\n" if partial
           else "Full pass complete for this corpus snapshot.\n")
        + "\n"
        "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
    )
    rc = subprocess.run(['git', 'commit', '-m', msg], cwd=str(REPO))
    if rc.returncode != 0:
        print("[post] nothing to commit, skipping push", flush=True)
        return
    print("[post] git push", flush=True)
    subprocess.run(['git', 'push'], check=True, cwd=str(REPO))
    print("[post] done", flush=True)


if __name__ == '__main__':
    main()
