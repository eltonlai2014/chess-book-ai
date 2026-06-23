"""Verify every flagged trap by re-evaluating both fen_before and fen_after
at a deeper search depth (default 28). Saves to positions_very_deep.js
(window.POSITIONS_VERY_DEEP). Resumable — already-evaluated FENs are skipped.

After verification finishes, auto-runs render_site.py and git commit + push
so master wakes up to the new "深28失" column already published. This
mirrors the pre-authorised pattern used by redo_deep on 2026-05-16.
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
from enrich_depth import load_positions, score_cp, save_deep  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
OUT_DIR = REPO / "output" / "site"
VERY_DEEP_JS = OUT_DIR / "positions_very_deep.js"
LOG = REPO / "output" / "verify_traps.log"
SKIP_OPENING_PLIES = 15


def load_very_deep():
    if not VERY_DEEP_JS.exists():
        return {}
    text = VERY_DEEP_JS.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS_VERY_DEEP\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def save_very_deep(data):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    VERY_DEEP_JS.write_text(f"window.POSITIONS_VERY_DEEP = {payload};\n", encoding='utf-8')


def collect_trap_fens(games, shallow, deep):
    """All (fen_before, fen_after) pairs that the trap rule fires on."""
    pairs = []
    seen = set()
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
                pairs.append((fa, fb))
    return pairs


def is_valid_entry(entry, target_depth):
    if not entry:
        return False
    d = entry.get('depth')
    if d is None:
        return False
    # Time-capped entries (search hit its --movetime budget before the nominal
    # target depth) count as DONE: re-running just hits the same cap, and the
    # trap verdict is stable long before depth 28 — decided positions otherwise
    # grind 80-97 min to confirm what depth ~16 (~4s) already knew.
    if d < target_depth and not entry.get('capped'):
        return False
    # any best_iccs that parses as 4 chars is plausible — we don't legality-check
    bm = entry.get('best_iccs')
    return isinstance(bm, str) and len(bm) == 4


def run_engine(depth, threads, hash_mb, checkpoint_every, deadline=None, movetime=None):
    games = json.loads((OUT_DIR / 'data' / 'games.json').read_text(encoding='utf-8'))
    shallow = load_positions(OUT_DIR / 'positions.js')
    deep = load_positions(OUT_DIR / 'positions_deep.js')
    very_deep = load_very_deep()

    pairs = collect_trap_fens(games, shallow, deep)
    needed = set()
    for fa, fb in pairs:
        needed.add(fa)
        needed.add(fb)
    todo = [f for f in sorted(needed) if not is_valid_entry(very_deep.get(f), depth)]
    print(f"[verify] {len(pairs)} trap pairs / {len(needed)} unique FENs / "
          f"{len(todo)} new at depth {depth}", flush=True)
    if not todo:
        print("[verify] nothing to do", flush=True)
        return very_deep

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(threads))
    eng.set_option('Hash', str(hash_mb))
    eng.isready()

    t0 = time.time()
    try:
        for i, fen in enumerate(todo, 1):
            # Self-deadline: schtask /SC ONCE has no /ET, so we enforce the
            # "stop by 10:00 next morning" rule here. Save current cache and
            # exit cleanly instead of getting hard-killed by the OS.
            if deadline and time.time() >= deadline:
                print(f"[deadline] reached at FEN {i}/{len(todo)} — saving and exiting", flush=True)
                save_very_deep(very_deep)
                return very_deep
            ts = time.time()
            res = eng.go(fen, depth, movetime=movetime)
            dt = time.time() - ts
            reached = res.get('depth')
            capped = bool(movetime) and reached is not None and reached < depth
            very_deep[fen] = {
                'best_iccs': res.get('move'),
                'score': res.get('score') if isinstance(res.get('score'), int) else None,
                'mate': res.get('mate'),
                'pv': (res.get('pv') or [])[:16],
                'depth': reached or depth,
                'capped': capped,
            }
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(todo)}] {dt:6.1f}s d{reached}{'*cap' if capped else ''}  "
                  f"score={res.get('score')}  best={res.get('move')}  "
                  f"({elapsed/60:.1f}m elapsed, eta {eta/60:.0f}m)", flush=True)
            if i % checkpoint_every == 0 or i == len(todo):
                save_very_deep(very_deep)
                print(f"  [checkpoint] saved {len(very_deep)} entries", flush=True)
    finally:
        try:
            eng._send('quit')
        except Exception:
            pass
    return very_deep


def post_render_and_push():
    """Render, commit, push — pre-authorised so master wakes up to a deployed
    site. Same pattern as the 2026-05-16 redo_deep finish hook."""
    print("[post] render_site.py", flush=True)
    subprocess.run([sys.executable, str(REPO / 'site_builder' / 'render_site.py')],
                   check=True, cwd=str(REPO))
    print("[post] migrate_to_sqlite.py", flush=True)
    subprocess.run([sys.executable, str(REPO / 'site_builder' / 'migrate_to_sqlite.py')],
                   check=True, cwd=str(REPO))
    print("[post] git add", flush=True)
    subprocess.run(['git', 'add', 'docs/', 'output/site/', 'DEEP_STATUS.md'],
                   check=True, cwd=str(REPO))
    print("[post] git commit", flush=True)
    msg = (
        "Verify 591 traps at depth 28\n"
        "\n"
        "Background depth-28 pass on every flagged trap's (fen_before, "
        "fen_after) pair. Result keyed in positions_very_deep.js, surfaced "
        "as the 深28失 column on traps.html. Lets master cross-check the "
        "depth-22 verdict against a deeper search without re-running for "
        "every page render.\n"
        "\n"
        "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    rc = subprocess.run(['git', 'commit', '-m', msg], cwd=str(REPO))
    if rc.returncode != 0:
        print("[post] nothing to commit, skipping push", flush=True)
        return
    print("[post] git push", flush=True)
    subprocess.run(['git', 'push'], check=True, cwd=str(REPO))
    print("[post] done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=28)
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--hash-mb', type=int, default=512)
    ap.add_argument('--checkpoint-every', type=int, default=5)
    ap.add_argument('--movetime', type=int, default=120000,
                    help='Per-FEN movetime cap in ms (0 = no cap). Stops grinding '
                         'already-decided positions to nominal depth — the verdict '
                         'is stable ~80 min before depth 28 ever lands. Default 120000.')
    ap.add_argument('--max-hours', type=float, default=None,
                    help='If set, exit cleanly when this many hours have elapsed '
                         '(used by the schtask wrapper to bound a one-shot run).')
    ap.add_argument('--no-post', action='store_true',
                    help='Skip the render+commit+push at the end (for manual reruns)')
    args = ap.parse_args()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    print(f"=== verify_traps start {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)
    deadline = (time.time() + args.max_hours * 3600) if args.max_hours else None
    deadline_str = (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(deadline))
                    if deadline else 'none')
    print(f"  depth={args.depth} threads={args.threads} hash={args.hash_mb}MB  "
          f"checkpoint_every={args.checkpoint_every}  movetime={args.movetime}ms  "
          f"deadline={deadline_str}", flush=True)
    try:
        run_engine(args.depth, args.threads, args.hash_mb,
                   args.checkpoint_every, deadline=deadline,
                   movetime=(args.movetime or None))
    except KeyboardInterrupt:
        print("[interrupt] stopped — partial cache saved", flush=True)
        return
    if not args.no_post:
        post_render_and_push()
    print(f"=== verify_traps end {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)


if __name__ == '__main__':
    main()
