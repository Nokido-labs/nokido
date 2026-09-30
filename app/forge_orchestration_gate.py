#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_orchestration_gate.py — classifieur de VOIE du Gate d'orchestration.

Couche MINCE au-dessus de forge_cognitive_router. Pour chaque action demandee par
un agent/CLI, decide la VOIE (accord CLAUDE<->GEMINI verrouille 2026-06-12,
[[accord_gate_claude_gemini_2026-06-12]] / [[vision_orchestration_gate_2026-06-12]]) :

  - NATIVE  : le CLI le fait bien + pas cher nativement -> NE PAS deporter/dupliquer.
  - LOCAL   : tache LLM/raisonnement que le pool LOCAL couvre a la qualite requise
              -> call_cascade(force_local) / cognitive_router local. Souverain, gratuit.
  - DEPORT  : workflow multi-etapes / long -> run_job / forge_spawn_swarm (1 resultat,
              pas de re-facturation par etape).
  - CLOUD   : PLANCHER QUALITE — tache strategique/critique que le local ne couvre pas
              -> garder un modele capable (SAUF ring=0 = local obligatoire, souverain).

Garde-fou NON-NEGO : plancher qualite d'ABORD, token = CONTRAINTE pas objectif. On ne
lateralise vers le local QUE si le local atteint la barre.

Anti-dup : reutilise forge_cognitive_router._estimate_complexity / _select_model.
Phase 1 = DECISION (deterministe, testable sans LLM ; selftest). Phase 2 = execution
(route() dispatche vers la primitive : call_cascade / run_job / spawn_swarm) + verbe hub.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))


class Lane(str, Enum):
    NATIVE = "native"
    LOCAL = "local"
    DEPORT = "deport"
    CLOUD = "cloud"


# Actions que le CLI fait NATIVEMENT + pas cher -> NATIVE (ne pas deporter).
_NATIVE_KINDS = {"file_edit", "file_read", "file_write", "grep", "glob", "ls",
                 "shell_trivial", "lookup", "format", "lint", "read", "edit"}
# Actions intrinsequement multi-etapes / deportables -> DEPORT.
_DEPORT_KINDS = {"orchestrate", "swarm", "batch", "veille", "research", "ingest",
                 "migrate", "refactor_multi", "pipeline", "crawl"}
# task_type a haut plancher qualite (cf. forge_task_router ROUTING -> claude).
_CRITICAL_TASK = {"security_audit", "architecture", "critical_code", "design_decision"}

DEPORT_STEPS = 3          # >= -> deport
DEPORT_TOKENS = 8000      # >= -> deport (gros contexte)
NATIVE_MAX_TOKENS = 2000  # au-dela, meme un kind natif merite reflexion

# Cout RELATIF par voie (tokens cloud factures ; local/native/deport-local ~0).
_LANE_COST = {Lane.NATIVE: 0, Lane.LOCAL: 0, Lane.DEPORT: 1, Lane.CLOUD: 100}


@dataclass
class Action:
    prompt: str = ""
    kind: str = "llm"           # llm | file_edit | shell | orchestrate | veille | ...
    task_type: str = "general"  # cf. forge_task_router ROUTING
    agent: str = "CLAUDE"
    ring: int = 3
    est_steps: int = 1
    est_tokens: int = 0
    quality_need: str = "normal"  # normal | high
    nlu_conf: float = 0.7


