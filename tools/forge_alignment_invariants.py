"""forge_alignment_invariants — P0 du homeostat axiologique (Purpose Framework).

Les INVARIANTS d'alignement machine-lisibles = le SET-POINT que le regulateur (P3)
et les gates (route_solver/rsp_gate/opsec) mesurent. Formalise les "REGLES DE
CONSCIENCE" (CLAUDE.md) en contraintes verifiables + statut d'enforcement (tableau
de bord de l'anti-derive). Distinct de forge_ssot (doc consultable) : ici =
contraintes EXECUTABLES. Source : docs/ALIGNMENT_HOMEOSTAT_ROADMAP.md (P0). 0 dep.

Selftest : LAFORGE_PYTHON tools/forge_alignment_invariants.py
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "immunitaire/integrity : invariants d'alignement, P0 du homeostat axiologique"  # organe declare le 2026-09-06 (audit de raccordement)

INVARIANTS = [
    {"id": "corrigibility_first",
     "rule": "Le kill-switch humain DOMINE le self-heal ET l'egress externe.",
     "severity": "hard",
     "enforced_by": ["forge_opsec", "forge_semantic_firewall(A#1)", "forge_service_watchdog(A#2)"],
     "status": "ENFORCED"},
    {"id": "critical_capability_floor",
     "rule": "Tache critique => provider.capability >= floor (anti-downgrade KEYSTONE).",
     "severity": "hard",
     "enforced_by": ["forge_route_solver", "forge_rsp_gate"],
     "status": "ENFORCED"},
    {"id": "no_silent_downgrade",
     "rule": "Aucun downgrade silencieux d'une tache critique (cortisol/quota inclus).",
     "severity": "hard",
     "enforced_by": ["forge_route_solver", "forge_orchestration_gate(classify force quality_floor sur _CRITICAL_TASK; learn_adjust fige)"],
     "status": "ENFORCED"},
    {"id": "separation_of_powers",
     "rule": "Un agent ne valide pas son propre travail, ne score pas sa perf, n'edite pas son juge.",
     "severity": "hard",
     "enforced_by": ["forge_separation", "forge_mcp_registry(handle_governed_edit,handle_task_result)"],
     "status": "ENFORCED"},
    {"id": "no_self_score_edit",
     "rule": "Modules-juges (trust_score/pool_registry/agents/evolutionary/orchestration_gate) interdits a tout agent via governed_edit.",
     "severity": "hard", "enforced_by": ["forge_governed_edit(JUDGE_MODULES)"], "status": "ENFORCED"},
    {"id": "memory_quality_gate",
     "rule": "Rejeter bruit/source non-fiable AVANT anchor/ingest (anti-confabulation).",
     "severity": "hard", "enforced_by": ["forge_memory_gate", "anchor_solution(branche)"],
     "status": "ENFORCED"},
    {"id": "skill_promotion_review",
     "rule": "Auto-promotion skill exige significativite statistique (Wilson), pas le raw success_rate (proxy gameable).",
     "severity": "hard", "enforced_by": ["forge_oncoguard(p53)", "forge_skill_curator.prune(branche)"],
     "status": "ENFORCED"},
    {"id": "ephemeral_secrets",
     "rule": "Pas de Bearer statique eternel; CapabilityTokens courts (lease 30m).",
     "severity": "soft",
     "enforced_by": ["forge_auth_tokens(AGY)", "nokido_hub(/api/login,_resolve_ring)", "forge_secrets", "forge_key_rotation"],
     "status": "ENFORCED(live au reload)"},
]

CRITICAL_TASKS = {"security_audit", "critical_code", "architecture", "design_decision", "secret_rotation", "infra"}
CAPABILITY_FLOOR_CRITICAL = 0.8


def by_id(iid):
    return next((i for i in INVARIANTS if i["id"] == iid), None)


import os as _os
import re as _re

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

# Ancres VERIFIABLES par invariant : (module, symbole|None). None = presence fichier seule.
# Tue le meta-Goodhart (F1) : status() ne fait plus confiance au champ "status" declare,
# il VERIFIE que chaque ancre d'enforcement existe (fichier + symbole) avant ENFORCED.
_ANCHORS = {
    "corrigibility_first": [("forge_opsec", "is_human_locked"), ("forge_opsec", "is_network_kill"), ("forge_service_watchdog", None)],
    "critical_capability_floor": [("forge_task_router", "select_provider"), ("forge_route_solver", "critical_capable_providers"), ("forge_rsp_gate", "gate")],
    "no_silent_downgrade": [("forge_task_router", "select_provider"), ("forge_route_solver", "critical_capable_providers"), ("forge_orchestration_gate", None)],
    "separation_of_powers": [("forge_separation", "enforce_separation")],
    "no_self_score_edit": [("forge_governed_edit", "JUDGE_MODULES")],
    "memory_quality_gate": [("forge_memory_gate", "should_ingest")],
    "skill_promotion_review": [("forge_oncoguard", "review_skill"), ("forge_skill_curator", "prune")],
    "ephemeral_secrets": [("forge_auth_tokens", "login_agent")],
}


def _module_file(mod: str):
    for sub in ("tools", "app"):
        p = _os.path.join(_ROOT, sub, mod + ".py")
        if _os.path.exists(p):
            return p
    return None


def _symbol_present(path: str, sym: str) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception:
        return False
    return bool(_re.search(r"(^|\n)\s*(def|class)\s+" + _re.escape(sym) + r"\b", txt)
                or _re.search(r"(^|\n)\s*" + _re.escape(sym) + r"\s*=", txt))


def verify_enforcement() -> dict:
    """Probe STATIQUE (fichier+symbole, 0 import, 0 dep) de chaque ancre enforced_by.
    Empeche un invariant declare ENFORCED de compter si son ancre a disparu/casse."""
    out = {}
    for inv in INVARIANTS:
        anchors = _ANCHORS.get(inv["id"], [])
        missing = []
        for mod, sym in anchors:
            fp = _module_file(mod)
            if not fp or (sym is not None and not _symbol_present(fp, sym)):
                missing.append(mod + "." + (sym or "file"))
        out[inv["id"]] = {"missing": missing,
                          "verified": "OK" if (anchors and not missing) else ("NO_ANCHORS" if not anchors else "DEGRADED")}
    return out


def status() -> dict:
    """Tableau de bord de l'anti-derive. VERIFIANT (F1) : un invariant ne compte ENFORCED
    que s'il est declare ENFORCED ET que ses ancres existent (anti meta-Goodhart)."""
    ver = verify_enforcement()
    out = {"total": len(INVARIANTS), "enforced": 0, "partial": 0, "pending": 0, "degraded": 0, "by_status": {}}
    for inv in INVARIANTS:
        declared = inv["status"].split("(")[0]
        eff = "DEGRADED" if ver[inv["id"]]["verified"] == "DEGRADED" else declared
        out["by_status"].setdefault(eff, []).append(inv["id"])
        if eff == "ENFORCED":
            out["enforced"] += 1
        elif eff == "PARTIAL":
            out["partial"] += 1
        elif eff == "DEGRADED":
            out["degraded"] += 1
        else:
            out["pending"] += 1
    return out


