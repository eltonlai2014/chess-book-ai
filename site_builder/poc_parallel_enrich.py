"""PoC: parallel multi-instance d22 enrich — ORCHESTRATION VALIDATION ONLY.

Proves the "split todo -> N workers each own Pikafish (1 thread) -> merge shards"
pattern is correct & complete, BEFORE we touch the real pipeline.

SAFETY: reads positions.js READ-ONLY for sample FENs; writes ONLY to output/poc/.
        Never touches positions_deep.js or any real output. Safe to run while the
        all-day single-instance job is going (it will just share CPU briefly).

Checks:
  1. contiguous partition covers the FEN list exactly once (no miss / no dup).
  2. real-engine end-to-end: serial 1-thread baseline vs N parallel 1-thread
     workers on the SAME FENs; merged result must match baseline (move+score),
     and wall-clock speedup is reported.

Run:  py site_builder/poc_parallel_enrich.py [--fens 9] [--workers 3] [--depth 16]
Internal worker entry (spawned by the orchestrator):
      py site_builder/poc_parallel_enrich.py --worker <in.json> <out.json> <depth>
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
from enrich_depth import load_positions  # noqa: E402
from clean_eval import CleanUciEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
POSITIONS_JS = REPO / "output" / "site" / "positions.js"
POC_DIR = REPO / "output" / "poc"


def split_contiguous(items, n):
    """Split list into n contiguous near-equal chunks (preserves DFS/TT locality)."""
    out, k, r, start = [], len(items) // n, len(items) % n, 0
    for i in range(n):
        size = k + (1 if i < r else 0)
        out.append(items[start:start + size])
        start += size
    return out


def atomic_write_json(path: Path, obj):
    """temp + os.replace — a killed worker can't leave a half-written shard."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def eval_fens(fens, depth, threads, hash_mb=256):
    eng = CleanUciEngine(str(EXE))
    eng.set_option("Threads", str(threads))
    eng.set_option("Hash", str(hash_mb))
    eng.isready()
    res = {}
    try:
        for fen in fens:
            act = eng.go(fen, depth)
            res[fen] = {
                "best_iccs": act.get("move"),
                "score": act.get("score") if isinstance(act.get("score"), int) else None,
                "mate": act.get("mate"),
                "depth": depth,
            }
    finally:
        try:
            eng.quit()
        except Exception:
            pass
    return res


def run_worker(in_json, out_json, depth, threads=1):
    fens = json.loads(Path(in_json).read_text(encoding="utf-8"))
    res = eval_fens(fens, depth, threads=threads)
    atomic_write_json(Path(out_json), res)


def parallel_eval(fens, n_workers, threads, depth, tag):
    """Spawn n_workers worker procs (threads each) over a contiguous split.
    Returns (wall_seconds, merged_dict)."""
    shards = split_contiguous(fens, n_workers)
    procs, outs = [], []
    t0 = time.time()
    for i, shard in enumerate(shards):
        in_j = POC_DIR / f"{tag}_{i}_in.json"
        out_j = POC_DIR / f"{tag}_{i}_out.json"
        in_j.write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")
        outs.append(out_j)
        procs.append(subprocess.Popen(
            [sys.executable, str(Path(__file__)), "--worker",
             str(in_j), str(out_j), str(depth), str(threads)]))
    for p in procs:
        p.wait()
    wall = time.time() - t0
    merged = {}
    for out_j in outs:
        merged.update(json.loads(out_j.read_text(encoding="utf-8")))
    return wall, merged


