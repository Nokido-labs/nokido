"""forge_lats_general.py — Language Agent Tree Search GENERAL purpose.

Companion de `forge_lats.py` (SWE-bench code edit specific). Ce module = LATS
pour problemes generaux (planning, diagnostic, decision multi-step) ou il n'y
a PAS de juge deterministe pytest.

Source veille 2026-05-29 : LATS Zhou et al. ICML 2024 + Tree of Thoughts Yao
2023 + reflection backtracking. Combine LLM rollouts + MCTS UCB1 + LLM judge
+ self-reflection.

Difference avec forge_lats.py :
- forge_lats : juge symbolique pytest, SWE-bench fix
- forge_lats_general : juge LLM cascade (frugal), problemes ouverts

Pattern :
1. SELECT : descend l arbre via UCB1
2. EXPAND : rollouts N actions LLM cascade
3. EVALUATE : score [0,1] LLM judge
4. BACKPROPAGATE : update visits + value
5. REFLECT : apres K iter sans progress -> critique + backtrack vers root + hint

Cas d usage Nokido :
- Diagnostic root cause incidents (BSOD analyse, deadlock detection)
- Planification veille themes profonds
- Refactor proposals architecturaux multi-fichier
- Strategy decisions (cloud cost vs latency, fallback chains)
"""

from __future__ import annotations
import json, logging, math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("lats_general")

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class MCTSNode:
    """Node de l arbre LATS general. Chaque node = un etat partiel du raisonnement."""

    action: str
    parent: Optional["MCTSNode"] = None
    children: list["MCTSNode"] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    score: float = 0.0
    rationale: str = ""
    depth: int = 0
    terminal: bool = False

    def ucb1(self, c: float = 1.4) -> float:
        if self.visits == 0:
            return float("inf")
        if not self.parent or self.parent.visits == 0:
            return self.value / self.visits
        exploit = self.value / self.visits
        explore = c * math.sqrt(math.log(self.parent.visits) / self.visits)
        return exploit + explore

    def best_child(self, c: float = 1.4) -> Optional["MCTSNode"]:
        if not self.children:
            return None
        return max(self.children, key=lambda ch: ch.ucb1(c))

    def to_path(self) -> list[str]:
        path = []
        cur = self
        while cur:
            if cur.action:
                path.append(cur.action)
            cur = cur.parent
        return list(reversed(path))


def _llm_rollout(problem: str, parent_path: list[str], n: int = 3) -> list[dict]:
    """Generate N candidate next-actions via frugal cascade LLM."""
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_frugal_cascade import cascade
    except Exception as e:
        logger.warning(f"frugal_cascade unavailable: {e}")
        return []

    context = "\n".join(f"  - {a}" for a in parent_path) if parent_path else "(start)"
    prompt = (
        f"Probleme:\n{problem[:1000]}\n\n"
        f"Chemin actuel:\n{context}\n\n"
        f"Propose {n} prochaines actions concretes DIFFERENTES.\n"
        f"Format STRICT JSON: "
        f'{{"candidates":[{{"action":"...","rationale":"..."}}]}}'
    )
    result = cascade(prompt, use_case="reasoning", max_tokens=800)
    text = result.get("response") or ""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return data.get("candidates", [])[:n]
    except Exception as e:
        logger.debug(f"rollout parse fail: {e}")
    return []


def _llm_evaluate(problem: str, node_path: list[str]) -> tuple[float, str, bool]:
    """Score [0,1] confiance + rationale + terminal flag."""
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_frugal_cascade import cascade
    except Exception:
        return 0.5, "frugal_cascade unavailable", False

    path_str = "\n".join(f"  {i + 1}. {a}" for i, a in enumerate(node_path))
    prompt = (
        f"Probleme:\n{problem[:1000]}\n\n"
        f"Plan propose:\n{path_str}\n\n"
        f"Evalue plan 0.0-1.0. Format JSON: "
        f'{{"score":0.X,"rationale":"...","terminal":true/false}}'
    )
    result = cascade(prompt, use_case="reasoning", max_tokens=300)
    text = result.get("response") or ""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        return (
            float(data.get("score", 0.5)),
            data.get("rationale", ""),
            bool(data.get("terminal", False)),
        )
    except Exception:
        return 0.5, "parse fail", False


def _reflect_and_backtrack(problem: str, failed_paths: list[list[str]]) -> str:
    """Apres K fails, critique + nouvelle direction (backtracking)."""
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_frugal_cascade import cascade
    except Exception:
        return ""
    fails = "\n".join(f"Path {i + 1}: {' -> '.join(p[:3])}" for i, p in enumerate(failed_paths[:5]))
    prompt = (
        f"Probleme: {problem[:800]}\n\n"
        f"Chemins echoues:\n{fails}\n\n"
        f"Critique + propose UNE direction RADICALEMENT differente (2 phrases)."
    )
    result = cascade(prompt, use_case="reasoning", max_tokens=400)
    return result.get("response") or ""


def lats_solve(
    problem: str, budget: int = 10, threshold: float = 0.75, rollouts_per_node: int = 3, max_depth: int = 5
) -> dict:
    """LATS general solver.

    Returns:
        {best_plan, best_score, n_iterations, n_backtracks, trace, rationale}
    """
    root = MCTSNode(action="", depth=0)
    best_node = root
    best_score = 0.0
    n_backtracks = 0
    trace = []

    for it in range(budget):
        # SELECT
        node = root
        while node.children and not node.terminal and node.depth < max_depth:
            nxt = node.best_child()
            if not nxt:
                break
            node = nxt

        # EXPAND
        if not node.terminal and node.depth < max_depth:
            candidates = _llm_rollout(problem, node.to_path(), n=rollouts_per_node)
            for cand in candidates:
                child = MCTSNode(
                    action=cand.get("action", "")[:300],
                    rationale=cand.get("rationale", "")[:200],
                    parent=node,
                    depth=node.depth + 1,
                )
                node.children.append(child)
            if node.children:
                node = node.children[0]

        # EVALUATE
        path = node.to_path()
        score, rationale, terminal = _llm_evaluate(problem, path)
        node.score = score
        node.rationale = rationale
        node.terminal = terminal

        # BACKPROPAGATE
        cur = node
        while cur:
            cur.visits += 1
            cur.value += score
            cur = cur.parent

        trace.append(
            {
                "iter": it,
                "depth": node.depth,
                "score": round(score, 3),
                "action": (node.action or "")[:80],
            }
        )

        if score > best_score:
            best_score = score
            best_node = node

        # STOP : threshold reached or terminal
        if best_score >= threshold or terminal:
            logger.info(f"LATS stop iter {it} (score={best_score:.2f}, terminal={terminal})")
            break

        # REFLECT after 3 iter stagnation
        if it >= 3 and len(trace) >= 3:
            recent = [t["score"] for t in trace[-3:]]
            if max(recent) < threshold * 0.7:
                failed = [c.to_path() for c in root.children if c.children]
                reflection = _reflect_and_backtrack(problem, failed[:3])
                if reflection:
                    hint = MCTSNode(
                        action=f"[REFLECT] {reflection[:200]}",
                        rationale="backtracking hint",
                        parent=root,
                        depth=1,
                    )
                    root.children.append(hint)
                    n_backtracks += 1

    return {
        "best_plan": best_node.to_path(),
        "best_score": round(best_score, 3),
        "n_iterations": len(trace),
        "n_backtracks": n_backtracks,
        "trace": trace,
        "rationale": best_node.rationale,
    }


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: forge_lats_general.py <problem>")
        return
    result = lats_solve(sys.argv[1], budget=8)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
