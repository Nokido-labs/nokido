"""
Phase 5 - AMI roadmap: Model Predictive Control (closed-loop planning).
AMI §4.3: Actor selects action by minimizing predicted cost over horizon H.
If actual_cost > predicted_cost * surprise_threshold → replan mid-horizon.

Depends on: forge_state_encoder, forge_cost_module (P0+P1),
            forge_actor (P2), forge_world_model (P3), forge_configurator (P4).
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HORIZON = 3  # steps to lookahead
DEFAULT_N_CANDIDATES = 5  # actor candidates per step
SURPRISE_THRESHOLD = 1.2  # replan if actual > predicted * threshold
MAX_REPLANS = 3  # safety cap on replan loops


# ---------------------------------------------------------------------------
# MPC result types
# ---------------------------------------------------------------------------


@dataclass
class MPCStep:
    action: dict  # {"description": str, "steps": list[str]}
    predicted_cost: float
    actual_cost: Optional[float] = None
    surprise: bool = False
    replan: bool = False
    elapsed_ms: float = 0.0


@dataclass
class MPCResult:
    goal: str
    steps: list[MPCStep] = field(default_factory=list)
    total_predicted_cost: float = 1.0
    total_actual_cost: float = 1.0
    n_replans: int = 0
    success: bool = False


# ---------------------------------------------------------------------------
# Core: plan_horizon
# ---------------------------------------------------------------------------


def plan_horizon(
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    goal_text: str,
    state_text: str,
    horizon: int = DEFAULT_HORIZON,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    task_type: str = "orchestration",
    use_jepa: bool = False,
    use_mcts: bool = False,
) -> list[tuple[list[dict], float]]:
    """
    For each of n_candidates root actions, roll out H steps using world_model.
    use_mcts=True: policy_net+value_net expansion, no Ollama, ~16ms per call.
    Returns [(action_sequence, cumulative_predicted_cost)] sorted ascending.
    """
    from nokido_agent.app.forge_world_model import predict, predict_cost, predict_jepa, predict_cost_jepa
    from nokido_agent.app.forge_cost_module import task_cost

    _predict = predict_jepa if use_jepa else predict
    _pred_cost = predict_cost_jepa if use_jepa else predict_cost

    sequences: list[tuple[list[dict], float]] = []

    if use_mcts:
        from nokido_agent.app.forge_actor import mcts_propose
        from nokido_agent.app.forge_world_model import predict as _predict_384  # MCTS needs 384D

        # Root: 32-sim MCTS → top-n candidates, no Ollama
        _plan, scored = mcts_propose(state_emb, goal_emb, n_simulations=max(n_candidates * 6, 32), task_type=task_type)
        for _cost, node in scored[:n_candidates]:
            seq = [node.plan]
            cum_cost = node.cost
            cur_emb = _predict_384(state_emb, node.plan["description"])  # stay 384D
            # Deeper steps: 8-sim MCTS (fast)
            for _ in range(1, horizon):
                next_plan, _ = mcts_propose(cur_emb, goal_emb, n_simulations=8, task_type=task_type)
                seq.append(next_plan)
                cur_emb = _predict_384(cur_emb, next_plan["description"])
                cum_cost += float(task_cost(cur_emb, goal_emb))
            sequences.append((seq, cum_cost / horizon))
    else:
        from nokido_agent.app.forge_actor import generate_candidates, score_and_select

        root_nodes = generate_candidates(goal_text, state_text, N=n_candidates, task_type=task_type)
        _, scored_roots = score_and_select(root_nodes, state_emb, goal_emb)
        for root_cost, root_node in scored_roots[:n_candidates]:
            seq = [root_node.plan]
            cum_cost = root_cost
            cur_emb = _predict(state_emb, root_node.plan["description"])
            for _ in range(1, horizon):
                child_state_text = f"predicted state after: {seq[-1]['description'][:120]}"
                child_nodes = generate_candidates(goal_text, child_state_text, N=3, task_type=task_type)
                if not child_nodes:
                    break
                _, child_scored = score_and_select(child_nodes, cur_emb, goal_emb)
                best_cost, best_node = child_scored[0]
                seq.append(best_node.plan)
                cum_cost += best_cost
                cur_emb = _predict(cur_emb, best_node.plan["description"])
            sequences.append((seq, cum_cost / horizon))

    sequences.sort(key=lambda x: x[1])
    try:  # viz flux-de-réflexion (best-effort)
        from nokido_agent.app.forge_swarm_bus import publish as _rp
        _bseq, _bcost = sequences[0] if sequences else ([], float("inf"))
        _rp(kind="mpc_plan_horizon", data={
            "horizon": horizon, "predicted_cost": float(_bcost),
            "n_candidates": n_candidates, "n_sequences": len(sequences),
        }, topic="reasoning")
    except Exception:
        pass
    return sequences


# ---------------------------------------------------------------------------
# Core: mpc_step — execute one step with surprise detection
# ---------------------------------------------------------------------------


def mpc_step(
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    goal_text: str,
    state_text: str,
    horizon: int = DEFAULT_HORIZON,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    use_jepa: bool = False,
    use_mcts: bool = False,
) -> tuple[dict, float, np.ndarray]:
    from nokido_agent.app.forge_world_model import predict, predict_jepa

    sequences = plan_horizon(
        state_emb,
        goal_emb,
        goal_text,
        state_text,
        horizon=horizon,
        n_candidates=n_candidates,
        use_jepa=use_jepa,
        use_mcts=use_mcts,
    )

    best_seq, predicted_cost = sequences[0]
    best_action = best_seq[0]
    # Always return 384D — JEPA (256D) stays internal to plan_horizon rollouts
    predicted_next_emb = predict(state_emb, best_action["description"])
    return best_action, predicted_cost, predicted_next_emb


# ---------------------------------------------------------------------------
# Online update — lightweight SGD from a single observed transition
# ---------------------------------------------------------------------------


def _insert_self_play_trace(
    state_emb: np.ndarray,
    next_state_emb: np.ndarray,
    action_desc: str,
    cost_before: float,
    cost_after: float,
    success: bool,
    task_type: str = "mpc_live",
) -> None:
    """Insert live MPC transition into execution_traces.db — self-play loop."""
    import hashlib, time as _t, json as _j
    from pathlib import Path as _P
    import sqlite3 as _sql

    db = _P(__file__).parent.parent / "RAG" / "execution_traces.db"
    if not db.exists():
        return
    try:
        conn = _sql.connect(db)
        tid = hashlib.sha256(f"live:{_t.time()}:{action_desc}".encode()).hexdigest()[:16]
        conn.execute(
            "INSERT OR IGNORE INTO traces (id, ts, state_t_emb, action_json, state_t1_emb, "
            "cost_before, cost_after, task_type, success) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                tid,
                _t.time(),
                state_emb.tobytes(),
                _j.dumps({"type": "mpc_live", "description": action_desc[:120]}),
                next_state_emb.tobytes(),
                float(cost_before),
                float(cost_after),
                task_type,
                int(success),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _online_update(
    state_emb: np.ndarray,
    next_state_emb: np.ndarray,
    goal_emb: np.ndarray,
    success: bool,
    actual_cost: float,
    lr: float = 0.0001,  # very small — prevent catastrophic forgetting
) -> None:
    """Update value_net + policy_net + cost_net from one live transition."""
    try:
        from nokido_agent.app.forge_value_net import get_model as get_v
        from nokido_agent.app.forge_policy_net import get_model as get_p

        # Value net: target = 1.0 if success, else cost-improvement ratio
        v_model = get_v()
        target_v = 1.0 if success else float(np.clip(1.0 - actual_cost, 0.0, 1.0))
        _, v_cache = v_model.forward(state_emb)
        v_model.backward(v_cache, target_v, lr=lr)

        # Policy net: only on good transitions (cost improved)
        if success or actual_cost < 0.5:
            p_model = get_p()
            x = np.concatenate([state_emb, goal_emb]).astype("float32")
            delta = next_state_emb - state_emb
            n = np.linalg.norm(delta)
            if n > 1e-8:
                target_a = (delta / n).astype("float32")
                _, p_cache = p_model.forward(x)
                p_model.backward(p_cache, target_a, lr=lr)

        # Cost net: always update from observed actual_cost
        from nokido_agent.app.forge_cost_net import online_update as cost_online

        cost_online(state_emb, goal_emb, actual_cost, lr=lr)
    except Exception:
        pass  # non-blocking: online update best-effort


# ---------------------------------------------------------------------------
# High-level: run_mpc_loop — full closed-loop with replan
# ---------------------------------------------------------------------------


def run_mpc_loop(
    goal_text: str,
    state_text: str,
    max_steps: int = 6,
    horizon: int = DEFAULT_HORIZON,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    surprise_threshold: float = SURPRISE_THRESHOLD,
    execute_fn=None,  # callable(action_dict) -> (new_state_text, actual_cost, success)
    config: dict | None = None,  # from forge_configurator.get_mpc_config() — overrides above
) -> MPCResult:
    """
    Closed-loop MPC:
      1. plan_horizon → best_action
      2. execute_fn(best_action)
      3. observe actual_cost
      4. if actual_cost > predicted_cost * surprise_threshold → replan
      5. repeat until goal reached or max_steps

    execute_fn: if None, uses world_model for fully simulated rollout.
    """
    from nokido_agent.app.forge_state_encoder import encode_state
    from nokido_agent.app.forge_cost_module import total_cost
    from nokido_agent.app.forge_world_model import predict
    from nokido_agent.app.forge_actor import reflect
    from nokido_agent.app.forge_self_correction import anchor_solution
    from nokido_agent.app.forge_stm import get_stm, augment_state_emb

    stm = get_stm()

    # Unpack configurator config (overrides defaults when provided)
    use_jepa = False
    use_mcts = False
    if config:
        horizon = config.get("horizon", horizon)
        n_candidates = config.get("n_candidates", n_candidates)
        surprise_threshold = config.get("surprise_threshold", surprise_threshold)
        use_jepa = config.get("use_jepa", False)
        use_mcts = config.get("use_mcts", False)

    result = MPCResult(goal=goal_text)
    state_emb = encode_state(state_text)
    goal_emb = encode_state(goal_text)

    current_state_text = state_text
    current_state_emb = state_emb
    replans = 0

    for step_i in range(max_steps):
        t0 = time.time()

        # STM augmentation: blend recent states into current emb
        aug_emb = augment_state_emb(current_state_emb, decay=0.12, n=3)

        # Plan (use augmented emb for richer context)
        best_action, predicted_cost, predicted_next_emb = mpc_step(
            aug_emb,
            goal_emb,
            goal_text,
            current_state_text,
            horizon=horizon,
            n_candidates=n_candidates,
            use_jepa=use_jepa,
            use_mcts=use_mcts,
        )

        elapsed_plan = (time.time() - t0) * 1000

        # Execute
        if execute_fn is not None:
            new_state_text, actual_cost, success = execute_fn(best_action)
            new_state_emb = encode_state(new_state_text)
        else:
            # simulated: trust world model
            new_state_emb = predicted_next_emb
            new_state_text = f"sim_step_{step_i}: {best_action['description'][:80]}"
            actual_cost = total_cost(
                new_state_emb,
                goal_emb,
                use_epistemic=True,
                action_text=best_action.get("description", ""),
            )
            success = actual_cost < 0.3

        elapsed_total = (time.time() - t0) * 1000

        # Surprise detection (use STM cost trend to adjust threshold dynamically)
        trend = stm.get_cost_trend(4)
        dyn_threshold = surprise_threshold * (1.0 + 0.05 * (len(trend) > 2 and trend[-1] > trend[0]))
        surprise = actual_cost > predicted_cost * dyn_threshold
        do_replan = surprise and replans < MAX_REPLANS

        mpc_step_obj = MPCStep(
            action=best_action,
            predicted_cost=predicted_cost,
            actual_cost=actual_cost,
            surprise=surprise,
            replan=do_replan,
            elapsed_ms=elapsed_total,
        )
        result.steps.append(mpc_step_obj)

        # STM push — episodic record of this step
        stm.push(
            state_text=current_state_text,
            action_desc=best_action.get("description", ""),
            actual_cost=actual_cost,
            success=success,
            state_emb=current_state_emb,
            goal_text=goal_text,
        )

        # Self-play trace insertion — grows training dataset from live runs
        if execute_fn is not None:
            _insert_self_play_trace(
                state_emb=current_state_emb,
                next_state_emb=new_state_emb,
                action_desc=best_action.get("description", ""),
                cost_before=predicted_cost,
                cost_after=actual_cost,
                success=success,
                task_type=config.get("task_type", "mpc_live") if config else "mpc_live",
            )

        # Online update — lightweight SGD from observed transition
        _online_update(current_state_emb, new_state_emb, goal_emb, success, actual_cost)

        if do_replan:
            replans += 1
            result.n_replans += 1

        current_state_emb = new_state_emb
        current_state_text = new_state_text

        if success or actual_cost < 0.2:
            result.success = True
            break

    result.total_predicted_cost = float(np.mean([s.predicted_cost for s in result.steps]))
    result.total_actual_cost = float(np.mean([s.actual_cost for s in result.steps if s.actual_cost is not None]))

    # Anchor to RAG
    anchor_solution(
        problem=f"MPC loop: {goal_text[:80]}",
        solution=f"{len(result.steps)} steps, {result.n_replans} replans, success={result.success}, avg_actual_cost={result.total_actual_cost:.3f}",
        example=f"run_mpc_loop(goal='{goal_text[:50]}', max_steps={max_steps})",
        domain="mpc",
    )

    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[mpc] Smoke test — simulated rollout (no execute_fn)\n")

    goal = "system stable, all tasks completed, hub healthy, no errors"
    state = "task queue: 3 pending, hub: UP, trust: 0.8, 1 error logged"

    result = run_mpc_loop(goal, state, max_steps=4, horizon=2, n_candidates=3)

    print(f"Goal: {goal}")
    print(f"Success: {result.success} | Steps: {len(result.steps)} | Replans: {result.n_replans}")
    print(f"Avg predicted cost: {result.total_predicted_cost:.4f}")
    print(f"Avg actual cost:    {result.total_actual_cost:.4f}")
    print()
    for i, s in enumerate(result.steps):
        surprise_flag = " [SURPRISE→REPLAN]" if s.surprise else ""
        print(f"  Step {i + 1}: {s.action['description'][:60]}")
        print(f"    predicted={s.predicted_cost:.4f} actual={s.actual_cost:.4f} {surprise_flag} ({s.elapsed_ms:.0f}ms)")
