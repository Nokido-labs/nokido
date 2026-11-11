# 04 — PRD : perimetre produit, anatomie et acteurs mesures

> Genere par `tools/forge_spec_extractor.py` (introspection deterministe, aucun horodatage) -- commit `bffa9f1a0`. Ne pas editer : relancer l'extracteur.


## 1. ETAT STATIQUE — Architecture, capacites et contrats (genere au commit)

> Architecture, contrats d'outils, anneaux de droits et jalons lus dans les sources versionnees du depot.

### 1.1 Identite du paquet et entrypoints CLI (`pyproject.toml`)

Paquet `nokido-agent` — licence `AGPL-3.0-or-later`.

| Entrypoint CLI | Cible |
|---|---|
| `nokido` | `nokido_agent.tools.llama_cli:main` |
| `nokido-cli` | `nokido_agent.tools.llama_cli:main` |
| `nokido-composants` | `nokido_agent.tools.forge_composants:main` |
| `nokido-doctor` | `nokido_agent.tools.nokido_doctor:main` |
| `nokido-hub` | `nokido_agent.tools.nokido_hub_cli:main` |
| `nokido-secrets` | `nokido_agent.app.forge_secrets:main` |
| `nokido-vault` | `nokido_agent.app.forge_machine_vault:main` |

### 1.2 Anatomie fonctionnelle par organe (`tools/forge_module_census.py`)

| Organe | Familles lexicales declarees (`ORGANS`) |
|---|---|
| Cognition/Agentique/Raisonnement | `active_inference`, `reasoning`, `arbitrat`, `actor`, `agentic`, `agent` |
| Digestif/Sens (ingestion/web) | `crawl`, `web`, `browser`, `gitingest`, `egress`, `ingest` |
| Graph/Connaissances | `graph`, `ppr`, `edge`, `cve`, `project_state`, `callgraph` |
| Immunitaire (firewall/garde) | `firewall`, `guard`, `membrane`, `integrity`, `sanitiz`, `rbac` |
| Infra/Bootstrap/Config | `__init__`, `bootstrap`, `bridge`, `facade`, `debug`, `diag` |
| Interface/UI (peau/expression) | `_form`, `web_hub`, `webhub`, `tui`, `dashboard`, `htmx` |
| Locomoteur/Orchestration | `orchestr`, `silo_engine`, `swarm`, `handoff`, `goap`, `_plan` |
| Memoire (hippocampe/RAG) | `rag`, `embed`, `memory`, `vector`, `ingest_self`, `tier` |
| Metabolisme LLM (routage/backends) | `llm_router`, `provider`, `cascade`, `ollama`, `llama`, `agent_proxy` |
| Observabilite/Trace | `trace`, `observ`, `span`, `telemetry`, `audit`, `langfuse` |
| Qualite/Build/Spec | `quality`, `dep_manager`, `spec_clar`, `_test`, `clinical`, `scaffold` |
| Reseau/Distribue/Sync | `nats`, `zmq`, `sync`, `distrib`, `p2p`, `mesh` |
| SN vegetatif (autonome) | `inspector`, `watchdog`, `monitor`, `keeper`, `sentinel`, `heartbeat` |
| SNC (cerveau/moelle/SNP) | `hub`, `mcp`, `registry`, `middleware`, `byte_router`, `nlu` |
| SWE-bench | `swebench`, `swe_`, `anchor_swe`, `aider` |

### 1.3 Surface contractuelle MCP (`tests/schemas_mcp_structure.json`)

Outils declares au contrat CI (detail complet dans `01_SCHEMA.md`) : `absorb_rfc_knowledge`, `acp`, `agy_add_dir`, `agy_config`, `agy_run`, `ask`, `auto_ingest`, `auto_test`, `biblio`, `blackboard_propose_fact`, `blackboard_read_zone`, `bundle`, `crawl`, `cross_platform_fs`, `delegate_to_local_scout`, `docker_action`, `event`, `forge_call_dynamic`, `forge_deep_explore`, `forge_list_dynamic_tools`, `forge_spawn_swarm`, `forge_stats`, `forge_trigger_audit`, `get_file_skeleton`, `get_function_dependencies`, `github`, `governed_edit`, `graph_cve_propagate`, `graph_edge_score`, `graph_ppr`, `hub`, `introspect`, `loop_orchestrate`, `manage_forge_lifecycle`, `md`, `memory`, `netcfg`, `nokido_ensure_service`, `oracle_python_repl`, `orchestrate`, `plan`, `query`, `query_documentation`, `query_local_json`, `rag`, `read`, `read_function_body`, `research_agent`, `route_task`, `run`, `search_local_file`, `secret`, `skill`, `task`, `tool_scope`, `trigger_autonomous_evolution`, `web_search`, `write`.

