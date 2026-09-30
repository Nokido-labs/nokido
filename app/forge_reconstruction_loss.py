"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-05 | VER:v1_reconstruction_loss
#FORGE:[score:90|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]

forge_reconstruction_loss.py — Validation de fidélité de reconstruction SAE-like.

Mesure l'écart entre tool_calls produits (LLM) et ground truth (golden_dataset).
Signal RETRY_WITH_EXPANSION si Jaccard < seuil → forge_extern_patterns re-extrait
avec granularité DEEP_AST (décorateurs, types de retour, exemples).

Organe : Cervelet Python (validation sensorielle de l'action reconstruite)
Vascularisation : forge_goap.execute_plan → dispatch_fn → ici → forge_extern_patterns
Scénario hémorragie : NO_GOLDEN guard évite retry infini si golden vide
Pourquoi ce module : forge_novelty_organ fait MSE sur anomaly detection (séries temporelles),
                     pas Jaccard sur tool_calls. Domaines orthogonaux.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:90|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]"
)

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("Nokido.ReconstructionLoss")

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "sandbox" / "promptfoo_clinical" / "golden_dataset.yaml"

JACCARD_THRESHOLD = 0.85
EXPANDED_BUDGET_MB = 5.0


def calculate_jaccard(produced: list[dict], golden: list[dict]) -> float:
    """Jaccard entre deux sets de tool_calls. 1.0 = reconstruction parfaite."""

    def _flatten(calls: list[dict]) -> set[str]:
        return {
            f"{c.get('name', c.get('method', '?'))}:{sorted(c.get('arguments', c.get('params', {})).keys())}"
            for c in calls
        }

    set_p = _flatten(produced)
    set_g = _flatten(golden)
    union = len(set_p | set_g)
    return len(set_p & set_g) / union if union else 0.0


def load_golden_tools(task_id: str) -> list[dict]:
    """Charge expected_tools depuis golden_dataset.yaml pour un task_id donné.

    Returns [] si absent → le caller doit retourner NO_GOLDEN (pas de retry).
    """
    if not GOLDEN_PATH.exists():
        return []
    try:
        import yaml

        data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8")) or []
        for entry in data:
            eid = entry.get("id", "")
            edesc = entry.get("description", "")
            if eid == task_id or edesc == task_id or edesc.startswith(task_id):
                tools = entry.get("expected_tools", [])
                if tools:
                    return tools
    except Exception as e:
        logger.debug(f"load_golden_tools({task_id}): {e}")
    return []


def validate_and_adapt(
    task_id: str,
    produced_payload: dict[str, Any],
    feature_budget_mb: float = 2.5,
) -> dict[str, Any]:
    """Calcule la perte de reconstruction et émet le signal d'adaptation.

    Returns:
        {"status": "SUCCESS", "score": float}
        {"status": "RETRY_WITH_EXPANSION", "score": float,
         "new_feature_budget_mb": float, "granularity": "DEEP_AST"}
        {"status": "NO_GOLDEN", "score": None}
    """
    golden = load_golden_tools(task_id)
    if not golden:
        logger.debug(f"[ReconLoss] task={task_id}: NO_GOLDEN — skip retry")
        return {"status": "NO_GOLDEN", "score": None}

    produced = produced_payload.get("tool_calls", [])
    score = calculate_jaccard(produced, golden)
    logger.info(f"[ReconLoss] task={task_id} jaccard={score:.3f} threshold={JACCARD_THRESHOLD}")

    if score < JACCARD_THRESHOLD:
        logger.warning(
            f"[ReconLoss] Fidelity low ({score:.2f} < {JACCARD_THRESHOLD}) "
            f"→ RETRY_WITH_EXPANSION (budget {feature_budget_mb}→{EXPANDED_BUDGET_MB}MB)"
        )
        return {
            "status": "RETRY_WITH_EXPANSION",
            "score": score,
            "new_feature_budget_mb": EXPANDED_BUDGET_MB,
            "granularity": "DEEP_AST",
        }

    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"Reconstruction fidelity check: {task_id}",
            solution=f"Jaccard {score:.3f} >= {JACCARD_THRESHOLD} — sparse encoding faithful",
            example=f"produced={len(produced)} tools | golden={len(golden)} tools",
            domain="reconstruction",
        )
    except Exception:
        pass

    return {"status": "SUCCESS", "score": score}
