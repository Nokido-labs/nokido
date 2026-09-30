#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_knowledge_concierge.py — le PORTIER de la recherche interne Nokido.

Spécialiste : sait OÙ trouver et CROISER l'info rapidement, à travers le code, les
DB, le RAG (toutes dimensions vectorielles) ET la fabrique MCP (interaction CLI↔hub).
Jumeau-CONNAISSANCE du Gate d'orchestration : le gate route les ACTIONS, le portier
route les REQUÊTES (quelle source / quelle dimension). Émane de Nokido : un seul
portier sert tous les agents -> alignement-depuis-le-système (cf. architecture_rules).

ANTI-DUP : n'implémente AUCUN moteur. Il ORCHESTRE les existants — forge_rag_engine
(RRF/rerank), rag_fts, forge_graph_universal, get_file_skeleton/read_function_body,
organ_map_full.json, forge_rag_qualify (trust), audit.db, blackboard, forge_mcp_federation.
Le NEUF = la CARTE des sources + le classifieur de requête + le planificateur multi-source
+ le détecteur de dérive (trafic MCP vs canon architecture_rules).

Phase 1 (ce fichier) = ROUTAGE déterministe testable SANS DB : SOURCES + classify(query)
+ plan(query) -> RetrievalPlan. Phase 2 = execute(plan) (fan-out parallèle réel + fusion
RRF cross-store + provenance + drift) — nécessite le hub.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


class Kind(str, Enum):
    CODE = "code-structure"        # où vit X, signature, deps
    FACT = "fact-semantic"         # qu'est-ce que / sait-on
    CONCEPT = "concept"            # voisinage conceptuel haut-niveau
    RELATION = "relationship"      # lié à / appelé par / propagation
    HISTORY = "history"            # qui a fait quoi quand
    SWARM = "swarm-state"          # blackboard / accords / autre agent
    MCP = "mcp-fabric"             # quel CLI / tool / serveur MCP / accès
    DRIFT = "drift-check"          # trafic réel vs canon (auditeur)
    KEEPER = "keeper-artifact"     # artefact PARTAGÉ (roadmap/memory/...) via registre keeper


@dataclass
class Source:
    label: str
    holds: str
    dim: str           # dimension vectorielle ("1024d-bge-m3" / "4096d" / "" )
    access: str        # primitive d'accès (Phase 2)


# ── La CARTE des sources (ce que le portier DOIT connaître) ──────────────────
SOURCES: dict[str, Source] = {
    # Savoir statique
    "rag_dense":   Source("RAG embeddings.db", "code+docs+anchors+lessons vectorisés", "1024d-bge-m3", "rag/query dense (RRF)"),
    "rag_fts":     Source("rag_fts FTS5", "lexical/BM25 sur le RAG", "", "query MATCH"),
    "code_ast":    Source("code AST", "structure, signatures, deps", "", "get_file_skeleton/read_function_body/get_function_dependencies/module_cards"),
    "organ_map":   Source("organ_map_full.json + census", "module→organe", "", "fichier"),
    "graph":       Source("forge_graph_universal", "relations concept↔concept, callgraph", "1024d", "graph_ppr/graph_edge_score"),
    "world_model": Source("world_model", "concepts haut-niveau", "4096d", "cognition"),
    "audit":       Source("audit.db / traces", "qui-a-fait-quoi-quand (spans)", "", "read/trace_viz"),
    "blackboard":  Source("blackboard WAL", "état travail swarm + architecture_rules", "", "blackboard_read_zone"),
    "memory":      Source("memory/*.md", "fils, handoffs, accords agent", "", "fichier"),
    # Fabrique MCP (interaction CLI↔hub)
    "cli_registry": Source("registre CLI", "CLI connectés, transport, identité, ring", "", "_AGENT_TOKENS/_agent_ring_map/mcp.json"),
    "tool_catalog": Source("catalogue tools/agent", "ce que chaque CLI PEUT appeler (ring-filtré)", "", "get_tool_list × _get_ring_needed"),
    "mcp_fed":      Source("fédération MCP externe", "serveurs MCP_DOCKER/video-gen + tools", "", "forge_mcp_federation discover/probe"),
    "net_log":      Source("trafic MCP (network log)", "qui-a-appelé-quel-tool-quand (latence/canal/ring)", "", "audit.db (_log_network)"),
    # Registre KEEPER : owners d'artefacts PARTAGÉS internalisés (consultation centrale rapide)
    "keepers":      Source("registre keeper", "artefacts partagés (roadmap/memory/rules/workflow/agents/...) — owners + vues internalisées", "", "forge_keeper_base.present_any/consult/discover"),
    "ssot":         Source("SSoT structuré", "savoir central STRUCTURÉ (roadmap_state.json, ...) — déterministe, uniforme cross-CLI", "", "forge_ssot.consult_ssot/answer_uniform/point"),
}


@dataclass
class RetrievalPlan:
    kind: str
    sources: list           # noms de sources à interroger (ordre/parallèle)
    dimensions: list        # dimensions vectorielles impliquées
    reason: str
    cross_ref: bool = False  # croisement multi-source requis
    extra: dict = field(default_factory=dict)


