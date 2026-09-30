"""tools/forge_mpc_seed_traces.py - amorce N transitions self-play synthetiques.

Quand pas d activite MPC reelle (services AMI assoupis), le trainer offline
n a rien a apprendre et trace_count stagne. Ce driver injecte N transitions
SYNTHETIQUES (state_emb 384D, action_desc, cost_before>cost_after dans 70%
des cas) via forge_mpc._insert_self_play_trace.

NB : embeddings synthetiques structures (gaussian + perturbation locale),
PAS encodage semantique reel - state_encoder import sentence_transformers
qui crashe sur perm denied packaging/__init__.py (icacls /T conda).
Resultat : pipeline trainer/world_model tourne et converge vers loss
mesurable, MAIS qualite predictive non comparable a vrai run MPC.

Usage :
  LAFORGE_PYTHON tools/forge_mpc_seed_traces.py [--n 200] [--dim 384]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ACTION_TEMPLATES = [
    "edit file {n}",
    "run pytest",
    "search rag for {k}",
    "ask llm to explain",
    "refactor function f_{n}",
    "add docstring to {k}",
    "fix bug in module_{n}",
    "git commit -m chore",
    "ingest doc {k}",
    "render template {n}",
]
TASK_TYPES = ["mpc_live", "orchestration", "coding", "research", "monitoring"]


def _gen_state_emb(rng: np.random.Generator, dim: int, cluster: int) -> np.ndarray:
    """Embedding 384D pseudo-clusterise (5 clusters), normalise L2."""
    centroid = rng.standard_normal(dim) * 0.5
    centroid[cluster * 10 % dim] += 3.0
    v = centroid + rng.standard_normal(dim) * 0.3
    return (v / (np.linalg.norm(v) + 1e-8)).astype(np.float32)


def _perturb(rng: np.random.Generator, v: np.ndarray, strength: float = 0.15) -> np.ndarray:
    """Petite perturbation locale (simule transition)."""
    delta = rng.standard_normal(v.shape) * strength
    out = v + delta
    return (out / (np.linalg.norm(out) + 1e-8)).astype(v.dtype)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="nombre de transitions a inserer")
    ap.add_argument(
        "--dim", type=int, default=384, help="dimension state_emb (doit matcher OUTPUT_DIM AMI)"
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from nokido_agent.app.forge_mpc import _insert_self_play_trace

    rng = np.random.default_rng(args.seed)
    t0 = time.monotonic()
    ok = fail = 0
    print(f"[seed] insertion de {args.n} transitions (dim={args.dim})...")
    for i in range(args.n):
        cluster = i % 5
        state_emb = _gen_state_emb(rng, args.dim, cluster)
        next_emb = _perturb(rng, state_emb, strength=0.15)
        cost_before = float(rng.uniform(0.3, 1.0))
        # 70% des cas : cost decroit (succes), 30% : cost monte (echec)
        if rng.random() < 0.7:
            cost_after = cost_before * float(rng.uniform(0.3, 0.9))
            success = True
        else:
            cost_after = min(1.0, cost_before * float(rng.uniform(1.05, 1.5)))
            success = False
        tpl = ACTION_TEMPLATES[i % len(ACTION_TEMPLATES)]
        action_desc = tpl.format(n=i, k=f"topic_{cluster}")
        task_type = TASK_TYPES[i % len(TASK_TYPES)]
        try:
            _insert_self_play_trace(
                state_emb=state_emb,
                next_state_emb=next_emb,
                action_desc=action_desc,
                cost_before=cost_before,
                cost_after=cost_after,
                success=success,
                task_type=task_type,
            )
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            if fail <= 3:
                print(f"  [FAIL {i}] {e}")
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{args.n} ({ok} ok, {fail} fail)")

    elapsed = time.monotonic() - t0
    print(
        f"[seed] DONE : {ok}/{args.n} insertes en {elapsed:.1f}s "
        f"({args.n / elapsed:.0f} insertions/s)"
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