def run_sweep(n_fens, depth, offset):
    """Speed + score-divergence across N x T configs (N*T=6), free cores.
    Baseline for divergence = 1x6t (closest to the existing all-day data)."""
    POC_DIR.mkdir(parents=True, exist_ok=True)
    shallow = load_positions(POSITIONS_JS)
    fens = list(shallow.keys())[offset:offset + n_fens]
    configs = [(1, 6), (2, 3), (3, 2), (6, 1)]
    print(f"[sweep] {len(fens)} FENs (read-only), depth={depth}, configs NxT (N*T=6)", flush=True)
    results = {}
    for (N, T) in configs:
        wall, res = parallel_eval(fens, N, T, depth, f"sw{N}x{T}")
        results[(N, T)] = (wall, res)
        print(f"  ran {N}x{T}: wall={wall:6.1f}s  ({wall/len(fens):.2f}s/FEN)", flush=True)
    base_wall, base = results[(1, 6)]
    print(f"\n[report] divergence baseline = 1x6t   speedup baseline = 1x6t wall ({base_wall:.1f}s)", flush=True)
    print(f"  {'config':>7} {'speedup':>8} {'mean|d|':>9} {'signed':>9} {'max|d|':>8}", flush=True)
    for (N, T) in configs:
        wall, res = results[(N, T)]
        sp = base_wall / wall if wall > 0 else 0
        ds = [res[f]["score"] - base[f]["score"] for f in fens
              if isinstance(res[f].get("score"), int) and isinstance(base[f].get("score"), int)]
        absd = [abs(x) for x in ds]
        mean_abs = (sum(absd) / len(absd)) if absd else 0
        signed = (sum(ds) / len(ds)) if ds else 0
        mx = max(absd) if absd else 0
        print(f"  {f'{N}x{T}':>7} {f'x{sp:.2f}':>8} {mean_abs:8.1f}c {signed:+8.1f}c {mx:7d}c", flush=True)


def run_poc(n_fens, n_workers, depth):
    POC_DIR.mkdir(parents=True, exist_ok=True)

    # ---- check 1: partition logic (instant, no engine) -------------------
    probe = list(range(53))
    parts = split_contiguous(probe, 7)
    flat = [x for p in parts for x in p]
    assert flat == probe, "partition lost/reordered items"
    assert sum(len(p) for p in parts) == len(probe)
    assert max(len(p) for p in parts) - min(len(p) for p in parts) <= 1, "unbalanced"
    print("[check1] contiguous partition: covers exactly once, balanced  OK", flush=True)

    # ---- sample real FENs (READ-ONLY) ------------------------------------
    shallow = load_positions(POSITIONS_JS)
    fens = list(shallow.keys())[:n_fens]
    print(f"[sample] {len(fens)} FENs from positions.js (read-only), depth={depth}", flush=True)

    # ---- baseline: serial, 1 thread --------------------------------------
    t0 = time.time()
    baseline = eval_fens(fens, depth, threads=1)
    t_serial = time.time() - t0
    print(f"[serial] {len(fens)} FENs in {t_serial:.1f}s  ({t_serial/len(fens):.2f}s/FEN)", flush=True)

    # ---- parallel: N workers, 1 thread each ------------------------------
    shards = split_contiguous(fens, n_workers)
    procs, outs = [], []
    t0 = time.time()
    for i, shard in enumerate(shards):
        in_j = POC_DIR / f"shard_{i}_in.json"
        out_j = POC_DIR / f"shard_{i}_out.json"
        in_j.write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")
        outs.append(out_j)
        procs.append(subprocess.Popen(
            [sys.executable, str(Path(__file__)), "--worker", str(in_j), str(out_j), str(depth)]))
    for p in procs:
        p.wait()
    t_par = time.time() - t0
    print(f"[parallel] {n_workers} workers x1-thread in {t_par:.1f}s", flush=True)

    # ---- merge shards (depth precedence) + coverage check ----------------
    merged = {}
    for out_j in outs:
        if not out_j.exists():
            print(f"[FAIL] missing shard output {out_j.name}", flush=True)
            return
        for fen, e in json.loads(out_j.read_text(encoding="utf-8")).items():
            if fen not in merged or e["depth"] > merged[fen]["depth"]:
                merged[fen] = e
    assert set(merged) == set(fens), "merge coverage mismatch (missing/extra FENs)"
    print(f"[check2] merge covers all {len(fens)} FENs, no miss/dup  OK", flush=True)

    # ---- correctness: merged vs serial baseline --------------------------
    mism_score, mism_move = [], []
    for fen in fens:
        b, m = baseline[fen], merged[fen]
        if b["score"] != m["score"] or b["mate"] != m["mate"]:
            mism_score.append(fen)
        if b["best_iccs"] != m["best_iccs"]:
            mism_move.append(fen)
    print(f"[correctness] score/mate mismatches: {len(mism_score)}/{len(fens)}", flush=True)
    print(f"[correctness] best-move mismatches:  {len(mism_move)}/{len(fens)} "
          f"(move ties at equal score are benign)", flush=True)
    if mism_score:
        for fen in mism_score[:3]:
            print(f"   SCORE DIFF {fen[:30]}.. serial={baseline[fen]} worker={merged[fen]}", flush=True)

    sp = (t_serial / t_par) if t_par > 0 else 0
    print(f"\n[summary] depth={depth} fens={len(fens)} workers={n_workers}", flush=True)
    print(f"          serial {t_serial:.1f}s  ->  parallel {t_par:.1f}s   speedup x{sp:.2f}", flush=True)
    print(f"          (NOTE: all-day job is sharing CPU now, so this speedup is a FLOOR;\n"
          f"           true number with free cores is higher. Correctness is load-independent.)", flush=True)
    verdict = "PASS" if not mism_score else "SCORE-MISMATCH — investigate"
    print(f"          correctness: {verdict}", flush=True)


