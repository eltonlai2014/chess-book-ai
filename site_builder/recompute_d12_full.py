"""Full d12 re-evaluation with the new DFS + warm-TT evaluator.

Triggered automatically by enrich_decisive.py when it detects the d22 sweep
has finished (0 todo at end of run). See D12_TT_SWEEP.md for the policy
background.

Pipeline:
  1. Backup current positions.js → positions_pre_dfs.js (rollback insurance)
  2. Delete positions.js + docs/positions.js (force build_data to rebuild
     from scratch under the new DFS evaluator)
  3. build_data.py -d 12  (full corpus, DFS preorder, Hash 1024 MB,
     auto-migrates into positions.db)
  4. enrich_decisive.py   (incremental — catches new d22 candidates from
     shifted |d12|>500 boundaries; new d22 entries get auto-added)
  5. render_site.py       (recomputes traps under new d12; auto-syncs
     DEEP_STATUS.md via update_deep_status_md)
  6. git add docs/ output/site/ output/positions_pre_dfs_*.js DEEP_STATUS.md
     → commit → push

After successful run drops a marker file so the trigger is one-shot — future
0-todo enrich runs won't re-fire the recompute.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output" / "site"
DOCS_DIR = REPO / "docs"
POSITIONS_JS = OUT_DIR / "positions.js"
DOCS_POSITIONS_JS = DOCS_DIR / "positions.js"
MARKER = REPO / "output" / ".d12_dfs_recompute_done"


def step(label: str):
    print(f"\n=== {label}  ({time.strftime('%H:%M:%S')}) ===", flush=True)


def run(cmd: list[str]):
    """Run subprocess; propagate failure."""
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(REPO))


def main():
    if MARKER.exists():
        print(f"[skip] marker exists ({MARKER}) — d12 DFS recompute already done. "
              f"Delete the marker manually if you want to re-run.", flush=True)
        return

    if not POSITIONS_JS.exists():
        print(f"[abort] {POSITIONS_JS} missing — nothing to recompute against. "
              f"Run build_data.py manually instead.", flush=True)
        sys.exit(1)

    overall_start = time.time()
    print(f"=== d12 DFS full recompute starting {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
          flush=True)

    step("1/6 backup current positions.js")
    ts = time.strftime('%Y%m%d_%H%M%S')
    backup = REPO / "output" / f"positions_pre_dfs_{ts}.js"
    backup.write_bytes(POSITIONS_JS.read_bytes())
    print(f"[backup] {POSITIONS_JS} → {backup} ({backup.stat().st_size // 1024} KB)",
          flush=True)

    step("2/6 delete master + docs positions.js so build_data rebuilds from zero")
    POSITIONS_JS.unlink()
    if DOCS_POSITIONS_JS.exists():
        DOCS_POSITIONS_JS.unlink()

    step("3/6 build_data.py -d 12  (full DFS rebuild)")
    # build_data auto-migrates into positions.db at the end (its --no-migrate
    # default is off). Threads=1, Hash=1024 are the script's new defaults.
    run([sys.executable, str(REPO / 'site_builder' / 'build_data.py'), '-d', '12'])

    step("4/6 enrich_decisive.py  (catch d22 boundary changes from new d12)")
    # No --auto-d12-recompute here — we're already inside the recompute.
    # No --max-hours — let it run to completion (boundary changes ought to be small;
    # if they're huge something is very wrong).
    # No --no-post — let it do its own render+commit+push at end.
    run([sys.executable, str(REPO / 'site_builder' / 'enrich_decisive.py'), '--depth', '22'])

    # enrich_decisive's post_render_and_push already did:
    #   - render_site (refreshes traps + DEEP_STATUS.md)
    #   - migrate_to_sqlite
    #   - git add docs/, output/site/, DEEP_STATUS.md
    #   - commit + push
    # So steps 5/6 are nominally done by step 4. Below is the fallback path if
    # enrich_decisive found nothing new to deepen (incremental boundary delta=0):
    # it would have exited without rendering. In that case we render manually.
    step("5/6 render_site.py  (fallback — only fires if enrich had no new FENs)")
    # Check by mtime: if positions_view.js is newer than positions.js, enrich
    # already re-rendered. Otherwise do it ourselves.
    view = OUT_DIR / "positions_view.js"
    if not view.exists() or view.stat().st_mtime < POSITIONS_JS.stat().st_mtime:
        run([sys.executable, str(REPO / 'site_builder' / 'render_site.py')])
        run([sys.executable, str(REPO / 'site_builder' / 'migrate_to_sqlite.py')])
        run(['git', 'add', 'docs/', 'output/site/', 'DEEP_STATUS.md',
             str(backup.relative_to(REPO))])
        rc = subprocess.run(
            ['git', 'commit', '-m',
             '全量 d12 DFS recompute (TT warm, Hash 1024MB)\n\n'
             '套用 D12_TT_SWEEP.md 新評估方式重算 positions.js。\n'
             'enrich_decisive 已 boundary-stable，直接補 render。\n\n'
             'Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>'],
            cwd=str(REPO))
        if rc.returncode == 0:
            run(['git', 'push'])
    else:
        print("[skip] view.js newer than positions.js — enrich already re-rendered",
              flush=True)
        # Still commit the backup file
        run(['git', 'add', str(backup.relative_to(REPO))])
        rc = subprocess.run(
            ['git', 'commit', '-m',
             f'Backup pre-DFS positions.js ({ts})\n\n'
             'Insurance copy before d12 full DFS recompute. Safe to delete '
             'after the new scores have been reviewed and accepted.\n\n'
             'Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>'],
            cwd=str(REPO))
        if rc.returncode == 0:
            run(['git', 'push'])

    step("6/6 drop completion marker — trigger is one-shot")
    MARKER.write_text(f"d12 DFS full recompute completed at "
                      f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding='utf-8')
    print(f"[marker] {MARKER}", flush=True)

    elapsed = (time.time() - overall_start) / 60
    print(f"\n=== d12 DFS full recompute done in {elapsed:.1f} min "
          f"({time.strftime('%Y-%m-%d %H:%M:%S')}) ===", flush=True)


if __name__ == '__main__':
    main()
