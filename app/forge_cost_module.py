"""
Phase 1 — AMI roadmap: Cost Module.
total_cost = (1 - λ) × intrinsic_cost(state) + λ × task_cost(state, goal)
Replaces prompt-only objectives with a scalar minimizable function.
"""

import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

DEFAULT_LAMBDA = 0.7  # task_cost weight vs intrinsic_cost


def intrinsic_cost(state_emb: np.ndarray) -> float:
    """Guardrail cost: variance-based stability estimate (fallback, no safety signals)."""
    try:
        import sys, pathlib

        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from nokido_agent.app.forge_trust_score import get_trust_score

        trust = get_trust_score()
        trust_penalty = 1.0 - float(trust)
    except Exception:
        trust_penalty = min(float(np.var(state_emb)) * 10.0, 1.0)
    return float(np.clip(trust_penalty, 0.0, 1.0))


# IntegrityRing levels: 0=MASTER, 1=SYSTEM, 2=DEV, 3=TRUSTED, 4=COLLAB, 5=UNTRUSTED
_RING_PENALTY = {0: 0.5, 1: 0.3, 2: 0.0, 3: 0.0, 4: 0.1, 5: 0.4}


def intrinsic_cost_wired(
    ring_level: int = 2,
    firewall_score: float = 1.0,  # [0,1], 0=blocked by SemanticFirewall
    canary_leaked: bool = False,
) -> float:
    """LeCun AMI intrinsic cost: immuable safety guardrails.

    Returns [0.0=safe, 1.0=max-dangerous]. Independent of task goal.
    Combines: ring privilege penalty + firewall rejection + canary leak (catastrophic).
    """
    penalty = _RING_PENALTY.get(ring_level, 0.0)
    penalty += max(0.0, 1.0 - firewall_score) * 0.4  # fw_score=0 → +0.4
    if canary_leaked:
        penalty += 1.0  # catastrophic override
    return float(min(penalty, 1.0))


def task_cost(state_emb: np.ndarray, goal_emb: np.ndarray) -> float:
    """Distance to goal. Uses CostNet when trained, falls back to cosine."""
    from pathlib import Path

    _model_path = Path(__file__).parent.parent / "RAG" / "cost_net.npz"
    if _model_path.exists():
        try:
            from nokido_agent.app.forge_cost_net import predict_cost

            return float(predict_cost(state_emb, goal_emb))
        except Exception:
            pass
    from nokido_agent.app.forge_state_encoder import cosine_similarity

    sim = cosine_similarity(state_emb, goal_emb)
    return float((1.0 - sim) / 2.0)


EPISTEMIC_ALPHA = 0.15  # weight of epistemic uncertainty in total_cost
EPISTEMIC_K = 3  # Monte Carlo perturbations
EPISTEMIC_SIGMA = 0.02  # Gaussian noise std on state_emb


def epistemic_cost(state_emb: np.ndarray, action_text: str = "") -> float:
    """LeCun: uncertain states carry higher cost → exploration signal.

    Monte Carlo: perturb state_emb K times → NMLP predict next state.
    Variance across predictions = epistemic uncertainty ∈ [0, 1].
    High uncertainty = novel state = exploration bonus (cost reduction for curious agents,
    or avoidance for safety agents — caller decides sign via EPISTEMIC_ALPHA).
    """
    try:
        from nokido_agent.app.forge_world_model import predict

        preds = []
        for _ in range(EPISTEMIC_K):
            noisy = state_emb + np.random.normal(0, EPISTEMIC_SIGMA, state_emb.shape).astype("float32")
            n = np.linalg.norm(noisy)
            noisy = noisy / n if n > 1e-8 else noisy
            preds.append(predict(noisy, action_text or "step"))
        preds_arr = np.stack(preds)
        variance = float(np.mean(np.var(preds_arr, axis=0)))
        return float(np.clip(variance * 50.0, 0.0, 1.0))  # scale: ~0.02 var → 1.0
    except Exception:
        return 0.0


def total_cost(
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    lam: float = DEFAULT_LAMBDA,
    ring_level: int = 2,
    firewall_score: float = 1.0,
    canary_leaked: bool = False,
    action_text: str = "",
    use_epistemic: bool = True,
) -> float:
    """total_cost = (1-λ)·intrinsic_cost_wired + λ·task_cost [+ α·epistemic_cost].

    use_epistemic=True: adds uncertainty term — penalises unknown states (safe mode)
    or reduces cost for them (explorer mode) depending on caller sign convention.
    """
    ic = intrinsic_cost_wired(ring_level, firewall_score, canary_leaked)
    tc = task_cost(state_emb, goal_emb)
    base = float((1.0 - lam) * ic + lam * tc)
    if use_epistemic and action_text:
        ec = epistemic_cost(state_emb, action_text)
        base = float(np.clip(base + EPISTEMIC_ALPHA * ec, 0.0, 2.0))
    return base


def score_plans(
    plans: list[dict],
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    lam: float = DEFAULT_LAMBDA,
) -> list[tuple[float, dict]]:
    """
    Score N candidate action plans by predicted cost.
    plans: [{"description": str, "steps": [...]}]
    Returns sorted [(cost, plan)] ascending (best first).
    """
    from nokido_agent.app.forge_state_encoder import encode_state

    scored: list[tuple[float, dict]] = []
    for plan in plans:
        plan_text = plan.get("description", "") + " " + " ".join(str(s) for s in plan.get("steps", []))
        plan_emb = encode_state(plan_text)
        # Predicted state: blend current state toward plan direction
        predicted = 0.5 * state_emb + 0.5 * plan_emb
        norm = np.linalg.norm(predicted)
        predicted = predicted / norm if norm > 0 else predicted
        cost = total_cost(predicted, goal_emb, lam)
        scored.append((cost, plan))

    return sorted(scored, key=lambda x: x[0])


if __name__ == "__main__":
    from nokido_agent.app.forge_state_encoder import encode_state

    state_text = "task queue: 3 pending, hub: UP, trust: 0.8"
    goal_text = "system stable, all tasks completed, no errors"

    s_emb = encode_state(state_text)
    g_emb = encode_state(goal_text)

    ic = intrinsic_cost(s_emb)
    tc = task_cost(s_emb, g_emb)
    tot = total_cost(s_emb, g_emb)
    print(f"[cost_module] intrinsic={ic:.4f}  task={tc:.4f}  total={tot:.4f}")

    plans = [
        {"description": "flush queue and health check", "steps": ["flush_queue", "health_check"]},
        {"description": "restart services and clear errors", "steps": ["restart_hub", "clear_errors"]},
        {"description": "noop — wait", "steps": ["noop"]},
    ]
    ranked = score_plans(plans, s_emb, g_emb)
    print("\n[cost_module] Plans ranked (best first):")
    for cost, plan in ranked:
        print(f"  {cost:.4f}  {plan['description']}")
