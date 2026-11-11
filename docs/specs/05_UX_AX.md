# 05 — UX / AX : surfaces agents, CLI, TUI et cockpit web mesures

> Genere par `tools/forge_spec_extractor.py` (introspection deterministe, aucun horodatage) -- commit `bffa9f1a0`. Ne pas editer : relancer l'extracteur.


## 1. ETAT STATIQUE — Contrats AX, CLI/TUI et routes web (genere au commit)

> Surfaces d'interaction et gardes extraits par AST depuis les modules du depot.

### 1.1 AX — Gardes et points d'entree vus par un agent client

- **Admission de job** (`app/forge_job_runner.py`) : `admettre_lancement` (`app/forge_job_runner.py:116`)
- **Regulateur de lanes** (`app/forge_lane_admission.py`) : `check_ressources` (`app/forge_lane_admission.py:539`), `admit` (`app/forge_lane_admission.py:644`)
- **Ecriture gouvernee** (`tools/forge_governed_edit.py`) : `governed_write` (`tools/forge_governed_edit.py:341`)
- **Garde shell PreToolUse** (`tools/bash_guard.py`) : `segment_ok` (`tools/bash_guard.py:247`)
- **Garde fin de tour Stop** (`tools/hook_stop_attente_passive.py`) : `main` (`tools/hook_stop_attente_passive.py:202`)
- **Garde memoire PreToolUse** (`tools/hook_recon_first.py`) : `main` (`tools/hook_recon_first.py:270`)
- **Ordres bureau / Tray** (`app/forge_ordres_bureau.py`) : `demander_ordre` (`app/forge_ordres_bureau.py:558`), `commandes_en_attente` (`app/forge_ordres_bureau.py:317`)
- **Contrats MCP** (`tests/schemas_mcp_structure.json`) : `absorb_rfc_knowledge`, `acp`, `agy_add_dir`, `agy_config`, `agy_run`, `ask`, `auto_ingest`, `auto_test`, `biblio`, `blackboard_propose_fact`, `blackboard_read_zone`, `bundle`, `crawl`, `cross_platform_fs`, `delegate_to_local_scout`, `docker_action`, `event`, `forge_call_dynamic`, `forge_deep_explore`, `forge_list_dynamic_tools`, `forge_spawn_swarm`, `forge_stats`, `forge_trigger_audit`, `get_file_skeleton`, `get_function_dependencies`, `github`, `governed_edit`, `graph_cve_propagate`, `graph_edge_score`, `graph_ppr`, `hub`, `introspect`, `loop_orchestrate`, `manage_forge_lifecycle`, `md`, `memory`, `netcfg`, `nokido_ensure_service`, `oracle_python_repl`, `orchestrate`, `plan`, `query`, `query_documentation`, `query_local_json`, `rag`, `read`, `read_function_body`, `research_agent`, `route_task`, `run`, `search_local_file`, `secret`, `skill`, `task`, `tool_scope`, `trigger_autonomous_evolution`, `web_search`, `write`

### 1.2 UX CLI, TUI et sondes de surfaces (`tools/forge_feature_checklist.py`, `tools/llama_cli.py`, `tools/nokido_tui.py`, `tools/forge_job_watch_cli.py`)

- **Sondes de surfaces** (`tools/forge_feature_checklist.py`) : `section_cli_entrypoints` (`:153`), `section_cli_nokido` (`:176`), `section_tools_cli` (`:222`), `section_services` (`:329`), `section_http_gui` (`:406`), `section_organique` (`:710`), `section_rest` (`:829`), `section_tui_nokido` (`:868`), `section_tui_legacy` (`:924`), `section_mcp` (`:967`), `section_organes` (`:1019`), `section_skills` (`:1048`)
- **Sous-commandes `nokido`** (`tools/llama_cli.py`) : `ask`, `chat`, `hub`, `metrics`, `models`, `props`, `slots`, `status`, `tools`, `ultra`
- **Commandes TUI** (`tools/nokido_tui.py`) : `/help`
- **Surveillance CLI** (`tools/forge_job_watch_cli.py`) : `lire_bilan` (`:480`), `main` (`:838`)

### 1.3 UX Cockpit Web — Pages et flux SSE (`app/web_hub/app.py`, `app/web_hub/wired_routes.py`)

| Methode | Route | Handler | Source |
|---|---|---|---|
| `GET` | `/` | `root_redirect` | `app/web_hub/app.py:1489` |
| `GET` | `/anatomy` | `anatomy_page` | `app/web_hub/app.py:1302` |
| `GET` | `/api/vitals/sse` | `vitals_sse` | `app/web_hub/app.py:1136` |
| `GET` | `/auth/login` | `auth_login_form` | `app/web_hub/app.py:1831` |
| `POST` | `/auth/login` | `auth_login` | `app/web_hub/app.py:1845` |
| `GET` | `/dashboard` | `dashboard` | `app/web_hub/app.py:1495` |
| `GET` | `/hub` | `hub_shell` | `app/web_hub/app.py:1503` |
| `GET` | `/launcher` | `launcher_page` | `app/web_hub/app.py:2156` |
| `GET` | `/organs` | `organs_page_route` | `app/web_hub/app.py:720` |
| `GET` | `/reports` | `reports_page` | `app/web_hub/app.py:1780` |
| `GET` | `/vitals` | `vitals_page` | `app/web_hub/app.py:1243` |
| `GET` | `/api/swarm/stream` | `swarm_stream` | `app/web_hub/wired_routes.py:596` |
| `GET` | `/postal` | `postal_page` | `app/web_hub/wired_routes.py:750` |
| `GET` | `/rag` | `rag_page` | `app/web_hub/wired_routes.py:734` |
| `GET` | `/roadmap/arbre` | `roadmap_arbre_page` | `app/web_hub/wired_routes.py:432` |
| `GET` | `/swarm` | `swarm_page` | `app/web_hub/wired_routes.py:742` |

## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)

> La disponibilite des pages, l'etat des controles JS/HTMX, les outils MCP servis a chaud et les flux SSE relevent de l'execution et se lisent via leurs sondes vivantes.

| Surface dynamique | Pointeur vers la source vivante | Contrat de lecture |
|---|---|---|
| Etat des surfaces GUI (`live` / `dormant` / `absent`) | `tools/forge_ui_manifest.py --json` et `tools/forge_feature_checklist.py::section_http_gui` | distingue backend actif, dormant on-demand et absent |
| Cablage des controles et pages web | `tools/forge_ui_nervous_census.py` (`sandbox/workspace/ui_audit/ui_contract_generated.json`) | mesure datee ISO ; refuse de conclure si age > 24 h |
| Inventaire MCP servi a chaud | `POST http://127.0.0.1:8766/mcp` (`tools/list`, `tools/forge_feature_checklist.py::section_mcp`) | confronte le serveur vivant a `.mcp.json` |
| Flux SSE et sante du cockpit web | `GET /api/vitals/sse`, `GET /api/swarm/stream`, `GET /status` (`:7400`) et `GET /health` (`:8766`) | flux temps reel sous semaphore |
| File d'ordres operateur au Tray | `hub action=demander_ordre ordre=commandes-en-attente` (`logs/commandes_owner.jsonl`) | sépare `DEPOSE` (attente validation) et `FAITE` |
