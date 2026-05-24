"""Full depth-28 sweep of every ply-≥15 FEN in the targeted books that isn't
already at depth 28. Extends positions_very_deep.js so new traps surface
in traps.html automatically (no UI change needed).

Resumable, checkpoints every 5 FENs, --max-hours self-deadline for nightly
schtask runs. Designed to be invoked daily 22:30 → 07:30 until done.

Targets: edit TARGET_REL_KEYWORDS below. Resume-safe across target list
changes — already-evaluated FENs are skipped, so adding a new book just
appends its FENs to the work queue.
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

TARGET_REL_KEYWORDS = ('順包直車3兵對橫車邊馬', '順包兩頭蛇對雙橫車', '牛頭滾')
SKIP_OPENING_PLIES = 15  # mirror enrich_decisive / verify_traps / render_site


def _load(path, var):
    if not path.exists():
        return {}
    m = re.search(rf'window\.{var}\s*=\s*(\{{.*\}});\s*$',
                  path.read_text(encoding='utf-8'), re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def _save(path, var, data):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    path.write_text(f"window.{var} = {payload};\n", encoding='utf-8')


def collect_target_fens():
    """All ply-≥15 unique FENs that live in the two 順包 books."""
    games = json.loads((OUT_DIR / 'data' / 'games.json').read_text(encoding='utf-8'))
    out = set()
    for g in games:
        rel = g.get('rel_path', '') or ''
        if not any(t in rel for t in TARGET_REL_KEYWORDS):
            continue
        for plies in g['variations']:
            for pi, p in enumerate(plies):
                fen = p.get('fen')
                if fen and pi >= SKIP_OPENING_PLIES:
                    out.add(fen)
    return sorted(out)


def is_valid_entry(entry, target_depth):
    if not entry:
        return False
    if entry.get('depth') is None or entry['depth'] < target_depth:
        return False
    bm = entry.get('best_iccs')
    return isinstance(bm, str) and len(bm) == 4


def run_engine(depth, threads, hash_mb, checkpoint_every, deadline=None):
    very_deep = _load(VERY_DEEP_JS, 'POSITIONS_VERY_DEEP')
    candidates = collect_target_fens()
    todo = [f for f in candidates if not is_valid_entry(very_deep.get(f), depth)]
    print(f"[d28-順包] {len(candidates)} candidates / {len(todo)} new at depth {depth}",
          flush=True)
    if not todo:
        print("[d28-順包] nothing to do", flush=True)
        return very_deep

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
                _save(VERY_DEEP_JS, 'POSITIONS_VERY_DEEP', very_deep)
                return very_deep
            ts = time.time()
            res = eng.go(fen, depth)
            dt = time.time() - ts
            very_deep[fen] = {
                'best_iccs': res.get('move'),
                'score': res.get('score') if isinstance(res.get('score'), int) else None,
                'mate': res.get('mate'),
                'pv': (res.get('pv') or [])[:16],
                'depth': res.get('depth') or depth,
            }
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(todo)}] {dt:6.1f}s  "
                  f"score={res.get('score')}  best={res.get('move')}  "
                  f"({elapsed/60:.1f}m elapsed, eta {eta/60:.0f}m)", flush=True)
            if i % checkpoint_every == 0 or i == len(todo):
                _save(VERY_DEEP_JS, 'POSITIONS_VERY_DEEP', very_deep)
                print(f"  [checkpoint] saved {len(very_deep)} entries", flush=True)
    finally:
        try:
            eng._send('quit')
        except Exception:
            pass
    return very_deep


def post_render_and_push():
    """Run render to surface any newly-detected traps, then commit + push."""
    print("[post] render_site.py", flush=True)
    subprocess.run(['py', str(REPO / 'site_builder' / 'render_site.py')],
                   check=True, cwd=str(REPO))
    print("[post] git add", flush=True)
    subprocess.run(['git', 'add', 'docs/', 'output/site/'],
                   check=True, cwd=str(REPO))
    msg = (
        "Full depth-28 sweep on 順包 two books — nightly progress\n"
        "\n"
        "Extends positions_very_deep.js with every ply-≥15 FEN in\n"
        "順包直車3兵對橫車邊馬 and 順包兩頭蛇對雙橫車, not just the\n"
        "depth-22-detected traps. Any new trap that the deeper search\n"
        "surfaces will appear in traps.html on next render.\n"
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
    ap.add_argument('--max-hours', type=float, default=None)
    ap.add_argument('--no-post', action='store_true')
    args = ap.parse_args()

    print(f"=== verify_d28_shunbao start {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
          flush=True)
    deadline = (time.time() + args.max_hours * 3600) if args.max_hours else None
    deadline_str = (time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(deadline))
                    if deadline else 'none')
    print(f"  depth={args.depth} threads={args.threads} hash={args.hash_mb}MB  "
          f"checkpoint_every={args.checkpoint_every}  deadline={deadline_str}",
          flush=True)
    try:
        run_engine(args.depth, args.threads, args.hash_mb,
                   args.checkpoint_every, deadline=deadline)
    except KeyboardInterrupt:
        print("[interrupt] stopped — partial cache saved", flush=True)
        return
    if not args.no_post:
        post_render_and_push()
    print(f"=== verify_d28_shunbao end {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
          flush=True)


if __name__ == '__main__':
    main()
