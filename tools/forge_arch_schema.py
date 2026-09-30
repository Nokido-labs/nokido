#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_arch_schema.py — schéma d'architecture Nokido COMPLET + souverain (zéro backend).

Couche STATIQUE data-driven depuis le scan AST import-graph (`forge_panorama_builder`,
fonctions PURES — pas le path LLM qui renvoie vide). Produit un markdown COMPLET :
  - stats globales,
  - carte par DOMAINE (les 430 modules clusterisés + arêtes inter-domaines pondérées
    = lisible ET exhaustif, ni hairball ni fragment top-N),
  - top hubs (centralité),
  - inventaire par domaine (chaque module rattaché).

Imprime le markdown complet (à rediriger vers docs/ARCHITECTURE_SCHEMA.md).
Couches DYNAMIQUE (`forge_trace_viz <trace_id> --tree`) + COGNITIVE (Phoenix :6006)
= ajoutées au doc séparément (runtime).

À lancer en trusted_script (lecture host de app/). Usage : trusted_script forge_arch_schema.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Domaine = (label, mots-clés). Premier match (ordre = priorité). Sinon "Divers".
import os as _os

# Famille déportée (lab borné) : mots-clefs de classification chargés SEULEMENT si le lab est
# actif. Hors lab, la famille reste déclarée mais vide (ne classe aucun module du cœur).
_REDTEAM_KW = (["ctf", "exploit", "heap", "exegol", "recon", "nuclei", "autopwn", "gdb",
                "libc", "r2pipe", "sanitizer", "cai", "network", "ids", "js_endpoint"]
               if _os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON") else [])

DOMAINS = [
    ("Observabilité", ["trace", "audit", "span", "otel", "langfuse", "profiler", "pyspy",
                        "uprof", "arch_schema", "panorama", "scorecard", "network_log", "metrics"]),
    ("Sécurité/Immunitaire", ["firewall", "membrane", "guard", "secret", "integrity", "rbac",
                              "auth", "jwt", "sentinel", "prompt_guard", "noise", "opsec",
                              "encrypt", "vault", "redact", "snapshot", "immune", "coagulation"]),
    ("AMI/Cognitif", ["hormone", "endocrine", "novelty", "motivation", "curiosity", "world_model",
                      "jepa", "value_net", "policy_net", "cost_net", "cost_module", "actor", "flow",
                      "semantic_pressure", "trauma", "mood", "intuition", "reflexion", "metacognition",
                      "active_inference", "continual", "spike", "snn", "lnn", "engram", "homeostasis",
                      "circadian", "glymphatic", "renal", "endocrine", "proprioception", "anatomy"]),
    ("Redteam", _REDTEAM_KW),
    ("Graph", ["graph", "ppr", "edge_scor", "cve", "hebbian", "tem_"]),
    ("RAG/Mémoire", ["rag", "embed", "ingest", "biblio", "hybrid", "chunk", "vector", "memory",
                     "hippocamp", "conv_index", "conv_logger", "knowledge", "epistemic", "distill",
                     "tldr", "stm", "mesh_memory", "trust", "sigreg", "synaptic", "qualify", "truth"]),
    ("LLM/Routing", ["llm", "provider", "router", "cascade", "agent_proxy", "handoff", "ollama",
                     "llamacpp", "lmstudio", "openrouter", "gemini", "claude", "groq", "cerebras",
                     "litellm", "quota", "token", "cost", "frugal", "ghost", "dt_router", "roles",
                     "nlu", "intent", "tokenizer", "specialists", "swarm_agent", "model"]),
    ("Orchestration", ["swarm", "silo", "orchestr", "handler", "dispatch", "commands", "goap",
                       "mpc", "triad", "dag", "pipeline", "task", "workflow", "lats", "loop",
                       "autonomous", "evolution", "self_", "meta_tool", "trajectory", "plan"]),
    ("Cycle-de-vie/Infra", ["supervisor", "inspector", "health", "heartbeat", "watchdog", "resource",
                            "service", "boot", "startup", "keeper", "lifecycle", "db", "conn", "lock",
                            "queue", "mmap", "runner", "runtime", "python_bin", "worker", "job",
                            "state", "registry", "context", "settings", "mailbox", "event", "bus",
                            "frame", "broker", "hub", "mcp", "byte_router", "payload", "log", "portable"]),
    ("Code/Build/Qualité", ["code", "build", "quality", "dep_manager", "spec", "stub", "repo_map",
                            "surgery", "ast", "diff", "commit", "test_fix", "tool_forger", "patch",
                            "swe_", "coherence", "audit_reduc", "impact", "extern_pattern"]),
    ("Web/UI/Sens", ["web", "crawl", "browser", "ui_", "dashboard", "tui", "vision", "perception",
                     "video", "mermaid", "graph_explorer", "pty", "ssh", "widgets", "events", "mixin_ui"]),
]


def _domain(mod: str) -> str:
    m = mod.lower()
    for label, kws in DOMAINS:
        if any(k in m for k in kws):
            return label
    return "Divers"


def main() -> int:
    from nokido_agent.app.forge_panorama_builder import scan_forge_modules, compute_orphans, _short

    graph = scan_forge_modules(include_virtual_roots=True)
    orph = compute_orphans(graph)
    st = orph["stats"]

    indeg = {m: 0 for m in graph}
    for m, deps in graph.items():
        for d in deps:
            if d in indeg:
                indeg[d] += 1

    dom_of = {m: _domain(m) for m in graph}
    dom_mods: dict[str, list[str]] = {}
    for m in graph:
        dom_mods.setdefault(dom_of[m], []).append(m)

    # Arêtes inter-domaines (pondérées) + intra-domaine (compteur)
    cross: dict[tuple, int] = {}
    intra: dict[str, int] = {}
    for m, deps in graph.items():
        for d in deps:
            if d not in graph:
                continue
            a, b = dom_of[m], dom_of[d]
            if a == b:
                intra[a] = intra.get(a, 0) + 1
            else:
                cross[(a, b)] = cross.get((a, b), 0) + 1

    labels = [lbl for lbl, _ in DOMAINS] + ["Divers"]
    labels = [lbl for lbl in labels if lbl in dom_mods]
    nid = {lbl: f"D{i}" for i, lbl in enumerate(labels)}

    out = []
    out.append("## Couche 1 — Structure statique (import-graph AST, **complet**)\n")
    out.append(f"**{st['total_modules']} modules** `app/forge_*.py` · **{st['total_edges']} liens** "
               f"internes · {st['roots_count']} racines · {st['leaves_count']} feuilles · "
               f"{st['true_orphans_count']} orphelins.\n")

    # Carte par domaine
    out.append("### Carte par domaine (les 430 modules clusterisés)\n")
    out.append("```mermaid")
    out.append("flowchart LR")
    for lbl in labels:
        n = len(dom_mods[lbl])
        intra_n = intra.get(lbl, 0)
        out.append(f'    {nid[lbl]}["{lbl}<br/>{n} modules · {intra_n} liens internes"]')
    for (a, b), w in sorted(cross.items(), key=lambda x: -x[1]):
        if w >= 2:  # filtre le bruit : seules les relations inter-domaines significatives
            out.append(f"    {nid[a]} -->|{w}| {nid[b]}")
    out.append("```\n")

    # Top hubs
    cent = sorted(graph, key=lambda m: -(len(graph[m]) + indeg[m]))[:18]
    out.append("### Top 18 hubs (centralité = liens entrants+sortants)\n")
    out.append("| module | out | in | domaine |")
    out.append("|---|--:|--:|---|")
    for m in cent:
        out.append(f"| `{_short(m)}` | {len(graph[m])} | {indeg[m]} | {dom_of[m]} |")
    out.append("")

    # Inventaire par domaine
    out.append("### Inventaire par domaine\n")
    for lbl in labels:
        mods = sorted(_short(m) for m in dom_mods[lbl])
        out.append(f"<details><summary><b>{lbl}</b> ({len(mods)})</summary>\n")
        out.append(", ".join(f"`{m}`" for m in mods))
        out.append("\n</details>\n")

    print(f"### STATS modules={st['total_modules']} edges={st['total_edges']} domains={len(labels)}")
    print("### MARKDOWN_BEGIN")
    print("\n".join(out))
    print("### MARKDOWN_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
