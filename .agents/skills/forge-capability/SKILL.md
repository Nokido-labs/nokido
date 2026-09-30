---
name: forge-capability
description: >-
  Fonctionnement EXACT de Nokido (hub souverain :8766) — carte des capacites par
  organe (census 727 modules), tools MCP, doctrine (RULES_SHARED + economie tokens),
  et acces a l'etat vivant (SSoT, MEMORY, blackboard, RAG). Genere depuis le census
  (0-token, auto-courant). A charger quand un agent (n'importe quel CLI) demande
  'que sait faire Nokido', 'comment marche Nokido', 'ou vit X', 'quel organe',
  'liste les capacites/outils', ou doit se reperer dans l'ecosysteme forge_*.
metadata:
  source: census organ_map_full.json + forge_ssot + RULES_SHARED (deterministe)
  generated: 2026-06-19
---

# Nokido — Capacité (référence autoritaire)

> Dérivé du **census** (`sandbox/workspace/organ_map_full.json`, source de vérité module→organe) + SSoT + `RULES_SHARED.md`. Régénérable 0-token. Pour le diagnostic différentiel par symptôme → skill jumeau **`forge-anatomy`**.

## Quoi

Nokido = système souverain local-first. **Cerveau = hub MCP HTTP `:8766`** (`tools/nokido_hub.py`). Tout client (Claude Code/Desktop, Antigravity agy/agi, Codex, VSCode, LM Studio) s'y branche en MCP et **dérive** règles + état depuis là (émanation, pas copie). Tu es un **CLIENT**, pas l'exécuteur : déporte le travail au hub.

## Carte des capacités — 727 modules / 15 organes

| Organe | Modules | Représentatifs |
|---|---|---|
| Infra/Bootstrap/Config | 84 | forge_arch_schema.py, forge_auth_debug.py, forge_bench_diagnose.py, forge_boot.py, forge_cai_bridge.py, forge_capabilities.py |
| Memoire (hippocampe/RAG) | 78 | forge_anchor_rag_session.py, forge_auto_compact.py, forge_bench_ragtool.py, forge_biblio_core.py, forge_biblio_refine.py, forge_biblio_schema.py |
| Locomoteur/Orchestration | 74 | forge_ami_strategist.py, forge_at_dispatch.py, forge_autonomous_orchestrator.py, forge_benchmark_runner.py, forge_bfcl_runner.py, forge_bounded_queue.py |
| SNC (cerveau/moelle/SNP) | 67 | forge_app_context.py, forge_bge_m3_shared.py, forge_boot_context.py, forge_brain_client.py, forge_broker_base.py, forge_broker_deepseek.py |
| SN vegetatif (autonome) | 67 | forge_aa_discover_daemon.py, forge_auto_evolution_loop.py, forge_autonomous_loops.py, forge_bell.py, forge_circadian.py, forge_circadian_loop.py |
| Cognition/Agentique/Raisonnement | 67 | forge_active_inference.py, forge_active_inference_agent.py, forge_actor.py, forge_agent_authority.py, forge_agent_benchmarker.py, forge_agent_hardware.py |
| Metabolisme LLM (routage/backends) | 60 | forge_agent_proxy.py, forge_ami_train_cycle.py, forge_artificialanalysis.py, forge_baml_adapter.py, forge_bitnet_loader.py, forge_cache_aligner.py |
| Immunitaire (firewall/garde) | 49 | forge_access_switches.py, forge_at_rest_efs.py, forge_at_rest_veracrypt.py, forge_auth_jwt.py, forge_biblio_sanitizer.py, forge_bundle_primitives.py |
| Qualite/Build/Spec | 42 | forge_archi_lint.py, forge_bench_all.py, forge_bench_auto_trigger.py, forge_bench_autotrigger.py, forge_bench_beir.py, forge_bench_engine.py |
| Graph/Connaissances | 40 | forge_ast_index.py, forge_binary_graph.py, forge_callgraph_jit.py, forge_code_surgery.py, forge_coherence_checker.py, forge_coherence_gate.py |
| Digestif/Sens (ingestion/web) | 35 | forge_anchor_swebench.py, forge_audit_swebench.py, forge_auto_ingest_daemon.py, forge_browser_tool.py, forge_bulk_import.py, forge_crawl_tool.py |
| Observabilite/Trace | 33 | forge_anatomy_state.py, forge_audit.py, forge_audit_log.py, forge_audit_personas.py, forge_audit_reducer.py, forge_audit_worker.py |
| Reseau/Distribue/Sync | 18 | forge_acp_adapter.py, forge_codeberg_sync.py, forge_cross_fs.py, forge_dataset_sync.py, forge_demo_netcfg_topology.py, forge_dt_router_wire.py |
| Offensif/CTF | 10 | forge_autopwn_scaffold.py, forge_continual_backprop.py, forge_ctf_agent.py, forge_ctf_solver.py, forge_exploit_chain.py, forge_exploitdb_scraper.py |
| SWE-bench | 3 | forge_pydantic_tools.py, forge_swe_ast_whole_func.py, forge_swe_multifile.py |

> Carte complète = `organ_map_full.json` + `module_inventory.md`. **Consulter AVANT d'affirmer qu'un module n'existe pas / d'en recréer un** (anti-dup).

## Tools MCP du hub (42)

`mcp__laforge-sovereign-hub__*` — `ask`, `auto_test`, `biblio`, `blackboard_propose_fact`, `blackboard_read_zone`, `bundle`, `crawl`, `cross_platform_fs`, `docker_action`, `dyn_orchestrate`, `dyn_skill_forge`, `event`, `forge_call_dynamic`, `forge_list_dynamic_tools`, `forge_spawn_swarm`, `forge_stats`, `forge_trigger_audit`, `get_file_skeleton`, `get_function_dependencies`, `governed_edit`, `graph_cve_propagate`, `graph_edge_score`, `graph_ppr`, `hub`, `loop_orchestrate`, `manage_forge_lifecycle`, `netcfg`, `oracle_python_repl`, `orchestrate`, `plan`, `query`, `rag`, `read`, `read_function_body`, `research_agent`, `route_dt`, `route_task`, `run`, `skill`, `task`, `trigger_autonomous_evolution`, `web_search`

Clé : `run` (shell/python/run_job déporté), `rag`/`query` (retrieval condensé), `read`/`read_function_body` (fenêtré), `orchestrate`/`task`/`plan`, `ask`/`forge_cli_swarm` (pool local), `blackboard_*`, `skill`.

## Doctrine (non négociable)

- **Tout via le hub** : outils `mcp__laforge-sovereign-hub__*`, pas les natifs sur le code/système Nokido. `Edit` natif OK (hook PostToolUse valide l'AST).
- **Réutiliser avant reconstruire** : `rag_fts` + `[[liens]]` memory + module existant AVANT toute création `forge_*.py`. Sinon STOP.
- **Déporter le long** : tâche multi-étapes / >70s → `run_job` détaché (survit au restart).
- **Confirmer l'irréversible** : migration secret, suppression, ACL, kill/restart service.
- **Économie tokens** : chaque tour re-facture l'historique → lecture fenêtrée, déport, pas de dumps en contexte. Détail : `RULES_SHARED.md` + `docs/token_economy.md`.

### Règles d'or
```
## 7. Regles d or (persistees dans rag_fts, cherchables)

1. JAMAIS de SQL LIKE primitif pour RAG - utiliser rag_fts ou RAGEngine.search
2. JAMAIS de creation de module app/forge_*.py sans query rag_fts prealable
3. JAMAIS d INSERT INTO rag_chunks sans id explicite (TEXT PRIMARY KEY)
4. JAMAIS d envoi cloud sans SemanticFirewall.pre_flight + .post_flight
5. TOUJOURS read_lessons(3000) en debut de session
6. TOUJOURS anchor_solution apres decision architecturale
7. TOUJOURS session_summary apres bloc de commits
8. TOUJOURS documenter les liens entre modules co-modifies
9. TOUJOURS tqdm sur toutes boucles longues dans scripts generes via task assign
10. JAMAIS nssm restart LaForgeMCP direct — LaForge-Master :8765 est
    proprietaire exclusif du hub. Crash loop = conflit port 8766. Toujours
    passer par LaForge-Master ou redemarrer les 2 ensembles.
11. JAMAIS Bash/curl vers hub — utiliser les tools mcp__laforge-sovereign-hub__*
    directement (token economy, moins de roundtrips)
12. JAMAIS code Python inline de plus de 5 lignes dans un tool call — creer
    un script tools/tmp_*.py via Write, puis appel hub run action=python 1 ligne
13. JAMAIS d['result'] sur reponse hub — toujours .get('result') car hub
    retourne {'error': '...'} sans cle result sur exception
14. "POINT SUR <domain>" (roadmap, et futurs memory/rules/...) — LIRE le SSoT
    AVANT de repondre : `forge_ssot.point(query)` (ou `docs/<domain>_state.json`).
    Source unique STRUCTUREE (state determinist capte + roadmap) -> reponse
    UNIFORME cross-CLI. Ne PAS re-deriver de la memoire de session (= la
    d
```

## État vivant — interroger, ne pas supposer

- **SSoT** (`forge_ssot.point('point <domaine>')`) — domaines: roadmap, rules, memory, providers, system_state. « point sur X » → LIRE le SSoT, ne pas re-dériver.
- **MEMORY** : `MEMORY.md` + fichiers mémoire du domaine (déréférencer les `[[liens]]`).
- **blackboard** : `blackboard_read_zone` (mission/architecture_rules/discovered_facts/active_bugs/scratch).
- **RAG** : `rag action=search` / `rag_fts` (FTS5 BM25) — jamais SQL LIKE brut.
- **Santé** : tail logs hub, `forge_organ_pulse`, heartbeats.

## Se brancher (nouveau CLI)

Commande d'init unique (owner) : `forge_client_bootstrap.py --apply` → provision token+ring, MCP→`:8766`, `@import RULES_SHARED`, skill_sync, print SSoT. Identité = token vault `FORGE_TOKEN_<AGENT>` + header `LaForge-Agent-Name` → ring (`config/agent_identities.json`).