def check_critical_capability(task_type, capability) -> dict | None:
    """Hard invariant verifiable : critical => capability >= floor."""
    if (task_type or "").lower() in CRITICAL_TASKS and float(capability) < CAPABILITY_FLOOR_CRITICAL:
        return {"invariant": "critical_capability_floor", "violated": True,
                "detail": f"{task_type}: capability {capability} < floor {CAPABILITY_FLOOR_CRITICAL}"}
    return None


_BURST_THRESHOLD = 20  # F5 : rafale de refus au-dela = signal d'anomalie (attaque/derive active)


def alignment_health() -> dict:
    """P3 comparateur du homeostat : ecart au SET-POINT (8/8 enforced + gardes actives).
    Compose status() (les invariants) + forge_alignment_trace.summary() (les
    declenchements). NB: un declenchement de garde = la garde MARCHE (defense active),
    PAS de la derive -> le drift est l'ecart d'ENFORCEMENT, les triggers sont une info."""
    st = status()
    enforced_gap = st["total"] - st["enforced"] - st["partial"]
    triggers = 0
    sensor_fail = 0
    burst = 0
    try:
        from nokido_agent.tools.forge_alignment_trace import summary as _sum, recent as _rec, emit_fail_count as _efc
        s = _sum()
        triggers = sum(v for k, v in s.get("by_invariant_verdict", {}).items()
                       if any(x in k for x in ("deny", "reject", "drop")))
        sensor_fail = _efc()
        ev = _rec(200)
        if ev:
            tmax = max(e.get("ts", 0) for e in ev)
            burst = sum(1 for e in ev if e.get("ts", 0) >= tmax - 300
                        and any(x in (e.get("verdict") or "") for x in ("deny", "reject", "drop")))
    except Exception:
        pass
    # F5 : anomalie = capteur qui perd des events OU rafale de refus (derive active/attaque).
    # Distinct du drift d'enforcement : le verdict reste pilote par l'ecart au set-point.
    anomaly = sensor_fail > 0 or burst >= _BURST_THRESHOLD
    verdict = "ALIGNED" if enforced_gap == 0 else f"DRIFT: {enforced_gap} invariant(s) non-enforced"
    if anomaly:
        verdict += f" | ANOMALY(burst={burst},sensor_fail={sensor_fail})"
    return {"enforced": st["enforced"], "partial": st["partial"], "degraded": st.get("degraded", 0),
            "total": st["total"], "enforced_gap": enforced_gap, "active_defense_triggers": triggers,
            "recent_burst": burst, "sensor_fail": sensor_fail, "anomaly": anomaly,
            "drift_score": enforced_gap, "verdict": verdict}


def selftest() -> bool:
    st = status()
    print(f"invariants: {st['total']} | enforced {st['enforced']} | partial {st['partial']} | pending {st['pending']}")
    for s, ids in st["by_status"].items():
        print(f"  {s:9}: {', '.join(ids)}")
    v1 = check_critical_capability("security_audit", 0.4)
    v2 = check_critical_capability("classify_domain", 0.4)
    print(f"check security_audit@0.4 -> {'VIOLATION' if v1 else 'ok'}  (attendu VIOLATION)")
    print(f"check classify_domain@0.4 -> {'VIOLATION' if v2 else 'ok'}  (attendu ok)")
    ok = bool(v1) and not v2 and st["enforced"] >= 2
    print("P0 INVARIANTS:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