### 1.4 Acteurs CLI et anneaux RBAC (`config/agent_identities.json`)

| Identite | Kind | Ring | Surface | Ecriture (`write_paths`) |
|---|---|---|---|---|
| `AGENT_PROXY` | relay | 4 | internal | -- |
| `AGY` | cli_agent | 1 | interactive | `sandbox/`, `docs/`, `tests/`, `logs/`, `migrations/`... |
| `ANTIGRAVITY` | cli_agent | 1 | interactive | `app/`, `tools/`, `proxy_deno/`, `src/`, `tests/`... |
| `BRIDGE` | relay | 2 | internal | `*` |
| `CLAUDE` | cli_agent | 1 | interactive | `*` |
| `CLINE` | cli_agent | 1 | interactive | `app/`, `tests/`, `src/`, `sandbox/`, `docs/` |
| `CODEX` | cli_agent | 1 | interactive | `app/`, `tools/`, `proxy_deno/`, `src/`, `tests/`... |
| `COLLAB_BROKER` | relay | 2 | internal | -- |
| `COPILOT` | cli_agent | 3 | interactive | -- |
| `GEMINI` | cli_agent | 1 | interactive | `sandbox/`, `docs/`, `tests/`, `logs/`, `migrations/`... |
| `GEMINI_RELAY` | relay | 2 | internal | -- |
| `MAMMOUTH` | cli_agent | 3 | interactive | `sandbox/`, `docs/`, `tests/` |
| `OPENAI_PROXY` | relay | 2 | internal | -- |
| `OPENCODE` | cli_agent | 1 | interactive | `sandbox/`, `docs/`, `tests/`, `app/web_hub/`, `design_handoff_nokido/` |
| `ROO` | cli_agent | 2 | interactive | -- |
| `SIXTH` | cli_agent | 2 | interactive | -- |
| `TASK_EXECUTOR` | relay | 2 | internal | -- |
| `VIBE` | cli_agent | 1 | interactive | `app/`, `tools/`, `proxy_deno/`, `src/`, `tests/`... |
| `VSCODE` | cli_agent | 1 | interactive | -- |
| `WORKER_CODE` | relay | 2 | autonomous | -- |
| `ZCODE` | cli_agent | 2 | interactive | `reviews/` |

### 1.5 Jalons prioritaires P0 de la roadmap (`docs/roadmap_arbre.json`)

| Item | Etat | Prio | Categorie | Reste |
|---|---|---|---|---|
| `P0_audit_dist_publique_mesure_20261020` | PARTIEL | P0 | autonome P0 | (a) Windows/macOS chiffrement NON_TESTE -> provisionnement CI e7888a61c a publier ; (b) Docker conte |
| `P0_jetons_clients_coffre_seul_rfc_20261024` | PARTIEL | P0 | autonome P0 | MESURER en sandbox ce que Codex desktop sait lire (bearer_token_env_var seul ? commande/helper ?) AV |
| `P0_veille_outils_economie_contexte_20261022` | PARTIEL | P0 | autonome P0 | AUCUN GAIN MESURE : rejouer tools/forge_contexte_par_source.py avant/apres P1a (et un filtre de sort |
| `P0_veracrypt_obligatoire_par_defaut_20261020` | PARTIEL | P0 | autonome P0 | volume chiffre monte portant data/ ; docs / installateur public ; le bilan (refus_consignes) ne dit  |
| `reprise_session_22_10_matin_pilotage` | OUVERT | P0 | autonome P0 | (non dit) |

## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)

> Aucun compteur volatil (nombre de tables, de chunks, de tests, de modules vivants ou d'avancement en %) n'est fige en prose : consulter les sources vivantes ci-dessous.

| Dimension dynamique | Pointeur vers la source vivante | Contrat de lecture |
|---|---|---|
| Etat global du corps et compteurs vivants | `nokido_agent.app.forge_ssot::point` et `hub action=whoami` | lecture temps reel en base |
| Avancement vivant de la roadmap et taches | `tools/forge_roadmap_keeper.py --arbre` (`docs/roadmap_arbre.json`) et `task action=status` (`sandbox/tasks.db`) | liste complete dans `06_PLAN.md` et recalcul vivant |
| Recensement vivant des modules par organe | `tools/forge_module_census.py` (`sandbox/workspace/organ_map_full.json`) | scan AST de `app/` et `tools/` |
| Verification des capacites a chaud | `nokido-doctor --vivant` et `tools/forge_feature_checklist.py` | separe declare / observe / verifie (abstention si sonde muette) |
| Quotas modeles et fournisseurs | `hub action=quota_status` (`nokido_agent.app.forge_quota_tracker`) | etat courant des budgets et replis |
