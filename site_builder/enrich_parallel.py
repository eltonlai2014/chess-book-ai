"""Parallel multi-instance d22 enrich — orchestrator + worker.

Throughput win: Pikafish SMP scaling at d22 is weak (~1.3x/4 threads), so N
independent engines x few threads each beats 1 engine x many threads. Measured
on the i7-8700 (6 cores): config 3x2-thread ≈ 2.1x the old 1x6-thread all-day
sweep, with only ~-3cp signed divergence (scatter ~10cp; bias negligible — see
the poc_parallel_enrich.py sweep, 2026-06-19).

SAFETY MODEL (same discipline as fanning out sub-agents):
  - Each worker writes ONLY its own shard file (atomic temp+replace). No worker
    touches positions_deep.js.
  - The orchestrator merges (existing deep ∪ all shards, higher depth wins) and
    writes positions_deep.js ONCE, atomically, after every worker has exited.
  - todo is deterministic, so each worker recomputes it and slices its own
    CONTIGUOUS chunk (preserves the DFS/TT locality that gives the ~24% warm-TT
    speedup; only N-1 seam FENs start cold).

Does NOT modify enrich_decisive.py (the nightly production script).

Usage (orchestrator):
  py site_builder/enrich_parallel.py --num-shards 3 --threads 2 --depth 22 \
       --full-public --auto-d12-recompute
Test without touching real data:
  py site_builder/enrich_parallel.py --num-shards 3 --threads 2 --full-public \
       --limit 4 --deep-out output/poc/test_deep.js \
       --shard-dir output/poc/_shards --no-post
Internal worker entry (spawned by the orchestrator):
  py site_builder/enrich_parallel.py --worker <shard> <num_shards> <depth> \
       <threads> <hash_mb> <full_public 0|1> <shard_out> <limit> <max_hours_or_->
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_decisive import (  # noqa: E402  (reuse production scan + post)
    collect_fens_to_eval, post_render_and_push,
    EXE, GAMES_JSON, POSITIONS_JS, DEEP_JS, PV_KEEP, REPO,
)
from enrich_depth import load_positions  # noqa: E402
from build_data import collect_fens_dfs  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402

OUT_DIR = REPO / "output" / "site"


def split_contiguous(items, n):
    """n contiguous near-equal chunks (preserve DFS/TT locality)."""
    out, k, r, start = [], len(items) // n, len(items) % n, 0
    for i in range(n):
        size = k + (1 if i < r else 0)
        out.append(items[start:start + size])
        start += size
    return out


def atomic_write_text(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_todo(depth, full_public, deep):
    """Deterministic work-list: DFS-ordered candidate FENs still needing `depth`.
    Identical across processes (set membership + deterministic DFS order)."""
    games = json.loads(GAMES_JSON.read_text(encoding="utf-8"))
    shallow = load_positions(POSITIONS_JS)
    candidates = collect_fens_to_eval(games, shallow, full_public=full_public)
    ordered = collect_fens_dfs(games)
    return [f for f in ordered
            if f in candidates and (f not in deep or deep[f].get("depth", 0) < depth)]


# ----------------------------------------------------------------- worker ----
def run_worker(shard, num_shards, depth, threads, hash_mb, full_public,
               shard_out, limit, max_hours):
    deep = load_positions(DEEP_JS)                      # global done-set (read-only)
    todo = build_todo(depth, full_public, deep)
    my = split_contiguous(todo, num_shards)[shard]

    shard_path = Path(shard_out)
    done = {}
    if shard_path.exists():                             # resume own progress
        try:
            done = json.loads(shard_path.read_text(encoding="utf-8"))
        except Exception:
            done = {}
    pending = [f for f in my if f not in done]
    if limit:
        pending = pending[:limit]
    tag = f"w{shard}/{num_shards}"
    print(f"[{tag}] slice={len(my)} done={len(done)} pending={len(pending)} "
          f"threads={threads}", file=sys.stderr, flush=True)
    if not pending:
        atomic_write_text(shard_path, json.dumps(done, ensure_ascii=False))
        return

    eng = CleanUciEngine(str(EXE))
    eng.set_option("Threads", str(threads))
    eng.set_option("Hash", str(hash_mb))
    eng.isready()

    t0 = time.time()
    deadline = (t0 + max_hours * 3600) if max_hours else None
    try:
        for idx, fen in enumerate(pending, 1):
            if deadline and time.time() >= deadline:
                print(f"[{tag}] deadline at {idx}/{len(pending)}", file=sys.stderr, flush=True)
                break
            act = eng.go(fen, depth)
            done[fen] = {
                "best_iccs": act.get("move"),
                "score": act.get("score") if isinstance(act.get("score"), int) else None,
                "mate": act.get("mate"),
                "pv": (act.get("pv") or [])[:PV_KEEP],
                "depth": depth,
            }
            if idx % 25 == 0:
                atomic_write_text(shard_path, json.dumps(done, ensure_ascii=False))
                el = time.time() - t0
                eta = (len(pending) - idx) / (idx / el) if el > 0 else 0
                print(f"[{tag}] {idx}/{len(pending)} ({el:.0f}s, eta {eta:.0f}s)",
                      file=sys.stderr, flush=True)
    finally:
        try:
            eng.quit()
        except Exception:
            pass
    atomic_write_text(shard_path, json.dumps(done, ensure_ascii=False))
    print(f"[{tag}] wrote {len(done)} entries -> {shard_path.name}", file=sys.stderr, flush=True)


# ----------------------------------------------------------- orchestrator ----
def merge_into_deep(deep_out: Path, shard_files):
    deep = load_positions(DEEP_JS)                      # existing real data
    added = 0
    for sf in shard_files:
        if not sf.exists():
            print(f"[merge] WARN missing {sf.name}", file=sys.stderr)
            continue
        sd = json.loads(sf.read_text(encoding="utf-8"))
        for fen, e in sd.items():
            if fen not in deep or e.get("depth", 0) > deep[fen].get("depth", 0):
                deep[fen] = e
                added += 1
    payload = json.dumps(deep, ensure_ascii=False, separators=(",", ":"))
    atomic_write_text(deep_out, f"window.POSITIONS_DEEP = {payload};\n")
    print(f"[merge] wrote {deep_out} — {len(deep)} total (+{added} from shards)", file=sys.stderr)
    return len(deep), added


def run_orchestrator(a):
    deep = load_positions(DEEP_JS)
    todo = build_todo(a.depth, a.full_public, deep)
    print(f"[plan] {len(deep)} already deep; {len(todo)} FENs need depth {a.depth}", file=sys.stderr)
    print(f"[plan] {a.num_shards} shards x {a.threads} threads "
          f"(~{len(todo)//max(a.num_shards,1)} FENs/shard)", file=sys.stderr)

    if not todo:
        print("[done] nothing to deepen", file=sys.stderr)
        _maybe_d12_recompute(a)
        return

    shard_dir = Path(a.shard_dir)
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_files = [shard_dir / f"deep_shard_{i}.json" for i in range(a.num_shards)]

    procs = []
    for i in range(a.num_shards):
        procs.append(subprocess.Popen([
            sys.executable, str(Path(__file__)), "--worker",
            str(i), str(a.num_shards), str(a.depth), str(a.threads),
            str(a.hash_mb), "1" if a.full_public else "0",
            str(shard_files[i]), str(a.limit or 0),
            (str(a.max_hours) if a.max_hours else "-"),
        ]))
    rcs = [p.wait() for p in procs]
    print(f"[orch] workers exited rc={rcs}", file=sys.stderr)

    total, added = merge_into_deep(Path(a.deep_out), shard_files)

    if not a.no_post:
        post_render_and_push(partial=bool(a.limit))     # limit => treat as partial
    _maybe_d12_recompute(a)


def _maybe_d12_recompute(a):
    if not a.auto_d12_recompute:
        return
    marker = REPO / "output" / ".d12_dfs_recompute_done"
    if marker.exists():
        print("[note] d12 recompute marker exists — skipping", file=sys.stderr)
        return
    deep = load_positions(DEEP_JS)
    if build_todo(a.depth, a.full_public, deep):
        return                                          # still work left, not cleared
    print("[d22-complete] sweep cleared — triggering d12 DFS recompute", file=sys.stderr)
    subprocess.run([sys.executable, str(REPO / "site_builder" / "recompute_d12_full.py")],
                   check=True, cwd=str(REPO))


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        _, _, shard, num_shards, depth, threads, hash_mb, fp, shard_out, limit, mh = sys.argv[:11]
        run_worker(int(shard), int(num_shards), int(depth), int(threads), int(hash_mb),
                   fp == "1", shard_out, int(limit) or None,
                   None if mh == "-" else float(mh))
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-shards", type=int, default=3)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--depth", type=int, default=22)
    ap.add_argument("--hash-mb", type=int, default=256)
    ap.add_argument("--full-public", action="store_true")
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--auto-d12-recompute", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="per-shard FEN cap (testing)")
    ap.add_argument("--shard-dir", default=str(REPO / "output" / "_shards"),
                    help="OUTSIDE output/site/ so post_render's `git add output/site/` "
                         "never stages these ~10MB intermediate shard files")
    ap.add_argument("--deep-out", default=str(DEEP_JS))
    run_orchestrator(ap.parse_args())


if __name__ == "__main__":
    main()
