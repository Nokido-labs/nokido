"""tools/bench_multithread.py - Vrai bench multi-thread Python (vrai test free-threading).

Per Gemini Web 2026-05-29 plan #c.

Probleme : single-thread bench montre py314t plus lent que py314 GIL (-2.7%) car
overhead atomic refcount sans gain concurrent. Le vrai test = N threads
parallel CPU-bound. Sur GIL = serialisation, throughput plafonne. Sur no-GIL =
linear scaling avec cores.

3 workloads CPU-bound :
- pure Python loop (fibonacci recursif) : aucune lib externe, mesure pure threads
- numpy ops (matmul + softmax) : releases GIL via BLAS, baseline pour comparer
- AMI NMLP forward batch : mix Python orchestration + numpy

Run cross-env :
    LAFORGE_PYTHON tools/bench_multithread.py --threads 1,2,4,8 --label py312
    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe tools/bench_multithread.py --threads 1,2,4,8 --label py314
    %USERPROFILE%/miniforge3/envs/laforge_py314t/python.exe tools/bench_multithread.py --threads 1,2,4,8 --label py314t
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PERF_HIST = ROOT / "sandbox" / "perf_history"


# ── Workloads ─────────────────────────────────────────────────────────────────


def fib(n: int) -> int:
    """Naive recursive fibonacci -- pure Python CPU-bound, no numpy escape."""
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def workload_pure_python(iters: int) -> None:
    """N calls to fib(25) -- pure Python, ~6ms each, GIL-bound on GIL build."""
    for _ in range(iters):
        fib(25)


def workload_numpy(iters: int) -> None:
    """Matmul + softmax -- numpy releases GIL inside BLAS calls anyway."""
    rng = np.random.default_rng()
    A = rng.standard_normal((256, 256)).astype(np.float32)
    B = rng.standard_normal((256, 256)).astype(np.float32)
    for _ in range(iters):
        C = A @ B
        # Softmax (releases GIL partially via numpy)
        e = np.exp(C - C.max(axis=1, keepdims=True))
        _ = e / e.sum(axis=1, keepdims=True)


def workload_ami_nmlp(iters: int) -> None:
    """NMLP forward -- mix Python orchestration (LayerNorm Python loop) + numpy."""
    from nokido_agent.app.forge_world_model import NMLP

    nmlp = NMLP(rng_seed=42)
    rng = np.random.default_rng(42)
    x = rng.standard_normal(768).astype(np.float32)
    for _ in range(iters):
        nmlp.forward(x)


WORKLOADS = {
    "pure_python_fib25": (workload_pure_python, 20),
    "numpy_matmul_softmax_256": (workload_numpy, 50),
    "ami_nmlp_forward_768": (workload_ami_nmlp, 100),
}


def _bench_workload(workload, iters_per_thread: int, n_threads: int, runs: int = 3) -> dict:
    """Run workload sur N threads en parallele, mesurer wall-clock total."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n_threads, thread_name_prefix="bench") as pool:
            futures = [pool.submit(workload, iters_per_thread) for _ in range(n_threads)]
            for f in futures:
                f.result()
        times.append(time.perf_counter() - t0)
    return {
        "n_threads": n_threads,
        "iters_per_thread": iters_per_thread,
        "wall_s_runs": [round(t, 4) for t in times],
        "wall_s_median": round(statistics.median(times), 4),
        "wall_s_min": round(min(times), 4),
        "total_ops": iters_per_thread * n_threads,
        "ops_per_s_median": round(iters_per_thread * n_threads / statistics.median(times), 1),
    }


def _runtime_meta() -> dict:
    try:
        from nokido_agent.app.forge_python_runtime import IS_FREE_THREADED, current_env_alias

        env_alias = current_env_alias()
        free_threaded = IS_FREE_THREADED
    except Exception:
        env_alias = "unknown"
        free_threaded = False
    return {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "executable": sys.executable,
        "env_alias": env_alias,
        "free_threaded": free_threaded,
        "numpy_version": np.__version__,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", default="1,2,4,8", help="Comma-separated thread counts")
    ap.add_argument("--label", default="auto")
    ap.add_argument("--runs", type=int, default=3, help="Repeats per (workload, threads) combo")
    args = ap.parse_args()

    thread_counts = [int(t) for t in args.threads.split(",")]
    rt = _runtime_meta()
    print(f"[multithread] {rt['python_version']} numpy={rt['numpy_version']} free_threaded={rt['free_threaded']}")
    print(f"[multithread] threads={thread_counts} runs={args.runs}")
    print()

    results: dict = {}
    for wname, (wfunc, iters) in WORKLOADS.items():
        print(f"=== workload : {wname} (iters/thread={iters}) ===")
        results[wname] = {}
        single_thread_median = None
        for nt in thread_counts:
            r = _bench_workload(wfunc, iters, nt, runs=args.runs)
            results[wname][f"threads_{nt}"] = r
            if nt == 1:
                single_thread_median = r["wall_s_median"]
            speedup = (single_thread_median / r["wall_s_median"]) if single_thread_median else 1.0
            r["speedup_vs_1thread"] = round(speedup, 2)
            r["efficiency_pct"] = round(100 * speedup / nt, 1)
            print(
                f"  threads={nt:>2d}: wall={r['wall_s_median']:>7.3f}s "
                f"ops/s={r['ops_per_s_median']:>8.1f} "
                f"speedup={r['speedup_vs_1thread']:>4.2f}x "
                f"eff={r['efficiency_pct']:>5.1f}%"
            )
        print()

    snapshot = {
        "runtime": rt,
        "label": args.label if args.label != "auto" else rt["env_alias"],
        "config": {"thread_counts": thread_counts, "runs_per_combo": args.runs},
        "workloads": results,
    }

    PERF_HIST.mkdir(parents=True, exist_ok=True)
    out = PERF_HIST / f"bench_multithread_{snapshot['label']}_{rt['ts'][:19].replace(':', '')}.json"
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
