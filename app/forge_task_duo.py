#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_task_duo.py — DUO planificateur + décomposeur : organise une roadmap en VAGUES
PARALLÈLES testables, avant de chaîner les exécuteurs.

Directive user : paralléliser au max + warm (réutiliser l'existant) + PLANIFIER & TESTER
chaque workflow d'une todolist décomposée AVANT d'actionner. En duo du planificateur, un
décomposeur qui découpe bien.

LE DUO (compose l'existant, anti-dup) :
  - DÉCOMPOSEUR : forge_goap.GoalPlanner.plan / decompose_goal (GOAP, subgoals+parallel) pour
    les buts NOUVEAUX ; décomposition DÉTERMINISTE curée pour les tâches CONNUES (rapide, 0 halluc).
  - PLANIFICATEUR : forge_orchestration_gate.classify/plan_route (VOIE par sous-tâche).
  - ORDONNANCEUR (ce module) : tri topologique par deps -> VAGUES parallèles ; warm-first.

Sortie = waves() : vagues de tâches concurrentes + par tâche {subtasks, deps, warm, effort,
test, lane}. Le but : voir d'un coup ce qui part EN PARALLÈLE tout de suite (warm) vs ce qui
attend (deps/reboot/auth/offline).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Les 12 tâches restantes de la roadmap, DÉCOMPOSÉES (curé = déterministe, exact).
# warm=True -> réutilise un module existant (rapide). effort XS<S<M<L<XL. deps=ids bloquants.
# gate: "" (aucun) | "reboot" | "auth" | "offline" — contrainte d'activation hors-code.
TASKS = [
    {"id": "active_inference_hotpath", "prio": "P0", "warm": True, "effort": "S", "gate": "",
     "title": "active_inference Phase 2 : record_route_outcome dans le hot-path exécuteur",
     "subtasks": ["repérer le point d'exécution (run_job/cascade fin d'action)",
                  "appeler forge_orchestration_gate.record_route_outcome(action, decision, success, elapsed)",
                  "passer la decision via le contexte d'exécution"],
     "deps": [], "kind": "file_edit",
     "test": "router une tâche kind=X 5×, vérifier get_prior(lane,X).n augmente + cortisol/dopamine émis"},
    {"id": "gate_flux_interceptor", "prio": "P1", "warm": True, "effort": "S", "gate": "",
     "title": "gate_flux intercepteur dans _tool_call (équipe flux opérante)",
     "subtasks": ["appeler forge_flow_control.gate_flux au début de _tool_call",
                  "logger la chaîne videur→convoyeur→...→facteur (observabilité)",
                  "ne PAS bloquer (advisory d'abord, enforce ensuite)"],
     "deps": [], "kind": "file_edit",
     "test": "un appel hub traverse la chaîne ; assert l'ordre videur→facteur dans le log"},
    {"id": "cortisol_throttle", "prio": "P2", "warm": True, "effort": "S", "gate": "",
     "title": "cortisol → resource_manager.should_throttle (efferent végétatif)",
     "subtasks": ["forge_resource_manager.should_throttle lit forge_endocrine.read(CORTISOL_*)",
                  "seuil cortisol>=0.8 -> throttle True (ralentit spawns avant OOM)",
                  "garde : ne jamais throttle le ring0"],
     "deps": [], "kind": "file_edit",
     "test": "release CORTISOL_FRUSTRATION=0.9 -> should_throttle()==True ; 0.1 -> False"},
    {"id": "coagulation_armed", "prio": "P2", "warm": True, "effort": "XS", "gate": "auth",
     "title": "coagulation --armed (heals bornés actifs)",
     "subtasks": ["lancer forge_coagulation --armed (autorisation user)",
                  "forge_remediation AGIT (embed/orphans/stale) au lieu de dry-run"],
     "deps": [], "kind": "shell_trivial",
     "test": "remediation.armed=true ; vérifier les dettes traitées (orphans=0, embed drainé)"},
    {"id": "regeneration_loop", "prio": "P1", "warm": True, "effort": "M", "gate": "",
     "title": "Régénération (gap) : memory(gaps/lessons) → evolution/tool_forger → quality_gate",
     "subtasks": ["lire les lessons récurrentes (forge_self_correction/memory_keeper)",
                  "proposer fix/module via evolutionary_engine + forge_tool_forger",
                  "gate par forge_quality_gate avant intégration (boucle close)"],
     "deps": [], "kind": "orchestrate",
     "test": "selftest sur une lesson fixture -> une proposition passe le quality_gate"},
    {"id": "sensory_fusion", "prio": "P2", "warm": True, "effort": "M", "gate": "",
     "title": "Sens multimodaux : fusion ui_oracle/video/android/crawl sous 1 contrat OrganAgent",
     "subtasks": ["déclarer un contrat sensoriel commun (modalities text/vision/audio)",
                  "fédérer les 4 sources sous forge_flow_control / portier",
                  "router une requête multimodale -> bon sens"],
     "deps": [], "kind": "orchestrate",
     "test": "contract selftest : 4 sens enregistrés, route(image)->vision"},
    {"id": "videur_phase2", "prio": "P0", "warm": True, "effort": "S", "gate": "reboot",
     "title": "videur Phase 2 : _resolve_ring passe par forge_videur.resolve_identity",
     "subtasks": ["câbler nokido_hub._resolve_ring -> forge_videur.resolve_identity (déjà édité)",
                  "valider selftest videur", "REBOOT lanceur pour activer"],
     "deps": [], "kind": "file_edit",
     "test": "post-reboot : un agent ring-1 résout ring 1 (plus le bug ring-4 fantôme)"},
    {"id": "rag_trust_ring", "prio": "P2", "warm": False, "effort": "L", "gate": "",
     "title": "Gouvernance épistémique RAG : trust-ring sur données + 3 cercles + gate min-trust",
     "subtasks": ["enveloppe unifiée (trust_ring/verification/provenance/authenticity/circle)",
                  "gate min-trust à la récupération (séparé du scoring RRF)",
                  "politiques par cercle (référence/définition/équivalence)"],
     "deps": [], "kind": "orchestrate",
     "test": "ingest chunk trust=R4 -> exclu d'une récup min-trust=R2"},
    {"id": "cognition_1024d", "prio": "P2", "warm": False, "effort": "XL", "gate": "offline",
     "title": "Cognition 1024D/4096D : réentraîner (unifie avec RAG BGE-M3)",
     "subtasks": ["collecteur traces -> dataset", "retrain @1024D", "A/B vs 384D", "cutover"],
     "deps": [], "kind": "batch",
     "test": "A/B : cos@1024 >= baseline ; selftest flip dim"},
    {"id": "multi_machine", "prio": "P2", "warm": False, "effort": "L", "gate": "",
     "title": "Multi-machine : Tailscale + P2P silo + pool LLM distant (LM Link)",
     "subtasks": ["Tailscale réseau souverain", "sync P2P silo", "pool LLM distant via LM Link"],
     "deps": [], "kind": "orchestrate",
     "test": "cross-machine : ask distant répond ; silo sync 2 nœuds"},
]

_EFFORT = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}


def _lane(task: dict) -> str:
    """PLANIFICATEUR : la VOIE de la tâche (forge_orchestration_gate.classify)."""
    try:
        from nokido_agent.app.forge_orchestration_gate import classify, Action
        steps = len(task.get("subtasks", [])) or 1
        d = classify(Action(kind=task.get("kind", "llm"), est_steps=steps))
        return d.lane
    except Exception:  # noqa: BLE001
        return "?"


def waves(tasks: list | None = None) -> dict:
    """ORDONNANCEUR : groupe en VAGUES parallèles. Tri topologique par deps ; au sein d'une
    vague, warm+petit d'abord. Les tâches 'gate' (reboot/auth/offline) -> vague dédiée."""
    tasks = tasks or TASKS
    by_id = {t["id"]: t for t in tasks}
    done, result = set(), []
    # Vague(s) de CODE parallèle : pas de deps non satisfaites ET pas de gate bloquante.
    pool = [t for t in tasks if not t.get("gate")]
    gated = [t for t in tasks if t.get("gate")]
    while pool:
        ready = [t for t in pool if all(d in done for d in t.get("deps", []))]
        if not ready:
            ready = pool[:]  # cycle/garde : on débloque tout
        ready.sort(key=lambda t: (not t["warm"], _EFFORT[t["effort"]]))
        wave = [t["id"] for t in ready]
        result.append({"parallel": wave,
                       "detail": [{"id": t["id"], "warm": t["warm"], "effort": t["effort"],
                                   "lane": _lane(t)} for t in ready]})
        done |= set(wave)
        pool = [t for t in pool if t["id"] not in done]
    # Vagues gated (hors-code : reboot/auth/offline), groupées par type de gate.
    gates = {}
    for t in gated:
        gates.setdefault(t["gate"], []).append(t["id"])
    return {"code_waves": result, "gated": gates,
            "summary": {"total": len(tasks), "warm": sum(t["warm"] for t in tasks),
                        "code_parallelizable": sum(len(w["parallel"]) for w in result),
                        "gated": len(gated)}}


def organize() -> dict:
    """Plan complet : vagues + détail par tâche (subtasks + test). Le livrable à greenlighter."""
    return {"waves": waves(), "tasks": TASKS}


def decompose(goal: str) -> dict:
    """Pour un but NOUVEAU (pas dans TASKS) : délègue au décomposeur GOAP existant (compose)."""
    try:
        import asyncio
        from nokido_agent.app.forge_goap import GoalPlanner
        return {"goal": goal, "plan": str(asyncio.run(GoalPlanner.plan(goal)))[:2000]}
    except Exception as e:  # noqa: BLE001
        return {"goal": goal, "error": f"goap indispo: {e}"}


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    w = waves()
    chk(len(TASKS) == 10, f"10 tâches restantes décomposées ({len(TASKS)})")
    chk(w["summary"]["code_parallelizable"] >= 6, f"code parallélisable: {w['summary']['code_parallelizable']}")
    chk(set(w["gated"]) <= {"reboot", "auth", "offline"}, f"gates: {w['gated']}")
    chk(w["code_waves"] and w["code_waves"][0]["parallel"], f"vague 1: {w['code_waves'][0]['parallel']}")
    chk(all(t.get("test") and t.get("subtasks") for t in TASKS), "chaque tâche a subtasks + test")
    chk(all("warm" in d for d in w["code_waves"][0]["detail"]), "détail vague porte warm/effort/lane")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--decompose", help="but nouveau -> GOAP")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.decompose:
        print(json.dumps(decompose(a.decompose), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    print(json.dumps(organize(), ensure_ascii=False, indent=2))
