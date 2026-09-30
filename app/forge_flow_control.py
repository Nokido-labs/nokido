#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_flow_control.py — ÉQUIPE agentique de CONTRÔLE D'ACCÈS & DE FLUX.

Directive user : étendre le VIDEUR en une ÉQUIPE qui couvre TOUS les flux (métaphore
transport = l'arborescence structurante). Chaque rôle = OrganAgent (contrat organ_agent_
contract) qui FÉDÈRE un primitive EXISTANT — on n'invente RIEN, on AGENTIFIE l'existant.

Roster (organe → owner) :
  - VIDEUR        flux ENTRANT (identité×ring)     -> forge_videur
  - CONVOYEUR     flux AUTH (capability tokens)    -> forge_integrity (HMAC, IntegrityRing)
  - CHEF DE GARE  flux PLANIFIÉ + files par agent  -> forge_message_frame (+ run_job)
  - VOITURIER     flux SESSION (park/reprise)      -> forge_sandbox_exec (spawn park / PTY)
  - COURSIER      flux PRIORITAIRE (urgent express)-> forge_postal (_priority_score)
  - FACTEUR       flux POSTAL (inter-agents)       -> forge_postal (notify/poll)
  - AIGUILLEUR    MÉTA : route TOUS les flux (ATC) -> forge_orchestration_gate (plan_route)

Valeur de l'ÉQUIPE (pas juste une liste) :
  - route_flow(kind) : aiguille un flux vers l'agent qui le contrôle.
  - gate_flux()      : la CHAÎNE canonique qu'un flux entrant traverse (identité -> auth ->
                       priorité -> routage -> file -> livraison) = couvre tous les flux.

ANTI-DUP : forge_videur/forge_integrity/forge_message_frame/forge_sandbox_exec/forge_postal/
forge_orchestration_gate possèdent déjà la mécanique. Ce module = la FÉDÉRATION agentique
(contrats + coordination), jumelle de la couche keeper (forge_keeper_base).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/rbac : equipe agentique de controle d'acces et de flux (videur etendu)"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Registre de l'ÉQUIPE : role -> contrat OrganAgent.
FLOW_TEAM: dict[str, dict] = {}


def flow_contract(role: str, *, organ: str, flux: str, owner: str, primitives: list,
                  modalities=None, triggers=None, poolable: bool = True,
                  connects_to=None) -> dict:
    """Contrat OrganAgent normalisé pour un agent de FLUX (forme unique = alignement émané)."""
    return {
        "role": role, "organ": organ, "flux": flux, "owner": owner,
        "primitives": primitives,
        "modalities": modalities or ["text"],
        "proactive_triggers": triggers or ["on_flux", "hook"],
        "poolable": poolable,                 # workers = poolables ; autorités = uniques
        "connects_to": connects_to or ["videur", "aiguilleur"],
        "kind": "FLOW_AGENT",
    }


# Spécification de l'équipe (role, organ, flux, owner, primitives, poolable).
_TEAM_SPEC = [
    ("videur", "immunitaire/accès", "flux ENTRANT (identité×ring)", "forge_videur",
     ["resolve_identity", "capture", "can_talk", "propose_ring_change"], False),
    ("convoyeur", "immunitaire/auth", "flux AUTH (capability tokens HMAC)", "forge_integrity",
     ["IntegrityRing", "verify", "capability_required", "_require_capability"], False),
    ("chef_de_gare", "locomoteur/files", "flux PLANIFIÉ + files par agent", "forge_message_frame",
     ["MessageFrame", "get_queue", "hydrate_queues_on_boot", "run_job"], True),
    ("voiturier", "digestif/session", "flux SESSION (park/reprise)", "forge_sandbox_exec",
     ["spawn_as_interactive_jobbed(park)", "LocalPTYSession"], True),
    ("coursier", "réseau/priorité", "flux PRIORITAIRE (urgent express)", "forge_postal",
     ["_priority_score", "_URGENT_KW", "digest urgent"], True),
    ("facteur", "réseau/postal", "flux POSTAL (inter-agents)", "forge_postal",
     ["notify", "poll", "_postal_dispatch"], True),
    ("aiguilleur", "SNC/routage", "MÉTA — route TOUS les flux (tour de contrôle)",
     "forge_orchestration_gate",
     ["plan_route", "classify", "intent_router", "spike_router"], False),
]

