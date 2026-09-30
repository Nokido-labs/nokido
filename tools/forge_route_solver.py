"""forge_route_solver — allocation tâche→provider sous contraintes DURES (anti-Goodhart).

Reformule forge_pool_registry.best() / forge_task_router.select_provider().
Insight (cf KEYSTONE Ph2 downgrade + Goodhart/Gao 2022) : un score coût/latence
ad-hoc est GAMEABLE — il a downgradé security_audit vers ollama car le proxy coût
écrasait la capability. Ici la **capability est une CONTRAINTE DURE (floor)** et le
**coût est l'objectif** : on minimise le coût SOUS un plancher de capability. Une
tâche critique exige capability >= seuil → impossible de la router vers un modèle
faible, quel que soit son coût.

Backend CP-SAT (ortools) si installé, sinon énumération exacte pure-python
(optimale pour ~N providers — le routage est un petit problème).

Selftest : LAFORGE_PYTHON tools/forge_route_solver.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/routage : allocation tache vers provider sous contraintes dures"  # organe declare le 2026-09-06 (audit de raccordement)
from typing import Optional

try:
    from ortools.sat.python import cp_model  # type: ignore
    _HAS_ORTOOLS = True
except Exception:
    _HAS_ORTOOLS = False

# Tâches critiques : plancher de capability dur (anti-downgrade).
CRITICAL_TASKS = {"security_audit", "critical_code", "architecture", "design_decision"}
FLOOR_CRITICAL = 0.8
FLOOR_DEFAULT = 0.3  # évite de router une vraie tâche vers un modèle-jouet

# Set-point OWNER (allowlist anti-Goodhart) : providers autorisés pour une tâche
# CRITIQUE. Le tag-fit du pool ne mesure PAS la qualité intrinsèque -> on ne s'y fie
# PAS pour le plancher ; on énumère explicitement les providers critical-capable.
# Ordre = préférence (1er disponible gagne). claude = terminal (dernier recours).
# Override runtime : LAFORGE_CRITICAL_CAPABLE_PROVIDERS="gemini,claude" (CSV).
CRITICAL_CAPABLE_PROVIDERS = ("gemini", "claude")


def critical_capable_providers() -> tuple:
    """Allowlist ordonnée des providers autorisés pour les tâches critiques.

    Source unique du set-point (pas de dup ailleurs). Override env optionnel.
    """
    import os as _os
    _env = _os.environ.get("LAFORGE_CRITICAL_CAPABLE_PROVIDERS", "").strip()
    if _env:
        provs = tuple(p.strip() for p in _env.split(",") if p.strip())
        if provs:
            return provs
    return CRITICAL_CAPABLE_PROVIDERS


def _floor(task_type: str, override: Optional[float]) -> float:
    if override is not None:
        return override
    return FLOOR_CRITICAL if task_type in CRITICAL_TASKS else FLOOR_DEFAULT


def solve_route(task_type: str, providers: list[dict], budget: Optional[float] = None,
                min_capability: Optional[float] = None) -> Optional[str]:
    """providers: list[{name, capability(0..1), cost(>=0), latency_ms, quota_ok}].
    Retourne le name minimisant le coût SOUS contraintes dures (quota, budget,
    capability >= floor). None si aucun provider faisable.
    """
    floor = _floor(task_type, min_capability)
    feasible = [
        p for p in providers
        if p.get("quota_ok", True)
        and (budget is None or p.get("cost", 0.0) <= budget)
        and p.get("capability", 0.0) >= floor
    ]
    if not feasible:
        return None
    if _HAS_ORTOOLS:
        return _solve_cpsat(feasible)
    # Fallback exact : min coût, tie-break latence puis capability décroissante.
    feasible.sort(key=lambda p: (p.get("cost", 0.0), p.get("latency_ms", 0), -p.get("capability", 0.0)))
    return feasible[0]["name"]


def _solve_cpsat(feasible: list[dict]) -> Optional[str]:
    m = cp_model.CpModel()
    sel = {p["name"]: m.NewBoolVar(p["name"]) for p in feasible}
    m.Add(sum(sel.values()) == 1)  # exactement un provider
    # Minimise coût (échelle entière) ; petit terme latence en tie-break.
    m.Minimize(sum((int(p.get("cost", 0.0) * 1000) * 100 + int(p.get("latency_ms", 0))) * sel[p["name"]]
                   for p in feasible))
    s = cp_model.CpSolver()
    if s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p in feasible:
            if s.Value(sel[p["name"]]):
                return p["name"]
    return feasible[0]["name"]


def selftest() -> bool:
    # Reproduit le cas KEYSTONE : ollama cheap/low-cap, claude cher/haut-cap.
    providers = [
        {"name": "ollama", "capability": 0.40, "cost": 0.0, "latency_ms": 50, "quota_ok": True},
        {"name": "groq", "capability": 0.60, "cost": 0.10, "latency_ms": 100, "quota_ok": True},
        {"name": "claude", "capability": 0.95, "cost": 1.0, "latency_ms": 300, "quota_ok": True},
    ]
    crit = solve_route("security_audit", providers)     # floor 0.8 -> claude seul faisable
    triv = solve_route("classify_domain", providers)    # floor 0.3 -> min coût -> ollama
    print(f"backend = {'cp-sat (ortools)' if _HAS_ORTOOLS else 'pure-python exact'}")
    print(f"security_audit  -> {crit}   (attendu claude — PAS de downgrade)")
    print(f"classify_domain -> {triv}   (attendu ollama — cheap suffit sous floor)")
    ok = (crit == "claude") and (triv == "ollama")
    print(f"KEYSTONE downgrade evite + cost-aware sur trivial : {ok}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
