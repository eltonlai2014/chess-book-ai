"""Unified parallel deep-eval runner — one orchestrator+worker core, N jobs.

d22 / d28(traps) / d32 share an identical skeleton: build a deterministic todo,
split into contiguous shards, run N independent Pikafish instances x few threads
(weak SMP scaling => many low-thread engines beat one many-thread engine), each
worker writes its own shard atomically, then the orchestrator merges once and
runs the job's post step. Only four things differ per job, captured in a Job spec:
  build_todo  - the work-list (deterministic, identical across worker processes)
  cache/var   - output window.X file
  depth       - default search depth
  pv_keep     - PV truncation
  post        - render/migrate/push variant

Supersedes the earlier enrich_parallel.py (d22) and verify_parallel.py (d28/d32).

SAFETY (same as fanning out sub-agents): each worker writes ONLY its own shard in
output/_shards (OUTSIDE output/site/ so post's `git add output/site/` never stages
it); the orchestrator merges existing ∪ shards (higher depth wins) and writes the
real cache ONCE, atomically, after all workers exit.

CAVEAT (thread count): fixed-depth Pikafish results shift slightly with thread
count (measured on d22: signed bias ~-3cp, scatter ~10-17cp). Existing entries were
built at threads=4; parallel workers default threads=2. Negligible-bias regime.

INTENDED FOR NON-WORKING DAYS — weekday CPU stays free for the master.

Usage:
  py site_builder/parallel_runner.py --job traps --num-shards 3 --threads 2
  py site_builder/parallel_runner.py --job d32   --num-shards 3 --threads 2
  py site_builder/parallel_runner.py --job d22   --num-shards 3 --threads 2
  py site_builder/parallel_runner.py --job traps --dry-run         # just print plan
No-touch test (shallow depth, temp outputs):
  py site_builder/parallel_runner.py --job traps --depth 12 --limit 2 --no-post \
     --cache-out output/poc/test.js --shard-dir output/poc/_shards
Worker (internal):
  py site_builder/parallel_runner.py --worker <job> <shard> <num_shards> <depth> \
     <threads> <hash_mb> <shard_out> <limit> <max_hours_or_->
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_decisive import (  # noqa: E402
    collect_fens_to_eval, post_render_and_push as _enrich_post,
    GAMES_JSON, POSITIONS_JS, DEEP_JS, EXE, REPO,
)
from build_data import collect_fens_dfs  # noqa: E402
from verify_traps import (  # noqa: E402
    collect_trap_fens, is_valid_entry, post_render_and_push as traps_post, VERY_DEEP_JS,
)
from verify_d32 import (  # noqa: E402
    collect_target_fens, post_render_and_push as d32_post, D32_JS,
)
from enrich_depth import load_positions  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402


# ------------------------------------------------------------- helpers ----
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


# --------------------------------------------------------- work-lists ----
def _d22_build_todo(depth):
    """Full-public d22 sweep, DFS-ordered (warm-TT locality)."""
    games = json.loads(GAMES_JSON.read_text(encoding="utf-8"))
    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)
    candidates = collect_fens_to_eval(games, shallow, full_public=True)
    ordered = collect_fens_dfs(games)
    return [f for f in ordered
            if f in candidates and (f not in deep or deep[f].get("depth", 0) < depth)]


def _traps_build_todo(depth):
    """Every flagged trap's (fen_before, fen_after), not yet at depth."""
    games = json.loads(GAMES_JSON.read_text(encoding="utf-8"))
    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)
    cache = load_positions(VERY_DEEP_JS)
    needed = set()
    for fa, fb in collect_trap_fens(games, shallow, deep):
        needed.add(fa)
        needed.add(fb)
    return [f for f in sorted(needed) if not is_valid_entry(cache.get(f), depth)]


def _d32_build_todo(depth):
    """順包 FENs that already have a d28 entry, not yet at depth 32."""
    cache = load_positions(D32_JS)
    return [f for f in collect_target_fens() if not is_valid_entry(cache.get(f), depth)]


def _d22_post():
    """render+migrate+push, then (if the sweep just cleared) auto d12 recompute."""
    _enrich_post(partial=False)
    marker = REPO / "output" / ".d12_dfs_recompute_done"
    if marker.exists() or _d22_build_todo(22):
        return
    print("[d22-complete] sweep cleared — triggering d12 DFS recompute", file=sys.stderr)
    subprocess.run([sys.executable, str(REPO / "site_builder" / "recompute_d12_full.py")],
                   check=True, cwd=str(REPO))


Job = namedtuple("Job", "name cache var depth pv_keep build_todo post movetime decisive_cp")
JOBS = {
    "d22":   Job("d22",   DEEP_JS,      "POSITIONS_DEEP",      22, 10, _d22_build_todo, _d22_post,  None,   None),
    # traps(d28) / d32: decided-position early stop (|score|>=800 at depth>=18 for
    # 2 straight completed depths) — these otherwise grind 80-97 min to the nominal
    # depth on already-decided positions; undecided ones still run full depth.
    # movetime is a far-out wall-time backstop. is_valid_entry treats an early-
    # stopped entry as done so resume never re-grinds it. d22 left full — depth 22
    # finishes fast, no multi-hour grind there.
    "traps": Job("traps", VERY_DEEP_JS, "POSITIONS_VERY_DEEP", 28, 16, _traps_build_todo, traps_post, 600000, 800),
    "d32":   Job("d32",   D32_JS,       "POSITIONS_D32",       32, 16, _d32_build_todo, d32_post,   600000, 800),
}