# Aiguillage : type de flux -> rôle qui le contrôle (le cœur de la tour de contrôle).
_FLUX_ROUTING = {
    "entrant": "videur", "access": "videur", "acces": "videur", "ring": "videur", "identite": "videur",
    "auth": "convoyeur", "token": "convoyeur", "credential": "convoyeur", "capability": "convoyeur",
    "planifie": "chef_de_gare", "queue": "chef_de_gare", "file": "chef_de_gare",
    "batch": "chef_de_gare", "job": "chef_de_gare",
    "session": "voiturier", "park": "voiturier", "reprise": "voiturier", "pty": "voiturier",
    "prioritaire": "coursier", "urgent": "coursier", "express": "coursier", "critique": "coursier",
    "postal": "facteur", "message": "facteur", "notify": "facteur", "inbox": "facteur",
    "route": "aiguilleur", "dispatch": "aiguilleur", "traffic": "aiguilleur", "trafic": "aiguilleur",
}


def _build_team() -> dict:
    """Peuple FLOW_TEAM depuis la spec. Idempotent."""
    for role, organ, flux, owner, prims, poolable in _TEAM_SPEC:
        FLOW_TEAM[role] = flow_contract(role, organ=organ, flux=flux, owner=owner,
                                        primitives=prims, poolable=poolable)
    return {r: FLOW_TEAM[r]["flux"] for r in FLOW_TEAM}


def route_flow(kind: str) -> dict:
    """AIGUILLEUR (tour de contrôle) : aiguille un flux vers l'agent qui le contrôle.
    `kind` libre (mots-clés) -> rôle + owner. Défaut = aiguilleur (réévalue/route)."""
    if not FLOW_TEAM:
        _build_team()
    k = (kind or "").strip().lower()
    role = _FLUX_ROUTING.get(k)
    if not role:  # match partiel sur mots-clés
        role = next((r for kw, r in _FLUX_ROUTING.items() if kw in k), "aiguilleur")
    c = FLOW_TEAM.get(role, {})
    return {"flux": kind, "role": role, "owner": c.get("owner"),
            "primitives": c.get("primitives", []), "organ": c.get("organ")}


def gate_flux(flux: str = "entrant") -> list:
    """La CHAÎNE canonique qu'un flux ENTRANT traverse — l'équipe au travail, dans l'ordre.
    Couvre tous les flux : identité -> auth -> priorité -> routage -> file -> livraison."""
    if not FLOW_TEAM:
        _build_team()
    return [
        ("videur", "resolve_identity + can_talk — qui entre, quel ring"),
        ("convoyeur", "verify capability token — authentifie (HMAC, scope/action)"),
        ("coursier", "_priority_score — urgent ? voie express"),
        ("aiguilleur", f"route_flow('{flux}') — vers le bon canal/agent"),
        ("chef_de_gare", "enqueue si planifié/file (MessageFrame par agent)"),
        ("facteur", "deliver / notify — remet au destinataire"),
    ]


def team() -> dict:
    """Décrit l'équipe complète (contrats OrganAgent). Intégrable au portier/registre central."""
    if not FLOW_TEAM:
        _build_team()
    return {"team": "flow_control", "anchor": "videur", "controller": "aiguilleur",
            "agents": dict(FLOW_TEAM)}


def integrate() -> dict:
    """INTÉGRATION : enregistre l'équipe comme surface dans le registre central des keepers
    (forge_keeper_base) -> découvrable par le portier/gate. Dégrade si la base est absente."""
    _build_team()
    try:
        from nokido_agent.app.forge_keeper_base import declare
        declare("flow_control", owns="équipe contrôle d'accès & flux (videur+6 agents)",
                owner_module="forge_flow_control", how="team/route_flow/gate_flux")
        return {"ok": True, "registered": "flow_control"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"keeper_base absent ({e})"}


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    reg = _build_team()
    chk(len(reg) == 7 and "videur" in reg and "aiguilleur" in reg,
        f"équipe 7 agents: {sorted(reg)}")
    chk(route_flow("auth")["role"] == "convoyeur", "route auth -> convoyeur")
    chk(route_flow("urgent")["role"] == "coursier", "route urgent -> coursier")
    chk(route_flow("park session")["role"] == "voiturier", "route park -> voiturier (partiel)")
    chk(route_flow("ring")["role"] == "videur", "route ring -> videur")
    chk(route_flow("inconnu_xyz")["role"] == "aiguilleur", "flux inconnu -> aiguilleur (défaut)")
    g = gate_flux()
    chk(g[0][0] == "videur" and g[-1][0] == "facteur" and len(g) == 6,
        f"gate_flux chaîne ordonnée ({len(g)}): {g[0][0]}…{g[-1][0]}")
    chk(all(FLOW_TEAM[r]["kind"] == "FLOW_AGENT" for r in FLOW_TEAM)
        and FLOW_TEAM["videur"]["poolable"] is False and FLOW_TEAM["facteur"]["poolable"] is True,
        "contrats FLOW_AGENT (autorités uniques, workers poolables)")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
