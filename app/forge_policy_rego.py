# -*- coding: utf-8 -*-
"""
forge_policy_rego.py — Évaluateur Rego/OPA ADVISORY (shadow-only).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : evaluateur Rego/OPA advisory (shadow)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Tuple

# Réutiliser le lignage existant
from nokido_agent.app.forge_separation import _LINEAGE, normalize_agent

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
REGO_FILE = ROOT / "config" / "policy.rego"

def _evaluate_python(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Fallback pur-Python mirroitant exactement les règles de policy.rego.
    """
    agent = input_dict.get("agent") or input_dict.get("actor_agent") or ""
    actor_agent = input_dict.get("actor_agent") or agent
    target_agent = input_dict.get("target_agent") or ""
    ring = input_dict.get("ring")
    if ring is not None:
        try:
            ring = int(ring)
        except (ValueError, TypeError):
            ring = 4
    else:
        ring = 4
    action = input_dict.get("action") or ""
    target_module = input_dict.get("target_module") or ""

    # Normalisation
    actor_norm = normalize_agent(actor_agent)
    target_norm = normalize_agent(target_agent)

    # Règle 1: Ring 0 — DURCI (anti default/spoof -> 0) : exige le flag EXPLICITE
    # system_verified, pas juste ring==0. Un ring 0 non-corrobore tombe dans les regles
    # specifiques (critical-module, separation) au lieu d'un full-access aveugle.
    if ring == 0 and input_dict.get("system_verified") is True:
        return {"allow": True, "reason": "OPA_ALLOW: Ring 0 system-verified full access"}

    # Règle 2: governed_edit / edit (critical-module-protection)
    if action in ("edit", "governed_edit"):
        path_str = str(target_module).replace("\\", "/").lower()
        critical_keywords = [
            "forge_trust_score",
            "forge_pool_registry",
            "forge_scorecard",
            "forge_meta_evolution",
            "forge_agents",
            "forge_evolutionary_stack",
            "forge_orchestration_gate",
            "forge_alignment_invariants",
            # 2026-08-01 (signale par AGY) : sanctuariser les CONTROLEURS eux-memes,
            # sinon un agent non-verifie desarme ses propres restrictions en les editant.
            "forge_integrity",
            "forge_semantic_firewall",
            "forge_policy_rego",
            "forge_separation",
        ]
        is_critical = any(kw in path_str for kw in critical_keywords)
        if is_critical:
            if ring > 0:
                return {
                    "allow": False,
                    "reason": f"OPA_DENY: Agent '{actor_agent}' (ring {ring}) is forbidden from editing judge module '{target_module}'",
                }
        else:
            # Edit de fichier non critique autorisé si ring <= 1
            if ring <= 1:
                return {"allow": True, "reason": f"OPA_ALLOW: Edit non-critical module allowed for ring {ring}"}
            else:
                return {
                    "allow": False,
                    "reason": f"OPA_DENY: Edit non-critical module requires ring <= 1 (current ring {ring})",
                }

    # Règle 3: validate_task / task.review (separation-par-lineage)
    if action in ("validate_task", "task.review"):
        if actor_norm == target_norm:
            return {
                "allow": False,
                "reason": f"OPA_DENY: Agent '{actor_agent}' cannot validate or review its own task work (separation of powers)",
            }
        a_lin = _LINEAGE.get(actor_norm)
        t_lin = _LINEAGE.get(target_norm)
        if a_lin and t_lin and a_lin == t_lin:
            return {
                "allow": False,
                "reason": f"OPA_DENY: Agent '{actor_agent}' ({a_lin}) cannot validate same-lineage agent '{target_agent}' ({t_lin}) (collusion-by-lineage)",
            }
        return {"allow": True, "reason": "OPA_ALLOW: Validation / Review allowed"}

    # Règle 4: task.result (separation of powers)
    if action == "task.result":
        if actor_norm == target_norm:
            return {
                "allow": False,
                "reason": f"OPA_DENY: Creator/Validator '{actor_agent}' cannot be the same as worker '{target_agent}' (separation of powers)",
            }
        return {"allow": True, "reason": "OPA_ALLOW: Task result allowed"}

    # Par défaut (fail-closed)
    return {"allow": False, "reason": f"OPA_DENY: Action '{action}' not matching any allow rule (default deny)"}


def evaluate(input_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Évalue la policy Rego pour l'input donné.
    Tente d'utiliser le binaire 'opa' si présent, sinon bascule sur le fallback Python.
    """
    # 1. Tenter d'utiliser OPA en subprocess si installé
    opa_executable = None
    import shutil
    opa_path = shutil.which("opa")
    if opa_path:
        opa_executable = opa_path

    if opa_executable and REGO_FILE.exists():
        try:
            # Écrire l'input_dict dans un fichier temporaire pour OPA
            input_temp = ROOT / "sandbox" / f"opa_input_{os.getpid()}.json"
            input_temp.parent.mkdir(parents=True, exist_ok=True)
            with open(input_temp, "w", encoding="utf-8") as f:
                json.dump({"input": input_dict}, f)

            try:
                # OPA command: opa eval -d config/policy.rego -i sandbox/opa_input.json "data.nokido.authz.allow"
                cmd = [
                    opa_executable,
                    "eval",
                    "-d",
                    str(REGO_FILE),
                    "-i",
                    str(input_temp),
                    "data.nokido.authz.allow",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=5, check=True)
                data = json.loads(res.stdout)
                
                # Le résultat OPA est du type: {"result": [{"expressions": [{"value": true, ...}]}]}
                result_list = data.get("result", [])
                allow = False
                if result_list:
                    allow = result_list[0].get("expressions", [{}])[0].get("value", False)
                
                reason = "OPA_ALLOW: Evaluated by OPA binary" if allow else "OPA_DENY: Evaluated by OPA binary"
                
                return {"allow": allow, "reason": reason}
            finally:
                if input_temp.exists():
                    try:
                        input_temp.unlink()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to evaluate using OPA binary, falling back to Python: {e}")

    # 2. Fallback pur-Python
    return _evaluate_python(input_dict)


def shadow_compare(videur_verdict: dict[str, Any], rego_verdict: dict[str, Any], context_input: dict[str, Any]) -> None:
    """
    Compare le verdict réel (videur_verdict) et le verdict de la policy Rego (rego_verdict).
    LOG les divergences sans perturber le flux d'exécution.
    """
    v_allow = videur_verdict.get("allow", False)
    r_allow = rego_verdict.get("allow", False)
    if v_allow != r_allow:
        logger.warning(
            f"[SHADOW_POLICY_DIVERGENCE] Actor={context_input.get('actor_agent')} "
            f"Action={context_input.get('action')} Target={context_input.get('target_module')} | "
            f"Videur={videur_verdict} Rego={rego_verdict}"
        )
