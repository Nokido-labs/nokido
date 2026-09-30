"""
Phase 2 - AMI roadmap: Actor with multi-plan exploration + UCT selection.
LATS Node/UCT + XAgent 4-role pattern (Generate/Refine/Tool/Reflect).
Depends on: forge_state_encoder, forge_cost_module (Phase 0+1).
"""

import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
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

ROOT = Path(__file__).parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
RAG_DB = ROOT / "RAG" / "embeddings.db"
_CURATED_CACHE: dict = {}  # task_type -> (ts, list[Node]) — boucle skill_curator -> planner
_CURATED_TTL = 300

# ---------------------------------------------------------------------------
# Action vocabulary — (direction_emb, task_type) from positive traces
# ---------------------------------------------------------------------------

_ACTION_VOCAB: Optional[list] = None  # list[tuple[np.ndarray, str]]


def _build_action_vocab(limit: int = 800) -> list:
    if not TRACES_DB.exists():
        return []
    conn = sqlite3.connect(TRACES_DB)
    rows = conn.execute(
        "SELECT state_t_emb, state_t1_emb, task_type, action_json FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL "
        "AND cost_after < cost_before AND task_type IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    vocab = []
    for s_blob, s1_blob, task_type, action_json in rows:
        try:
            s = np.frombuffer(s_blob, dtype="float32")
            s1 = np.frombuffer(s1_blob, dtype="float32")
            if len(s) != 384 or len(s1) != 384:
                continue
            delta = s1 - s
            n = np.linalg.norm(delta)
            if n < 1e-8:
                continue
            # Enrich label with state_text context from action_json
            label = task_type
            if action_json:
                try:
                    aj = json.loads(action_json)
                    st = aj.get("state_text", "")[:60]
                    if st and st != "tasks:unknown":
                        label = f"{task_type}:{st}"
                except Exception:
                    pass
            vocab.append((delta / n, label))
        except Exception:
            pass
    return vocab


def decode_action_emb(action_emb: np.ndarray) -> str:
    """Nearest-neighbor: action_emb → enriched label (task_type:state_context)."""
    global _ACTION_VOCAB
    if _ACTION_VOCAB is None:
        _ACTION_VOCAB = _build_action_vocab()
    if not _ACTION_VOCAB:
        return "policy_action"
    sims = [float(np.dot(action_emb, v)) for v, _ in _ACTION_VOCAB]
    best = int(np.argmax(sims))
    label = _ACTION_VOCAB[best][1]
    return label.split(":")[0]  # task_type only for clean plan description


# ---------------------------------------------------------------------------
# Node - LATS style
# ---------------------------------------------------------------------------


class Node:
    def __init__(self, plan: dict, parent: Optional["Node"] = None, depth: int = 0):
        self.id = str(uuid.uuid4())[:8]
        self.plan = plan  # {"description": str, "steps": list[str]}
        self.parent = parent
        self.children: list["Node"] = []
        self.value: float = 0.0  # cumulative reward
        self.visits: int = 0
        self.reflection: str = ""
        self.cost: float = 1.0  # last computed total_cost (lower = better)
        self.depth = depth

    def uct(self, exploration: float = 1.41) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else self.visits
        return (self.value / self.visits) + exploration * math.sqrt(math.log(max(parent_visits, 1)) / self.visits)

    def best_child(self) -> Optional["Node"]:
        return max(self.children, key=lambda c: c.uct()) if self.children else None

    def update(self, reward: float) -> None:
        self.visits += 1
        self.value += reward


def gather_context_from_tree(node: Node) -> tuple[list[str], list[str]]:
    """Walk ancestors, collect cost history and reflections (oldest first)."""
    costs, reflections = [], []
    cur: Optional[Node] = node
    while cur:
        if cur.reflection:
            reflections.append(cur.reflection)
        if cur.cost < 1.0:
            costs.append(f"cost={cur.cost:.3f}")
        cur = cur.parent
    return costs[::-1], reflections[::-1]


# ---------------------------------------------------------------------------
# LLM helper (Ollama local)
# ---------------------------------------------------------------------------


def _ollama(prompt: str, temperature: float = 0.7, timeout: int = 60) -> str:
    import urllib.request

    body = json.dumps(
        {
            "model": "qwen2.5-coder:latest",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 512},
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "").strip()


_FALLBACK_PLANS = [
    "analyze current state and identify blockers",
    "execute highest-priority pending task",
    "check system health and resolve errors",
    "optimize resource usage and clear queue",
    "gather more context then act",
]


# ---------------------------------------------------------------------------
# PlanGenerateAgent
# ---------------------------------------------------------------------------


def _curated_candidates(task_type: Optional[str], n: int = 3) -> list:
    """Skills appris (forge_skill_curator, domain=curated_skills) réinjectés comme
    candidats — FERME la boucle auto-amélioration. SQL sync + cache TTL, gardé."""
    if not task_type:
        return []
    now = time.time()
    hit = _CURATED_CACHE.get(task_type)
    if hit and now - hit[0] < _CURATED_TTL:
        return hit[1][:n]
    nodes = []
    try:
        if RAG_DB.exists():
            conn = sqlite3.connect(f"file:{RAG_DB}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                "SELECT text, meta FROM rag_chunks WHERE domain='curated_skills' "
                "AND json_extract(meta,'$.task_type')=? "
                "AND CAST(json_extract(meta,'$.success_rate') AS REAL)>=0.6 "
                "ORDER BY CAST(json_extract(meta,'$.score') AS REAL) DESC LIMIT ?",
                (task_type, max(1, n)),
            ).fetchall()
            conn.close()
            for text, meta in rows:
                try:
                    m = json.loads(meta) if isinstance(meta, str) else (meta or {})
                except Exception:
                    m = {}
                atype = str(m.get("action_type") or "").strip()
                desc = atype or (text or "")[:120]   # action prouvée = verbe, pas la phrase meta
                if desc:
                    nodes.append(Node(plan={
                        "description": desc, "steps": [desc], "source": "curated_skill",
                        "task_type": m.get("task_type"), "action_type": atype,
                        "success_rate": m.get("success_rate"), "curator_score": m.get("score"),
                    }))
    except Exception:
        nodes = []
    _CURATED_CACHE[task_type] = (now, nodes)
    return nodes[:n]


def generate_candidates(goal: str, state_text: str, N: int = 5, task_type: Optional[str] = None) -> list[Node]:
    _, reflections = gather_context_from_tree(Node(plan={"description": "", "steps": []}))

    from nokido_agent.app.forge_stm import get_stm

    stm_ctx = get_stm().get_context(n=4)
    ctx = (f"Past failures: {reflections[-2:]}\n" if reflections else "") + (f"{stm_ctx}\n" if stm_ctx else "")
    prompt = (
        f"{ctx}"
        f"Goal: {goal}\n"
        f"Current state: {state_text}\n"
        f"Generate {N} distinct one-line action plans. Each starts with '- '.\n"
        f"Format: '- <verb> <what> to <achieve what>'\n"
        f"Plans:"
    )
    try:
        raw = _ollama(prompt, temperature=0.7)
        lines = [
            ln.lstrip("- ").strip() for ln in raw.splitlines() if ln.strip().startswith("-") and len(ln.strip()) > 4
        ][:N]
    except Exception:
        lines = []

    while len(lines) < N:
        lines.append(_FALLBACK_PLANS[len(lines) % len(_FALLBACK_PLANS)])

    llm_nodes = [Node(plan={"description": d, "steps": [d]}) for d in lines[:N]]
    return llm_nodes + _curated_candidates(task_type, n=max(1, N // 2))  # curated = candidats EN PLUS


# ---------------------------------------------------------------------------
# PlanRefineAgent
# ---------------------------------------------------------------------------


def refine_plan(node: Node, iterations: int = 1) -> Node:
    current = node
    for _ in range(iterations):
        _, reflections = gather_context_from_tree(current)
        prompt = (
            f"Plan: {current.plan['description']}\n"
            f"Cost score: {current.cost:.3f} (lower=better, 1.0=worst)\n"
            f"Reflections: {reflections[-2:] if reflections else 'none'}\n"
            f"Propose ONE improved plan. One line only:"
        )
        try:
            improved = _ollama(prompt, temperature=0.4, timeout=30).strip().split("\n")[0]
            child = Node(
                plan={"description": improved, "steps": [improved]},
                parent=current,
                depth=current.depth + 1,
            )
            current.children.append(child)
            current = child
        except Exception:
            break
    return current


# ---------------------------------------------------------------------------
# Score + UCT select (cost_module integration)
# ---------------------------------------------------------------------------


def score_and_select(
    nodes: list[Node],
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    gradient_refine: bool = False,
) -> tuple[Node, list[tuple[float, Node]]]:
    """Score nodes via world model predict() — replaces naive 0.5*s+0.5*p blend.
    gradient_refine=True: Phase D — refine top-1 action_emb by gradient descent.
    """
    from nokido_agent.app.forge_cost_module import total_cost
    from nokido_agent.app.forge_state_encoder import encode_state
    from nokido_agent.app.forge_world_model import predict, gradient_refine_action

    scored: list[tuple[float, Node]] = []
    for node in nodes:
        plan_emb = encode_state(node.plan["description"])
        if gradient_refine:
            plan_emb = gradient_refine_action(state_emb, plan_emb, goal_emb, steps=10)
        predicted = predict(state_emb, node.plan["description"])  # JEPA-lite forward
        cost = total_cost(predicted, goal_emb)
        node.cost = cost
        node.update(1.0 - cost)
        scored.append((cost, node))

    scored.sort(key=lambda x: x[0])
    return scored[0][1], scored


# ---------------------------------------------------------------------------
# ReflectAgent
# ---------------------------------------------------------------------------


def reflect(node: Node, execution_result: str, success: bool) -> str:
    reward = 1.0 - node.cost if success else 0.0
    node.update(reward)
    note = "OK" if success else "FAIL"
    node.reflection = f"{note} cost={node.cost:.3f}: {execution_result[:120]}"
    return node.reflection


# ---------------------------------------------------------------------------
# MCTS — Hassabis/AlphaZero style, no LLM dependency
# Uses policy_net for expansion + value_net for backprop
# World model (JEPA/NMLP) for rollouts
# ---------------------------------------------------------------------------


def mcts_propose(
    state_emb: np.ndarray,
    goal_emb: np.ndarray,
    n_simulations: int = 32,
    noise_std: float = 0.08,
    task_type: Optional[str] = None,
) -> tuple[dict, list[tuple[float, "Node"]]]:
    """AlphaZero-style MCTS. No LLM. Policy net proposes, value net evaluates.

    n_simulations: tree rollouts (each ~0.5ms → 32 sims = ~16ms total)
    noise_std: Dirichlet-like exploration noise on action_emb
    Returns (best_plan_dict, scored_nodes).
    """
    from nokido_agent.app.forge_policy_net import propose_action_emb
    from nokido_agent.app.forge_value_net import predict_value
    from nokido_agent.app.forge_world_model import predict_jepa, predict
    from nokido_agent.app.forge_cost_module import task_cost

    root = Node(plan={"description": "root", "steps": []})
    root.cost = float(task_cost(state_emb, goal_emb))
    nodes_expanded: list[Node] = []

    for sim in range(n_simulations):
        # 1. Expansion: policy_net → action_emb + noise for exploration
        noise = np.random.randn(384).astype("float32") * noise_std
        action_emb = propose_action_emb(state_emb, goal_emb)
        action_emb_noisy = action_emb + noise
        n = np.linalg.norm(action_emb_noisy)
        action_emb_noisy = action_emb_noisy / n if n > 1e-8 else action_emb_noisy

        # 2. Rollout: world model predicts next state
        try:
            next_state = predict_jepa(state_emb, "policy_action")
            # Inject direction: blend predicted with policy direction
            next_state = (
                0.7 * next_state[:384] + 0.3 * action_emb_noisy
                if len(next_state) >= 384
                else state_emb + 0.1 * action_emb_noisy
            )
        except Exception:
            next_state = state_emb + 0.1 * action_emb_noisy
        norm = np.linalg.norm(next_state)
        next_state = next_state / norm if norm > 1e-8 else next_state

        # 3. Evaluation: value_net + task_cost
        v = predict_value(next_state)
        c = float(task_cost(next_state, goal_emb))
        combined_cost = 0.6 * c + 0.4 * (1.0 - v)  # blend cost + (1-value)

        # 4. Build candidate node — semantic label via action vocabulary
        label = decode_action_emb(action_emb_noisy)
        desc = f"{label}:sim{sim:02d}"
        node = Node(plan={"description": desc, "steps": [desc]}, parent=root, depth=1)
        node.cost = combined_cost
        node.update(v)
        root.children.append(node)
        nodes_expanded.append(node)

    # #3b bias auto-amélioration : skills prouvés (curated_skills) injectés comme
    # candidats forts (cost = 1-success_rate => priorisés par l'UCT). Boucle fermée
    # aussi côté MCTS (path use_mcts), pas seulement LLM.
    for _cn in _curated_candidates(task_type, n=2):
        try:
            _sr = float(_cn.plan.get("success_rate") or 0.0)
        except Exception:
            _sr = 0.0
        _cn.cost = max(0.0, 1.0 - _sr)
        _cn.update(1.0 - _cn.cost)
        nodes_expanded.append(_cn)

    # 5. UCT select best
    scored = sorted([(n.cost, n) for n in nodes_expanded], key=lambda x: x[0])
    best = scored[0][1] if scored else Node(plan={"description": "noop", "steps": []})
    try:  # viz flux-de-réflexion (best-effort, ne casse jamais le raisonnement)
        from nokido_agent.app.forge_swarm_bus import publish as _rp
        _rp(kind="actor_mcts_decision", data={
            "action": best.plan.get("description", "noop"),
            "value": float(getattr(best, "value", 0.0)) if getattr(best, "visits", 0) else 0.0,
            "n_sims": n_simulations, "visits": getattr(best, "visits", 0),
        }, topic="reasoning")
    except Exception:
        pass
    return best.plan, scored


# ---------------------------------------------------------------------------
# Main entry: propose_and_select
# ---------------------------------------------------------------------------


def propose_and_select(
    goal: str,
    state_text: str,
    N: int = 5,
    refine_top: bool = True,
) -> tuple[dict, list[tuple[float, Node]]]:
    """
    Generate N candidate plans, score via cost_module, return best.
    If refine_top=True: run PlanRefineAgent on top-2 candidates.
    Returns (best_plan_dict, scored_list).
    """
    from nokido_agent.app.forge_state_encoder import encode_state

    state_emb = encode_state(state_text)
    goal_emb = encode_state(goal)

    nodes = generate_candidates(goal, state_text, N)
    best, scored = score_and_select(nodes, state_emb, goal_emb)

    if refine_top and len(scored) >= 2:
        top2 = [scored[0][1], scored[1][1]]
        refined = [refine_plan(n) for n in top2]
        _, scored = score_and_select(nodes + refined, state_emb, goal_emb)
        best = scored[0][1]

    return best.plan, scored


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    goal = "system stable, all tasks completed, hub healthy"
    state = "task queue: 3 pending, hub: UP, trust: 0.8"

    print("[actor] Generating candidates (Ollama)...")
    best_plan, scored = propose_and_select(goal, state, N=5, refine_top=False)

    print(f"\n[actor] Best: {best_plan['description']}")
    print("\n[actor] All ranked:")
    for cost, node in scored:
        marker = ">" if node.plan == best_plan else " "
        print(f"  {marker} {cost:.4f}  {node.plan['description'][:65]}")
