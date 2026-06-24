"""One-off depth-32 re-eval on the existing depth-28 FENs that belong to
two specific opening files:

  - 順包直車3兵對橫車邊馬.xqf
  - 順包兩頭蛇對雙橫車.xqf

Purpose: cross-check depth-28 verdicts against an even deeper search. The
depth-22→depth-28 pass flipped ~47% of trap verdicts, so depth-32 may still
matter.

Output: positions_d32.js (window.POSITIONS_D32). Resumable. Auto-renders
and pushes when done so master wakes up to fresh data.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT_DIR = REPO / "output" / "site"
VERY_DEEP_JS = OUT_DIR / "positions_very_deep.js"
D32_JS = OUT_DIR / "positions_d32.js"

# Substring-match against rel_path. '順包\\' covers every file under 順包/
# (2026-05-31: 5 files). Kept in sync with verify_d28_shunbao.py.
TARGET_REL_KEYWORDS = ('順包\\',)


def _load_window_cache(path, var_name):
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(rf'window\.{var_name}\s*=\s*(\{{.*\}});\s*$', text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _save_window_cache(path, var_name, data):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    path.write_text(f"window.{var_name} = {payload};\n", encoding='utf-8')


def collect_target_fens():
    """All unique FENs that (a) live in the two target XQFs AND
    (b) already have a depth-28 entry in positions_very_deep.js."""
    games = json.loads((OUT_DIR / 'data' / 'games.json').read_text(encoding='utf-8'))
    very_deep = _load_window_cache(VERY_DEEP_JS, 'POSITIONS_VERY_DEEP')
    in_targets = set()
    for g in games:
        rel = g.get('rel_path', '') or ''
        if not any(t in rel for t in TARGET_REL_KEYWORDS):
            continue
        for plies in g['variations']:
            for p in plies:
                fen = p.get('fen')
                if fen:
                    in_targets.add(fen)
    return sorted(in_targets & set(very_deep.keys()))


def is_valid_entry(entry, target_depth):
    if not entry:
        return False
    d = entry.get('depth')
    if d is None:
        return False
    # Decided-position early-stop entries (depth < target but 'capped') count as
    # done — re-running just re-decides the same way. See clean_eval.go decisive_cp.
    if d < target_depth and not entry.get('capped'):
        return False
    bm = entry.get('best_iccs')
    return isinstance(bm, str) and len(bm) == 4


def run_engine(depth, threads, hash_mb, checkpoint_every, deadline=None,
               movetime=None, decisive_cp=None):
    d32 = _load_window_cache(D32_JS, 'POSITIONS_D32')
    candidates = collect_target_fens()
    todo = [f for f in candidates if not is_valid_entry(d32.get(f), depth)]
    print(f"[d32] {len(candidates)} target FENs / {len(todo)} new at depth {depth}",
          flush=True)
    if not todo:
        print("[d32] nothing to do", flush=True)
        return d32

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(threads))
    eng.set_option('Hash', str(hash_mb))
    eng.isready()

    t0 = time.time()
    try:
        for i, fen in enumerate(todo, 1):
            if deadline and time.time() >= deadline:
                print(f"[deadline] reached at FEN {i}/{len(todo)} — saving and exiting",
                      flush=True)
                _save_window_cache(D32_JS, 'POSITIONS_D32', d32)
                return d32
            ts = time.time()
            res = eng.go(fen, depth, movetime=movetime, decisive_cp=decisive_cp)
            dt = time.time() - ts
            reached = res.get('depth')
            d32[fen] = {
                'best_iccs': res.get('move'),
                'score': res.get('score') if isinstance(res.get('score'), int) else None,
                'mate': res.get('mate'),
                'pv': (res.get('pv') or [])[:16],
                'depth': reached or depth,
                'capped': bool(res.get('stopped_early')) or (
                    bool(movetime) and reached is not None and reached < depth),
            }
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(todo)}] {dt:6.1f}s  "
                  f"score={res.get('score')}  best={res.get('move')}  "
                  f"({elapsed/60:.1f}m elapsed, eta {eta/60:.0f}m)", flush=True)
            if i % checkpoint_every == 0 or i == len(todo):
                _save_window_cache(D32_JS, 'POSITIONS_D32', d32)
                print(f"  [checkpoint] saved {len(d32)} entries", flush=True)
    finally:
        try:
            eng._send('quit')
        except Exception:
            pass
    return d32


def _refresh_sqlite_best_effort():
    """Rebuild output/positions.db for the sibling chess-book-editor — best-effort.

    If the editor backend holds positions.db open, migrate's DB_PATH.unlink()
    raises WinError 32. We swallow it so a DB lock can never abort the commit/
    push that ran *before* this call (the nightly bug that silently blocked
    deploys for two nights, fixed 2026-06-24). Rebuild the DB manually once the
    editor is free."""
    print("[post] migrate_to_sqlite.py (best-effort)", flush=True)
    try:
        subprocess.run([sys.executable, str(REPO / 'site_builder' / 'migrate_to_sqlite.py')],
                       check=True, cwd=str(REPO))
    except subprocess.CalledProcessError as e:
        print(f"[post] WARNING: migrate_to_sqlite failed ({e}); positions.db likely "
              f"locked by chess-book-editor — skipped, rebuild manually when free.",
              flush=True)


def post_render_and_push():
    """UI doesn't surface d32 yet, but we refresh the SQLite eval DB (consumed
    read-only by the sibling chess-book-editor) and commit + push so master
    can inspect cross-machine + cross-repo."""
    print("[post] git add data", flush=True)
    subprocess.run(['git', 'add', str(D32_JS.relative_to(REPO))],
                   check=True, cwd=str(REPO))
    msg = (
        "Cross-check depth-28 verdicts at depth 32 (順包 two files)\n"
        "\n"
        "Re-evaluates the 56 depth-28 FENs that live in 順包直車3兵對橫車邊馬\n"
        "and 順包兩頭蛇對雙橫車 at depth 32 to test whether depth-28 confirm/\n"
        "reject classifications are stable. Commits positions_d32.js; also\n"
        "rebuilds the local output/positions.db (gitignored) so the sibling\n"
        "chess-book-editor sees fresh evals. UI in this repo not yet plumbed.\n"
        "\n"
        "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    rc = subprocess.run(['git', 'commit', '-m', msg], cwd=str(REPO))
    if rc.returncode == 0:
        print("[post] git push", flush=True)
        subprocess.run(['git', 'push'], check=True, cwd=str(REPO))
    else:
        print("[post] nothing to commit, skipping push", flush=True)
    _refresh_sqlite_best_effort()
    print("[post] done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=32)
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--hash-mb', type=int, default=512)
    ap.add_argument('--checkpoint-every', type=int, default=5)
    ap.add_argument('--decisive-cp', type=int, default=800,
                    help='Decided-position early stop (|score|>=cp at depth>=18, '
                         '2 straight depths). Undecided positions still run to '
                         'depth 32. 0 = off. Default 800.')
    ap.add_argument('--movetime', type=int, default=600000,
                    help='Hard per-FEN wall-time backstop in ms (0 = none). '
                         'Default 600000 (10 min).')
    ap.add_argument('--max-hours', type=float, default=None)
    ap.add_argument('--no-post', action='store_true')
    args = ap.parse_args()

    print(f"=== verify_d32 start {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)
    deadline = (time.time() + args.max_hours * 3600) if args.max_hours else None
    deadline_str = (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(deadline))
                    if deadline else 'none')
    print(f"  depth={args.depth} threads={args.threads} hash={args.hash_mb}MB  "
          f"checkpoint_every={args.checkpoint_every}  decisive_cp={args.decisive_cp}  "
          f"movetime={args.movetime}ms  deadline={deadline_str}",
          flush=True)
    try:
        run_engine(args.depth, args.threads, args.hash_mb,
                   args.checkpoint_every, deadline=deadline,
                   movetime=(args.movetime or None),
                   decisive_cp=(args.decisive_cp or None))
    except KeyboardInterrupt:
        print("[interrupt] stopped — partial cache saved", flush=True)
        return
    if not args.no_post:
        post_render_and_push()
    print(f"=== verify_d32 end {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)


if __name__ == '__main__':
    main()