def run_speedtest(n_fens, n_workers, depth, threads_a, hash_a, offset):
    """The decisive comparison (needs FREE cores):
       config A = 1 engine x threads_a  (= current all-day single-instance)
       config B = n_workers engines x 1 thread  (= proposed parallel)
    Same FENs, same depth. Reports wall-clock speedup B-over-A + score divergence."""
    POC_DIR.mkdir(parents=True, exist_ok=True)
    shallow = load_positions(POSITIONS_JS)
    fens = list(shallow.keys())[offset:offset + n_fens]
    print(f"[speed] {len(fens)} FENs (read-only), depth={depth}", flush=True)
    print(f"[speed] A = 1 engine x{threads_a}t (hash {hash_a}MB)  [current all-day]", flush=True)
    print(f"[speed] B = {n_workers} engines x1t (hash 256MB)      [proposed]", flush=True)

    t0 = time.time()
    res_a = eval_fens(fens, depth, threads=threads_a, hash_mb=hash_a)
    t_a = time.time() - t0
    print(f"[A] 1x{threads_a}t : {t_a:.1f}s  ({t_a/len(fens):.2f}s/FEN)", flush=True)

    shards = split_contiguous(fens, n_workers)
    procs, outs = [], []
    t0 = time.time()
    for i, shard in enumerate(shards):
        in_j = POC_DIR / f"sp_{i}_in.json"
        out_j = POC_DIR / f"sp_{i}_out.json"
        in_j.write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")
        outs.append(out_j)
        procs.append(subprocess.Popen(
            [sys.executable, str(Path(__file__)), "--worker", str(in_j), str(out_j), str(depth)]))
    for p in procs:
        p.wait()
    t_b = time.time() - t0
    print(f"[B] {n_workers}x1t : {t_b:.1f}s  ({t_b/len(fens):.2f}s/FEN-effective)", flush=True)

    res_b = {}
    for out_j in outs:
        res_b.update(json.loads(out_j.read_text(encoding="utf-8")))

    diffs = []
    for fen in fens:
        sa, sb = res_a[fen].get("score"), res_b[fen].get("score")
        if isinstance(sa, int) and isinstance(sb, int):
            diffs.append(abs(sa - sb))
    mean_d = (sum(diffs) / len(diffs)) if diffs else 0
    max_d = max(diffs) if diffs else 0
    print(f"[correctness] B vs A score: mean |d|={mean_d:.2f}cp  max={max_d}cp  "
          f"(A itself is {threads_a}-thread nondeterministic)", flush=True)
    sp = (t_a / t_b) if t_b > 0 else 0
    print(f"\n[SPEEDUP] config B is x{sp:.2f} vs config A  (free cores)", flush=True)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        th = int(sys.argv[5]) if len(sys.argv) >= 6 else 1
        run_worker(sys.argv[2], sys.argv[3], int(sys.argv[4]), th)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["orch", "speed", "sweep"], default="orch")
    ap.add_argument("--fens", type=int, default=9)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--depth", type=int, default=16)
    ap.add_argument("--threads-a", type=int, default=6)
    ap.add_argument("--hash-a", type=int, default=1024)
    ap.add_argument("--offset", type=int, default=0)
    a = ap.parse_args()
    if a.mode == "speed":
        run_speedtest(a.fens, a.workers, a.depth, a.threads_a, a.hash_a, a.offset)
    elif a.mode == "sweep":
        run_sweep(a.fens, a.depth, a.offset)
    else:
        run_poc(a.fens, a.workers, a.depth)


if __name__ == "__main__":
    main()
