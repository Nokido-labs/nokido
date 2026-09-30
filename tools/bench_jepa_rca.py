"""tools/bench_jepa_rca.py - cProfile JEPA train_step pour identifier hotspot.

Per Gemini Web 2026-05-29 plan #b (post-bench analyse).

Pourquoi : test_bench_jepa_train_step regression -14% sur py314 GIL vs py312.
Numpy 1.26 -> 2.4 explique grosse partie du gain ailleurs, mais train_step EST
plus lent sur 3.14 GIL. Faut localiser.

Output : top 20 fonctions par tottime, dump pstats brut + savedump.

Usage:
    LAFORGE_PYTHON tools/bench_jepa_rca.py --label py312_baseline
    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe tools/bench_jepa_rca.py --label py314_gil
"""

from __future__ import annotations

import argparse
import cProfile
import datetime
import pstats
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROF_DIR = ROOT / "sandbox" / "perf_history"


def run_profile(n_steps: int, jepa, state_t, action_emb, state_t1):
    """Profile n_steps de jepa.train_step. Retourne pstats.Stats."""
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(n_steps):
        jepa.train_step(state_t, action_emb, state_t1, lr=1e-3)
    pr.disable()
    return pr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200, help="Number of train_step calls to profile")
    ap.add_argument("--label", default="auto")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    import numpy as np

    from nokido_agent.app.forge_world_model import JEPA

    jepa = JEPA(rng_seed=42)
    rng = np.random.default_rng(42)
    state_t = rng.standard_normal(384).astype(np.float32)
    action_emb = rng.standard_normal(384).astype(np.float32)
    state_t1 = rng.standard_normal(384).astype(np.float32)

    # Warmup
    for _ in range(10):
        jepa.train_step(state_t, action_emb, state_t1, lr=1e-3)

    print(f"[rca] {sys.version.split()[0]} ({sys.executable})")
    print(f"[rca] numpy {np.__version__}")
    print(f"[rca] profiling {args.steps} train_step calls...")

    pr = run_profile(args.steps, jepa, state_t, action_emb, state_t1)
    ps = pstats.Stats(pr).sort_stats("tottime")

    # Save raw stats
    PROF_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
    label = args.label if args.label != "auto" else "unknown"
    out_dump = PROF_DIR / f"rca_jepa_train_{label}_{ts}.prof"
    pr.dump_stats(str(out_dump))
    print(f"[rca] raw profile saved: {out_dump}")

    # Print top N
    buf = StringIO()
    ps.stream = buf
    ps.print_stats(args.top)
    output = buf.getvalue()

    print()
    print(output)

    # Also save text top
    out_txt = PROF_DIR / f"rca_jepa_train_{label}_{ts}.top20.txt"
    out_txt.write_text(
        f"# JEPA train_step cProfile -- {label}\n"
        f"# Python : {sys.version.split()[0]}\n"
        f"# numpy  : {np.__version__}\n"
        f"# Steps  : {args.steps}\n\n"
        + output,
        encoding="utf-8",
    )
    print(f"[rca] top{args.top} text saved: {out_txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