# ------------------------------------------------------------- worker ----
def run_worker(job, shard, num_shards, depth, threads, hash_mb, shard_out, limit, max_hours):
    todo = job.build_todo(depth)
    my = split_contiguous(todo, num_shards)[shard]
    sp = Path(shard_out)
    done = {}
    if sp.exists():
        try:
            done = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            done = {}
    pending = [f for f in my if f not in done]
    if limit:
        pending = pending[:limit]
    tag = f"{job.name}-w{shard}/{num_shards}"
    print(f"[{tag}] slice={len(my)} done={len(done)} pending={len(pending)} "
          f"depth={depth} threads={threads}", file=sys.stderr, flush=True)
    if not pending:
        atomic_write_text(sp, json.dumps(done, ensure_ascii=False))
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
            res = eng.go(fen, depth, movetime=job.movetime, decisive_cp=job.decisive_cp)
            reached = res.get("depth")
            done[fen] = {
                "best_iccs": res.get("move"),
                "score": res.get("score") if isinstance(res.get("score"), int) else None,
                "mate": res.get("mate"),
                "pv": (res.get("pv") or [])[:job.pv_keep],
                "depth": reached or depth,
                "capped": bool(res.get("stopped_early")) or (
                    bool(job.movetime) and reached is not None and reached < depth),
            }
            if idx % 5 == 0:
                atomic_write_text(sp, json.dumps(done, ensure_ascii=False))
                el = time.time() - t0
                eta = (len(pending) - idx) / (idx / el) if el > 0 else 0
                print(f"[{tag}] {idx}/{len(pending)} ({el/60:.1f}m, eta {eta/60:.0f}m)",
                      file=sys.stderr, flush=True)
    finally:
        try:
            eng.quit()
        except Exception:
            pass
    atomic_write_text(sp, json.dumps(done, ensure_ascii=False))
    print(f"[{tag}] wrote {len(done)} entries -> {sp.name}", file=sys.stderr, flush=True)


# ------------------------------------------------------- orchestrator ----
def run_orchestrator(a):
    job = JOBS[a.job]
    depth = a.depth or job.depth
    todo = job.build_todo(depth)
    print(f"[plan] job={a.job} depth={depth}: {len(todo)} FENs todo "
          f"({a.num_shards} shards x {a.threads} threads, ~{len(todo)//max(a.num_shards,1)}/shard)",
          file=sys.stderr)
    if a.dry_run:
        return
    if not todo:
        print("[done] nothing to do", file=sys.stderr)
        if a.job == "d22" and not a.no_post:
            _d22_post()                       # may trigger d12 recompute when cleared
        return

    shard_dir = Path(a.shard_dir)
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_files = [shard_dir / f"{a.job}_shard_{i}.json" for i in range(a.num_shards)]
    procs = []
    for i in range(a.num_shards):
        procs.append(subprocess.Popen([
            sys.executable, str(Path(__file__)), "--worker",
            a.job, str(i), str(a.num_shards), str(depth), str(a.threads),
            str(a.hash_mb), str(shard_files[i]), str(a.limit or 0),
            (str(a.max_hours) if a.max_hours else "-"),
        ]))
    rcs = [p.wait() for p in procs]
    print(f"[orch] workers exited rc={rcs}", file=sys.stderr)

    cache = load_positions(job.cache)
    added = 0
    for sf in shard_files:
        if not sf.exists():
            print(f"[merge] WARN missing {sf.name}", file=sys.stderr)
            continue
        for fen, e in json.loads(sf.read_text(encoding="utf-8")).items():
            if fen not in cache or e.get("depth", 0) > cache[fen].get("depth", 0):
                cache[fen] = e
                added += 1
    cache_out = Path(a.cache_out) if a.cache_out else job.cache
    payload = json.dumps(cache, ensure_ascii=False, separators=(",", ":"))
    atomic_write_text(cache_out, f"window.{job.var} = {payload};\n")
    print(f"[merge] wrote {cache_out} — {len(cache)} total (+{added})", file=sys.stderr)

    if not a.no_post:
        job.post()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        _, _, job, shard, num_shards, depth, threads, hash_mb, shard_out, limit, mh = sys.argv[:11]
        run_worker(JOBS[job], int(shard), int(num_shards), int(depth), int(threads),
                   int(hash_mb), shard_out, int(limit) or None, None if mh == "-" else float(mh))
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=list(JOBS), required=True)
    ap.add_argument("--num-shards", type=int, default=3)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--depth", type=int, default=0, help="0 = job default (d22 22 / traps 28 / d32 32)")
    ap.add_argument("--hash-mb", type=int, default=512)
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print plan (todo count) and exit")
    ap.add_argument("--limit", type=int, default=0, help="per-shard FEN cap (testing)")
    ap.add_argument("--shard-dir", default=str(REPO / "output" / "_shards"))
    ap.add_argument("--cache-out", default="", help="override output path (testing); default = real cache")
    run_orchestrator(ap.parse_args())


if __name__ == "__main__":
    main()