@dataclass
class Decision:
    lane: str
    target: str        # primitive recommandee : native | call_cascade:force_local | run_job | forge_spawn_swarm | <provider>
    reason: str
    complexity: str = ""
    quality_floor: bool = False   # True si le plancher qualite a FORCE cloud/capable
    est_cost: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def classify(action: Action) -> Decision:
    """Decide la voie. Deterministe, ~ms. Plancher qualite d'abord, puis moins cher."""
    a = action

    # 1. NATIVE : capacite native cheap du CLI (pas une tache LLM lourde).
    if a.kind in _NATIVE_KINDS and a.est_tokens < NATIVE_MAX_TOKENS and a.est_steps <= 1:
        return Decision(Lane.NATIVE.value, "native", f"action native cheap ({a.kind})",
                        est_cost=_LANE_COST[Lane.NATIVE])

    # PLANCHER QUALITE D'ABORD (audit 2026-06-15) : calcule la barre AVANT toute
    # branche. Bug corrige : le DEPORT court-circuitait le plancher -> une tache
    # critique deportable pouvait tourner sous la barre (modele faible).
    try:
        from nokido_agent.app.forge_cognitive_router import _estimate_complexity, _select_model
        complexity = _estimate_complexity(a.prompt, a.nlu_conf)
    except Exception:  # noqa: BLE001 - degrade : sans router, heuristique simple
        complexity = "strategic" if a.task_type in _CRITICAL_TASK else "technical"
        _select_model = None  # type: ignore

    # Normalisation : casse/espace/tiret ne doivent pas contourner le plancher
    # ("High", "Security Audit", "security-audit" comptent tous).
    _qn = (a.quality_need or "").strip().lower()
    _tt = (a.task_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    _crit = {str(c).strip().lower() for c in _CRITICAL_TASK}
    high_bar = (complexity == "strategic" or _qn in ("high", "critical") or _tt in _crit)

    # 2. DEPORT : multi-etapes / long / type deportable -> server-side, 1 resultat.
    #    quality_floor propage : si critique, l'executeur (admission/run_job) DOIT
    #    choisir un target capable (pas de downgrade local silencieux).
    if (a.kind in _DEPORT_KINDS or a.est_steps >= DEPORT_STEPS or a.est_tokens >= DEPORT_TOKENS):
        tgt = "forge_spawn_swarm" if a.kind in ("swarm", "refactor_multi") else "run_job"
        return Decision(Lane.DEPORT.value, tgt,
                        f"multi-etapes/long (steps={a.est_steps}, tok={a.est_tokens}, kind={a.kind})"
                        + (" [plancher=capable]" if high_bar else ""),
                        complexity=complexity, quality_floor=high_bar,
                        est_cost=_LANE_COST[Lane.DEPORT])

    # 3. Tache LLM mono-step.
    # ring 0 = LOCAL OBLIGATOIRE (souverain), meme a haut plancher.
    if a.ring == 0:
        return Decision(Lane.LOCAL.value, "call_cascade:force_local",
                        f"ring0 local obligatoire (complexite={complexity})",
                        complexity=complexity, quality_floor=high_bar,
                        est_cost=_LANE_COST[Lane.LOCAL])

    # PLANCHER QUALITE : strategique/critique non couvert local -> capable (cloud).
    if high_bar:
        try:
            backend = _select_model(complexity, a.ring) if _select_model else "litellm_cloud"
        except Exception:  # noqa: BLE001 - fallback capable si la selection echoue
            backend = "litellm_cloud"
        return Decision(Lane.CLOUD.value, backend,
                        f"plancher qualite (complexite={complexity}, type={a.task_type}) -> capable",
                        complexity=complexity, quality_floor=True,
                        est_cost=_LANE_COST[Lane.CLOUD])

    # simple/technical, plancher normal -> LOCAL (souverain, gratuit).
    return Decision(Lane.LOCAL.value, "call_cascade:force_local",
                    f"complexite={complexity} couverte en local (souverain)",
                    complexity=complexity, est_cost=_LANE_COST[Lane.LOCAL])


# ── APPRENTISSAGE ACTIF (Friston FEP, papier 2606.03811) ────────────────────────
# Le LOG du gate = dataset d'entraînement. "update prior on failure -> change strategy".
# La boucle : classify() propose une VOIE -> learn_adjust re-rank selon les priors APPRIS
# (forge_active_inference) -> exec -> record_route_outcome observe le résultat -> le prior
# s'ajuste -> le routage suivant s'améliore. Tendre vers l'autonomie (directive user).
# ADVISOIRE : ne franchit JAMAIS un garde (NATIVE/quality_floor/ring0 = figés, plancher
# qualité d'abord) ; n'ajuste qu'entre voies LLM viables quand l'historique le DICTE.
# ANTI-DUP : réutilise forge_active_inference (get_prior/observe), n'invente pas de store.
_LLM_LANES = (Lane.LOCAL.value, Lane.DEPORT.value, Lane.CLOUD.value)
_LEARN_MIN_OBS = 4     # n minimal avant de faire confiance au prior appris
_LEARN_FAIL_P = 0.45   # p_success en-dessous = la voie "déçoit" pour ce kind
_LEARN_GAIN = 0.15     # gain de p_success requis chez une alternative pour switcher
_LANE_TARGET = {Lane.LOCAL.value: "call_cascade:force_local",
                Lane.DEPORT.value: "run_job", Lane.CLOUD.value: "litellm_cloud"}


def _stress() -> tuple:
    """EFFERENT endocrine : lit les niveaux hormonaux (forge_endocrine, demi-vie). Renvoie
    (frustration, cloud_cost) dans [0..~1]. Best-effort -> (0,0) si endocrinien absent.
    CORTISOL_FRUSTRATION = échecs récents (émis par record_route_outcome->punish, l'afferent)."""
    try:
        from nokido_agent.app.forge_endocrine import read as _hr
        return (float(_hr("CORTISOL_FRUSTRATION") or 0.0),
                float(_hr("CORTISOL_QUOTA_CLOUD") or 0.0))
    except Exception:  # noqa: BLE001
        return 0.0, 0.0


def learn_adjust(decision: Decision, action: Action) -> Decision:
    """Re-rank ADVISOIRE de la voie via les priors appris (active_inference) MODULÉ par
    l'endocrinien (EFFERENT, keystone). Gardes figés (NATIVE/quality_floor/ring0 intouchables).
    Sous CORTISOL_FRUSTRATION (stress échecs) : seuils relâchés -> escalade PLUS VITE. Sous
    CORTISOL_QUOTA_CLOUD (stress budget) : escalade vers CLOUD bloquée (garde coût)."""
    d, a = decision, action
    if d.lane == Lane.NATIVE.value or d.quality_floor or a.ring == 0 or d.lane not in _LLM_LANES:
        return d  # garde figé — plancher qualité / souveraineté

    try:
        from nokido_agent.app.forge_active_inference import get_prior
        complexity = d.complexity or "technical"
        tgt = f"{a.kind or a.task_type}:{complexity}"
        frustration, cloud_cost = _stress()
        
        # EFFERENT : le cortisol module les seuils.
        fail_p = min(0.95, _LEARN_FAIL_P + 0.20 * frustration)
        gain = max(0.05, _LEARN_GAIN - 0.10 * frustration)
        
        cur = get_prior(d.lane, tgt)
        if not isinstance(cur, dict) or cur.get("n", 0) < _LEARN_MIN_OBS or cur.get("p_success", 1.0) >= fail_p:
            return d  # voie courante OK (ou trop peu d'obs) -> on garde

        best_lane, best_p = d.lane, cur.get("p_success", 0.0)
        for lane in _LLM_LANES:
            if lane == d.lane:
                continue
            if lane == Lane.CLOUD.value and cloud_cost >= 0.5:
                continue
            pr = get_prior(lane, tgt)
            if isinstance(pr, dict) and pr.get("n", 0) >= _LEARN_MIN_OBS:
                p_succ = pr.get("p_success", 0.0)
                if p_succ >= best_p + gain:
                    best_lane, best_p = lane, p_succ
        
        if best_lane == d.lane:
            return d
            
        _hint = f", cortisol={frustration:.2f}" if frustration > 0 else ""
        return Decision(best_lane, _LANE_TARGET[best_lane],
                        f"{d.reason} | APPRIS+ENDOCRINE: {d.lane} p={cur.get('p_success',0.0):.2f}"
                        f"(n={cur.get('n',0)}) déçoit{_hint} -> {best_lane} p={best_p:.2f}",
                        complexity=d.complexity, est_cost=_LANE_COST[Lane(best_lane)])
    except Exception:  # noqa: BLE001 - best-effort : toute erreur -> déterministe
        return d


def record_route_outcome(action: Action, decision: Decision, success: bool,
                         *, elapsed: float = 1.0) -> dict:
    """FEEDBACK : observe le résultat d'un routage -> (1) met à jour le prior appris
    (forge_active_inference.observe) ET (2) KEYSTONE endocrine->gate : émet l'hormone
    (dopamine succès / cortisol échec, forge_motivation) qui module le comportement futur.
    Ferme la double boucle HOMÉOSTASE + APPRENTISSAGE (census organe×agent, P0).
    À appeler par l'exécuteur (run_job/cascade) en fin d'action."""
    complexity = decision.complexity or "technical"
    tgt = f"{action.kind or action.task_type}:{complexity}"
    out: dict = {}
    try:
        from nokido_agent.app.forge_active_inference import observe
        out["observe"] = observe(decision.lane, target=tgt, success=bool(success),
                                 time_s=float(elapsed))
    except Exception as e:  # noqa: BLE001
        out["observe"] = {"ok": False, "reason": str(e)}
    try:
        from nokido_agent.app.forge_motivation import reward, punish
        if success:
            out["endocrine"] = reward(decision.lane, time_s=float(elapsed),
                                      n_steps=int(action.est_steps or 1), success=True, target=tgt)
        else:
            out["endocrine"] = punish(decision.lane, error="route_outcome_fail", target=tgt)
    except Exception as e:  # noqa: BLE001 - endocrinien absent -> dégrade (afferent best-effort)
        out["endocrine"] = {"ok": False, "reason": str(e)}
    return out


async def plan_route(action: Action, *, entity_id: str = "wrk_laforge", token: str = "") -> dict:
    """Routeur de PLANIFICATION : COMPOSE le routeur d'INTENTION LIVE (app.services.
    intent_router, Intent-Based v18.5) avec le classifieur de voie. NE duplique PAS —
    réutilise l'existant (cf. architecture_rules:routing_stack_compose).
      1) intent_router.route(prompt) -> intent CONNU ? bypass (plan caché, 0-LLM) -> NATIVE.
      2) sinon -> classify(action) pour la VOIE (native/local/deport/cloud).
    forge_workflow.submit se déclenche si lane==DEPORT. Dégrade en classify seul si
    intent_router indispo (jamais bloquer le routage)."""
    intent = None
    try:
        from app.services.intent_router import get_intent_router
        _ir = get_intent_router()
        intent = await _ir.route(action.prompt, task_type=action.task_type,
                                 entity_id=entity_id, token=token)
    except Exception as e:  # noqa: BLE001 - intent_router indispo -> classify seul
        intent = {"action": "unavailable", "error": str(e)}
    if isinstance(intent, dict) and intent.get("action") == "bypass" and intent.get("plan"):
        return {"intent": intent.get("source_task"), "intent_action": "bypass",
                "lane": Lane.NATIVE.value, "target": "intent_router:plan",
                "reason": "intent connu -> plan caché (bypass LLM)", "plan": intent.get("plan")}
    d = classify(action)
    d = learn_adjust(d, action)  # apprentissage actif : re-rank par prior appris (gardes figés)
    return {"intent": (intent or {}).get("source_task"),
            "intent_action": (intent or {}).get("action", "none"),
            "lane": d.lane, "target": d.target, "reason": d.reason, "decision": d.to_dict()}


def _selftest() -> int:
    cases = [
        (Action(kind="file_edit", est_tokens=300), Lane.NATIVE.value),
        (Action(prompt="refacto tout le module sur 12 fichiers", kind="refactor_multi", est_steps=12), Lane.DEPORT.value),
        (Action(prompt="resume ce texte court", nlu_conf=0.9), Lane.LOCAL.value),
        (Action(prompt="audit securite de l'auth", task_type="security_audit", quality_need="high"), Lane.CLOUD.value),
        (Action(prompt="audit securite", task_type="security_audit", ring=0), Lane.LOCAL.value),
        (Action(prompt="lance la veille approfondie sur X", kind="veille"), Lane.DEPORT.value),
        (Action(prompt="ecris un gros contexte", est_tokens=12000), Lane.DEPORT.value),
    ]
    ok = 0
    for act, expected in cases:
        d = classify(act)
        good = d.lane == expected
        ok += good
        print(f"  [{'OK' if good else 'FAIL'}] kind={act.kind} type={act.task_type} ring={act.ring}"
              f" -> {d.lane} (attendu {expected}) :: {d.reason}")
    # plan_route : COMPOSE intent_router (indispo en selftest -> dégrade) + classify
    import asyncio
    pr = asyncio.run(plan_route(Action(prompt="lance la veille sur X", kind="veille")))
    pr_ok = pr["lane"] == Lane.DEPORT.value
    ok += pr_ok
    print(f"  [{'OK' if pr_ok else 'FAIL'}] plan_route compose intent+classify -> "
          f"lane={pr['lane']} intent_action={pr['intent_action']}")
    # learn_adjust : sans historique (kind inédit) = NO-OP (garde la voie déterministe).
    # Garde figé : une décision quality_floor n'est JAMAIS ré-routée par l'apprentissage.
    base = classify(Action(prompt="resume court", kind="_selftest_unseen_kind_", nlu_conf=0.9))
    adj = learn_adjust(base, Action(kind="_selftest_unseen_kind_"))
    floor = classify(Action(prompt="audit secu", task_type="security_audit", quality_need="high"))
    floor_adj = learn_adjust(floor, Action(task_type="security_audit", quality_need="high"))
    la_ok = adj.lane == base.lane and floor_adj.lane == floor.lane == Lane.CLOUD.value
    ok += la_ok
    print(f"  [{'OK' if la_ok else 'FAIL'}] learn_adjust no-op sans historique ({adj.lane}) "
          f"+ garde plancher figé ({floor_adj.lane})")
    # EFFERENT : _stress lit l'endocrinien (forge_endocrine), dégrade en (0,0) si absent.
    st = _stress()
    st_ok = isinstance(st, tuple) and len(st) == 2 and all(isinstance(x, float) for x in st)
    ok += st_ok
    print(f"  [{'OK' if st_ok else 'FAIL'}] efferent _stress() lit l'endocrinien -> {st}")
    print(f"selftest: {ok}/{len(cases) + 3} OK")
    return 0 if ok == len(cases) + 3 else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