# ── Classifieur de requête (heuristique mots-clés, déterministe) ─────────────
_PATTERNS = {
    Kind.KEEPER:  ("roadmap", "présente la", "présentation", "keeper", "artefact partagé", "tenue", "où en est", "statut du projet", "vue d'ensemble"),
    Kind.DRIFT:   ("dérive", "improvise", "improvisation", "mauvais tool", "conforme", "vs canon", "respecte", "drift"),
    Kind.MCP:     ("quel cli", "quel tool", "quels outils", "mcp", "connecté", "catalogue", "accès tool", "serveur mcp", "gateway", "fédér"),
    Kind.HISTORY: ("qui a", "quand", "historique", "a changé", "a appelé", "trace", "dernier commit", "qui est l'auteur"),
    Kind.RELATION: ("relation", "lié à", "appelé par", "appelle", "dépend", "dépendent", "dépendance", "propagation", "voisins", "callgraph", "impact"),
    Kind.CODE:    ("où vit", "où est", "quel module", "signature", "fonction", "classe", "structure", "implément", "le code de", "deps"),
    Kind.CONCEPT: ("concept", "haut-niveau", "vision", "analogie", "équivalent", "taxonom", "sémantiquement proche"),
    Kind.SWARM:   ("swarm", "blackboard", "accord", "autre agent", "gemini fait", "mission", "qui s'occupe de"),
}


def classify(query: str) -> str:
    q = (query or "").lower()
    # ordre = priorité (drift > mcp > history > relation > code > concept > swarm)
    for kind, kws in _PATTERNS.items():
        if any(k in q for k in kws):
            return kind.value
    return Kind.FACT.value  # défaut : recherche sémantique RAG


# ── Planificateur multi-source (la valeur : croiser les bonnes sources) ──────
_PLANS = {
    Kind.CODE.value:     (["code_ast", "organ_map", "graph"], True),
    Kind.FACT.value:     (["rag_dense", "rag_fts", "memory"], True),
    Kind.CONCEPT.value:  (["world_model", "rag_dense", "graph"], True),
    Kind.RELATION.value: (["graph", "code_ast", "rag_dense"], True),
    Kind.HISTORY.value:  (["audit", "net_log", "blackboard"], True),
    Kind.SWARM.value:    (["blackboard", "memory"], False),
    Kind.MCP.value:      (["cli_registry", "tool_catalog", "mcp_fed", "net_log"], True),
    # DRIFT = auditeur : croise TRAFIC réel (net_log/audit) vs CANON (blackboard architecture_rules + tool_catalog).
    Kind.DRIFT.value:    (["net_log", "audit", "blackboard", "tool_catalog"], True),
    # KEEPER = consultation CENTRALE d'un artefact partagé internalisé (rapide, pas de re-scan).
    Kind.KEEPER.value:   (["keepers", "rag_fts"], False),
}


def plan(query: str) -> RetrievalPlan:
    """Décide quelles sources interroger + quelles dimensions. Déterministe."""
    kind = classify(query)
    srcs, cross = _PLANS.get(kind, (["rag_dense", "rag_fts"], True))
    extra = {}
    # KEEPER + domaine SSoT structuré (roadmap_state.json...) -> router vers le SSoT
    # déterministe (uniforme cross-CLI) AVANT le markdown keeper. L'exécuteur appelle
    # forge_ssot.answer_uniform(domain) / point(query).
    if kind == Kind.KEEPER.value:
        try:
            from nokido_agent.app.forge_ssot import detect_domain as _detect_domain
            _ssot_d = _detect_domain(query)
        except Exception:  # noqa: BLE001
            _ssot_d = None
        if _ssot_d:
            extra["ssot_domain"] = _ssot_d
            extra["executor"] = "forge_ssot.point(query) / answer_uniform(domain)"
            if "ssot" in SOURCES and "ssot" not in srcs:
                srcs = ["ssot", *srcs]
    dims = sorted({SOURCES[s].dim for s in srcs if SOURCES[s].dim})
    if kind == Kind.DRIFT.value:
        extra["compare"] = "trafic(net_log,audit) vs canon(blackboard:architecture_rules, tool_catalog)"
    return RetrievalPlan(
        kind=kind, sources=srcs, dimensions=dims, cross_ref=cross,
        reason=f"{kind} -> {len(srcs)} sources" + (" (multi-dim: " + ",".join(dims) + ")" if dims else ""),
        extra=extra,
    )


def source_map() -> dict:
    """Expose la carte des sources (pour les agents : 'où trouver quoi')."""
    return {k: {"holds": s.holds, "dim": s.dim or None, "access": s.access} for k, s in SOURCES.items()}


def _selftest() -> int:
    cases = [
        ("où vit la fonction _tool_call ?", Kind.CODE.value),
        ("qu'est-ce que le gate d'orchestration ?", Kind.FACT.value),
        ("quels outils Gemini peut appeler en MCP ?", Kind.MCP.value),
        ("qui a appelé docker_action cette heure ?", Kind.HISTORY.value),
        ("quels modules dépendent de forge_rag_engine ?", Kind.RELATION.value),
        ("est-ce que Gemini improvise vs le canon docker ?", Kind.DRIFT.value),
        ("concept haut-niveau d'autopoïèse dans Nokido", Kind.CONCEPT.value),
        ("que fait l'autre agent sur le blackboard ?", Kind.SWARM.value),
    ]
    ok = 0
    for q, expected in cases:
        p = plan(q)
        good = p.kind == expected
        ok += good
        print(f"  [{'OK' if good else 'FAIL'}] {p.kind} (attendu {expected}) :: {p.reason} -> {p.sources}")
    print(f"selftest: {ok}/{len(cases)} OK | carte = {len(SOURCES)} sources")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
