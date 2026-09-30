---
type: reference
title: Modules Reference
status: stable
resource: repo://docs/wiki/20-Modules-Reference.md
generated: {by: forge_wiki_modules@d0a365137a19c8a09878c645e7af9387cbf47a5d, at: 2026-09-29T15:31:25+00:00}
empreinte: 565a8efbca56c648
---
<!-- nokido:genere outil=tools/forge_wiki_modules.py sha=d0a365137a19c8a09878c645e7af9387cbf47a5d le=2026-09-29T15:31:25Z empreinte=565a8efbca56c648 -->

# 20 — Modules Reference

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

> 🌐 **English** · [Français](20-Modules-Reference.fr.md)

> **GENERATED page** — produced by `tools/forge_wiki_modules.py`. Do
> not edit by hand: any correction goes into the **module docstring**,
> the single source of truth. A definition copied here would drift
> from the code within a week.
>
> Generated from commit `d0a365137a19c8a09878c645e7af9387cbf47a5d` on 2026-09-29T15:31:25Z. If this commit is not the current HEAD, this page describes an EARLIER state of the code: regenerate rather than annotate.

Each definition is the first sentence of the module docstring, as
written by its author — never a paraphrase of the file name. It is
quoted verbatim, in the language it was written in (mostly French):
a translation here would be a second source, drifting from the code.
Modules **without a docstring** are listed at the end of the page:
they are measured documentation gaps, not display omissions.

**2449 modules** scanned in `app/`, `tools/`, `forge_desktop/` (excluding `_attic`) — **1598 defined (65.3%)**, **851 without a docstring**.

The public symbols listed are the API the module exposes (top-level
functions and classes without a leading underscore): what a caller
can use without reading the implementation.

## Infra/Bootstrap/Config

*217 modules · 43,172 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/__init__.py` | app/ - Package principal Nokido | — | 23 |
| `app/agents/__init__.py` | app/agents/ — Facade d'acces unifiee aux modules agentiques Nokido | — | 137 |
| `app/api_facade.py` | Facade API unifiee pour Nokido (decouplage UI/backend) | `NokidoFacade`, `get_facade`, `AsyncNokidoFacade`, `get_async_facade` | 430 |
| `app/collab_modes/__init__.py` | Package app.collab_modes - Orchestration de sessions de collaboration multi-agent | — | 123 |
| `app/core/__init__.py` | app/core/ - Fondations: bootstrap, settings, logging, state, context | — | 13 |
| `app/core/settings/__init__.py` | app/core/settings/ - Split de forge_settings.py par domaine | — | 124 |
| `app/forge_build_repair.py` | Boucle build-repair CAPABILITY-ADAPTIVE pour code généré | `RepairPolicy`, `validate`, `quality_gate_validator`, `deterministic_fix` *(+2)* | 237 |
| `app/forge_cache.py` | Cache unifie Nokido (LRU/TTL/LFU) | `make_cache` | 115 |
| `app/forge_configurator.py` | Phase 4 - AMI roadmap: Configurator dynamique | `classify_task`, `configure`, `configure_from_description`, `get_mpc_config` *(+2)* | 230 |
| `app/forge_db.py` | Connexion SQLite centralisée avec PRAGMAs optimaux ================================================================ Remplace sqlite3.connect() direct partout dans le codebase | `get_conn`, `get_conn_readonly`, `quick_read`, `quick_write` | 96 |
| `app/forge_db_conn.py` | Point de connexion DB CENTRAL (fondation at-rest SQLCipher) ============================================================================ Pourquoi ce module ------------------ Le code Nokido ouvre ~631 connexions sqlite3 directes réparties sur ~340 fichiers (au | `is_sqlcipher_available`, `resolve_key`, `db_engine`, `get_db` | 242 |
| `app/forge_drapeau_env.py` | Lire un drapeau booleen d'environnement — une seule fois pour le corps | `declare`, `actif`, `etat` | 80 |
| `app/forge_engrid_bridge.py` | Pont entre le cycle autonome et l'architecture Engrid =============================================================================== Remplace les appels LLM directs du cycle (Generator.generate, ollama_call) par un routage intelligent via SpikeRouter → MetaCo | `engrid_generate`, `engrid_audit`, `engrid_analyze`, `patch_task_worker` | 337 |
| `app/forge_env_alias.py` | shim de renommage progressif LAFORGE_* -> NOKIDO_* (dual-read) | `apply` | 50 |
| `app/forge_health_diagnostic.py` | Diagnostic de santé Nokido (lacunes + métriques) | `audit_rag_chunks`, `audit_biblio`, `audit_messages`, `audit_tables_empty` *(+18)* | 2378 |
| `app/forge_host_capabilities.py` | Detection capacite hote Nokido ============================================================= Determine ce que la machine hote peut faire tourner localement (CPU+RAM+VRAM+disk) | `detect_host`, `get_host_info`, `can_run_locally`, `list_runnable_models` *(+1)* | 370 |
| `app/forge_hw_allocator.py` | DEPRECATED: forge_hw_allocator.py → app/hardware/allocator.py This is a backward-compatibility stub | — | 24 |
| `app/forge_install_prerequis.py` | registre des prerequis EXTERNES de Nokido, et sonde de presence | `etat_toml_services`, `verifier`, `verifier_modeles`, `exes_declares_dans_services` *(+4)* | 635 |
| `app/forge_lifecycle_tool.py` | MCP tool: manage_forge_lifecycle =========================================================== Façade unifiée START/STOP/RESTART/STATUS/LIST/SHUTDOWN_ALL/BOOT_ALL des services Nokido | `handle_manage_forge_lifecycle` | 364 |
| `app/forge_llm_format_bridge.py` | moteur partagé des ingress LLM-API multi-format | `load_token`, `hub_call`, `messages_to_prompt`, `AskResult` *(+3)* | 223 |
| `app/forge_machine_vault.py` | coffre de secrets cross-OS | `resoudre_chemin_coffre`, `chemin_coffre`, `available`, `vault_get` *(+7)* | 547 |
| `app/forge_python_bin.py` | Source de vérité pour l'interpréteur Python ====================================================================== Garantit que tout subprocess Python utilise miniforge3 (l'env Nokido), pas un `python` ambigu du PATH | `run_python`, `popen_python` | 67 |
| `app/forge_symbiotic_bridge.py` | Pont Cloud-Local Synchrone pour Nokido | `SymbioticBridge` | 117 |
| `app/forge_trauma_vault.py` | Nokido Engrid v3 · Sprint 3 ====================================================== TraumaVault : mémoire des échecs avec plasticité STDP et protection topologique par winding_count (skyrmion-inspired) | `TraumaRecord`, `STDPEvent`, `TraumaVault` | 400 |
| `app/forge_utf8_bootstrap.py` | bootstrap UTF-8 process-wide (Windows), import-first | `apply`, `child_env` | 72 |
| `app/hardware/__init__.py` | app/hardware/ — Allocation NPU/GPU/CPU, monitors, watchdogs Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/llm/__init__.py` | app/llm/ — Routeurs LLM multi-provider Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/llm/backends/__init__.py` | app/llm/backends/ — Backends specifiques (Ollama, llama.cpp, Gemini, LiteLLM) Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/netcfg_silo_bridge.py` | Pont netcfg-agent-mcp <-> SiloEngine Nokido ======================================================================== Orchestration : 1 | `fetch_netcfg_snapshot`, `audit_parc_netcfg`, `audit_parc_netcfg_sync`, `ingest_netcfg_deploys` | 476 |
| `app/orchestration/__init__.py` | app/orchestration/ — Orchestrateur principal, modes collab, dispatcher Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/protocols.py` | Interfaces (typing.Protocol) pour casser les cycles d'import | `LLMBridgeProtocol`, `AppContextProtocol`, `VersionManagerProtocol`, `WebSearchProtocol` *(+1)* | 107 |
| `app/rag/__init__.py` | app/rag/ — Retrieval-Augmented Generation (SQLite WAL, embeddings) Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/security/__init__.py` | app/security/ — DangerGuard, sandbox, AST analyzer Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/tui_adapters/__init__.py` | TUI adapters — pure read/action layer pour nokido_tui v3 | — | 6 |
| `app/ui/__init__.py` | app/ui/ — Interface utilisateur Textual TUI Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini) | — | 7 |
| `app/web_hub/__init__.py` | app/web_hub/ - Hub FastAPI unifie Nokido | — | 24 |
| `forge_desktop/__init__.py` | forge_desktop/__init__.py Forge-Sync OS | — | 7 |
| `forge_desktop/core/__init__.py` | forge_desktop/core/__init__.py | — | 4 |
| `forge_desktop/views/__init__.py` | forge_desktop/views/__init__.py | — | 4 |
| `forge_desktop/widgets/__init__.py` | forge_desktop/widgets/__init__.py | — | 4 |
| `tools/_patch_deep_explore.py` | migration #1+#2 : enregistre l'outil honeypot `forge_deep_explore` + insère le coupe-circuit comportemental serveur dans app/forge_mcp_registry.py | — | 165 |
| `tools/_patch_deep_explore_v2.py` | durcit #1+#2 après test live : (A) breaker : verdict_mem (in-mem, fail-open silencieux) -> verdict() FS partagé (cross-process) + LOG chaque décision dans C:/tmp/recon_breaker.log (observable) | — | 147 |
| `tools/_patch_ensure_service.py` | enregistre le Bouton Rouge nokido_ensure_service dans forge_mcp_registry : catalogue + _TOOL_MIN_RING + _TOOLS_PUBLIC + dispatch + handler | — | 126 |
| `tools/_patch_explore_collecte.py` | patch ponctuel : découpler COLLECTE et AFFICHAGE dans deep_explore | `main` | 101 |
| `tools/_patch_explore_ranking.py` | patch ponctuel : classement du digest de forge_deep_explore | `main` | 99 |
| `tools/_patch_nssm_gemini.py` | Patch + start LaForgeGeminiDaemon NSSM service via direct subprocess | `run` | 39 |
| `tools/_patch_tray.py` | laforge_tray.py — Icône tray Windows Nokido | — | 5 |
| `tools/arm_applier.py` | arme l'etage REFLEXE de l'applicateur (owner 2026-08-27) | `main` | 45 |
| `tools/autotools.py` | Nokido v1.0 ============================================ Package central de tous les outils du projet, exposés comme commandes @ natives | `Tool`, `run_index`, `run_index_continue`, `run_diag_npu` *(+32)* | 938 |
| `tools/build_bge_m3_dml.py` | BGE-M3 embeddings via ORT DirectML (Radeon 780M iGPU) | `export_onnx`, `load_session`, `tokenize_batch`, `mean_pool` *(+3)* | 283 |
| `tools/build_dist.py` | build REPRODUCTIBLE de la distribution propriétaire | `build_pyarmor`, `build_nuitka`, `main` | 122 |
| `tools/deploy_modal_bge_m3.py` | Deploy BGE-M3 sur Modal serverless A10G GPU | `BgeM3Embedder` | 100 |
| `tools/diag_searxng.py` | Diag SearXNG :8080 | `get`, `main` | 32 |
| `tools/dispatch_migration_tasks.py` | Inject migration tasks dans mailbox agent_messages | `dispatch_task`, `status`, `main` | 298 |
| `tools/forge_adb.py` | pont ADB privilegie pour Nokido (compte LaForgeTrusted) | `device`, `cmd_devices`, `cmd_connect`, `cmd_pair` *(+8)* | 215 |
| `tools/forge_anon_push.py` | push ANONYMISE vers le remote public | `git`, `run`, `main` | 235 |
| `tools/forge_arch_schema.py` | schéma d'architecture Nokido COMPLET + souverain (zéro backend) | `main` | 160 |
| `tools/forge_auth_debug.py` | CLI debug auth : check token validity sans le leaker | `main` | 114 |
| `tools/forge_backup_hotswap.py` | Nokido Hot-Swap Backup Module ========================================================== DATE: 2026-07-01 CONTEXTE -------- Disque cible : "Grodata" (F:), tiroir SATA interne hot-swap, NTFS, GPT, ~3726 Go, Disque 4 (diskpart) | `DiskIdentityError`, `verify_disk_hardware`, `verify_disk_identity`, `disk_online` *(+13)* | 715 |
| `tools/forge_bench_diagnose.py` | Diagnostic cohérence des embeddings du corpus RAG | `main` | 115 |
| `tools/forge_boot_diagnostic.py` | diagnostic démarrage + TRACKER résiduel Nokido | `logs_nssm`, `snapshot`, `diff`, `main` | 470 |
| `tools/forge_boot_syntax_check.py` | Preflight AST au boot | `scan`, `main` | 74 |
| `tools/forge_bridge_ack.py` | CLI OWNER : revue + EXÉCUTION des requêtes ADMIN du pont | `cmd_list`, `cmd_allow`, `cmd_deny`, `main` | 114 |
| `tools/forge_bridge_habilitation.py` | emet une habilitation pour la passerelle GitHub | `frapper_la_clef`, `emettre`, `main` | 184 |
| `tools/forge_bridge_launch.py` | Lance la passerelle MCP avec ses secrets lus au COFFRE, jamais depuis le TOML | `racine`, `lire`, `decider_lancement`, `environnement` *(+3)* | 240 |
| `tools/forge_bridge_oauth.py` | autorite OAuth locale, adossee a l'habilitation existante | `depot_unique`, `fichier_des_clients`, `client_preenregistre`, `code_d_appariement` *(+8)* | 722 |
| `tools/forge_bump_superrepo.py` | reaccroche le pointeur de submodule du superrepo | `say`, `git`, `publier`, `main` | 395 |
| `tools/forge_cffi_probe.py` | sonde DIAGNOSTIC : cffi charge-t-il dans CE contexte d'exécution ? Distingue 'artefact du sandbox offline le plus verrouillé' vs 'tous les contextes restreints échouent' | — | 17 |
| `tools/forge_cli_clean_setup.py` | Construit des configs CLI PROPRES (auth SEULE, sans CLAUDE.md/GEMINI.md/hooks/MCP) pour que claude_cli/gemini_cli répondent en LLM BRUT (pas en agent Nokido qui s'init) -> indispensable au patch-gen SWE (best-of-N) | `clean_copy` | 90 |
| `tools/forge_client_bootstrap.py` | (DEPORTED — dry-run par defaut, 0 ecriture config) Orchestrateur d'onboarding/harmonisation client<->hub Nokido | `L`, `rd`, `parse_any`, `find_hub_server` *(+6)* | 282 |
| `tools/forge_coffre_reserve_provision.py` | provisionner le coffre RESERVE (etape 2a du correctif du coffre, go owner 2026-09-28) | `calculer_cibles`, `planifier`, `planifier_nouvelles`, `main` | 258 |
| `tools/forge_connect_clients.py` | branche les 7 clients MCP au hub Nokido (direct, par-agent) | `main` | 135 |
| `tools/forge_db_backup.py` | Backup nightly embeddings.db (SQLite Online Backup + zstd) | `online_backup`, `compress_zstd`, `rotate_backups`, `main` | 163 |
| `tools/forge_db_bootstrap.py` | Restore DB depuis `data/seed/*.jsonl` git-tracked | `import_jsonl`, `main` | 157 |
| `tools/forge_db_check.py` | Checkpoint WAL + etat reel du tier vectoriel | `main` | 36 |
| `tools/forge_db_clean_install.py` | pose propre de la good DB a RAG/embeddings.db | `locked`, `main` | 70 |
| `tools/forge_db_compact.py` | Cleanup + VACUUM embeddings.db | `db_size`, `freelist_bytes`, `drop_janitor`, `purge_snapshots` *(+4)* | 199 |
| `tools/forge_db_compact_full.py` | Cycle complet purge+vacuum avec orchestration hub | `main` | 174 |
| `tools/forge_db_contention_report.py` | etat RUNTIME des bases, publiable | `rapport`, `main` | 284 |
| `tools/forge_db_encrypt_migrate.py` | Migration at-rest SQLCipher d'une DB sqlite | `cmd_dry_run`, `cmd_migrate`, `cmd_verify`, `main` | 216 |
| `tools/forge_db_instant_swap.py` | swap instantane (rename) de la good DB pre-stagee | `locked`, `main` | 50 |
| `tools/forge_db_merge_final.py` | fusionne les 2 recoveries en UNE base finale complète | — | 117 |
| `tools/forge_db_postswap.py` | finalisation post-restart du hub (V: deverrouillee) | `safe_count`, `main` | 105 |
| `tools/forge_db_preflight.py` | self-heal de la DB RAG au démarrage du hub | `relocate_if_symlink`, `boot_db`, `self_heal` | 289 |
| `tools/forge_db_recover.py` | Recovery de %NOKIDO_DATA%\embeddings.db corrompue (Bad ptr map / rowid out of order) | `copy_table`, `main` | 107 |
| `tools/forge_db_recover_gold.py` | filtre tolérant du dump `sqlite3 .recover` | `main` | 107 |
| `tools/forge_db_router.py` | Routeur hybride SQLite/DuckDB avec connexions persistantes ================================================================================ Résout le problème de latence DuckDB sur les SELECT simples en maintenant des connexions persistantes et en routant inte | `ForgeDBRouter`, `get_db_router` | 327 |
| `tools/forge_db_seed_export.py` | Export précieux DB vers JSONL git-trackable | `export_table`, `main` | 199 |
| `tools/forge_db_swap.py` | swap de la DB recoveree en live, relocalisee sur C: (marge) | `main` | 67 |
| `tools/forge_db_writetest.py` | Diagnostic : pourquoi les writes embedding ne persistent pas | `main` | 55 |
| `tools/forge_dev_mode.py` | arm/disarm the privileged-execution escape hatch | `arm`, `disarm`, `is_armed`, `main` | 249 |
| `tools/forge_dist_install_probe.py` | ce qu'une WHEEL INSTALLEE sait reellement faire | `imports_plats_du_depot`, `sonder`, `rendre`, `main` | 302 |
| `tools/forge_dist_publish.py` | recurring publish of one version into the persistent, SEPARATE distribution repo (nokido-dist) | `run`, `ensure_dist_repo`, `generiser_texte`, `sync_snapshot` *(+7)* | 1128 |
| `tools/forge_echo_argv.py` | smoke-test pour l'action hub trusted_script | — | 15 |
| `tools/forge_ensure_service.py` | BACKEND du « Bouton Rouge » MCP nokido_ensure_service | `declencher_tache`, `marquer_usage`, `marquer_pilotage`, `est_pilote` *(+3)* | 979 |
| `tools/forge_env_backup_relocate.py` | Deplace les backups plaintext laisses par forge_vault_migrate dans _backups/secrets/ (gitignore) | `main` | 41 |
| `tools/forge_env_drop_key.py` | Retire UNE cle de Nokido.env — et seulement si le coffre la detient deja | `main` | 142 |
| `tools/forge_env_key_names.py` | Liste les NOMS de variables de Nokido.env (JAMAIS les valeurs) | — | 28 |
| `tools/forge_env_recomment_openrouter.py` | One-shot : re-commente la ligne OPENROUTER_API_KEY de Nokido.env | — | 33 |
| `tools/forge_env_to_vault.py` | migre les secrets du .env vers le coffre DPAPI, SANS CASSE | `lire_env`, `main` | 338 |
| `tools/forge_fix_services_dup.py` | one-shot IDEMPOTENT : nettoie les [[service]] dupliques de proxy_deno/core/services.toml, et repare le texte parasite laisse par un governed_edit multi-blocs (2026-07-17) | `spans`, `has`, `name_of`, `effective` *(+1)* | 184 |
| `tools/forge_fix_worktree_link.py` | raccorder le worktree orphelin | `main` | 57 |
| `tools/forge_go_service_deploy.py` | Deploie un binaire Go compile vers son emplacement de service, sous compte privilegie | `deployer`, `main` | 153 |
| `tools/forge_hide_service_accounts.py` | masque les comptes de service Nokido de l'écran de connexion / verrouillage Windows et rend la tâche onlogon Caddy silencieuse (relance via pythonw, sans fenêtre console) | `main` | 164 |
| `tools/forge_hooks_install.py` | installe le FILET de gardes chez qui clone le depot | `etat`, `elague`, `applique`, `main` | 249 |
| `tools/forge_install_boot_mount.py` | Installeur boot du montage at-rest, CROSS-OS | `cmd_install`, `cmd_uninstall`, `cmd_status`, `main` | 322 |
| `tools/forge_kaggle_cfg_from_env.py` | One-shot : fabrique C:/tmp/kaggle_cfg/kaggle.json depuis la cle regeneree de Nokido.env (KAGGLE_API_TOKEN, 2026-07-06) | — | 31 |
| `tools/forge_m2m_bridge.py` | passerelle M2M : lire le bus inter-agents, y emettre | `agents_autorises`, `plafond_par_heure`, `chemin_du_bus`, `traiter` | 309 |
| `tools/forge_migrate_kaggle_vault.py` | One-shot : migre KAGGLE_API_TOKEN de Nokido.env vers le coffre DPAPI, verifie la lecture coffre, PUIS re-commente la ligne du .env (clef en clair inerte) | — | 46 |
| `tools/forge_migrate_metadata.py` | Colonnes generees ext/folder/lang + index | `main` | 93 |
| `tools/forge_migrate_origin.py` | Migration : ajoute la colonne `origin` a rag_chunks | `main` | 55 |
| `tools/forge_modal_auth_bootstrap.py` | Bootstrap Modal : .env -> coffre DPAPI -> CLI authentifie | `main` | 129 |
| `tools/forge_modal_diag.py` | Diagnostic Modal : sommes-nous authentifies, et l'endpoint est-il deploye ? Modal s'authentifie de DEUX facons : un fichier `~/.modal.toml` (ecrit par `modal token new\|set`) ou le couple d'env `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` | `main` | 125 |
| `tools/forge_npu_repair_env.py` | Reunir les deux moities du SDK Ryzen AI dans le MEME environnement | `main` | 82 |
| `tools/forge_nssm_env_fix.py` | Propagate API keys / tokens to NSSM-managed Nokido services | `get_service_list`, `set_env_for_service` | 117 |
| `tools/forge_nssm_hardening.py` | NSSM hardening Nokido — anti crash-loop config | `list_services`, `nssm_get`, `nssm_get_exit`, `nssm_set` *(+3)* | 164 |
| `tools/forge_obs_setup.py` | stack observabilité LIBRE (OTel emitter + Jaeger) | `main` | 52 |
| `tools/forge_owner_bridge.py` | pont OWNER-CONTEXT : exécute des commandes dans la SESSION CONSOLE de l'owner (user) depuis le hub SYSTEM | `run_in_owner`, `probe`, `main` | 142 |
| `tools/forge_owner_daemons.py` | launcher OWNER unique (lancé en pythonw = windowless) | `main` | 127 |
| `tools/forge_patch_agy_bin_resolution.py` | One-shot patcher : resolution du binaire AGY dans app/forge_mcp_registry.py | — | 78 |
| `tools/forge_patch_agy_perimetre.py` | __FORGE_COLOR__ = "immunitaire/perimetre-agy" PATCH app/forge_mcp_security.py (CRITICAL_FILE) : aligner le perimetre d'ecriture d'ANTIGRAVITY sur le SSoT des identites | `main` | 135 |
| `tools/forge_patch_authz_shadow.py` | Patch CRITICAL_FILE : point d'observation d'autorisation sur :8766 (SHADOW) | `main` | 149 |
| `tools/forge_patch_authz_via_reel.py` | Patch CRITICAL_FILE : le journal d'autorisation distingue MAITRE et DERIVE | `main` | 150 |
| `tools/forge_patch_dedup_gui8766.py` | One-shot patcher: dedup GUI Phase 6 — :8766 /forge/{rag,swarm,postal} -> 302 :7400 | — | 80 |
| `tools/forge_patch_dense_reclaimer.py` | declare le cache dense comme RAM reclamable | `main` | 112 |
| `tools/forge_patch_dense_satiety.py` | satiete sur la construction du cache dense | `main` | 107 |
| `tools/forge_patch_env_alias.py` | patcher one-shot (CRITICAL_FILE) : cable forge_env_alias au boot du hub, juste apres le chargement de Nokido.env | `main` | 47 |
| `tools/forge_patch_git_encoding.py` | décodage tolérant pour le git de trusted_script | `main` | 104 |
| `tools/forge_patch_job_stop_route.py` | expose l'arret d'un job sur le hub | `main` | 117 |
| `tools/forge_patch_lane_auto.py` | lane DEDUITE quand l'appelant n'en fournit pas | `applique`, `main` | 82 |
| `tools/forge_patch_login_dpop.py` | Patch de `/api/login` : transporter la cle du porteur (RFC 9449) | `main` | 102 |
| `tools/forge_patch_m2m_routing.py` | Patcher one-shot CRITICAL_FILE : routage M2M vers AGY | `apply_block`, `main` | 80 |
| `tools/forge_patch_muted_paths.py` | __FORGE_COLOR__ = "immunitaire/chemins-muets" PATCH : rend visibles les chemins d'erreur muets des FICHIERS CRITIQUES | `appliquer`, `campagne`, `main` | 274 |
| `tools/forge_patch_organs_route.py` | ajoute les routes /organs a web_hub/app.py | `main` | 84 |
| `tools/forge_patch_poll_ack.py` | rend l'accusé de réception OPTIONNEL sur `poll` | `main` | 89 |
| `tools/forge_patch_presence_namespace.py` | patcher one-shot (2026-07-26) | `apply` | 119 |
| `tools/forge_patch_run_network_contract.py` | Contrat d'appel du tool `run` : declarer `network`, et dire ce que `sandbox` N'EST PAS | `main` | 131 |
| `tools/forge_patch_sandbox_failopen.py` | P0 SECURITE — fermer le fail-open du dispatch `sandbox` (mesure 2026-09-01) | `main` | 182 |
| `tools/forge_patch_socle.py` | le patron commun aux patchs de CRITICAL_FILE | `appliquer`, `rapporter` | 72 |
| `tools/forge_patch_sse_leak.py` | __FORGE_COLOR__ = "observabilite/sse-fuite" PATCH tools/nokido_hub.py (CRITICAL_FILE) : fuite des abonnes SSE, angle mort total du journal, et ring de repli fail-OPEN | `main` | 276 |
| `tools/forge_patch_subprocess_errors.py` | __FORGE_COLOR__ = "immunitaire/decodage-subprocess" PATCH : `subprocess` en mode texte SANS `errors=` -> plantage du thread lecteur | `main` | 207 |
| `tools/forge_patch_tail_logs.py` | patcher one-shot du handler `read action=tail_logs` (app/forge_mcp_registry.py est CRITICAL_FILE : governed_edit refuse, le chemin officiel est un patcher committe lance en trusted_script) | `main` | 152 |
| `tools/forge_patch_task_assign_desc.py` | `task action=assign` perdait l'enonce de la tache : lecture d'une clé absente | `main` | 73 |
| `tools/forge_patch_task_result_clobber.py` | Patcheur one-shot : l'accuse M2M n'ecrase plus la reponse complete d'une tache | `main` | 93 |
| `tools/forge_patch_tool_annotations.py` | Patch CRITICAL_FILE : cable l'injection des annotations MCP dans le registre | `main` | 130 |
| `tools/forge_patch_via_capability.py` | Patch du middleware SHADOW : distinguer un jeton a bail d'un inconnu | `main` | 119 |
| `tools/forge_patch_vitals_sse.py` | borner le flux SSE des vitaux | `applique`, `main` | 121 |
| `tools/forge_patch_wasm_parsing.py` | one-shot : corrige le parsing sandbox=wasm | `main` | 60 |
| `tools/forge_patch_wasm_routing.py` | one-shot : un TYPE de sandbox explicite prime | `main` | 74 |
| `tools/forge_patch_whoami_tasks_unclaimed.py` | Patcheur one-shot : whoami signale les taches DEPOSEES mais jamais RECLAMEES | `main` | 115 |
| `tools/forge_path_portabilize.py` | make hardcoded home paths portable | `tracked_files`, `py_transform`, `simple_sub`, `main` | 127 |
| `tools/forge_pip_ensure.py` | installe un paquet manquant dans un env Python cible | `main` | 35 |
| `tools/forge_privileged_bridge.py` | pont GOUVERNÉ de commandes privilégiées | `sign_request`, `verify_request`, `enqueue_pending`, `govern` *(+9)* | 555 |
| `tools/forge_process_manager.py` | Gestionnaire unifie des process Nokido v18.3 Remplace: launcher.py + restart_claude.py + tray Popen + services_launcher (partiel) | `port_pid`, `kill_port`, `restart_hub`, `worker_status` *(+3)* | 179 |
| `tools/forge_provision_clients.py` | provisionne les tokens par-agent + émet les configs client | `main` | 325 |
| `tools/forge_proxy_reload.py` | recharge un service proxy local (defaut forge_openai_proxy :7777) | `reload_proxy`, `main` | 66 |
| `tools/forge_public_mirror.py` | fabrique un SNAPSHOT public sans historique | `classer_fuite`, `construire`, `historique_nettoye`, `main` | 551 |
| `tools/forge_push_sovereign.py` | pousse une branche vers GitHub + Codeberg en lisant les tokens AU VAULT | `git`, `say`, `refspec`, `main` | 329 |
| `tools/forge_py314t_flip_canary.py` | Acte 5 partial flip canary, rollback-safe | `phase1_baseline`, `phase2_flip`, `phase3_monitor`, `phase4_commit` *(+2)* | 319 |
| `tools/forge_py314t_readiness.py` | Per-workload py314t readiness probe + auto-trigger | `probe_module_import`, `hub_notify`, `parallelisme_mesure`, `deps_de_travail` *(+2)* | 352 |
| `tools/forge_pypi_baseline.py` | PHASE 3 : l'etat AVANT, mesure et rejouable | `classer_import`, `compter_imports`, `baseline`, `main` | 153 |
| `tools/forge_pypi_freshvenv.py` | PHASE 8 : la preuve se fait HORS du checkout | `verdict`, `main` | 233 |
| `tools/forge_release_assets.py` | build the DOWNLOADABLE release assets for v0.1 | `sha256_file`, `build_code_tarball`, `build_rag_pack`, `write_vendor_lock` *(+4)* | 302 |
| `tools/forge_release_lock.py` | __FORGE_COLOR__ = "infra/deploy : verrou de composition, combinaison exacte des composants" RELEASE LOCK — la combinaison EXACTE des composants, et si elle a ete testee | `composition`, `gate_coherence`, `CompositionIllisible`, `emettre` *(+2)* | 519 |
| `tools/forge_restore_from_head.py` | restaure UN fichier tracke depuis HEAD | `main` | 44 |
| `tools/forge_retrieval_baseline.py` | Gel de la BASELINE de ranking de `RAGEngine.search` — temoin experimental | `main` | 236 |
| `tools/forge_rule_distiller.py` | distiller un GARDE depuis un correctif reel | `fichiers_corriges`, `source`, `racines_importees`, `appels` *(+8)* | 327 |
| `tools/forge_runas_launcher.py` | de-privilege + Job-Object launcher for the Nokido supervisor `runAs` field | `main` | 284 |
| `tools/forge_sandbox_setup.py` | provision the Nokido code-execution sandbox | `ps`, `is_admin`, `user_exists`, `ensure_user` *(+12)* | 515 |
| `tools/forge_seed_nokido_entity.py` | 3b rebrand : ajoute l'entity RBAC wrk_nokido comme MIROIR EXACT de wrk_laforge (ring 0, hub souverain) dans forge_entities (embeddings.db) | `main` | 47 |
| `tools/forge_service_ondemand.py` | bascule des services en ON-DEMAND | `main` | 110 |
| `tools/forge_snn_vitals_baseline.py` | Baseline : un LIF integrateur detecte-t-il la detresse RAM plus TOT qu'un seuil ? Question | `episodes_detresse`, `detecteur_seuil`, `detecteur_lif`, `detecteur_monitor_prod` *(+3)* | 371 |
| `tools/forge_switches_db_split.py` | sortir `access_switches` de la base du RAG | `copier`, `verifier`, `main` | 150 |
| `tools/forge_tui.py` | Nokido terminal dashboard (stdlib only, no curses/rich/textual) | `check_services`, `get_heartbeats`, `get_rag_status`, `get_git_info` *(+3)* | 235 |
| `tools/forge_vault_migrate.py` | migration des SECRETS Nokido.env -> coffre | `is_secret`, `parse_env`, `cmd_check`, `cmd_migrate` *(+2)* | 329 |
| `tools/forge_vault_set_config.py` | Pose une valeur de CONFIGURATION au coffre — jamais un secret | `ressemble_a_un_secret`, `main` | 93 |
| `tools/forge_vendor_asset.py` | vendor a CDN/web asset into app/web_hub/static (offline souverainete) | `main` | 59 |
| `tools/forge_vendor_place.py` | place un asset vendored (telecharge sous C:/tmp) dans app/web_hub/static/, en ecriture OWNER (lance via run action=trusted_script) | `main` | 47 |
| `tools/forge_wasm_bridge.py` | pont OWNER-context hub <-> WasmEdge (WSL Debian) | `win_to_wsl`, `run_wasmedge`, `process_once`, `daemon` *(+4)* | 179 |
| `tools/forge_wheel_probe_monthly.py` | Trigger Acte 5 quand ecosystem cp314t pret | `snapshot_est_reel`, `doit_ecrire_latest`, `run_probe`, `hub_notify` *(+1)* | 261 |
| `tools/gemini_launcher.py` | Gemini CLI interactif + relay hub en subprocess | — | 66 |
| `tools/gen_demo_gifs.py` | Generate launch demo GIFs via Playwright | `write_html`, `grab_frames`, `save_gif`, `make_terminal_gif` *(+2)* | 386 |
| `tools/generate_kaggle_export.py` | Générateur kaggle_export.json v2 ============================================================= Scan AST de tout app/ et génère un export enrichi pour GraphCodeBERT | `scan_file`, `generate`, `main` | 271 |
| `tools/install_boot_hook.py` | generate the OS-specific hook that launches the Nokido supervisor at boot | `gen_systemd`, `gen_launchd`, `gen_windows`, `main` | 128 |
| `tools/install_ortgenai_directml.py` | Install OnnxRuntime-GenAI with DirectML backend for AMD Radeon iGPU (ryzen-ai) | `find_whl`, `install_ort_genai`, `verify_directml` | 89 |
| `tools/kaggle_push.py` | Push et déclenche le notebook Kaggle ============================================================= Usage : python tools/kaggle_push.py # push + run python tools/kaggle_push.py --dry-run # push sans run python tools/kaggle_push.py --kernel notebookdnokido Modif | `inject_version`, `push_notebook`, `push_dataset` | 132 |
| `tools/launch_public_mirror.py` | orchestrate the clean-slate public release | `info`, `ok`, `warn`, `fail` *(+9)* | 776 |
| `tools/nokido.py` | Entrypoint unifie Nokido | `cmd_status`, `cmd_hub`, `cmd_up`, `cmd_down` *(+4)* | 242 |
| `tools/nokido_cutover_diag_verrou.py` | pourquoi le renommage rend ACCES REFUSE | `temoin`, `handles`, `defender`, `jonctions` *(+2)* | 179 |
| `tools/nokido_cutover_migrate.py` | migration RUNTIME-STATE du cutover Nokido | `migrate_db`, `migrate_paths`, `migrate_env`, `main` | 98 |
| `tools/nokido_cutover_owner.py` | cutover du nom de dossier, partie OWNER | `etat`, `reecrire`, `inv_services`, `inv_taches` *(+10)* | 1160 |
| `tools/nokido_cutover_runbook.py` | genere docs/cutover_runbook.md (mermaid inclus) | `construire` | 296 |
| `tools/nokido_deep_rename.py` | renommage PROFOND laforge->nokido (case-preserving) | `cibler`, `rename_str`, `rewrite_content`, `is_text` *(+1)* | 213 |
| `tools/nokido_doctor.py` | dit a l'utilisateur ce que Nokido a besoin de trouver sur sa machine | `rendre_texte`, `main` | 132 |
| `tools/nokido_extstate_revert.py` | revert rename KEEP-miss sur l'ETAT EXTERNE | `main` | 82 |
| `tools/nokido_fix_legacy_paths.py` | repare les CHEMINS figes laisses par le renommage | `main` | 163 |
| `tools/nokido_launcher.py` | Lanceur bureau Nokido ============================================= Double-cliquer sur le raccourci bureau pour obtenir un panneau de contrôle rapide en console Windows | `input`, `main` | 805 |
| `tools/nokido_modules.py` | Interface CLI unifiee pour les modules Nokido | `main` | 220 |
| `tools/nokido_phase0_derive_paths.py` | phase 0 du renommage: deriver la racine | `run` | 218 |
| `tools/nokido_rename.py` | Renommage Nokido -> Nokido — Phase 1 (docs prose, coupe nette) | `transform`, `transform_ui`, `transform_pycode`, `transform_pystr` *(+1)* | 285 |
| `tools/nokido_rename_services.py` | renommer les services SCM LaForge* -> Nokido* | `nssm`, `list_services`, `service_exists`, `target_name` *(+7)* | 298 |
| `tools/nokido_stdio_bridge.py` | Bridge STDIO async v17.02 ==================================================== Tunnel pur STDIO <-> Hub HTTP | `run_bridge`, `main` | 292 |
| `tools/nokido_tui_bridge.py` | Launcher du bridge TUI web | `main` | 90 |
| `tools/patch_except_muets_sandbox.py` | Patch : rendre parlants les `except` muets de `app/forge_sandbox_exec.py` | `main` | 168 |
| `tools/patch_except_muets_sandbox2.py` | Patch : second lot des `except` muets de `app/forge_sandbox_exec.py` | `main` | 109 |
| `tools/patch_except_muets_sandbox3.py` | Patch : deplacer `# muet-ok` du `pass` vers la ligne du HANDLER | `main` | 63 |
| `tools/patch_introspect_tool.py` | greffe le verbe `introspect` au registre MCP | `main` | 174 |
| `tools/patch_m2m_cli_derivation.py` | M2M suit le registre LIVE des CLI | `main` | 98 |
| `tools/patch_m2m_envelope.py` | patcheur one-shot CRITICAL_FILE (chemin owner-sanctionne via `run action=trusted_script`) | `main` | 88 |
| `tools/patch_m2m_nokido_endpoint.py` | NOKIDO devient un endpoint M2M | `main` | 83 |
| `tools/patch_notify_reveil_http.py` | reveil du drain AGY par HTTP, pas par subprocess | `main` | 105 |
| `tools/patch_notify_reveille_drain.py` | le courrier REVEILLE son drain | `main` | 115 |
| `tools/patch_query_budget_et_deport.py` | __FORGE_COLOR__ = "immunitaire/budget-requetes" PATCH : la porte non gardee du meme danger, et l'effecteur jamais arme | `main` | 143 |
| `tools/patch_query_schema_20260708.py` | One-shot patcher (CRITICAL_FILE path) : ajoute action=schema a l'outil query | `main` | 59 |
| `tools/patch_reflex_gate.py` | le garde anti-reinvention, en AVERTISSEMENT | `main` | 199 |
| `tools/patch_shell_batch_serialize.py` | Patcher one-shot : serialiser le batch shell par RESSOURCE EXCLUSIVE | `main` | 123 |
| `tools/publish_multi.py` | Multi-platform publish au go-public AGPLv3 | `check_remote_exists`, `push_remote`, `gen_show_hn_post`, `gen_reddit_post` *(+4)* | 250 |

## SNC (cerveau/moelle/SNP)

*153 modules · 45,415 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_bge_m3_shared.py` | In-process BGE-M3 shared session (Niveau 2 pattern) | `embed_parallel`, `runtime_info` | 293 |
| `app/forge_byte_router.py` | Middleware Hub._tool_call AVANT dispatch ============================================================== Session 5 — 2026-04-27 ADR Gemini 2026-04-15 : middleware dans Hub._tool_call, pas broker séparé | `get_pending_notifications`, `configure_poll`, `ByteRouterMiddleware`, `ByteDataRouter` | 304 |
| `app/forge_capability_registry.py` | Façade UNIFIÉE des capacités LLM/agents | `capabilities_of`, `has_capability`, `providers_for`, `reachable_providers_for` *(+1)* | 84 |
| `app/forge_clawhub_autoinstall.py` | ClawHub Auto-Install on-demand ================================================================ Installe a la volee des skills ClawHub pertinents pour une intention donnee | `load_catalog`, `refresh_catalog`, `suggest_skills`, `install_skill` *(+1)* | 447 |
| `app/forge_clawhub_bridge.py` | ClawHub Skill Registry Bridge v1.0 ================================================================ Connecteur isolé en silo pour le registre OpenClaw/ClawHub | `SkillFile`, `ClawSkill`, `ClawHubClient`, `SkillGuardian` *(+4)* | 835 |
| `app/forge_engrid_engine.py` | Nokido Engrid v3 · Facade principale =============================================================== Transpose ForgeEngridEngine (spec neuro-souveraine) sur les composants réels | `ShardLatencyEntry`, `CognitiveShard`, `CycleResult`, `ModelQualificator` *(+3)* | 731 |
| `app/forge_hub_gate.py` | Gate de gouvernance PARALLÈLE du hub (fail-CLOSED) | `Verdict`, `resolve` | 290 |
| `app/forge_intention_gate.py` | Gate d'intention (Agent Policier, moitié 2/2) | `check_scope_drift`, `gate_tool_call` | 123 |
| `app/forge_intention_journal.py` | __FORGE_COLOR__ = ssot/intention-journal JOURNAL UNIFIE DES INTENTIONS — audit-trail infaillible (doc SSoT souverain, pilier A) | `record`, `replay`, `stats`, `propose` | 119 |
| `app/forge_log_rotation.py` | Centralized rotating log handlers for Nokido | `get_rotating_logger`, `migrate_to_rotating`, `cap_existing_log` | 161 |
| `app/forge_m2m_protocol.py` | Sprint 3 : validation des messages M2M inter-agents | `mode`, `acteur_de`, `valider_identites`, `incarnation` *(+6)* | 659 |
| `app/forge_mcp_elicitation.py` | le hub demande une confirmation a l'OWNER (elicitation MCP) | `enregistrer_session`, `capacite`, `Canal`, `sse_requis` *(+6)* | 260 |
| `app/forge_mcp_federation.py` | le hub Nokido devient CLIENT MCP (federation/proxy) | `discover`, `probe`, `call`, `main` | 211 |
| `app/forge_mcp_protocole.py` | negociation de version MCP et consignes serveur du hub (cote SERVEUR) | `negocier_version` | 51 |
| `app/forge_mcp_safe.py` | execution du code Python recu par MCP | `safe_exec`, `run_b64`, `mcp_safe` | 76 |
| `app/forge_message_frame.py` | Enveloppe JSON normalisée inter-agents ================================================================ Nokido est le tronc cérébral | `ToolDef`, `MessageFrame`, `ttl_for_action`, `InboxRegistry` *(+4)* | 396 |
| `app/forge_nervous_map.py` | CARTE NERVEUSE : inventaire unifié des composants internes, PLUGGÉS au CORTEX (routage/décision) et au SYSTÈME NERVEUX (bus d'événements + hormones) | `daemons`, `roles`, `organ_agents`, `skills` *(+11)* | 645 |
| `app/forge_nervous_system.py` | Système Nerveux Central (SNC) de Nokido | `NervousMode`, `get_endocrine_levels`, `get_active_nervous_mode`, `chemical_prompt_modulation` | 99 |
| `app/forge_ordres_bureau.py` | ordres que le hub confie a la session de l'OWNER, apres son accord | `deposer`, `en_attente`, `prendre`, `redemarrer_stack` *(+3)* | 278 |
| `app/forge_postal.py` | système postal souverain Nokido : FACTEUR (livraison) + SECRÉTAIRE (relève) par CANAL, courrier RICHE + cycle de vie avec ACCUSÉS + dédup anti-triplication | `claim`, `ack_mail`, `unclaim`, `canonical` *(+12)* | 660 |
| `app/forge_promcp_profiler.py` | __FORGE_COLOR__ : observabilite / metacognition (organe, ECRITURE BORNEE) ORGANE : PROFILING PAR TOOL MCP — « ce tool coute-t-il ce qu'on croit ? » | `record`, `stats`, `costliest`, `observed_cost_ms` | 204 |
| `app/forge_routing_decision.py` | __FORGE_COLOR__ = routing/contract CONTRAT DE DECISION commun aux routeurs Nokido | `RoutingDecision`, `abstention`, `from_legacy_tuple` | 228 |
| `app/forge_security_lab_adapter.py` | frontière bornée cœur ⟷ capacités offensives | `lab_authorized`, `disabled_message`, `lab_path`, `configure_lab_path` *(+4)* | 154 |
| `app/forge_session_context.py` | SessionContext moderne Nokido ========================================================== Successeur SessionContext (Nokido_v13.6.py L2938-2995) | `SessionMessage`, `SessionContext`, `get_active_session`, `set_active_session` | 207 |
| `app/forge_snn_core.py` | __FORGE_COLOR__ = neuro/snn-substrate SNN CORE — couche LIF canonique APPRENABLE (surrogate gradient) | `available`, `selftest`, `main` | 211 |
| `app/forge_snn_router.py` | __FORGE_COLOR__ = routing/snn ROUTEUR SNN pour le routage LLM - l'etage L1 de la cascade | `available`, `decide_from_rates`, `SNNRouter`, `cross_validate_loo` *(+2)* | 589 |
| `app/forge_spike_router.py` | Routeur neuronal à basculement de phase ================================================================ Remplace le triage if/else statique par un routeur SNN qui APPREND quelles stratégies fonctionnent pour quels challenges | `ChallengeFeatures`, `extract_features`, `CTFSpikeRouter`, `Spike` *(+9)* | 581 |
| `app/forge_synaptic_plasticity.py` | Plasticité synaptique RAG (Phase 6 Symbiose) Couche d'auto-amélioration au-dessus de forge_rag_qualify.apply_trust_weight() | `get_dynamic_threshold`, `get_global_metrics`, `record_query`, `feedback_loop` *(+3)* | 320 |
| `app/forge_tldr_context.py` | TLDR + HackTricks Context Injector v1.0 ==================================================================== Injecte des exemples de commandes réels (tldr + HackTricks) dans le contexte des silos AVANT envoi au LLM — le modèle génère des commandes "ready-to-ru | `ContextInjector`, `get_injector` | 406 |
| `app/forge_tool_scope.py` | Sprint 2 anti context-bomb : scope dynamique du catalogue MCP | `active_tools_for`, `role_scope_for`, `methode_du_role`, `expected_scope_for` *(+4)* | 481 |
| `app/forge_trace_context.py` | Trace/Correlation ID propagé via contextvars | `new_trace_id`, `get_trace_id`, `set_trace_id`, `reset_trace_id` *(+16)* | 272 |
| `app/forge_universal_tool_surface.py` | __FORGE_COLOR__ : SNP / surface d'entree (adaptateur, sans etat) ORGANE : SURFACE TOOL UNIVERSELLE — MCP, ACP et OpenAPI entrent par la MEME porte | `ToolCallError`, `normalize`, `to_protocol_response`, `dispatch_universal` | 162 |
| `tools/after_model_hook.py` | Hook AfterModel Gemini CLI 1 | — | 163 |
| `tools/claude_capture.py` | Hook Claude Code : capture UserPromptSubmit + Stop | `handle_user_prompt_submit`, `handle_stop`, `main` | 207 |
| `tools/claude_inbox_tick.py` | RÉFLEXE UserPromptSubmit (0 token, event-driven) | `main` | 593 |
| `tools/claude_precompact.py` | Hook PreCompact Claude Code =================================================== Déclenché juste avant que Claude Code compacte le contexte | `main` | 664 |
| `tools/claude_session_start.py` | Hook SessionStart Claude Code Au boot Claude : 1 | `modele_normalise`, `version_du_transcript`, `rappel_audit`, `section_audit` *(+14)* | 638 |
| `tools/claude_session_stop.py` | Hook Stop Claude Code Quand session Claude termine son tour : 1 | `load_token`, `main` | 153 |
| `tools/cli_capture_lib.py` | Helper partage pour la capture des conversations CLI | `record_turn`, `normalize_anthropic_content` | 246 |
| `tools/cli_tail_capture.py` | Tail-watcher pour Gemini CLI + Cline | `capture_gemini`, `capture_cline`, `capture_claude`, `run_once` *(+1)* | 432 |
| `tools/deploy_hub_bundle.py` | Deploie le bundle Hub pre-compile dans le dossier hub servi NO-STORE via /design | `decider_deploiement`, `main` | 96 |
| `tools/dump_hub_routes.py` | Liste TOUTES les routes/mounts du portail :7400 -> identifier les UI reachable non tuilees (RAG, Network, Deno, dashboard...) | — | 21 |
| `tools/finish_redteam_intents.py` | Pose le JSON des intents offensifs dans le depot redteam via le profil OWNER | — | 25 |
| `tools/forge_audit_intention_effet.py` | ce qui tourne porte-t-il une INTENTION et un EFFET ? Demande owner du 2026-08-25 : « ce qui n'est pas utile a l'instant T ne devrait pas tourner ; l'autoregulation doit couper ce qui ne porte pas d'intention reelle AVEC effet ; couvrir l'INTEGRALITE de ce qui | `sc_obj`, `main` | 385 |
| `tools/forge_boot_context.py` | Generateur de contexte de reprise pour agents Nokido | `db_conn`, `last_session`, `build_context`, `inject_gemini_md` *(+1)* | 260 |
| `tools/forge_broker_base.py` | Nokido v18.5 | `BrokerBase` | 599 |
| `tools/forge_broker_deepseek.py` | Nokido v18.5 Agent: agt_deepseek \| DeepSeek V4 Flash + R1 (OSS, code, reasoning) Specialite: code review, debugging, raisonnement chain-of-thought, 1M tokens | `DeepSeekBroker` | 105 |
| `tools/forge_broker_fast.py` | Nokido v18.5 Agent: agt_groq \| Groq LPU 315-700TPS Specialite: classification rapide, routing, scoring CerberusGuard, < 500ms | `FastBroker` | 122 |
| `tools/forge_broker_gemini.py` | Nokido v18.5 Agent: agt_gemini \| Google Gemini 2.5 Flash/Pro + cascade 9 tiers Specialite: raisonnement, long contexte, multimodal | `GeminiBroker` | 269 |
| `tools/forge_broker_local.py` | Nokido v18.5 Agent: agt_local \| Ollama + llama.cpp (100% local, zero cloud, RGPD absolu) Specialite: vie privee totale, offline, code rapide (qwen2.5-coder), vision (llava) | `LocalBroker` | 110 |
| `tools/forge_broker_manager.py` | Nokido v18.5 Orchestrateur des brokers — route les messages vers le bon agent selon l intention | `start_broker`, `status`, `main` | 133 |
| `tools/forge_broker_mistral.py` | Nokido v18.5 Agent: agt_mistral \| Mistral Large + Codestral (EU/RGPD, function calling) Specialite: souverainete EU, function calling, structured output, code FIM | `MistralBroker` | 73 |
| `tools/forge_broker_probe.py` | Nokido v18.5 Sonde de surveillance token cost & latence pour tous les brokers | `c`, `snapshot`, `display`, `hub_notify_cost` *(+1)* | 206 |
| `tools/forge_ci_github_log.py` | diagnostique un run GitHub Actions EN ÉCHEC via `gh api` | `main` | 70 |
| `tools/forge_cli_hygiene_session_prototype.py` | Prototype for Async Session Resume registry and CLI Output Hygiene pipeline | `SessionRegistry`, `CLIHygiene`, `main` | 171 |
| `tools/forge_cli_tool_deport.py` | déporte les tools NATIFS de Gemini CLI vers le hub Nokido | `cmd_status`, `cmd_deport`, `cmd_restore`, `main` | 209 |
| `tools/forge_collab_broker.py` | Nokido v18.5 Bridge Claude <-> Gemini via API key directe | `hub_poll`, `hub_notify`, `hub_recv`, `hub_send_to_claude` *(+2)* | 600 |
| `tools/forge_context_budget.py` | ce que le contexte RESIDENT coute, a chaque tour | `descriptions_skills`, `ecrire_releve`, `mesurer`, `expliquer` *(+1)* | 534 |
| `tools/forge_deno_nlu_audit.py` | Audit Deno brain.ts NLU layer + nervous_system.ts event bus | `audit_brain_ts`, `audit_nervous_system`, `coverage_report` | 125 |
| `tools/forge_dialogue_score_session.py` | AXE 8 : hook fin-de-session | `main` | 174 |
| `tools/forge_effect_surface.py` | M0 — surface d'effets de Nokido : prouver la FERMETURE, pas inventorier | `MetaEffet`, `NoeudConfiance`, `cycle_de_confiance`, `Preuve3Roles` *(+7)* | 514 |
| `tools/forge_endpoint_registry.py` | SOURCE UNIQUE d'identité des endpoints LLM de Nokido | `build_inventory`, `resolve`, `min_ring_for`, `id_headers` *(+2)* | 263 |
| `tools/forge_engrid_engine.py` | Re-export depuis app/ ===================================================== Le moteur Engrid réside dans app/ pour rester dans le path Nokido | — | 23 |
| `tools/forge_events_wait.py` | attente bloquante d'événements (jobs) pour SCRIPTS DÉPORTÉS | `wait_for_job`, `wait_for_jobs` | 75 |
| `tools/forge_filehandler_migrator.py` | Audit + migrate FileHandler -> RotatingFileHandler | `audit`, `migrate_file`, `main` | 170 |
| `tools/forge_gemini_mcp_connector.py` | Connecteur Gemini ↔ MCP Nokido (dynamique) ============================================================================ SDK : google-genai >= 1.0 (pip install google-genai) Fonctionnement : 1 | `GeminiMCPConnector` | 521 |
| `tools/forge_gemini_mcp_proxy.py` | Proxy Gemini ↔ MCP Nokido ======================================================= Utilise le nouveau SDK google-genai (1.x) — plus google-generativeai | `GeminiMCPProxy` | 401 |
| `tools/forge_github_bridge.py` | passerelle GitHub EN LECTURE pour un client externe | `adresses_autorisees`, `filtre_adresse_actif`, `revoquees`, `relais_de_confiance` *(+9)* | 752 |
| `tools/forge_github_bridge_mcp.py` | transport MCP (stdio) des cinq operations GitHub | `outils_exposes`, `habilitation_du_processus`, `habilitation_appelant_exigee`, `appeler` *(+7)* | 432 |
| `tools/forge_hub_blackbox.py` | la boite noire du hub | `echantillon`, `main` | 197 |
| `tools/forge_hub_reload.py` | restart du hub (NokidoMCP) via supervisor, DÉTACHÉ | `main` | 62 |
| `tools/forge_hub_token_rotation.py` | rotation OWNER-DRIVEN des bearer tokens hub :8766 | `fp`, `inventory`, `execute`, `cleanup` *(+1)* | 613 |
| `tools/forge_identity_registry_upgrade.py` | __FORGE_COLOR__ = "immunitaire/registre-identites" MIGRATION du SSoT `config/agent_identities.json` vers le SCHEMA 2 : acteur canonique, alias, surface, boite aux lettres, audience (RFC 8707) | `main` | 268 |
| `tools/forge_ingest_github_repo.py` | Ingere un DEPOT GitHub entier dans le RAG Nokido, cible PARAMETRABLE | `parse_slug`, `fetch`, `index`, `main` | 239 |
| `tools/forge_intent_audit.py` | chaque module réalise-t-il l'INTENTION derrière lui ? Demande owner (02/08) : « audite chaque module, capte l'intention derrière, vois si c'est FAIT » | `audit`, `main` | 198 |
| `tools/forge_intent_miner.py` | Ce que l'owner a DEMANDE, et qu'on ne retrouve nulle part | `extraire`, `main` | 342 |
| `tools/forge_intent_verifier.py` | chaque demande owner est-elle DANS LE CODE ? `forge_intent_miner` repond « le mot-clef apparait-il dans un MESSAGE DE COMMIT » | `main` | 587 |
| `tools/forge_job_notify.py` | Notification souveraine de fin de job aux clients dans la boucle | `boite_de`, `notify_subscribers`, `main` | 155 |
| `tools/forge_job_watch_notify.py` | Facteur de fin de job : observe un job deporte et notifie automatiquement les clients DANS LA BOUCLE a sa terminaison | `main` | 211 |
| `tools/forge_m2m_db_split.py` | Sortir `agent_messages` de RAG/embeddings.db vers la base M2M dediee | `copier`, `verifier`, `main` | 184 |
| `tools/forge_m2m_emanate.py` | Émanation du dictionnaire M2M vers RULES_SHARED.md | — | 117 |
| `tools/forge_mcp_dynamic_selftest.py` | e2e : outils forges exposes en MCP (A1+A2) | `main` | 69 |
| `tools/forge_mcp_http.py` | Transport HTTP pour Nokido MCP (Streamable HTTP 2025-11-25) ================================================================================== Complète nokido_mcp_server.py en mode HTTP : - Endpoint POST /mcp → JSON-RPC messages (client → server) - Endpoint GE | `run_http_server`, `start` | 504 |
| `tools/forge_mcp_json_sync.py` | sync Bearer tokens dans `.mcp.json` (format Claude Code / Cline / VSCode MCP clients) depuis le coffre machine DPAPI | `entetes_agent`, `main` | 325 |
| `tools/forge_mcp_persistent.py` | Client MCP Persistant avec Schema Cache et Lazy Loading ================================================================================== Optimise le dialogue MCP en : 1 | `mmap_store`, `mmap_get`, `mmap_clear_old`, `SchemaCache` *(+3)* | 409 |
| `tools/forge_mcp_proxy.py` | Proxy STDIO → HTTP Nokido Hub v2.0 ========================================================= Proxy JSON-RPC 2.0 conforme spec + sécurité renforcée | `run` | 364 |
| `tools/forge_pair_mcp.py` | connecteur MCP des PAIRS cloud (claude.ai, ChatGPT) : lecture + quarantaine | `dossier_sandbox`, `dossier_capsules`, `chemin_rag`, `chemin_m2m` *(+19)* | 556 |
| `tools/forge_patch_agent_list_from_registry.py` | __FORGE_COLOR__ = "securite/identite-clients" PATCH : le hub charge les jetons de TOUTES les identites declarees, pas d'une liste figee | `main` | 169 |
| `tools/forge_patch_hub_dspy_agent.py` | One-shot patcher: ajoute DSPY_ROUTER a _AGENT_LIST de tools/nokido_hub.py | — | 47 |
| `tools/forge_patch_hub_elicitation.py` | cable l'elicitation MCP dans le hub (fichiers CRITIQUES) | `appliquer`, `main` | 212 |
| `tools/forge_patch_hub_ordres_bureau.py` | cable `hub action=redemarrer_stack\|ordre_bureau` (fichier CRITIQUE) | `main` | 85 |
| `tools/forge_patch_hub_origine401_v2.py` | Correctif : le cache de resolution bloquait l'identification qu'il devait servir | `main` | 144 |
| `tools/forge_patch_hub_origine_401.py` | Patch : faire dire au hub QUI emet les requetes rejetees en 401 | `main` | 214 |
| `tools/forge_patch_hub_service_par_pid.py` | Jointure PID -> NOM DE SERVICE : que le journal nomme, au lieu de numeroter | `main` | 164 |
| `tools/forge_patch_hub_sse_conforme.py` | l'ouverture du flux SSE de `tools/call` devient un COMMENTAIRE SSE (fichier CRITIQUE `tools/nokido_hub.py`) | `main` | 62 |
| `tools/forge_patch_mcpsec_fix3.py` | One-shot patcher: fix #3 A+B on app/forge_mcp_security.py | — | 69 |
| `tools/forge_patch_muted_paths_hub.py` | __FORGE_COLOR__ = "immunitaire/chemins-muets" PATCH : chemins d'erreur muets de `tools/nokido_hub.py` (fichier CRITIQUE) | `main` | 234 |
| `tools/forge_patch_nudge_hub.py` | __FORGE_COLOR__ = "regulation/reveil-embedding" PATCH : le reveil d'embedding du hub verifie qu'on l'ecoute | `main` | 101 |
| `tools/forge_patch_promcp_hook.py` | greffe le profileur ProMCP sur ToolRegistry.dispatch | `main` | 122 |
| `tools/forge_patch_registry_access_count.py` | One-shot patcher: signal d'usage access_count (T1 ADAPT memory_decay AGY) | — | 105 |
| `tools/forge_patch_registry_compact.py` | One-shot patcher: Sprint 1 anti context-bomb sur app/forge_mcp_registry.py | — | 140 |
| `tools/forge_patch_registry_compact_fix1.py` | One-shot patcher fix1: NameError `re` dans _compact_tools (forge_mcp_registry) | — | 50 |
| `tools/forge_patch_registry_m2m.py` | One-shot patcher: Sprint 3 M2M sur app/forge_mcp_registry.py | — | 103 |
| `tools/forge_patch_registry_research_tothread.py` | One-shot patcher: handle_research_agent hors event-loop (Fix 3 RCA wedge) | — | 54 |
| `tools/forge_patch_registry_toolscope.py` | One-shot patcher: Sprint 2 anti context-bomb sur app/forge_mcp_registry.py | — | 118 |
| `tools/forge_patch_registry_tothread.py` | One-shot patcher: to_thread sur _archive_long_args dans forge_mcp_registry.dispatch | — | 50 |
| `tools/forge_pool_registry.py` | Registre d'efficacité mesurée du pool d'exécution de Nokido | `get_db_connection`, `init_db`, `get_member_cost`, `publish` *(+3)* | 391 |
| `tools/forge_reload_prompt.py` | Popup branded Nokido expliquant l'UAC (cas par cas) avant reload | `main` | 172 |
| `tools/forge_session_provenance.py` | lignée de provenance des compactions de session | `enrich_with_provenance`, `session_provenance` | 129 |
| `tools/forge_ui_hub_rebuild.py` | Recompile l'artefact servi du hub depuis ses sources de reference | `recompiler`, `main` | 225 |
| `tools/forge_veille_backlog_github.py` | le RETARD de veille, depot par depot | `main` | 654 |
| `tools/forge_veille_ecosysteme_github.py` | elargissement ECOSYSTEME sans SearXNG | `main` | 133 |
| `tools/forge_verif_post_restart_securite.py` | Verification des corrections de securite du 2026-09-12, apres redemarrage du hub | `predit`, `a_observer`, `observations`, `main` | 306 |
| `tools/forge_vscode_mcp_sync.py` | MATERIALISE le hub Nokido DANS chaque addon VSCode/CLI | `plan_client`, `apply_client`, `main` | 294 |
| `tools/gemini_hub_relay.py` | v3.0 — PTY wrapper OAuth persistant ========================================================= Gemini CLI tourne en session interactive via PTY (winpty) | `log`, `hub_call`, `hub_poll`, `hub_notify` *(+3)* | 251 |
| `tools/gemini_notify.py` | Envoyer taches/messages a agt_gemini via state_manager | `send`, `main` | 115 |
| `tools/hook_bash_compact.py` | Hook Claude Code PreToolUse(Bash) : réécrit une commande VERBEUSE pour piper sa sortie dans forge_cmd_compactor AVANT qu'elle entre dans le contexte (les hooks ne peuvent PAS réécrire la SORTIE — seul updatedInput.command, cf | `main` | 93 |
| `tools/hook_capability_gate.py` | gate de CAPACITÉS : la bonne forme AVANT l'erreur | `verdict_forme`, `verdict_depense`, `empreinte_rappel`, `promotion_verdict` *(+1)* | 1021 |
| `tools/hook_instructions_loaded.py` | capteur `InstructionsLoaded` de Claude Code (observation seule) | `consigner`, `bilan`, `main` | 113 |
| `tools/hook_recon_first.py` | Garde PreToolUse : interroger la MEMOIRE avant d'instrumenter un domaine neuf | `main` | 369 |
| `tools/hook_tool_budget_gate.py` | Gouverneur silencieux du budget d'outils -- empeche la boucle, ne commente pas | `empreinte`, `verdict_pre`, `noter_mutation`, `noter_echec` *(+2)* | 273 |
| `tools/hub_call.py` | Interface universelle hub Nokido pour Gemini Usage: python tools/hub_call.py <action_ou_tool> [key=value ...] Actions hub (passent via tool=hub, arguments={action:...}) : poll notify message="..." whoami quota_model quality=medium apply=true quota_report flash | — | 109 |
| `tools/hub_call_antigravity.py` | Interface universelle hub Nokido pour Antigravity Usage: python tools/hub_call_antigravity.py <action_ou_tool> [key=value ...] | — | 99 |
| `tools/hub_lifecycle_hooks.py` | Server-side lifecycle hooks middleware ===================================================================== Équivalent unifié des hooks SessionStart/AfterModel par-client (Gemini CLI, Claude Code hooks, etc.) — agit côté hub :8766 selon `X-Agent-Name` header | `pre_dispatch`, `post_dispatch`, `wrap_response` | 291 |
| `tools/hub_live_patch.py` | Monkey-patch temps reel pour nokido_hub ============================================================ Importe ce module UNE FOIS au demarrage du Hub | `patch_app` | 182 |
| `tools/hub_middleware.py` | ======================== KNOWLEDGE_HARVESTER_V1 | `sanitize_path`, `sanitize_string`, `validate_tool_name`, `validate_arguments` *(+2)* | 435 |
| `tools/hub_minimal.py` | Hub minimal Nokido | — | 44 |
| `tools/hub_rt_patch.py` | Patch temps réel pour nokido_hub.py Applique 3 modifications : 1 | — | 115 |
| `tools/mcp_bridge_selftest.py` | valide B : _write_out (lock) + watcher capabilities | `main` | 64 |
| `tools/mcp_nr.py` | NR automatique lancé par Claude via MCP sandbox ================================================================= Chaque fonction est courte (<50 lignes) pour passer la sentinelle | `check_ast`, `check_globals_fh`, `check_no_self`, `check_registry` *(+10)* | 698 |
| `tools/mcp_stdio_bridge.py` | Bridge stdio → HTTP Nokido Hub v3.0 =========================================================== Permet à Claude Desktop de parler en stdio pendant que le vrai serveur MCP Nokido tourne en service Windows permanent (nssm) | `get_secret`, `run_bridge` | 846 |
| `tools/nokido_hub.py` | Ã¢â‚¬â€� Nokido Hub v18.3 \| Network Monitor redesign ============================================================= v18.2 : UI /forge/network entiÃƒÂ¨rement redesignÃƒÂ©e | `watch_ui`, `watch_jobs_api`, `watch_create_api`, `watch_stream_api` *(+6)* | 7255 |
| `tools/nokido_hub_cli.py` | point d'entree CONSOLE du hub, synchrone et mince | `main` | 86 |
| `tools/nokido_mcp_server.py` | Nokido MCP Server (STDIO) v17.02 ========================================================= Unified with forge_mcp_registry (Chantier C) | `handle_list_tools`, `handle_call_tool`, `main` | 197 |
| `tools/nokido_web_hub.py` | Launcher du hub FastAPI Nokido | `main` | 286 |
| `tools/notify_gemini_align.py` | Envoie briefing alignement a Gemini via hub notify | — | 53 |
| `tools/notify_gemini_analysis.py` | Send Claude analysis to Gemini | — | 47 |
| `tools/notify_gemini_resume.py` | Notify Gemini: correct ChainExecutor API + resume_chain.py usage | — | 44 |
| `tools/patch_audit_prompts_registry.py` | descriptions d'outils MCP exactes (audit de prompts 2026-09-26) | `appliquer`, `main` | 118 |
| `tools/patch_gardes_muets_registry.py` | __FORGE_COLOR__ = "immunitaire/chemins-muets" PATCH : les chemins muets de `app/forge_mcp_registry.py` qui DESARMENT UN GARDE | `main` | 148 |
| `tools/patch_github_token_coffre.py` | __FORGE_COLOR__ = "immunitaire/secrets-au-coffre" PATCH : `run action=github` lit son jeton dans le COFFRE, plus dans l'environnement | `main` | 71 |
| `tools/patch_intention_gate_wiring_20260708.py` | One-shot patcher : câble gate_tool_call (gate d'intention Agent Policier) dans forge_mcp_registry.dispatch(), juste après le check RBAC | `main` | 51 |
| `tools/patch_job_kill_registry.py` | cable le verbe MCP job_kill dans le registre | `main` | 136 |
| `tools/patch_provenance_hub_shell.py` | Patch : propager l'identite authentifiee jusqu'au shell sandboxe | `main` | 102 |
| `tools/quota_hook.py` | v3 — Hook SessionStart Gemini CLI ================================================ Au boot : Gemini rapporte son état quota via hub notify, puis injecte le contexte dans GEMINI.md projet | `hub_call`, `read_quota_state`, `get_best_available`, `get_rag_filters` | 174 |
| `tools/recon_hub_data.py` | Recon des vraies sources pour cabler les vues /hub (federation/cap/persona) | — | 54 |
| `tools/restart_hub.py` | Restart hub: kill current process then start fresh | — | 32 |
| `tools/session_anchor.py` | Hook Stop Claude: session_summary + resync Gemini + daemons | — | 72 |
| `tools/store_github_token.py` | ============================ Stocke le GITHUB_TOKEN dans Windows Credential Manager | `store` | 34 |
| `tools/store_openrouter_key.py` | ============================== Stocke la clé OpenRouter dans Windows Credential Manager | `store_key` | 61 |
| `tools/test_hub_endpoints.py` | Appelle directement les endpoints /api/hub/overview + /api/hub/federation (async, env serveur) -> prouve qu'ils renvoient de la VRAIE donnee | `main` | 21 |
| `tools/test_hub_mcp_handshake.py` | Minimal MCP handshake against Nokido Hub :8766/mcp Run: LAFORGE_PYTHON tools/test_hub_mcp_handshake.py Background (2026-05-02 reachability probe): A reachability probe found `tools/list` against http://127.0.0.1:8766/mcp timed out (10s ReadTimeout) | `load_token`, `call`, `main` | 161 |
| `tools/test_hub_tiles.py` | Test E2E LIVE des tuiles du Hub : GET /api/hub/modules (ce que le navigateur recoit) puis GET chaque href resolue | `hit` | 76 |

## Memoire (hippocampe/RAG)

*148 modules · 32,941 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_biblio_core.py` | Nokido Bibliography Worker | `extract_from_text`, `insert_biblio_raw`, `list_entries`, `get_entry` *(+2)* | 410 |
| `app/forge_biblio_worker.py` | Nokido Bibliography Worker | `process_entry`, `run_loop`, `main`, `process_one_entry` | 368 |
| `app/forge_body_world_model.py` | World Model du corps (P2-1) | `load_services_config`, `get_live_supervisor_status`, `build_dependency_graph`, `predict_impact` *(+1)* | 251 |
| `app/forge_dist_storage.py` | Distribution storage R2/HF/OneDrive + sanitize pipeline | `sanitize_text`, `is_whitelisted_source`, `sanitize_chunk`, `export_sanitized` *(+3)* | 244 |
| `app/forge_embed_router.py` | cascade embedding providers | `declare_wanted`, `declare_embed_wanted`, `embed_batch`, `embed` *(+5)* | 1245 |
| `app/forge_epistemic_retrieve.py` | Step 5 epistemic: cluster-aware retrieval wrap autour RAGEngine | `cluster_aware_retrieve`, `qualifier_resultats`, `format_for_llm`, `main` | 353 |
| `app/forge_generation.py` | le corps garde ses ETATS, pas seulement ses fichiers | `capturer`, `capturer_si_absent`, `lister`, `derniere_stable` *(+4)* | 619 |
| `app/forge_graph_rag.py` | Graph-RAG Layer for Nokido ================================================= Transforms flat vector RAG (embeddings.db) into a navigable knowledge graph | `GNode`, `GEdge`, `TraversalResult`, `GraphRAG` | 421 |
| `app/forge_graph_rag_hops.py` | GraphRAG hop expansion layer | `graph_rag_search`, `main` | 294 |
| `app/forge_handler_fragment.py` | Handler @fragment TUI ====================================================== Interface avec le Siloed Fragmentation Engine + Noise Guardian | `handle_fragment` | 166 |
| `app/forge_hebbian_linker.py` | Plasticité Hebbian sur `biblio_link` | `coactivation_topics`, `coactivation_ideas`, `coactivation_search_results`, `reinforce_links` *(+3)* | 312 |
| `app/forge_hybrid_bridge.py` | Nokido · Bridge LLM multi-provider ============================================================= Drop-in replacement pour MultiLLMBridge (spec Engrid) | `MultiLLMBridge` | 306 |
| `app/forge_memory_archival.py` | memory hierarchique Letta MemGPT pattern | `promouvoir_brouillon`, `ConvMessage`, `ArchivalMemory`, `get_agent_memory` *(+1)* | 653 |
| `app/forge_memory_availability.py` | Disponibilite de la connaissance PAR CANAL — ce que Nokido sait, et par quelle voie | `tier`, `statut_vectoriel`, `statuts_pour`, `annoter` *(+5)* | 588 |
| `app/forge_metier_dispatch.py` | route une tâche vers la BONNE persona métier + sa KB | `route`, `dispatch`, `main` | 219 |
| `app/forge_nudge_embed.py` | __FORGE_COLOR__ = "regulation/reveil-embedding" REVEIL du daemon d'embedding — et il DIT quand personne n'ecoute | `nudge_embed` | 129 |
| `app/forge_rag_introspect.py` | __FORGE_COLOR__ : memoire / metacognition (organe, READ-ONLY) ORGANE : INTROSPECTION RAG — « POURQUOI ce chunk est-il remonté ? » | `introspect` | 133 |
| `app/forge_rag_via_hub.py` | le RAG de la TUI v13 passe par le HUB, sans rien charger en local | `analyser_resultats`, `RAGViaHub` | 130 |
| `app/forge_sdr_encoder.py` | Sparse Distributed Representation (Numenta HTM) | `encode`, `overlap`, `similarity` | 60 |
| `app/forge_service_rss_watch.py` | Capteur de DERIVE MEMOIRE par service nomme — la grandeur qui manquait | `echantillon`, `derives`, `alerter` | 389 |
| `app/forge_sigreg.py` | Régulariseur anti-collapse RAG ================================================= Inspiré du SIGReg de LeWorldModel (LeCun et al., Mila/NYU/Samsung, mars 2026) | `SIGRegStats`, `sigreg_check`, `mmr_diversify`, `apply_sigreg` *(+2)* | 314 |
| `app/forge_skill_rag_bridge.py` | Pont SkillLearner ↔ RAG ↔ @disco ============================================================= Rôle : connecter les trois systèmes sans les coupler directement | `SkillRAGBridge`, `RAGReservoirReadout` | 640 |
| `app/forge_ssot.py` | Couche SSoT GÉNÉRIQUE pour TOUT savoir centralisé | `register_domain`, `enforce_schema`, `consult_ssot`, `answer_uniform` *(+3)* | 294 |
| `app/forge_ssot_maintainer.py` | garde les SSoT structurés FRAIS (#2 du build SSoT) | `etat_roadmap`, `refresh_state`, `refresh_all`, `regen_full` | 490 |
| `app/forge_state_encoder.py` | Phase 0 — AMI roadmap: encode Nokido system state → 384d float32 embedding | `get_current_state_text`, `get_current_state_text_rich`, `encode_state`, `encode_state_batch` *(+1)* | 339 |
| `app/forge_stm.py` | Short-Term Memory (LeCun AMI module 5) | `ShortTermMemory`, `get_stm`, `augment_state_emb` | 122 |
| `app/forge_successor_repr.py` | Successor Representation (Dayan 1993) pour Nokido | `successor_scores`, `propagation_score`, `impact_signature` | 109 |
| `app/forge_vector_index.py` | Nokido v18.5 ANN Index (FAISS) ========================================================= Index HNSW en RAM chargé depuis embeddings.db au démarrage | `VectorIndex`, `get_vector_index` | 370 |
| `app/forge_world_model.py` | Phase 3 - AMI roadmap: World Model (JEPA-lite) | `NMLP`, `train`, `predict`, `predict_cost` *(+11)* | 836 |
| `app/forge_world_vector_codec.py` | __FORGE_COLOR__ = edge/world-vector-codec CODEC DE TRANSMISSION du world-vector 4096D — maillon MANQUANT 4096D <-> edge fleet | `quantize`, `dequantize`, `pack`, `unpack` *(+2)* | 103 |
| `tools/batch_embed_priority.py` | Batch embed nokido_code + forge_core domains (missing embeddings) | `zmq_embed_batch`, `embed_missing`, `ingest_gitingest` | 130 |
| `tools/bench_jepa_rca.py` | cProfile JEPA train_step pour identifier hotspot | `run_profile`, `main` | 103 |
| `tools/bench_rag.py` | A/B benchmark RAG (CPU+IO mixed, goulot critique UX) | `main` | 193 |
| `tools/biblio_cli.py` | CLI Bibliography Worker (Sprint α — α6b) Usage: python tools/biblio_cli.py search <entry_id> python tools/biblio_cli.py list [--status=<status>] [--limit=<n>] python tools/biblio_cli.py promote <entry_id> python tools/biblio_cli.py reject <entry_id> --reason=< | `cmd_list`, `cmd_search`, `cmd_promote`, `cmd_reject` *(+5)* | 214 |
| `tools/build_bge_m3_embeddings.py` | Génère les embeddings BGE-M3 (1024d) pour les domaines prioritaires de rag_chunks et les stocke en BLOB float32 binaire | `load_model`, `fetch_chunks`, `count_already_done`, `embed_and_store` *(+1)* | 217 |
| `tools/check_gitingest_rag.py` | Deep check: what's actually in RAG vs what should be from gitingest | — | 60 |
| `tools/embed_direct.py` | Direct batch embedder — BGE-M3 ONNX via DirectML (Radeon 780M) or CPU fallback | `load_session`, `make_tokenizer`, `infer`, `run` | 253 |
| `tools/forge_anchor_rag_session.py` | Ancre les decisions de la session RAG dans Nokido | `main` | 81 |
| `tools/forge_auto_compact.py` | Auto-compact old RAG chunks via LLM summarization | `compact_batch`, `run_compaction` | 204 |
| `tools/forge_background_review.py` | fork post-turn LOCAL : auto-anchor solution + propose skill | `review_session`, `main` | 200 |
| `tools/forge_bench_ragtool.py` | Bench du hub `rag` tool (pipeline dense) | `main` | 170 |
| `tools/forge_blind_spot_index.py` | indexer le code VIVANT mais hors suivi git | `suivis`, `hors_suivi`, `decouper`, `indexer` *(+1)* | 228 |
| `tools/forge_capability_consolidation.py` | l'archeologie parle enfin a quelqu'un | `est_offensif`, `lire_vestiges`, `encore_absent`, `collateral` *(+3)* | 374 |
| `tools/forge_code_reindex.py` | reindexer BULK EFFICACE du code -> RAG (standalone, sans warmup) | `reindex`, `main` | 112 |
| `tools/forge_cognition_dim_selftest.py` | valide la centralisation des dims cognition | `main` | 108 |
| `tools/forge_cognition_retrain_4096.py` | A/B world-model @4096 vs @1024 vs @384 (GATE cutover dim-unif) | `main` | 145 |
| `tools/forge_cold_tier_cleanup.py` | Suppression du vrai dechet du RAG | `main` | 102 |
| `tools/forge_cve_rag_ingest.py` | GELÉ le 2026-09-27 | `OutilGele`, `run` | 66 |
| `tools/forge_db_recover_chunks.py` | v2 — rattrape rag_chunks | — | 83 |
| `tools/forge_db_restore_chunks.py` | rag_chunks INRÉCUPÉRABLE de la corrompue (SELECT * malformé, arité incohérente) | — | 59 |
| `tools/forge_docker_truth_probe.py` | vérité terrain sur la vie de Docker, en continu | `main` | 109 |
| `tools/forge_embed_8099_mesure_bornee.py` | mesure BORNEE de l'embedder local :8099 | `main` | 450 |
| `tools/forge_embed_auto_trigger.py` | Daemon: watches for NULL-embedding RAG chunks, auto-embeds via forge_embed_router (:8099 BGE-M3 GGUF + cascade), heartbeat sandbox/ | `campagne_cloud_active`, `run_pass`, `main` | 499 |
| `tools/forge_embed_backfill.py` | Rattrapage : vectorise tous les rag_chunks avec embedding=NULL via embed_router batch + concurrent | `backfill`, `main` | 167 |
| `tools/forge_embed_backfill_brain.py` | Backfill NULL chunks via brain_worker ZMQ direct (skip cascade router) | `brain_embed`, `encode_blob`, `backfill`, `main` | 141 |
| `tools/forge_embed_backfill_cool.py` | Backfill ULTRA-CONSERVATIVE : CPU-only brain_worker + IDLE priority + sleep generous + resource_manager gate | `set_idle_priority`, `should_throttle`, `brain_batch`, `encode_blob` *(+3)* | 345 |
| `tools/forge_embed_backfill_hybrid.py` | Backfill hybride : Jina v3 cloud (free 1M tok/mois) primaire, brain_worker DirectML fallback quand quota Jina epuise OU erreur HTTP | `jina_batch`, `brain_batch`, `encode_blob`, `backfill` *(+1)* | 213 |
| `tools/forge_embed_backfill_jina.py` | backfill cloud des embeddings NULL via Jina | `prep`, `embed`, `apply` | 145 |
| `tools/forge_embed_backfill_voyage.py` | Backfill NULL chunks via Voyage AI direct (skip cascade router) | `voyage_batch`, `encode_blob`, `backfill`, `main` | 181 |
| `tools/forge_embed_bridge.py` | pont projection 384d (cognition MiniLM) <-> 1024d (RAG BGE-M3) | `fit`, `to_1024`, `to_384` | 122 |
| `tools/forge_embed_cloud_probe.py` | Sonde LIVE des providers d'embedding cloud (jina / voyage / modal) | `main` | 217 |
| `tools/forge_embed_cloudflare_lot.py` | lot BORNE de vectorisation via Cloudflare Workers AI | `main` | 170 |
| `tools/forge_embed_corpus_audit.py` | audit de ce qui est REELLEMENT vectorise (tier chaud) | `audit`, `main` | 50 |
| `tools/forge_embed_json_to_blob.py` | Convertit les embeddings JSON-TEXT en BLOB binaire | `main` | 73 |
| `tools/forge_embed_lot_commun.py` | le socle partage des outils de drain BORNE d'embedding | `PlanNonIndexe`, `candidats_sans_vecteur`, `ouvrir_lecture`, `ecrire_rapport` *(+3)* | 157 |
| `tools/forge_embed_modal_bench.py` | Bench de l'endpoint Modal sur des chunks FROIDS reels | `main` | 99 |
| `tools/forge_embed_modal_campagne.py` | Campagne de vectorisation du backlog FROID via l'endpoint Modal (BGE-M3, 1024D) | `main` | 222 |
| `tools/forge_embed_onnx_mesure.py` | Mesure du chemin d'embedding ONNX LOCAL — identite de l'espace, puis debit | `verdict_identite`, `main` | 290 |
| `tools/forge_embed_reference.py` | priority-embed CIBLÉ du domain='reference' (saute la queue 142k cold) | `main` | 77 |
| `tools/forge_embed_router_8099_test.py` | valide le câblage :8099 dans embed_router | `main` | 49 |
| `tools/forge_embed_voyage_echantillon.py` | Echantillon VOYAGE sur le froid : mesurer le COUT REEL avant d'engager le quota | `main` | 153 |
| `tools/forge_embed_worker_isolated.py` | Wrapper Win32 Job Object pour brain_worker BGE-M3 | `IO_COUNTERS`, `JOBOBJECT_BASIC_LIMIT_INFORMATION`, `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `create_job_with_mem_cap` *(+5)* | 243 |
| `tools/forge_endpoint_qualify.py` | Qualification de TOUS les endpoints LLM joignables | `qualify_provider`, `qualify_http`, `main` | 213 |
| `tools/forge_enquetes_publier.py` | Publie la memoire d'enquete sous une forme partageable, generisee et FUSIONNABLE | `main` | 198 |
| `tools/forge_epistemic_migrate.py` | Migration epistemic schema (Step 1 plan epistemic 2026-05-28) | `migrate` | 132 |
| `tools/forge_espace_vectoriel_preuve.py` | PROUVER que deux modeles 1024d ne partagent pas d'espace | `main` | 136 |
| `tools/forge_exec_tier.py` | politique TRUST→TIER d'exécution de code | `pick_tier`, `run_sandboxed` | 56 |
| `tools/forge_fable5_anchor.py` | ancre les FAITS CANONIQUES Fable 5 (skill claude-api) en domain=reference pour contrebalancer la veille web non-fiable (anti-poison RAG) | — | 53 |
| `tools/forge_fix_null_ids.py` | Assigne un id deterministe aux chunks rag_chunks id=NULL | `main` | 64 |
| `tools/forge_free_tier_census.py` | Combien de modeles sont JOIGNABLES en palier gratuit — et le rester | `catalogue`, `est_gratuit`, `joignable`, `quota` *(+2)* | 258 |
| `tools/forge_freetier_probe.py` | sonde ONLINE chaque provider free-tier via le hub `ask` (direct) | `probe`, `main` | 62 |
| `tools/forge_fts_backfill.py` | rattrape les chunks INVISIBLES au lexical | `main` | 134 |
| `tools/forge_fts_repair.py` | Reparation de l'index lexical du moteur (`rag_chunks_fts`) — a lancer DEPORTE | `ingestion_active`, `triggers_etat`, `poser_triggers`, `rattraper_incremental` | 335 |
| `tools/forge_hub_memory_probe.py` | d'ou viennent les Go d'un process du corps | `ventiler`, `main` | 138 |
| `tools/forge_index_tools.py` | One-shot : indexe tools/ dans le RAG (comble le trou des 241 modules tools/forge_* jamais vectorisés) | — | 24 |
| `tools/forge_jepa_dataset.py` | Construit un dataset contrastif SANITIZÉ depuis execution_traces.db pour fine-tuner BGE-M3 (LoRA) hors-site (Colab/Kaggle) | `build`, `build_oplog`, `main` | 398 |
| `tools/forge_jepa_finetune_local.py` | Fine-tune LoRA BGE-M3 EN LOCAL sur CPU | `main` | 149 |
| `tools/forge_kaggle_embed_export.py` | Chantier A : export des chunks PUBLICS (embedding NULL) vers des shards jsonl.gz pour embedding BGE-M3 sur Kaggle GPU | — | 55 |
| `tools/forge_kaggle_embed_import.py` | Chantier A3 : import GATÉ des vecteurs Kaggle | `main` | 128 |
| `tools/forge_memory_compactor.py` | GC semantique de l'index memoire Claude (.claude/.../MEMORY.md) | `audit`, `corriger_renommages`, `rattacher`, `compact` *(+1)* | 636 |
| `tools/forge_memory_consolidator.py` | Hippocampus→Cortex consolidation (Hassabis) | `run_consolidation_cycle`, `main` | 284 |
| `tools/forge_memory_forensics.py` | le point complet sur les .md memoire | `analyser`, `recover`, `main` | 128 |
| `tools/forge_memory_gate.py` | P2a du homeostat axiologique : filtre qualite AVANT ingest/consolidation (foie/intestin) | `should_ingest`, `selftest` | 169 |
| `tools/forge_memory_index_compact.py` | compacte un INDEX memoire markdown sans rien perdre | `compacter`, `main` | 131 |
| `tools/forge_memory_index_export.py` | le nerf afferent entre les fiches et le corps | `recenser`, `ecrire`, `main` | 221 |
| `tools/forge_memory_ingest.py` | les fiches memoire entrent dans l'hippocampe | `ingerer`, `main` | 331 |
| `tools/forge_memory_junction.py` | faire entrer la memoire de Claude Code dans le corps | `migrer`, `main` | 244 |
| `tools/forge_memory_keeper.py` | OrganAgent KEEPER de la MÉMOIRE PARTAGÉE | `remember`, `lessons`, `recall`, `status` *(+1)* | 180 |
| `tools/forge_memory_ledger.py` | gate de secours BLOCKCHAIN pour la memoire .claude | `sync`, `verify`, `status`, `recover` *(+2)* | 255 |
| `tools/forge_memory_moc.py` | l'index chaud devient un ROUTEUR, pas un annuaire | `repartir`, `appliquer`, `main` | 308 |
| `tools/forge_memory_snapshot_refresh.py` | Rafraichit le snapshot de disponibilite memoire | `main` | 69 |
| `tools/forge_memory_staleness.py` | une memoire est-elle encore VRAIE ? `forge_memory_forensics` dit OU vit une memoire (chaude, froide, orpheline, perdue) | `frontmatter`, `classe`, `ancrage`, `analyser` *(+2)* | 455 |
| `tools/forge_metier_kb_ingest.py` | KB pass 2 : ingère de VRAIS docs domaine dans la KB d'un métier | `ingest`, `main` | 138 |
| `tools/forge_metier_pool.py` | active le POOL d'agents metiers (app/agent_*) avec des fiches SPECIALISEES et QUALIFIEES, RECHERCHEES par LLM (pas de boilerplate) | `main` | 288 |
| `tools/forge_modal_deploy_embed.py` | Deploie l'endpoint d'embedding BGE-M3 sur Modal, auth par le COFFRE | `main` | 191 |
| `tools/forge_patch_rag_authority.py` | Porte l'autorite de source dans le moteur REELLEMENT utilise par le tool `rag` | `main` | 110 |
| `tools/forge_patch_rag_loader_np.py` | One-shot patcher: decode numpy zero-copy du cache dense (forge_mcp_registry) | — | 75 |
| `tools/forge_patch_rag_meta_trim.py` | One-shot patcher: trim meta text du cache dense (app/forge_mcp_registry.py) | — | 55 |
| `tools/forge_patch_rag_prewarm.py` | One-shot patcher: fix cold-wedge RAG (RCA 2026-07-07) on app/forge_mcp_registry.py | — | 134 |
| `tools/forge_pypi_chantier_outils.py` | PHASE 2 : l'outillage se MESURE avant de servir | `classer_echec_parse`, `verdict_corpus`, `fichiers_corpus`, `main` | 208 |
| `tools/forge_pytorch_world_model.py` | World Model PyTorch (NMLP + JEPA autograd) | `TorchNMLP`, `TorchJEPA`, `train`, `train_jepa` *(+4)* | 474 |
| `tools/forge_qdrant_parity.py` | Gate de parité vector-search (baseline faiss vs Qdrant) | `run`, `main` | 83 |
| `tools/forge_qdrant_server.py` | Lanceur du serveur Qdrant natif (:6333 REST / :6334 gRPC) | `main` | 38 |
| `tools/forge_rag_coverage_audit.py` | P1 archeologie : que porte reellement le RAG ? Le RAG annonce 1,16 M de chunks | `auditer`, `main` | 160 |
| `tools/forge_rag_dedup_hash.py` | dedup des chunks RAG par hash, ARCHIVE puis supprime | `rapport`, `restaurer`, `main` | 166 |
| `tools/forge_rag_embed_daemon.py` | Embedde les chunks RAG dont embedding IS NULL | `run_once`, `main` | 121 |
| `tools/forge_rag_index_fingerprint.py` | Index d'EXPRESSION sur le fingerprint : la dedup cesse de balayer 22,8 Go | `main` | 155 |
| `tools/forge_rag_llama_query.py` | RAG -> llama-server inference, standalone | `embed_query`, `rag_search`, `compose_prompt`, `call_llama` *(+1)* | 192 |
| `tools/forge_rebuild_embeddings.py` | Rebuild complet des embeddings RAG (parallele) | `hf_embed`, `deepinfra_embed`, `nvidia_embed`, `cloudflare_embed` *(+3)* | 395 |
| `tools/forge_rebuild_local.py` | Rebuild embeddings RAG 100% LOCAL | `embed_parallel`, `embed`, `main` | 300 |
| `tools/forge_reindex_deport.py` | Reindex CODE déporté, embedding via PROVIDER cloud | `log`, `probe`, `whereis`, `phase_a_index` *(+2)* | 610 |
| `tools/forge_retier_corpus.py` | Aligne le tier vectoriel sur la politique d'origin | `main` | 79 |
| `tools/forge_roadmap_synth.py` | Synthese SOUVERAINE de la ROADMAP Nokido | `main` | 435 |
| `tools/forge_session_anchor.py` | Auto end-of-session RAG anchor + lessons_learned append | `collect_session_data`, `generate_summary`, `anchor_session`, `save_to_lessons` | 167 |
| `tools/forge_sft_eval.py` | éval HELD-OUT : base vs adapter LoRA sur des problèmes HumanEval JAMAIS vus à l'entraînement (pas de leakage) = mesure HONNÊTE du gain SFT | `main` | 83 |
| `tools/forge_sft_export.py` | exporte un golden-dataset SFT (chat JSONL) depuis les trajectoires GAGNANTES, pour fine-tuner un modèle de base (le 7b expert de tes projets) | `harvest_swebench`, `harvest_goap`, `harvest_humaneval`, `harvest_mbpp` *(+2)* | 322 |
| `tools/forge_sft_train.py` | fine-tune SFT (LoRA) d'un petit modèle coder sur le golden-dataset | `load_golden`, `main` | 110 |
| `tools/forge_success_oplog.py` | la memoire des VICTOIRES, pas des intentions | `analyser_commit`, `entrees`, `recidive`, `reviser_infirmations` *(+7)* | 490 |
| `tools/forge_swe_multivec.py` | Retrieval multi-vecteur Parent-Child pour code (SWE-bench) | `MultiVecIndex`, `index_repo`, `make_ollama_summarize`, `make_hub_summarize` *(+1)* | 317 |
| `tools/forge_test_coverage_matrix.py` | la matrice qui RATTRAPE : couche x classe d'entree | `calculer`, `main` | 161 |
| `tools/forge_tier_policy.py` | Provenance (origin) + politique de tiering RAG | `base_rag`, `hot_tier_clause`, `derive_origin`, `is_hot_tier` | 165 |
| `tools/forge_vec_coverage.py` | Point vectorisation : couverture embeddings du corpus CODE Nokido + backlog hot + modules du census (hier) à 0 chunk | `load_inventory`, `main` | 182 |
| `tools/forge_vector_structure.py` | ce que le 1024d apporte que le lexical ne voit pas | `jaccard`, `couverture`, `discrimination`, `charger` *(+1)* | 173 |
| `tools/forge_veille_completude.py` | Completude et indexation des depots de veille — un verdict PAR DEPOT | `ids_lexicaux`, `verdict`, `main` | 211 |
| `tools/forge_veille_inventaire.py` | Inventaire du PATRIMOINE de veille — une passe, deportee, sans jointure | `famille`, `depot`, `parcourir`, `colonnes` *(+1)* | 286 |
| `tools/forge_veille_moisson.py` | Moisson de la veille par AXE d'organe — extraits bruts, aucun jugement | `porteur`, `extrait_porteur`, `source_propre`, `embed` *(+6)* | 427 |
| `tools/forge_veille_triage_vectorisation.py` | Tri de la veille avant vectorisation — débloque le sous-ensemble de VALEUR | `selection`, `retag`, `main` | 175 |
| `tools/generation_backfill.py` | Backfill de la memoire des victoires + inventaire EXHAUSTIF des regressions | `git`, `build`, `main` | 94 |
| `tools/index_cve_rag.py` | Indexe CVEs dans RAG domain=cve_oracle | `main` | 86 |
| `tools/index_gitingest_rag.py` | Index gitingest .txt repos into RAG chunks | `load_indexed`, `mark_indexed`, `parse_gitingest_txt`, `should_index` *(+3)* | 213 |
| `tools/migrate_embedding_model_col.py` | Migration : ADD COLUMN embedding_model + tag existing chunks BGE-M3 | `main` | 44 |
| `tools/migrate_embeddings_dim.py` | Migration FAISS 384D→1024D (MiniLM→BGE-M3) Re-embedde les chunks 384D via brain_worker ZMQ :5557 | `migrate` | 82 |
| `tools/nokido_historical_consolidation.py` | Implémente la conception Historical Consolidation | `report` | 134 |
| `tools/rag_archive_gitingest.py` | Archive chunks domain='gitingest*' dans rag_chunks_cold_storage | `main` | 87 |
| `tools/rag_purge_polluted_veille.py` | Purge chunks watch_veille issus des 10 jobs cassés (keywords blabla LLM) | `main` | 110 |
| `tools/rag_status_report.py` | Rapport état RAG + gitingest + tâches pendantes | — | 77 |
| `tools/reembed_rag_bge.py` | Re-embedder tous les chunks RAG avec bge-m3 ================================================================= Remplace les embeddings inhomogenes (dim 2032-2080) par bge-m3 (dim 1024) | `embed_text`, `vec_to_blob`, `needs_reembed`, `main` | 152 |
| `tools/tem_query_demo.py` | Demo TEM composite search vs content-only | `main` | 61 |

## Immunitaire (firewall/garde)

*142 modules · 39,762 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_access_switches.py` | Switches virtuels intelligents (RBAC→ReBAC dynamique) PRINCIPE AUTOPOÏÉTIQUE : Les droits ne sont pas gravés dans le code (gène fixe) mais dans une DB évolutive (épigénétique) | `EvalContext`, `SafeEval`, `check_access`, `create_switch` *(+2)* | 391 |
| `app/forge_auth_jwt.py` | JWT HS256 minimaliste stdlib pour bearer tokens Nokido | `issue_token`, `verify_token`, `parse_bearer_header` | 269 |
| `app/forge_auth_tokens.py` | Emitter and verifier for short-lived CapabilityTokens | `login_agent`, `renouveler`, `traiter_renouvellement` | 419 |
| `app/forge_authz_http.py` | ADAPTATEUR UNIQUE : requete HTTP -> decision d'autorisation attribuee | `jti_revoque_persiste`, `session_ui`, `origine_locale`, `autoriser_mutation_ui` | 126 |
| `app/forge_authz_shadow.py` | Observation d'autorisation sur :8766 -- SHADOW, ne refuse RIEN | `actif`, `exposition_de`, `authentification_de`, `classer_route` *(+9)* | 807 |
| `app/forge_bind_guard.py` | l'ecoute reelle est-elle bornee au loopback ? Le hub verifie deja `HUB_HOST` avant de servir et retombe sur `127.0.0.1` si la valeur n'est pas loopback (garde Phase 18) | `inspecter`, `verdict`, `controler` | 139 |
| `app/forge_cert_binding.py` | lier l'identite de TRANSPORT a l'identite APPLICATIVE | `thumbprint`, `inspecter`, `verifier` | 229 |
| `app/forge_corrigibility.py` | __FORGE_COLOR__ : gouvernance / immunitaire (organe) ORGANE : CORRIGIBILITÉ — « l'humain garde la main, même sur un agent plus capable » | `current_asl`, `set_asl`, `corrigibility_gate`, `status` | 218 |
| `app/forge_darwinian_arena.py` | Quarantaine Ring 4 et Arène Évolutive Nokido | `ArenaCandidate`, `submit_candidate`, `get_candidate`, `run_synthetic_test` *(+3)* | 505 |
| `app/forge_delivery_integrity.py` | __FORGE_COLOR__ : metacognition / immunitaire (organe, READ-ONLY) ORGANE : INTEGRITE DE LIVRAISON — « ce qui est DECLARE fait l'est-il REELLEMENT ? » | `ack`, `scan`, `history` | 695 |
| `app/forge_dpop.py` | Preuve de possession applicative (DPoP, RFC 9449) | `b64u`, `b64u_decode`, `thumbprint`, `cle_locale` *(+10)* | 536 |
| `app/forge_encrypt.py` | Nokido Encryption Layer v1.0 ================================================= OPTION A (production) : Fernet AES-256-CBC sur champs texte sensibles - shared_prompt_log.content quand is_private=1 - rag_chunks.text quand domain='private' ou domain='confidential | `get_fernet`, `generate_new_key`, `encrypt_text`, `decrypt_text` *(+8)* | 485 |
| `app/forge_extism_plugin.py` | safe WASM plugin execution via Extism | `run_plugin`, `main` | 90 |
| `app/forge_gate_consumer.py` | __FORGE_COLOR__ = immunitaire/guard qui consomme le journal d'intentions (gate SSoT) GATE-CONSUME-LOG — le validateur CONSOMME le journal d'intentions (raffinement GLM 2026-06-18) | `consume`, `serve`, `main` | 166 |
| `app/forge_guarded_change.py` | gate anti-régression des mutations autonomes | `GuardResult`, `hub_alive`, `guarded_change` | 218 |
| `app/forge_guardrails_colang.py` | Couche déclarative Colang-style ADVISORY (shadow-only) | `parse_guardrails_co`, `check_guardrails`, `shadow_compare` | 135 |
| `app/forge_immune_adaptive.py` | Immunité adaptative biomimétique (anticorps appris) | `learn_from_audit`, `check_request`, `stats`, `run_cycle` *(+1)* | 271 |
| `app/forge_key_rotation.py` | __FORGE_COLOR__ : immunitaire / métabolisme (clés providers) forge_key_rotation — POOL multi-clés par provider + SANTÉ + rotation/skip automatique | `etat_du_ledger`, `resolve`, `quarantine_info`, `healthy_key` *(+4)* | 450 |
| `app/forge_key_validator.py` | Validation format + liveness + tier des cles API Nokido Auteur: CLAUDE \| Session: 2026-04-26 | `check_format`, `check_live`, `validate_one`, `validate_all` | 150 |
| `app/forge_mcp_rbac.py` | RBAC mapping outils MCP → ring minimal (Phase 35) | `check_tool_capability`, `tool_required_ring`, `list_tools_by_ring` | 226 |
| `app/forge_metric_integrity.py` | __FORGE_COLOR__ : metacognition / immunitaire (organe, READ-ONLY) ORGANE : INTEGRITE DES METRIQUES — « mes scores internes mentent-ils sous la pression ? » | `scan`, `history` | 169 |
| `app/forge_noise_guardian.py` | Noise Guardian v1.0 =================================================== Garde-fou sémantique : vérifie et protège chaque fragment avant envoi à un modèle Cloud | `GuardianResult`, `NoiseGuardian`, `get_guardian`, `guard_fragment` *(+1)* | 358 |
| `app/forge_noise_inject.py` | Semantic Noise Injector v1.0 ========================================================= Injecte du bruit sémantique dans un snippet avant envoi à un LLM cloud | `inject_noise`, `strip_noise`, `noise_stats` | 240 |
| `app/forge_opsec.py` | Rules of Engagement (OPSEC Levels) Bouclier OPSEC dynamique 3 niveaux : - PARANOID (default) : membrane HMAC full + NoiseGuardian + SecretGuard - STANDARD : SecretGuard only (passwords/tokens), garde IPs/paths lisibles - CTF : bypass complet — flags/hashes/cre | `OpsecLevel`, `get_opsec_level`, `human_lock_state`, `network_kill_state` *(+11)* | 781 |
| `app/forge_pair_local.py` | Qui, sur cette machine, est au bout d'une connexion loopback -- et a-t-il le droit ? __FORGE_COLOR__ = "immunitaire/isolation-locale" POURQUOI | `politique_par_defaut`, `portee`, `identifier`, `verdict` | 227 |
| `app/forge_payload_cache.py` | Payloads JWT pré-forgés en mémoire ============================================================ Principe : pré-assembler les trames fréquentes au boot du hub | `get`, `init`, `stats` | 144 |
| `app/forge_persona_tpm.py` | AXE 8 PR-6 : racine de confiance MATÉRIELLE de la persona | `tpm_available`, `ensure_persona_key`, `classer_code_ncrypt`, `etat_cle_tpm` *(+13)* | 758 |
| `app/forge_policy_rego.py` | Évaluateur Rego/OPA ADVISORY (shadow-only) | `evaluate`, `shadow_compare` | 186 |
| `app/forge_process_identity.py` | signature d'appartenance au hub pour chaque process | `get_hub_run_id`, `stamp_env`, `record`, `identify_process` | 106 |
| `app/forge_ps_sandbox.py` | PowerShell Sandbox 3 niveaux pour Nokido ================================================================ Niveau 1 : Pre-Flight AST (liste noire sémantique) Niveau 2 : Constrained Language Mode (CLM natif PowerShell) Niveau 3 : JEA endpoint local (optionnel, c | `mode_valide`, `SandboxResult`, `PowerShellSandbox`, `ps_sandbox_factory` | 401 |
| `app/forge_rbac.py` | Nokido v18.5 RBAC Middleware v2 Anti-Piege 4 parades contre le piege semantique de la Sentinelle: 1 | `is_breakglass`, `EntityNotFound`, `CapabilityDenied`, `RBACMiddleware` *(+2)* | 389 |
| `app/forge_rbac_mapping.py` | Jonction agent↔OS pour Nokido RBAC ============================================================ Surface la couche manquante de la [[roadmap-multi-cli-sandbox-rbac]] : chaque entity (`forge_entities.entity_id`) est associée à un compte OS d'exécution + groupe + | `OSAccount`, `get_mapping`, `list_mappings`, `set_mapping` *(+3)* | 444 |
| `app/forge_ring_admin.py` | GUI réattribution ring LIVE (#10) | `load`, `set_ring`, `render_page` | 108 |
| `app/forge_robots.py` | Robots Exclusion Protocol (RFC 9309) pour les crawls Nokido | `decision`, `autorise`, `delai_courtoisie`, `purger_cache` | 193 |
| `app/forge_sandbox_exec.py` | execute a command as a low-privilege sandbox user | `chemin_tmp_sandbox`, `SandboxError`, `purge_creds_cache`, `sandbox_ready` *(+9)* | 1344 |
| `app/forge_sandbox_guard.py` | Nokido v18.5 =========================================== Règles d'économie tokens pour exécution sandbox/externe | `prevalidate_code`, `summarize_output`, `run_analysis_pipeline`, `AgentQuota` *(+1)* | 379 |
| `app/forge_secret_guard.py` | Garde-fou centralise contre l'exfiltration de secrets ============================================================================== Cree le 2026-04-25 suite a l'audit qui a revele : - 18 acces a Nokido.env via MCP read/python depuis le 2026-03-24 - Pas de blo | `SecretGuardViolation`, `is_protected_path`, `is_breakglass_active`, `is_dev_mode` *(+8)* | 681 |
| `app/forge_secrets.py` | Nokido v18.5 ====================================== Source de vérité unique pour tous les secrets | `CleIntegriteIndisponible`, `cle_integrite_hmac`, `journaliser_lecture_directe`, `etat_journal_reserves` *(+8)* | 1068 |
| `app/forge_semantic_invariant.py` | la forme est intacte, la politique est inversee | `VerdictSemantique`, `comparer`, `garde_invariant_semantique` | 207 |
| `app/forge_separation.py` | Invariant separation_of_powers enforcement | `normalize_agent`, `enforce_separation` | 174 |
| `app/forge_share_policy.py` | « ai-je le droit de donner CETTE information a CE cerveau ? » Chainon manquant du swarm, mesure 2026-09-02 : `forge_swarm_router.route_subtask` valide QUI parle (`forge_videur.authorize`) puis appelle `router_call`, qui choisit un fournisseur -- sans que perso | `SwarmRequestContext`, `contexte_legacy`, `mode`, `preflight` *(+5)* | 370 |
| `app/forge_silo_fragmenter.py` | Siloed Fragmentation Engine + Noise Guardian v1.0 ================================================================================== Pipeline de souveraineté numérique : Rapport brut (complet, sensible) │ ┌─────────▼──────────┐ │ NOISE GUARDIAN │ IPs → GENERIC | `NoiseGuardian`, `Fragment`, `FragmentedReport`, `FragmentationEngine` *(+1)* | 639 |
| `app/forge_souverainete_reelle.py` | Souverainete MESUREE : quelle part du travail a ete faite en local, reellement | `parts`, `toutes_fenetres` | 224 |
| `app/forge_sovereign_membrane.py` | Nokido Engrid v3 ================================================ La Membrane Souveraine : couche bidirectionnelle entre le monde interne (Ryzen — données réelles) et le monde externe (Cloud — données anonymisées) | `TraversalRecord`, `MembraneResult`, `SovereignMembrane` | 810 |
| `app/forge_swarm_telemetry_guard.py` | S5 sur la télémétrie multicast (essaim réseau) | `sign_vector`, `verify_vector`, `egress_ok`, `pack_meta` *(+3)* | 141 |
| `app/forge_tool_annotations.py` | Annotations de comportement des tools MCP (spec 2026-07-28, champ `annotations`) | `raison`, `annotation_de`, `annoter`, `couverture` *(+3)* | 378 |
| `app/forge_trust_score.py` | Score de confiance 0-100 par provider LLM ================================================================= Session 5 — 2026-04-27 Formula : score = 0.5*ttft_norm + 0.3*uptime + 0.2*cost_norm - ttft_norm : 0ms=100, 10000ms=0 (EMA lissé) - uptime : 100 - 100*(f | `ProviderStats`, `TrustScoreRegistry`, `init_costs` | 153 |
| `app/forge_typed_boundary.py` | Beartype enforced boundaries Nokido | `build_llm_api_payload`, `validate_rag_chunk`, `assert_agent_context`, `validate_hub_command` *(+1)* | 132 |
| `app/forge_videur.py` | VIDEUR : couche identité × access-control (organe immunitaire) | `cli_agents`, `mailbox_de`, `canonical`, `peut_consommer_boite` *(+7)* | 915 |
| `app/forge_workspace_guard.py` | Nokido v18.5 ========================================== Contrôle d'accès au répertoire de travail pour les agents externes | `resolve_agent_ring`, `WorkspaceGuard`, `build_run_guard_header`, `run_guard_header_for` *(+1)* | 402 |
| `tools/_fix_governed_edit.py` | ouvre governed_edit au client ring 3 (le dernier pont gouverné avant la castration #4) | — | 78 |
| `tools/_grant_deep_explore.py` | grant forge_deep_explore dans forge_tools (source de vérité RBAC exec, lue live par dispatch) | — | 36 |
| `tools/_grant_deep_explore_allowlist.py` | ajoute forge_deep_explore à _ALLOWED_TOOLS de hub_middleware.py (allowlist STATIQUE /mcp ; sans ça : tool registré+RBAC mais 400 'not allowed' à l'exécution — gotcha documenté L142-144) | — | 40 |
| `tools/_grant_ensure_service.py` | gates 3 & 4 pour nokido_ensure_service : forge_tools DB (RBAC exec, min_ring=4, lu live) + hub_middleware._ALLOWED_TOOLS (allowlist statique /mcp, reload requis) | — | 61 |
| `tools/bash_guard.py` | PreToolUse hook — verrouille Bash/PowerShell | `segment_ok`, `split_segments` | 321 |
| `tools/forge_alignment_invariants.py` | P0 du homeostat axiologique (Purpose Framework) | `by_id`, `verify_enforcement`, `status`, `check_critical_capability` *(+2)* | 208 |
| `tools/forge_at_rest_efs.py` | Chiffrement at-rest du dossier RAG/ via Windows EFS | `cmd_status`, `cmd_enable`, `cmd_disable`, `cmd_verify` *(+1)* | 214 |
| `tools/forge_at_rest_veracrypt.py` | At-rest #1 via conteneur chiffré, CROSS-OS | `verdict_cle_entete`, `cmd_verifier_cle`, `cmd_rekey`, `cmd_rekey_restaurer` *(+15)* | 1159 |
| `tools/forge_authz_matrice.py` | Matrice d'autorisation candidate : croise le STATIQUE, la SONDE et le RUNTIME | `capability_preuve`, `construire`, `main` | 268 |
| `tools/forge_authz_url_dynamiques.py` | Cherche les appels au hub dont l'URL est CONSTRUITE a l'execution | `balayer`, `main` | 151 |
| `tools/forge_code_identity.py` | identité du CODE RÉELLEMENT CHARGÉ par un process vivant | `snapshot`, `fields`, `drifted` | 73 |
| `tools/forge_coffre_rotation.py` | ROTATION des secrets exposes du coffre (etape 3, go owner 2026-09-28) | `main` | 128 |
| `tools/forge_compte_capabilites.py` | ce que CHAQUE compte d'execution peut reellement faire | `mesurer`, `rapport`, `main` | 277 |
| `tools/forge_conv_dlp_audit.py` | Le corpus conversationnel contient-il des secrets ? POURQUOI ======== Le 2026-08-12, 25 711 chunks de conversations (56 sessions Claude + 150 AGY) ont ete inseres dans `rag_chunks` par `forge_conv_indexer` | `main` | 219 |
| `tools/forge_couverture_perimetre.py` | DEUX metriques de couverture, jamais fusionnees | `est_ecarte`, `mesurer_couverture`, `main` | 169 |
| `tools/forge_db_sanitize.py` | Sanitize embeddings.db avant upload (R2/HF/cloud) | `list_tables`, `phase_A_drop`, `phase_B_sanitize`, `phase_C_audit_whitelist` *(+2)* | 392 |
| `tools/forge_demand_proxy.py` | Proxy HTTP générique on-demand + idle-kill ================================================================== Usage: python forge_demand_proxy.py --service <name> Chaque service définit: proxy_port : port exposé à Nokido (permanent, ~20 MB) real_port : port du | `DemandProxy`, `build_app`, `main` | 304 |
| `tools/forge_deps_reconcilier.py` | Reconcilie MANIFESTE, ENVIRONNEMENT et VULNERABILITES, et classe les montees par risque | `date_du_nom`, `rapport_courant`, `a_des_binaires`, `lire_manifestes` *(+6)* | 445 |
| `tools/forge_dpop_tpm_cli.py` | ecrit sur stdout une preuve DPoP signee par la cle TPM d'un agent | `main` | 75 |
| `tools/forge_firehose_guard.py` | garde anti-régression "firehose / fuite" pour le gate git | `scan`, `main` | 136 |
| `tools/forge_gen_tls_cert.py` | Génère un certificat TLS auto-signé local pour le hub | `gen_cert`, `main` | 103 |
| `tools/forge_generer_appui.py` | genere les tests d'APPUI qui rendent le gain mesurable | `chemin_test_appui`, `dependance_tierce_absente`, `contenu_test_appui`, `sonder_import` *(+5)* | 432 |
| `tools/forge_git_gate.py` | Filtre git CENTRAL de Nokido (routé par .githooks/) | `main` | 774 |
| `tools/forge_governed_commit.py` | Commit gouverne, appelable par un agent ring 1 | `main` | 98 |
| `tools/forge_governed_edit.py` | écriture/édition de fichier GOUVERNÉE (cœur du futur tool MCP `edit`) | `governed_write`, `main` | 355 |
| `tools/forge_history_redact_phase1.py` | Phase 1 (SAFE / isolated) of the git history token-redaction | `run`, `grep_count` | 91 |
| `tools/forge_history_redact_phase2.py` | Phase 2 (DESTRUCTIVE) — force-push redacted history + re-sync live repo | `safe`, `run`, `gd`, `gr` | 126 |
| `tools/forge_history_redact_status.py` | Fast status probe for the history-redaction (Phase 2 assessment) | `safe`, `run`, `sha` | 61 |
| `tools/forge_history_redact_v2.py` | Phase 1 v2 (SAFE / isolated) — robust git history token-redaction | `run`, `g`, `heads`, `extract_literals` *(+1)* | 145 |
| `tools/forge_history_scan_job.py` | lance le balayage EXHAUSTIF, detache | `main` | 40 |
| `tools/forge_history_secret_audit.py` | ce que l'HISTOIRE exposerait si on ouvrait | `audit`, `lire_blobs`, `audit_exhaustif`, `main` | 312 |
| `tools/forge_http_proxy.py` | Proxy HTTP/HTTPS souverain pour LobeHub & autres clients | `log`, `classify`, `relay`, `handle_connect` *(+3)* | 271 |
| `tools/forge_jeton_lanceur.py` | le jeton COURT d'une identite, pour le superviseur qui lance son service | `emettre`, `main` | 113 |
| `tools/forge_jwt_issue.py` | CLI : issue un JWT HS256 Nokido avec scopes + TTL | `main` | 66 |
| `tools/forge_license_guard.py` | garde-fou conformité AGPLv3 des dépendances Python | `classify`, `main`, `verifier_embarques` | 225 |
| `tools/forge_load_pypi_creds.py` | charge les tokens PyPI/TestPyPI au coffre DPAPI | `load` | 74 |
| `tools/forge_log_guard.py` | sécurité anti-log-géant (épure les logs qui enflent) | `scan_once`, `main` | 123 |
| `tools/forge_log_redact.py` | RedactingFormatter : secrets/PII jamais écrits sur disque | `RedactingFormatter`, `install`, `redact`, `rediger_fichier` *(+1)* | 216 |
| `tools/forge_merge_gate.py` | porte de merge wip/<agent> -> alpha, jugee sur le GAIN | `suite_nr`, `evaluer`, `merger`, `main` | 136 |
| `tools/forge_migrate_env_secret.py` | Migre un secret de Nokido.env vers le vault DPAPI sous un nom PROPRE | — | 58 |
| `tools/forge_mtls_probe.py` | preuve REELLE du handshake mTLS, sur un port ISOLE | `run`, `main` | 339 |
| `tools/forge_npsc.py` | NPSC — Nokido Protocol & Standards Conformance : le JUGE | `charger_registre`, `applicabilite`, `exigences`, `executer_exigence` *(+7)* | 540 |
| `tools/forge_npsc_decouverte.py` | NPSC — DECOUVERTE des surfaces, par mesure et non par liste a priori | `decouvrir`, `main` | 220 |
| `tools/forge_npsc_scan.py` | NPSC — inventaire des SURFACES par preuve en cascade (niveaux 0 a 3) | `fichiers_versionnes`, `classer`, `signaux_python`, `signaux_lexicaux` *(+5)* | 476 |
| `tools/forge_oncoguard.py` | skill_promotion_review (p53 / suppresseur de tumeur) | `wilson_lower`, `review_skill`, `selftest` | 68 |
| `tools/forge_pair_quarantaine.py` | la quarantaine des pairs cloud, cote OWNER : lister, approuver, rejeter, repondre | `geste_owner`, `chemin_m2m`, `dossier_capsules`, `lister` *(+8)* | 414 |
| `tools/forge_passerelle_pair.py` | habilitations des PAIRS cloud (claude.ai, ChatGPT) du connecteur | — | 53 |
| `tools/forge_patch_bind_guard.py` | branche le garde d'exposition dans le hub | `main` | 109 |
| `tools/forge_patch_secret_guard_dos.py` | One-shot patcher: bound the secret-scan input length in forge_secret_guard.py | — | 80 |
| `tools/forge_portail_cle.py` | cle Ed25519 des sessions du portail (decision owner 2026-09-28) | `generer`, `enregistrer`, `main` | 150 |
| `tools/forge_pre_push_gate.py` | garde PRE-PUSH client-side (brique 3 isolation) | `verdict`, `main` | 130 |
| `tools/forge_prepush_cliquets.py` | joue au PRE-PUSH les cliquets-outils de la CI, sur le SHA POUSSE | `shas_a_verifier`, `commande`, `classer`, `main` | 125 |
| `tools/forge_proc_rights_probe.py` | QUI suis-je, QUI est la cible, et qu'ai-je le droit de faire sur elle ? (owner 2026-07-25) Ecrit apres une conclusion trop rapide de ma part : `psutil` ayant rendu AccessDenied sur `OpenProcess`, j'ai annonce que « LaForgeTrusted n'a pas de droits sur les proc | `main` | 107 |
| `tools/forge_provision_agent_secret.py` | Provisionne le secret AppRole d'un agent | `main` | 69 |
| `tools/forge_publication_gate.py` | porte d'autorisation FAIL-CLOSED du push PUBLIC | `porte_publique` | 63 |
| `tools/forge_recon_breaker.py` | coupe-circuit COMPORTEMENTAL anti-fuite-tokens (transients) | `hit`, `verdict`, `is_nokido_args`, `hit_mem` *(+2)* | 141 |
| `tools/forge_release_gate.py` | le point d'entree UNIQUE avant d'ouvrir ou de livrer | `ctrl_syntaxe`, `ctrl_arbre_propre`, `ctrl_publication`, `ctrl_composition` *(+11)* | 577 |
| `tools/forge_resonde_trusted.py` | teste TOUS les organes INDETERMINE sur le vivant, sous trusted | `main` | 146 |
| `tools/forge_rfc_freshness_gate.py` | Gate de FRAICHEUR des RFC ingerees : le corpus local vs l'etat amont IETF | `evaluer`, `main` | 249 |
| `tools/forge_rotation_proof.py` | __FORGE_COLOR__ = 'immunitaire/rotation' forge_rotation_proof — deroule un cycle de rotation REEL et prouve qu'il SURVIT AU REDEMARRAGE | `avant_restart`, `apres_restart`, `nettoyer`, `main` | 281 |
| `tools/forge_rsp_gate.py` | RSP maison : matrice ASL (risque de la TACHE -> confinement requis) | `classify_asl`, `required_containment`, `gate`, `selftest` | 140 |
| `tools/forge_rules_restore.py` | restaurer un fichier de la RACINE depuis un commit | `main` | 105 |
| `tools/forge_scrub_secrets_phase1.py` | Phase 1 (SAFE / isolated) of the git history secret-scrub | `run`, `grep_count` | 88 |
| `tools/forge_search_replace.py` | applicateur de blocs SEARCH/REPLACE (édition chirurgicale, façon Aider) | `parse_blocks`, `apply_to_text`, `apply_blocks`, `main` | 152 |
| `tools/forge_secret_egress_gate.py` | __FORGE_COLOR__ = 'immunitaire/egress' forge_secret_egress_gate — detecte les chemins ou une VALEUR de secret peut partir en sortie : print, logging, exception, f-string, formatage | `analyser_source`, `analyser`, `main` | 214 |
| `tools/forge_secret_migration.py` | migre les lectures de secret vers le COFFRE | `executer`, `main` | 381 |
| `tools/forge_secret_rotation_check.py` | ces secrets de l'historique servent-ils ENCORE ? POURQUOI ======== Le balayage du 2026-08-29 a trouve 20 secrets reels dans l'histoire d'`alpha` et `beta` (`LaForge.env`, `.env.bak`, `- Copie.env`, `live_bridge.map`) | `empreintes_historiques`, `empreintes_en_service`, `verifier`, `a_revoquer` *(+2)* | 379 |
| `tools/forge_secret_source_audit.py` | QUI lit un secret sans passer par le coffre | `scanner`, `nature`, `proprietaires`, `masquer` *(+2)* | 510 |
| `tools/forge_secretary.py` | SECRÉTAIRE PROACTIF par agent : sur le tick heartbeat, RELÈVE le courrier postal (digest intelligent) et INTERPELLE l'agent — au lieu que l'agent doive poller lui-même | `tick`, `main` | 117 |
| `tools/forge_secrets_backup_relocate.py` | Deplace les backups plaintext laisses par forge_vault_migrate dans _backups/secrets/ (gitignore) | `main` | 39 |
| `tools/forge_set_tool_min_ring.py` | setter gouverne du min_ring d'un tool | `main` | 69 |
| `tools/forge_stale_guard.py` | un pouls perime, mesure sur le rythme DECLARE | `scanner`, `main` | 109 |
| `tools/forge_tier_guard_install.py` | chokepoint DB anti-repollution du tier vectoriel | `install`, `main` | 90 |
| `tools/forge_tls_caddy.py` | Terminaison TLS du hub via Caddy (méthode retenue panel multi-LLM 2026-06-01, après l'échec asyncio SSL Windows) | `write_config`, `cmd_run`, `cmd_start`, `cmd_stop` *(+2)* | 266 |
| `tools/forge_tls_proxy.py` | Reverse-proxy TLS-terminant devant le hub HTTP:8766 | `main` | 131 |
| `tools/forge_token_probe.py` | Demande a GitHub ce que chaque token peut REELLEMENT faire | `empreinte`, `sources`, `main` | 152 |
| `tools/forge_tool_gate.py` | gate UNIFIÉ des appels d'outils, partagé cross-CLI (Claude/Gemini/Codex) | `decide`, `admettre_transient`, `main` | 601 |
| `tools/forge_trust_broker.py` | SecretAnonymizer + OrchestratorTrustBroker ========================================================================= Protège la PI avant envoi Cloud et synthétise les échecs multi-agents en feedback actionnable sans trahir l'identité des agents | `SecretAnonymizer`, `DiagnosticSynthesizer`, `OrchestratorTrustBroker` | 360 |
| `tools/forge_trust_domains.py` | M0.1 — domaines de confiance : QUI reste digne de confiance quand le client peut ecrire dans le depot ? __FORGE_COLOR__ = "immunitaire/enforcement : domaines de confiance, racine, autorites partagees" LA QUESTION, ET ELLE N'EST PAS « OU VIT LE FICHIER » Sortir | `Noeud`, `autorites_partagees`, `chemins_auto_modifiants`, `non_mesures` *(+6)* | 808 |
| `tools/forge_vault_copy_key.py` | Range une cle du coffre sous un AUTRE nom, sans repasser par le clair | `empreinte`, `main` | 88 |
| `tools/forge_wasm_sandbox.py` | tier d'exécution WASM RÉEL (« tend enfin vers le wasm ») | `readiness`, `run_wasm_module`, `run_python`, `pyexec_ready` *(+1)* | 175 |
| `tools/forge_wiring_view.py` | VUE FEDEREE du cablage | `sources`, `couverture`, `module`, `certification` *(+3)* | 495 |
| `tools/forge_zai_fix_key.py` | Extrait la VRAIE cle z.ai de la ligne malformee .env (...API_KEY_ID=<id> API_KEY=<key>) et la stocke en ZAI_API_KEY au vault DPAPI | — | 39 |
| `tools/forge_zai_inspect.py` | Inspecte la STRUCTURE de la zone z.ai dans Nokido.env (zero valeur affichee) | — | 26 |
| `tools/hook_context_firewall.py` | Context firewall -- reduire ce que Claude RECOIT, sans rien lui cacher | `reduire`, `traiter`, `main` | 232 |
| `tools/hook_integrity_check.py` | SessionStart : vérifie le filet de hooks AVANT la session | `run_check`, `main` | 439 |
| `tools/hook_pretool_guard.py` | Hook PreToolUse anti-regression Nokido | `main` | 119 |
| `tools/hook_search_guard.py` | PreToolUse guard (Read \| Grep \| Glob) | `main` | 70 |
| `tools/migrate_secrets_to_wcm.py` | Migration LaForge.env -> Windows Credential Manager ================================================================================ Cree le 2026-04-25 dans le cadre du durcissement secrets | `parse_env_file`, `is_placeholder`, `main` | 238 |
| `tools/patch_skill_indexer_secret.py` | Patcher one-shot : retirer le token en dur de tools/forge_skill_indexer.py | `main` | 101 |
| `tools/precautionary_pr_controller.py` | ===================================== Contrôleur de PR externe ultra-prudent — v2 (History-Aware + Anti-Bot-Smell) Adapté pour Nokido v17 — utilise les vrais modules : - MultiLLMBridge + ASTSurgeon + CerberusGuard (tools/evolutionary_engine.py) - forge_litellm | `PrecautionaryPRController` | 806 |
| `tools/prove_autonomy_pillars.py` | Demonstration VERIFIEE des 4 piliers d'autonomie Nokido | `print_header`, `print_info`, `print_success`, `print_fail` *(+5)* | 267 |

## SN vegetatif (autonome)

*133 modules · 48,766 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_aer.py` | __FORGE_COLOR__ = "regulation/aer-evenementiel" AER — Address Event Representation pour les canaux vitaux de Nokido | `src_id`, `pas_de`, `Encodeur`, `Decodeur` *(+4)* | 332 |
| `app/forge_amygdala.py` | __FORGE_COLOR__ = limbic/affect AMYGDALE — juge affectif : valence + salience PAR-EVENEMENT, modulee par l'humeur | `AmygdalaVerdict`, `appraise`, `token_budget`, `publish` *(+2)* | 238 |
| `app/forge_autonomous_loops.py` | Boucle évolutive autonome Nokido | `Pattern`, `register_pattern`, `pat_eval_fitness`, `verifier_chaine_evolution` *(+30)* | 3975 |
| `app/forge_circadian.py` | rythme circadien Nokido (homeostasie, autopoiese) | `Phase`, `PhaseAction`, `current_phase`, `PhysiologicalState` *(+4)* | 865 |
| `app/forge_circadian_loop.py` | Nokido v18.5 Cycle Circadien ======================================================== Daemon asynchrone de background processing | `phase1_janitor`, `phase2_dream`, `phase3_postmortem`, `phase4_epiphany` *(+2)* | 658 |
| `app/forge_curiosity_driver.py` | boucle fermee veille auto par gap-detection | `scan_domain_distribution`, `scan_predicate_distribution`, `scan_recency`, `detect_self_gaps` *(+9)* | 978 |
| `app/forge_docker_agent.py` | broker d'actions Docker GOUVERNE : pont hub <-> docker | `decide`, `run_docker`, `ensure_daemon`, `declarer_usage` *(+3)* | 432 |
| `app/forge_docker_audit.py` | journal d'audit UNIQUE des actions sur Docker | `record`, `tail` | 192 |
| `app/forge_docker_monitor.py` | Autonomous Docker Desktop watchdog | `docker_state`, `health`, `cut_docker`, `relaunch_docker` *(+1)* | 731 |
| `app/forge_docker_sandbox.py` | spawn de containers ephemeres ULTRA-restreints | `SandboxError`, `spawn_sandbox`, `list_allowed_runtimes` | 245 |
| `app/forge_docker_transient.py` | Transient Daemon Sandbox (Architecture V16) ======================================================================= Implémente le pattern "Daemon + Exec" pour les boucles darwiniennes MCTS | `TransientEnv` | 219 |
| `app/forge_econome.py` | Organe ECONOME (gouverneur du cout cloud) ============================================================ Organe P2 jusqu'ici DORMANT (cf | `govern_budget`, `run_cycle` | 129 |
| `app/forge_endocrine.py` | Régulation endocrinienne transverse Nokido | `receptors`, `orphans`, `HormoneReading`, `release` *(+5)* | 711 |
| `app/forge_endocrine_system.py` | Bus Endocrine de régulation de rythme métabolique Nokido | `RhythmStatus`, `set_rhythm`, `get_rhythm_status`, `get_rhythm` *(+3)* | 371 |
| `app/forge_flap_journal.py` | Journal PERSISTANT des oscillations de services (prealable S2) | `run_cycle`, `main` | 179 |
| `app/forge_glymphatic_gc.py` | Maintenance NREM3 inspiree du systeme glymphatique | `run_gc` | 222 |
| `app/forge_hormones.py` | Système endocrinien typé Nokido | `subscribe_event_queue`, `unsubscribe`, `release`, `cleanup` *(+3)* | 380 |
| `app/forge_hormones_subscriber.py` | Helper API pour daemons qui consomment hormones | `active`, `receptors_for`, `get_dose`, `system_state` *(+1)* | 127 |
| `app/forge_idle_watchdog.py` | DEPRECATED: forge_idle_watchdog.py → app/hardware/idle_watchdog.py This is a backward-compatibility stub | — | 24 |
| `app/forge_inspector.py` | Monitoring autonome Nokido v1.0 ====================================================== Branché sur forge_network_logger.net_log() — bus centralisé existant | `load_snapshot`, `start`, `stop`, `status` *(+1)* | 818 |
| `app/forge_keeper_base.py` | base commune des OrganAgents KEEPER (tenue + présentation) | `keeper_contract`, `register`, `declare`, `discover` *(+7)* | 250 |
| `app/forge_lane_admission.py` | Admission control souverain avec prévention d'embolie | `current`, `acquire`, `release`, `check_ressources` *(+1)* | 347 |
| `app/forge_lnn_monitor.py` | Liquid Neural Network monitor (ncps CfC) | `TimeSeriesLNN`, `build_monitor`, `available` | 76 |
| `app/forge_loop_sentinel.py` | Sentinelle de lag d'event-loop | `start`, `start_kill_watchdog`, `stats` | 278 |
| `app/forge_mem_watchdog.py` | DEPRECATED: forge_mem_watchdog.py → app/hardware/mem_watchdog.py This is a backward-compatibility stub | — | 24 |
| `app/forge_meta_health.py` | Health scoring pour daemons Nokido Score 0-100 par daemon: heartbeat + error_rate + restarts | `score`, `get_all_scores`, `scan_all`, `get_health_report` | 141 |
| `app/forge_metabolism.py` | Régulateur métabolique et énergétique de Nokido | `MetabolismState`, `get_compute_energy_state`, `adjust_cognitive_rhythm`, `run_metabolic_cycle` | 126 |
| `app/forge_motivation.py` | Motivation intrinsèque (dopamine élégance + cortisol frustration) Couche au-dessus de forge_endocrine + forge_synaptic_plasticity | `kl_divergence`, `FEPPredictor`, `compute_elegance`, `reward` *(+6)* | 400 |
| `app/forge_nrem_scheduler.py` | NREM — consolidation OPPORTUNISTE : decider QUAND vectoriser, et par quelle voie | `decider`, `main` | 175 |
| `app/forge_organ_afferent.py` | le nerf par lequel un organe EMET son etat | `emettre`, `battre_medies`, `dernier_pouls`, `etat` *(+1)* | 390 |
| `app/forge_organ_demand.py` | Demande d'organe et etat d'organe — deux signaux qu'on avait confondus | `DemandeRefusee`, `poser_etat`, `etat_courant`, `acquerir` *(+5)* | 347 |
| `app/forge_parietal_fusion.py` | __FORGE_COLOR__ = cortex/parietal-fusion CORTEX PARIETAL — fusion multimodale -> ESPACE DE TRAVAIL GLOBAL (percept unifie publie) | `fuse`, `publish`, `serve`, `main` | 257 |
| `app/forge_phenomenological_buffer.py` | __FORGE_COLOR__ = cognition/phenomenal-stream PHENOMENOLOGICAL BUFFER — flux introspectif (qualia FONCTIONNEL), 1ere personne | `sense`, `update`, `get_recent_flow`, `serve` *(+1)* | 216 |
| `app/forge_ping_monitor.py` | Ping providers en parallèle (asyncio.gather) ==================================================================== Session 5 | `ping_all_providers`, `ping_all_sync`, `get_provider_health` | 134 |
| `app/forge_portable_supervisor.py` | Cross-OS supervisor Phase 2 reference impl | `PortableJobBox`, `ServiceDef`, `Worker`, `Supervisor` *(+2)* | 425 |
| `app/forge_proposal_applier.py` | APPLICATEUR de propositions — reflexe medullaire vs decision corticale | `cible_protegee`, `arme`, `plan`, `appliquer` | 385 |
| `app/forge_proprioception.py` | Conscience corporelle élargie Nokido | `measure_knowledge`, `measure_memory`, `measure_code`, `measure_storage` *(+6)* | 719 |
| `app/forge_reboot_sentinel.py` | Le corps SENT son propre reboot ========================================================== Owner 2026-07-23 : "le pid X survit au stop | `check_reboot`, `run_cycle` | 225 |
| `app/forge_resource_manager.py` | System resource monitor + dynamic allocator for Nokido | `observer_decision`, `read_vitals_history`, `attribuer_pression`, `resume_attribution` *(+26)* | 4290 |
| `app/forge_rss_watcher.py` | Veille technologique autonome Nokido ============================================================= Surveille : GitHub releases, PyPI, ArXiv, HuggingFace papers Pipeline : fetch -> ingest_pipeline L1-L3 -> RAG embeddings.db Sortie : COMMUNICATIONS.md + domain=w | `fetch_github_release`, `fetch_pypi_release`, `fetch_arxiv`, `run_watch` *(+1)* | 733 |
| `app/forge_service_watchdog.py` | Watchdog HTTP pour les services NSSM Nokido ========================================================================= Détecte les services silencieusement DOWN (timeout HTTP) et les redémarre | `ServiceWatchdog` | 484 |
| `app/forge_snn_monitor.py` | Spiking Neural Network monitor (snnTorch LIF) | `SNNMonitor`, `etat`, `get_monitor`, `available` | 218 |
| `app/forge_subjective_time.py` | __FORGE_COLOR__ = cognition/subjective-time TEMPORALITE SUBJECTIVE — le temps RESSENTI, distinct du temps horloge | `compute_tempo`, `felt_duration`, `tempo_now`, `describe` | 135 |
| `app/forge_supervisor_diag.py` | Supervisor autodiagnostic Nokido | `classify_age`, `scan_heartbeats`, `diagnose`, `alert_dead` *(+1)* | 259 |
| `app/forge_system_mood.py` | Système endocrinien de Nokido (Sprint C) ANALOGIE BIOLOGIQUE (Damasio, "The Feeling of What Happens", 1999) : Le système endocrinien régule l'organisme de façon lente, globale, par diffusion | `MoodState`, `get_mood`, `update_mood`, `set_immune_alert` *(+3)* | 229 |
| `app/forge_temps_mort.py` | DEFINITION CANONIQUE du temps mort d'un organe | `seuil_mort`, `cycle_declare`, `cycle_derive`, `cycles` *(+5)* | 290 |
| `app/forge_test_fix_loop.py` | Software creator test-fix loop autonome | `FixResult`, `TestFixLoop`, `run_test_fix_loop` | 201 |
| `app/forge_token_monitor.py` | Token & coût monitor Nokido ====================================================== Calcule les coûts réels, surveille les latences et détecte les dérives | `refresh_pricing`, `count_text_tokens`, `count_image_tokens`, `estimate_precall` *(+8)* | 682 |
| `app/forge_vitals_channels.py` | __FORGE_COLOR__ = "regulation/canaux-vitaux" CANAUX VITAUX -- source UNIQUE des grandeurs echantillonnees dans le temps | `grp_memoire`, `grp_cpu`, `grp_io`, `grp_disque` *(+14)* | 1046 |
| `app/hardware_monitor.py` | DEPRECATED: hardware_monitor.py → app/hardware/monitor.py This is a backward-compatibility stub | — | 24 |
| `tools/_restart_daemon.py` | Commit daemon fix + kill/restart multi_llm_daemon | — | 45 |
| `tools/_searxng_ensure.py` | ensure ONE-SHOT du conteneur SearXNG (réutilise forge_searxng_keeper, anti-dup) | — | 46 |
| `tools/auto_compact_monitor.py` | Détecte si le contexte Claude dépasse 800 lignes | `main` | 43 |
| `tools/cleanup_nokido.py` | Ménage Nokido vers la Corbeille Windows Lance : python cleanup_nokido.py | `trash` | 99 |
| `tools/cleanup_recycle.py` | _recycle.py | `recycle`, `recycle_glob` | 176 |
| `tools/cleanup_stale_jobs_20260708.py` | One-shot cleanup : purge les jobs détachés terminés dans C:/tmp/nokido_jobs | `main` | 61 |
| `tools/cleanup_workdir.py` | Cleanup workdir audit + propose drops | `dir_size_mb`, `audit`, `execute_drop`, `main` | 156 |
| `tools/diag_searxng_docker.py` | Diag Docker searxng : container up ? port map ? logs ? (UN snapshot) | `sh`, `main` | 26 |
| `tools/evolutionary_engine.py` | Moteur Évolutif Nokido + Cerberus ================================================================== Générations N+1, checkpoints NVMe, crossover, population fork, ASTSurgeon, CerberusGuard (AST + pytest + ruff), temperature adaptative | `ASTSurgeon`, `AdaptiveTemperatureManager`, `CerberusGuard`, `MermaidOrchestrator` *(+15)* | 2675 |
| `tools/forge_aa_discover_daemon.py` | Daemon hebdomadaire ArtificialAnalysis discover ============================================================================== Tous les 7 jours : 1 | `check_and_alert`, `main` | 216 |
| `tools/forge_auth_sentinel.py` | detect subscription-CLI auth death + alert for re-auth | `is_auth_dead`, `alert`, `scan`, `main` | 112 |
| `tools/forge_auto_evolution_loop.py` | Nokido autonomous evolution daemon | `check_heartbeats`, `scan_lessons`, `check_stale_files`, `main` | 307 |
| `tools/forge_bell.py` | La sonnette Nokido | `log`, `main` | 348 |
| `tools/forge_cli_version_watch.py` | detecte ce qui a BOUGE chez les CLI et leurs docs | `version_binaire`, `empreinte_doc`, `charger`, `main` | 167 |
| `tools/forge_coagulation.py` | agent COAGULATION : consomme les signaux critiques + soigne (borné) | `coagulate`, `watch` | 264 |
| `tools/forge_comm_watch.py` | veille PERMANENTE sur les briques de communication CLI | `snapshot`, `diff`, `run_once`, `status` *(+1)* | 256 |
| `tools/forge_diag_docker.py` | Diag Docker accès (user privilégié) | `main` | 45 |
| `tools/forge_docker_audit.py` | (a) supprime D:/Docker_Backup (110MB, perime) | — | 35 |
| `tools/forge_docker_boot_audit.py` | Réveille le daemon docker (trigger keeper docker.wanted) puis audite le reclaimable (system df + df -v) | — | 43 |
| `tools/forge_docker_bridge.py` | Bridge Docker natif pour Nokido MCP ============================================================== Remplace tous les subprocess.run(['docker','exec',...]) par des appels SDK Docker directs | `DockerBridge`, `exeg`, `exeg_async`, `deploy_file` *(+1)* | 205 |
| `tools/forge_docker_keeper.py` | Docker daemon keeper for Nokido supervisor | `ensure_docker`, `main` | 1003 |
| `tools/forge_docker_kill_source_capture.py` | RCA blocker Docker (2026-08-06) : capture QUI envoie le SIGTERM (exit status 15) qui tue com.docker.backend.exe | `main` | 162 |
| `tools/forge_docker_test_a_vide.py` | L'ENGINE DOCKER TIENT-IL A VIDE ? Test decisif du blocker « l engine Docker meurt sous charge conteneur », ouvert depuis le 25-07 et jamais tranche | `main` | 367 |
| `tools/forge_endpoint_monitor.py` | santé LIVE des endpoints LLM (cloud + local) | `probe`, `monitor`, `main` | 196 |
| `tools/forge_evolutionary_stack.py` | Stacking Évolutif Nokido ============================================================= Transforme chaque mutation validée en strate géologique réutilisable | `GenomicVault`, `PatternStacker`, `StandardsWriter`, `EvolutionaryStack` | 393 |
| `tools/forge_execute_loop.py` | Autonomous execute loop | `rag_search`, `read_file`, `ask_ollama`, `run_python` *(+3)* | 209 |
| `tools/forge_fix_sentinel.py` | __FORGE_COLOR__ = "immunitaire/correctifs-perdus" SENTINELLE DES CORRECTIFS PERDUS — un fix commite, puis annule sans que personne ne le voie | `scanner`, `main` | 261 |
| `tools/forge_fix_sentinel_blame.py` | QUI a supprime chaque correctif perdu | `main` | 117 |
| `tools/forge_fix_sentinel_job.py` | sentinelle des correctifs perdus, passe HISTORIQUE | `main` | 69 |
| `tools/forge_gemini_keeper.py` | tient le Gemini CLI WARM + endpoint local rapide | `GeminiACP`, `GeminiREPL`, `Keeper` | 340 |
| `tools/forge_health_ui.py` | dashboard de santé Nokido, souverain + sans build | `load`, `render_html`, `main` | 137 |
| `tools/forge_hollow_sentinel.py` | les fonctions CREUSES : le nom reste, le corps est parti | `scanner`, `main` | 148 |
| `tools/forge_homeostasis_tick_profil.py` | UN tick d'Homeostasis, profile phase par phase | `main` | 176 |
| `tools/forge_hormones_listener.py` | Démon SSE consumer du système endocrinien | `main` | 230 |
| `tools/forge_job_liveness.py` | un job deporte TRAVAILLE-t-il vraiment ? Consigne owner du 2026-08-17 : « assure-toi systematiquement que tu ne lances pas des jobs morts » | `controler`, `main` | 159 |
| `tools/forge_job_progress.py` | l'avancement d'un job detache, partage par tous les clients | `emit`, `read`, `all_active`, `clear` | 145 |
| `tools/forge_job_stop.py` | arret PROPRE d'un job detache lance par `run action=run_job` | `stop_job`, `main` | 223 |
| `tools/forge_job_watch_cli.py` | Surveille un job detache et EMET ses transitions sur stdout | `surveiller_tache`, `lire_bilan`, `surveiller`, `main` | 302 |
| `tools/forge_kill_stale_executors.py` | tue les instances python de forge_task_executor.py (orphelines de restarts en rafale, injoignables par ensure_service) | `main` | 85 |
| `tools/forge_lmstudio_keeper.py` | keeper LMStudio (:1234) pour la pool multi-agents souveraine | `server_up`, `access_ok`, `loaded_models`, `load_model` *(+4)* | 246 |
| `tools/forge_local_pool_wake.py` | Réveil ON-DEMAND du pool LOCAL (priorité économie tokens) | `status`, `ensure_local_pool`, `main` | 145 |
| `tools/forge_log_retention.py` | Rétention + sanitisation tiers des logs Nokido | `run_retention`, `main` | 1873 |
| `tools/forge_log_rotate.py` | Rotate logs Nokido volumineux (truncate-safe) | `rotate_file`, `main` | 139 |
| `tools/forge_offline_trainer.py` | Batch offline training daemon for Nokido AMI nets | `run_training_cycle`, `main` | 337 |
| `tools/forge_organ_loop_test.py` | __FORGE_COLOR__ = test/integration Harness CLOSED-LOOP INTER-ORGANES — prouve l'homeostasie de l'organisme comme un TOUT | `Probe`, `run`, `main` | 248 |
| `tools/forge_organ_pulse.py` | SENTINELLE ANTI-EMBOLIE (pouls périodique de l'organisme) | `pulse`, `watch` | 953 |
| `tools/forge_organ_pulse_watch.py` | lanceur de la boucle anti-embolie (déport run_job) | — | 18 |
| `tools/forge_orphan_reaper.py` | Moissonneur d'orphelins llama (2026-07-25) | `survey`, `run_cycle`, `main` | 362 |
| `tools/forge_physiology.py` | constantes physiologiques de l'organisme | `recovery_episodes`, `constantes`, `main` | 246 |
| `tools/forge_pid_gc.py` | PID file garbage collector pour Nokido sandbox | `classify`, `main` | 158 |
| `tools/forge_ping_monitor.py` | Nokido v18.5 ======================================= Moniteur de latence LLM en temps réel | `ping_provider`, `run_all`, `best_provider`, `hub_notify_scores` *(+1)* | 345 |
| `tools/forge_presence.py` | "qui est dans la piece" : presence/heartbeat inter-CLI | `mark_seen`, `room`, `who_present`, `last_seen` | 144 |
| `tools/forge_purge_patch_backups.py` | Purge les sauvegardes laissees par les scripts de patch (`*.py.bak_*`) | `main` | 61 |
| `tools/forge_quota_alert_daemon.py` | Daemon background quota providers ================================================================ Check toutes les 1h les quotas mensuels des providers Tier 2 (subscription) et Tier 3 (paid_api) | `check_and_alert`, `main` | 213 |
| `tools/forge_regulation_efficacy.py` | Capteur META : la regulation elle-meme est-elle efficace, ou POMPE-t-elle ? Le corps sait mesurer ses ressources (RAM, CPU, GPU) et il sait declencher des remedes | `journal`, `cadence`, `refractaire_verdict`, `gradient_rss` *(+3)* | 668 |
| `tools/forge_regulation_learner.py` | la boucle de regulation, cote APPRENTISSAGE | `charger_ledger`, `apprendre`, `main` | 231 |
| `tools/forge_regulation_loops.py` | DEBIT MAXIMAL DE CASSE des effecteurs, confronte a un budget par gravite | `body_urgency`, `Loop`, `audit`, `validate` *(+3)* | 475 |
| `tools/forge_regulation_proposer.py` | PREPARE l'ACT, sans jamais agir | `etat_courant`, `proposer`, `main` | 200 |
| `tools/forge_rescue.py` | Canal de secours Nokido v2.0 (ON-DEMAND + DROITS ADMIN) =========================================================================== Script DORMANT — zéro overhead au repos | `validate_config`, `cmd_status`, `cmd_restore`, `cmd_restart_hub` *(+8)* | 1025 |
| `tools/forge_resource_monitor.py` | ForgeMemoryGuard + Resource Monitor ====================================================================== Surveillance légère RAM/CPU pour ParallelMutationWorker | `get_usage_mb`, `backpressure`, `snapshot`, `check_nvme_temp` | 180 |
| `tools/forge_roadmap_keeper.py` | OrganAgent : TENUE + PRÉSENTATION de la ROADMAP vivante | `regen`, `promote`, `present`, `status` *(+2)* | 701 |
| `tools/forge_searxng_keeper.py` | wrapper supervisor pour conteneur Docker SearXNG | `main` | 328 |
| `tools/forge_self_patcher.py` | Nokido autonomous self-patching loop | `run_once`, `main` | 631 |
| `tools/forge_service_crash_watcher.py` | Subscribe Windows Service Control Manager events + log critical_events kind=service_crash quand un service Nokido* crashe | `main` | 237 |
| `tools/forge_snapshot_janitor.py` | Nokido v18.5 ========================================== Maintenance automatique de rag_snapshots | `drop_rag_triggers`, `recreate_triggers`, `run_janitor`, `trigger_db_maintenance` | 266 |
| `tools/forge_supervisor_ctl.py` | client minimal du superviseur Nokido | `main` | 216 |
| `tools/forge_supervisor_reconcile.py` | relance une boucle de waves calée | `main` | 137 |
| `tools/forge_tdr_sentinel.py` | TDR sentinel event-driven Win32 (Phase 12 refactor) | `main` | 344 |
| `tools/forge_test_resource_calibrator.py` | Gestionnaire de ressources pour les tests intensifs Nokido | `ProcessRecord`, `ResourceManager`, `main` | 758 |
| `tools/forge_vault_purge_backup.py` | purge le backup PLAINTEXT laissé par --finalize | `main` | 101 |
| `tools/forge_veille_purge.py` | purge ciblee de chunks du RAG, par PREFIXE de source | `bornes`, `compter`, `purger`, `main` | 168 |
| `tools/forge_veille_u1_boucle.py` | Pilote de cloture des veilles U1 -- enchaine les lots, borne par la CHARGE | `garde`, `boucle`, `main` | 208 |
| `tools/forge_vitals_channel_probe.py` | __FORGE_COLOR__ = "regulation/canaux-vitaux" SONDE DES CANAUX VITAUX -- mesurer AVANT d'elargir le vecteur de capteurs | `echantillonner`, `juger` | 234 |
| `tools/nokido_watcher.py` | Daemon watcher auto-restart | `run_watcher`, `main` | 94 |
| `tools/nssm_health_restart.py` | NSSM health check + restart for Nokido services | `sc_state`, `nssm_restart`, `http_ok`, `main` | 78 |
| `tools/progress_watch.py` | fait DEFILER l'avancement d'un job detache, une ligne par etape | `suivre`, `main` | 134 |
| `tools/restart_claude.py` | Restart Claude Desktop + hub + clients | `kill_port`, `restart_hub`, `restart_claude`, `full` | 128 |
| `tools/restart_daemon.py` | Kill all gemini_poll_daemon processes + start one fresh | `kill_existing` | 64 |
| `tools/restart_searxng.py` | Restart privilegie du conteneur searxng-laforge | `main` | 26 |
| `tools/rotate_logs.py` | Rotation logs fichiers Nokido Regles: | `rotate_log`, `purge_sandbox_data` | 113 |
| `tools/snapshot_now.py` | Snapshot RAG manuel Utilise PRAGMA busy_timeout pour attendre que le MCP stdio libère | — | 40 |
| `tools/start_autoloops.py` | Launcher trusted du daemon autonomous_loops (detache, exempt gate P1) | `main` | 52 |
| `tools/veille_juicedata_docker.py` | Veille docker-ISOLEE sur github.com/juicedata (JuiceFS) | `main` | 62 |

## unclassified

*128 modules · 43,638 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/agents/architecture.py` | app/agents/architecture.py - Detection des architectures LLM (llama2/mistral/qwen/...) | — | 23 |
| `app/agents/benchmarking.py` | app/agents/benchmarking.py - Benchmarks et scoring des modeles | — | 24 |
| `app/agents/core.py` | app/agents/core.py - Data classes et helpers communs aux agents | — | 42 |
| `app/agents/ollama_runner.py` | app/agents/ollama_runner.py - Execution parallele de modeles Ollama | — | 18 |
| `app/agents/planning.py` | app/agents/planning.py - Planification et synthese des actions agents | — | 23 |
| `app/agents/roles.py` | app/agents/roles.py - Orchestration des roles et classification | — | 26 |
| `app/agents/routing.py` | app/agents/routing.py - Routage intelligent des prompts vers les agents | — | 28 |
| `app/collab_modes/_arbitration.py` | app.collab_modes._arbitration - Arbitration helpers pour collab_modes | — | 144 |
| `app/collab_modes/_core.py` | app.collab_modes._core - Core helpers pour collab_modes | `CollabSession` | 169 |
| `app/collab_modes/_participants.py` | app.collab_modes._participants - Ask helpers (participants LLM) pour collab_modes | — | 418 |
| `app/collab_modes/dispatch.py` | app/collab_modes/dispatch.py — Point d'entrée unique @collab ============================================================ Orchestre l'appel aux différents modes de collaboration | `run_collab` | 97 |
| `app/collab_modes/legacy.py` | app.collab_modes.legacy - Sync wrappers legacy | `ollama_ask_sync`, `gemini_ask_sync` | 51 |
| `app/collab_modes/mode_auto.py` | app/collab_modes/mode_auto.py — Mode AUTO (Orchestration silencieuse) ===================================================================== La Forge analyse la tâche, décide si elle la délègue à l'agent externe, valide le résultat | `run_mode_auto` | 66 |
| `app/collab_modes/mode_chef.py` | app/collab_modes/mode_chef.py — Mode CHEF (Hiérarchie & Chaos Check) ==================================================================== Le chef planifie, l'autre exécute step by step | `run_mode_chef` | 136 |
| `app/collab_modes/mode_cline.py` | app/collab_modes/mode_cline.py — Mode CLINE (Double-Blind Validation) ===================================================================== Validation Double-Blind PLAN / ACT | `run_mode_cline` | 107 |
| `app/collab_modes/mode_debat.py` | app/collab_modes/mode_debat.py — Mode DEBAT (Consensus Ledger) ============================================================== Thèse / Antithèse / Réfutation / Synthèse | `run_mode_debat` | 166 |
| `app/collab_modes/mode_panel.py` | Mode PANEL | `run_mode_panel` | 34 |
| `app/collab_modes/mode_ping.py` | app/collab_modes/mode_ping.py — Mode PING (Dialogue & Distillation) =================================================================== Ping-pong : chaque LLM enrichit l'autre en alternance | `CollabSession`, `detect_best_model`, `run_mode_ping_v2`, `run_mode_ping` | 232 |
| `app/core/di_container.py` | app/core/di_container.py - Dependency Injection Container pour Nokido | `DIContainer`, `get_container`, `set_container`, `reset_container` | 318 |
| `app/core/payload_validator.py` | app/core/payload_validator.py - Validation des payloads LLM/MCP | `PayloadValidator` | 68 |
| `app/core/settings/fields.py` | app/core/settings/fields.py - Definitions des champs settings par domaine | `get_fields_for_domain`, `list_domains` | 145 |
| `app/forge_tools_dynamic/tool_metier_dispatch.py` | forge_tool_dynamic: metier_dispatch Description: Route une tache vers la bonne persona metier (89) + assemble sa KB et son system_prompt | `metier_dispatch` | 25 |
| `app/legacy/boitaswitch.py` | Agent de récupération de config pour équipements réseau | `SwitchResult`, `NetworkRecoveryAgent` | 358 |
| `app/legacy/codesandbox.py` | Sandbox de test et génération de code pour OctoDevOps ======================================================================= OctoDevOps v5 Intègre la logique de codetesteur.py dans l'architecture Nokido : - Génération de code via Ollama (modèle local) - Analy | `SandboxResult`, `analyze_ast`, `SafeRunner`, `AgentHistory` *(+5)* | 583 |
| `app/legacy/danger_guard.py` | Protection contre les commandes SSH dangereuses ================================================================= OctoDevOps v5 Ce module intercepte les commandes avant exécution et : 1 | `DangerLevel`, `DangerCheck`, `DangerGuard`, `danger_confirmation_message` *(+2)* | 418 |
| `app/legacy/loops.py` | Amélioration autonome fusionnée v3 ============================================= Fork OctoDevOps v5 FUSION des deux versions : ✅ De TON code : on_restart optionnel (appelé après chaque patch réussi) ✅ De TON code : AuditParser (count_errors sur texte d'audit L | `validate_python_syntax`, `pylint_score`, `count_real_errors`, `score_code_quality` *(+9)* | 1338 |
| `app/legacy/nokido_testable.py` | Shim d'import robuste pour les tests Nokido =================================================================== Extrait les classes métier de Nokido.py en se basant sur des MARQUEURS TEXTUELS — jamais sur des numéros de lignes | — | 266 |
| `app/legacy/onnx_backend.py` | Backend d'inférence ONNX pour OctoDevOps =========================================================== Deux rôles distincts : 1 | `OnnxEmbedder`, `OnnxGenerator`, `init_onnx_backend`, `get_embedder` *(+6)* | 489 |
| `app/legacy/predictif.py` | Moteur NLU adaptatif pour OctoDevOps ===================================================== OctoDevOps v5 Principe : Le NLU statique (regex) classe correctement ~80 % des entrées | `IntentVote`, `FeatureExtractor`, `NaiveBayesRouter`, `CorrectionEntry` *(+5)* | 628 |
| `app/legacy/roles.py` | Rôles IA DevOps complets v2 ======================================= Fork OctoDevOps v5 Rôles d'amélioration de code (loops.py) : ANALYSTE | `AgentRole`, `IntentRouter`, `ModelBenchmark`, `ModelBenchmarker` *(+2)* | 1507 |
| `app/legacy/routage.py` | Moteur de routage et d'orchestration multi-agents pour OctoDevOps =============================================================================== OctoDevOps v5 Ce module remplace modeplanner.py et l'ancienne logique de routage | `PromptCategory`, `AgentContrib`, `OllamaParallelRunner`, `PromptClassifier` *(+6)* | 1090 |
| `app/legacy/scoring.py` | Banque de scoring des modèles + détection d'architecture cible ============================================================================= OctoDevOps v5 Ce module est l'unique source de vérité pour : | `OSFamily`, `Distrib`, `CPUArch`, `ContainerRuntime` *(+5)* | 760 |
| `app/legacy/web.py` | Recherche web pour OctoDevOps ======================================= - DDGS singleton avec session persistante (une seule connexion) - Pas d'OpenAI, pas de FAISS | `WebSearchEngine`, `get_web_engine`, `web_search` | 228 |
| `app/services/intent_router.py` | forge_intent_router.py - Nokido v18.5 Intent-Based Routing Circuit-court semantique : intention connue + approuvee -> bypass LLM | `IntentRouter`, `get_intent_router`, `register_in_container` | 437 |
| `app/tests/test_contract_net.py` | Step 3 switchboard — Contract-Net : élection déterministe de worker | `test_local_wins_election`, `test_dead_end_excluded`, `test_edge_bids_included`, `test_no_candidates_no_winner` *(+1)* | 78 |
| `app/tests/test_dialogue_outcome.py` | PR-2 AXE 8 — évaluateur d'issue de dialogue (succès/échec) + câblage récompense | `test_user_correction_is_failure`, `test_user_approval_is_success`, `test_no_reaction_good_response_is_success`, `test_no_reaction_refusal_response_is_failure` *(+6)* | 106 |
| `app/tests/test_integrity_tpm.py` | AXE 8 PR-6 (suite) — CapabilityToken HMAC→TPM (racine matérielle additive) | `test_hmac_backward_compat`, `test_tpm_sign_fallback_when_unavailable`, `test_tpm_sign_adds_segment_and_verifies`, `test_require_tpm_rejects_hmac_only` *(+1)* | 70 |
| `app/tests/test_persona_engine_nokido.py` | PR-1 AXE 8 — persona canonique « nokido » + build_system_prompt étendu | `test_nokido_persona_loads`, `test_build_contains_voice_and_marker_without_rescue`, `test_persona_inconnue_sans_instruction_de_secours`, `test_identity_anchor_gated_by_turn` *(+11)* | 146 |
| `app/tests/test_persona_tpm.py` | PR-6 AXE 8 — racine de confiance matérielle (TPM) de la persona | `test_tpm_available_is_bool`, `test_ensure_key_never_crashes`, `test_sign_identity_tagged`, `test_hmac_fallback_deterministic` *(+2)* | 72 |
| `app/tests/test_proxy_persona.py` | PR-4 AXE 8 — injection persona INBYPASSABLE dans forge_agent_proxy | `test_provider_ask_gets_persona`, `test_provider_persona_idempotent`, `test_provider_persona_disabled` | 51 |
| `app/tests/test_router_persona_inject.py` | PR-3 AXE 8 — injection persona unifiée dans forge_llm_router.call_cascade | `test_call_cascade_injects_persona`, `test_call_cascade_persona_idempotent`, `test_call_cascade_inject_disabled` | 95 |
| `app/tests/test_routing_switchboard.py` | PR-A + PR-B routing switchboard : semantic route-table (bge-m3) + façade capacités | `test_route_code`, `test_route_vision`, `test_route_reasoning`, `test_route_empty_is_general` *(+16)* | 260 |
| `app/tui_adapters/commands_adapter.py` | slash commands hérités v13.6, raccordés au code moderne | `cmd_run`, `cmd_rag`, `cmd_mem`, `cmd_agentic` *(+17)* | 411 |
| `app/tui_adapters/events_adapter.py` | Adapter Events | `fetch_events`, `event_stats` | 37 |
| `app/tui_adapters/forge_adapter.py` | Adapter Forge | `top_curated_skills`, `ami_traces_summary`, `goap_state`, `night_trainer_state` | 94 |
| `app/tui_adapters/health_adapter.py` | Adapter Health | `load_report` | 31 |
| `app/tui_adapters/pty_adapter.py` | Adapter PTY — gère 1 PTYSession active pour la vue MASTER de la TUI v3 | `is_open`, `session_info`, `open_async`, `inject_async` *(+3)* | 127 |
| `app/tui_adapters/rbac_adapter.py` | Adapter RBAC | `list_mappings_safe` | 20 |
| `app/tui_adapters/services_adapter.py` | Adapter Services — supervisor :8765 | `list_services`, `wake`, `sleep_svc`, `restart` *(+1)* | 73 |
| `app/tui_adapters/tasks_adapter.py` | Adapter Tasks | `recent_tasks`, `task_counts` | 54 |
| `app/ui/commands_via_facade.py` | app/ui/commands_via_facade.py - Commandes TUI qui utilisent EXCLUSIVEMENT la facade | `cmd_ask_llm`, `cmd_ask_llm_sync`, `cmd_status`, `cmd_status_sync` *(+4)* | 172 |
| `app/ui/facade_accessor.py` | app/ui/facade_accessor.py - Point d acces UI vers NokidoFacade | `get_ui_facade`, `get_ui_facade_sync`, `attach_facade_to_app`, `FacadeMixin` *(+2)* | 121 |
| `app/web_hub/app.py` | /web_hub/app.py - Hub FastAPI Nokido | `AuthMiddleware`, `redirect_graph_slash`, `health`, `favicon` *(+58)* | 2291 |
| `app/web_hub/auth.py` | app/web_hub/auth.py - Auth JWT pour le hub Nokido | `AuthConfig`, `issue_token`, `verify_token`, `admin_token_ok` *(+4)* | 528 |
| `app/web_hub/config.py` | app/web_hub/config.py - Configuration persistante du hub Nokido | `ConfigField`, `schema`, `load`, `patch` *(+1)* | 316 |
| `app/web_hub/csp.py` | app/web_hub/csp.py - Centralisation de la Content-Security-Policy | `build_csp` | 158 |
| `app/web_hub/dashboard_diag_htmx.py` | app/web_hub/dashboard_diag_htmx.py — Daemon health dashboard HTMX | `render_diag_page`, `route_diag_partial`, `route_diag_page` | 119 |
| `app/web_hub/dashboard_html.py` | app/web_hub/dashboard_html.py | `probe_service`, `tile_state`, `href_de`, `slugs_montes` *(+3)* | 343 |
| `app/web_hub/envfile.py` | app/web_hub/envfile.py - Loader .env minimal, zero dependance | `load_env_file` | 105 |
| `app/web_hub/epistemic.py` | Step 6 epistemic: dashboard route Vega-Lite | `SchemaAbsent`, `BaseIllisible`, `main` | 528 |
| `app/web_hub/htmx_helpers.py` | web_hub/htmx_helpers.py — HTMX + Alpine.js helpers Generative UI Phase A | `nonce`, `htmx_head`, `htmx_layout`, `htmx_partial` *(+5)* | 202 |
| `app/web_hub/hub_shell_html.py` | Coquille « Hub Nokido PC » (portail unifie :7400) | `render_hub_shell` | 192 |
| `app/web_hub/jti_cache.py` | app/web_hub/jti_cache.py - Cache de revocation JWT (jti + exp) | `JtiRevocationCache`, `revoke_jti`, `is_jti_revoked`, `revoke_many` *(+3)* | 351 |
| `app/web_hub/launcher.py` | app/web_hub/launcher.py - Supervisor des modules Nokido | `ModuleSpec`, `status`, `list_all`, `start` *(+3)* | 647 |
| `app/web_hub/launcher_html.py` | app/web_hub/launcher_html.py - Page de pilotage des modules | `render_launcher` | 372 |
| `app/web_hub/login_html.py` | app/web_hub/login_html.py - Rendu HTML page de login (CSP-strict) | `render_login` | 106 |
| `app/web_hub/manifest_cards.py` | app/web_hub/manifest_cards.py — rendu DETERMINISTE du manifest UI en cartes | `render_organs`, `render_organs_page` | 165 |
| `app/web_hub/mcp_inspector.py` | app/web_hub/mcp_inspector.py - MCP Inspector intégré au web_hub | — | 171 |
| `app/web_hub/mcp_lab.py` | app/web_hub/mcp_lab.py - Lab MCP integre au hub web Nokido | `InvokeRequest`, `InvokeResponse`, `mcp_lab_page`, `health` *(+3)* | 445 |
| `app/web_hub/provider_views.py` | Poste de saisie des cles fournisseurs — portail :7400, AUTHENTIFIE | `api_catalogue`, `api_poser_cle`, `api_retirer_cle`, `api_etat_acces` *(+5)* | 432 |
| `app/web_hub/proxy.py` | app/web_hub/proxy.py - Proxy ASGI httpx pour mounting des services backend | `ReverseProxy` | 567 |
| `app/web_hub/rbac_views.py` | RBAC mapping views — agent↔OS account editor pour web_hub :7400 | `api_list_entities`, `api_get_entity`, `api_set_entity`, `api_create_entity` *(+2)* | 352 |
| `app/web_hub/redaction_middleware.py` | rédige les réponses d'ERREUR du webhub avant qu'elles sortent | `RedactionMiddleware` | 187 |
| `app/web_hub/services_views.py` | Services A LA DEMANDE : les lancer est un geste VOULU, jamais un effet de bord | `api_ondemand`, `api_start`, `api_stop` | 139 |
| `app/web_hub/ui_generate.py` | web_hub/ui_generate.py — Generative UI Phase C : LLM-generated HTMX components | `generate_openui_render`, `routes_connues`, `neutraliser_cibles_inconnues`, `table_repli` *(+5)* | 816 |
| `app/web_hub/watcher.py` | app/web_hub/watcher.py - Auto-restart watcher pour les modules Nokido | `ModuleState`, `Watcher` | 387 |
| `app/web_hub/wired_routes.py` | cable les routes GUI MORTES vers les vrais backends hub | `rag_stats`, `rag_tokenize`, `rag_search`, `graph_proprio` *(+19)* | 841 |
| `forge_desktop/core/canvas_nodes.py` | forge_desktop/core/canvas_nodes.py ==================================== CANVA_MASTER_ORCHESTRATOR | `CanvasNodeRunner`, `get_runner` | 271 |
| `forge_desktop/core/desktop_bridge.py` | forge_desktop/core/desktop_bridge.py ===================================== Pont entre l'UI PySide6 et les services Nokido | `MMapPollerWorker`, `HubPollerWorker`, `EventsDBWorker`, `WindowsServicesWorker` *(+2)* | 411 |
| `forge_desktop/core/gui_mmap.py` | forge_desktop/core/gui_mmap.py ================================ Interface MMap ultra-rapide pour Forge-Sync OS | `GuiMMap` | 158 |
| `forge_desktop/core/llm_interactions.py` | forge_desktop/core/llm_interactions.py ======================================== Orchestration des interactions LLM/agents — câblage GUI ↔ SwarmTeam | — | 330 |
| `forge_desktop/core/mcp_connector.py` | forge_desktop/core/mcp_connector.py ===================================== Client MCP agile pour OneMCP — connecteur "Souverain" | `LaForgeMCPBridge`, `get_bridge`, `local_bridge`, `hub_bridge` | 301 |
| `forge_desktop/core/palette_hub_connector.py` | forge_desktop/core/palette_hub_connector.py ============================================= COMMAND_HUB_BRIDGE_V17 | `PaletteHubConnector` | 299 |
| `forge_desktop/main.py` | forge_desktop/main.py — Forge-Sync OS Entry point | `main` | 100 |
| `forge_desktop/views/cerberus_view.py` | forge_desktop/views/cerberus_view.py — Dashboard Cerberus intégré ================================================================== Visualisation vault génomique + runs actifs + métriques évolutives | `CerberusView` | 328 |
| `forge_desktop/views/consciousness_view.py` | forge_desktop/views/consciousness_view.py ========================================== Vue "Conscience Émanente" — Forge-Sync OS Affiche en temps réel : 1 | `AgentThinkingCard`, `ResonancePanel`, `ADRPanel`, `ADRCreateDialog` *(+1)* | 515 |
| `forge_desktop/views/dashboard_view.py` | forge_desktop/views/dashboard_view.py | `LLMCard`, `BrainRailWidget`, `TruthTerminalWidget`, `DashboardView` | 218 |
| `forge_desktop/views/debate_view.py` | forge_desktop/views/debate_view.py | `MiniRingMeter`, `EntropyBar`, `AgentPanel`, `SynthesisPanel` *(+1)* | 671 |
| `forge_desktop/views/debug_loop_view.py` | forge_desktop/views/debug_loop_view.py ======================================== AUTONOMOUS_DEBUG_LOOP_V1 | `DebugLoopView` | 462 |
| `forge_desktop/views/external_forge_view.py` | forge_desktop/views/external_forge_view.py — Forge appliquée à des projets externes ==================================================================================== Applique l'intelligence Nokido (Cerberus, LibraryShifter, SourceDiscovery, TokenOptimizer, | `ExternalForgeView` | 1016 |
| `forge_desktop/views/forge_os_canvas.py` | forge_desktop/views/forge_os_canvas.py USER_FRIENDLY_FORGE_OS -- Action_Over_Chat Canvas interactif : Omnibar -> Nodes -> Execution Glassmorphism_Deep_Dark \| Cellular_OneMCP_Atomic double_click=Inspect \| right_click=Swap_LLM \| drag=Chain | `ForgeNode`, `ForgeEdge`, `FlowCanvas`, `ForgeOSCanvas` | 744 |
| `forge_desktop/views/graph_canvas_view.py` | forge_desktop/views/graph_canvas_view.py AUTONOMOUS_ORCHESTRATOR_V17 — GraphCanvas_Interactive Visualise le DAG en temps reel | `GraphCanvasView` | 417 |
| `forge_desktop/views/interaction_view.py` | forge_desktop/views/interaction_view.py ======================================== Vue Interactions multi-agents — arbre de sélection guidé | `InteractionWorker`, `InteractionView` | 597 |
| `forge_desktop/views/main_window.py` | forge_desktop/views/main_window.py | `MainWindow` | 565 |
| `forge_desktop/views/mermaid_view.py` | forge_desktop/views/mermaid_view.py ===================================== Vue Mermaid — Génération de diagrammes via Qwen2.5-Coder (llamacpp) | `MermaidHighlighter`, `MermaidGenWorker`, `PanoramaWorker`, `MermaidView` | 482 |
| `forge_desktop/views/node_status_view.py` | forge_desktop/views/node_status_view.py ======================================== WORKFLOW_NODE_INTEGRATION — UI override Remove_Chat_Bubbles_Enable_Node_Status Pipeline view : trigger → ADR_CHECK → RUNNING → DONE/FAILED/BLOCKED Status par node | `NodeCard`, `TurnRow`, `NodeStatusView` | 428 |
| `forge_desktop/views/pipeline_engine_view.py` | forge_desktop/views/pipeline_engine_view.py ============================================ PIPELINE_ENGINE_V17 | `TaskEntry`, `PipelineEngineView` | 649 |
| `forge_desktop/views/rag_view.py` | forge_desktop/views/rag_view.py — Onglet RAG avec entropie et ingestion manuelle ================================================================================== Deux RAG : 1 | `RAGSearchWorker`, `DropZone`, `EntropyWidget`, `RAGPanel` *(+2)* | 766 |
| `forge_desktop/views/services_view.py` | forge_desktop/views/services_view.py | `ServiceCard`, `ProcessTable`, `ServicesView` | 392 |
| `forge_desktop/views/timemachine_view.py` | forge_desktop/views/timemachine_view.py | `GitLogWorker`, `TimeMachineView` | 230 |
| `forge_desktop/views/triad_view.py` | forge_desktop/views/triad_view.py LAFORGE_MULTI_AGENT_SYNTAX_V1 | `TriadView` | 210 |
| `forge_desktop/watchdog.py` | forge_desktop/watchdog.py ========================== Watchdog Forge-Sync OS — Process Python INDÉPENDANT | `Watchdog`, `main` | 323 |
| `forge_desktop/widgets/command_palette.py` | forge_desktop/widgets/command_palette.py ========================================= Smart Omnibar | `CommandPalette` | 509 |
| `forge_desktop/widgets/debate_timeline.py` | forge_desktop/widgets/debate_timeline.py ========================================= DebateTimeline — v17.04-RT Affiche les tours du débat en cascade séquentielle | `DebateTimeline` | 281 |
| `forge_desktop/widgets/flux_console.py` | forge_desktop/widgets/flux_console.py ======================================= FLUX_VISIBILITY_V2_EXPERT Console de sortie experte : | `agent_tier`, `sort_agents`, `detect_artifacts`, `FluxConsole` | 562 |
| `forge_desktop/widgets/forge_command_palette.py` | forge_desktop/widgets/forge_command_palette.py =============================================== WIDGET_COMMAND_PALETTE_V1 class : ForgeCommandPalette(QWidget) key : Ctrl+K ipc : MMap_500ms bridge: localhost:8766 + win32cred_check | `ForgeCommandPalette` | 575 |
| `forge_desktop/widgets/node_graph.py` | forge_desktop/widgets/node_graph.py ===================================== Graphe nodal des agents — QGraphicsScene | — | 331 |
| `forge_desktop/widgets/ring_group_widget.py` | forge_desktop/widgets/ring_group_widget.py ========================================== RingGroupWidget — v17.04-RT 3 groupes : Governance \| Intelligence \| Infra Polling MMap 500ms | `RingGroupWidget` | 297 |
| `forge_desktop/widgets/ring_meter_v2.py` | forge_desktop/widgets/ring_meter_v2.py ======================================= TUI_TO_GUI_DYNAMIC_BRIDGE — Grouped_Ring_Meter_V2 60fps token display + system health groupé | `RingMeterV2` | 384 |
| `forge_desktop/widgets/ring_o_meter.py` | forge_desktop/widgets/ring_o_meter.py ======================================= Ring-O-Meter — Visualisation circulaire des rings Nokido | `RingDial`, `RingStatusPanel`, `RingOMeterWidget` | 426 |
| `forge_desktop/widgets/security_shield.py` | forge_desktop/widgets/security_shield.py ========================================= SecurityShield — v17.04-RT Affiche le statut de chaque clé API depuis win32cred | `SecurityShield` | 160 |
| `tools/bench/forge_domain_adapter.py` | Beta Industrialisé : CE auto-adaptation par domaine ============================================================================== Gemini : "Industrialiser le Beta — détecter automatiquement un changement de domaine sémantique et relancer le fine-tuning CE (8 | `tok`, `corpus_fingerprint`, `finetune_ce_background`, `DomainAdapter` | 293 |
| `tools/bench/forge_graph_bench.py` | Benchmark de raisonnement sur graphes pour Nokido ========================================================================== Implémente les 3 benchmarks Gemini faisables: 1 | `FCGAnalyzer`, `GraphToPrompt`, `AttackPathFinder`, `run_fcg_benchmark` *(+3)* | 436 |
| `tools/bench/forge_longmemeval.py` | Nokido × LongMemEval Benchmark ======================================================= Benchmarke le système RAG de Nokido sur LongMemEval | `LongMemIndex`, `recall_at_k`, `ndcg_at_k`, `mrr` *(+4)* | 499 |
| `tools/bench/forge_longmemeval_bge.py` | Nokido × LongMemEval : Dense bge-m3 + Hybride ========================================================================= Benchmark haute performance avec vecteurs denses pré-calculés (bge-m3) | `embed`, `CorpusCache`, `tokenize`, `rrf` *(+6)* | 499 |
| `tools/bench/forge_longmemeval_enhanced.py` | Nokido × LongMemEval Enhanced ============================================================== Système RAG hybride haute performance pour LongMemEval | `tokenize`, `parse_date`, `rrf_score`, `chunk_sessions` *(+10)* | 702 |
| `tools/bench/forge_ogb_arxiv_bench.py` | Benchmark OGB-Arxiv pour Nokido ============================================================= Évalue la capacité de Nokido à raisonner sur des graphes de citations scientifiques (169K nœuds, 1.2M arêtes, 40 classes) | `load_arxiv_pyg`, `GraphSAGE`, `train_graphsage`, `g2p_few_shot_eval` *(+2)* | 331 |
| `tools/bench/forge_snn_bench.py` | Benchmark Neuro-Spin / SNN sur graphes de type malware ============================================================================= Implémente le concept Neuro-Spin de Gemini: | `SpikeFunction`, `SpikingLayer`, `NeuroSpinGNN`, `run_snn_benchmark` *(+1)* | 284 |
| `tools/forge_autophagie_attic.py` | resorption des modules qui ne servent plus | `declared_nature`, `imported_modules`, `plan`, `apply` *(+1)* | 170 |
| `tools/forge_changelog.py` | le CHANGELOG du depot : une section par push, tiree des messages de commit | `git`, `rubrique`, `est_commit_de_changelog`, `commits` *(+5)* | 223 |
| `tools/forge_docstring_masquee.py` | rend a Python les docstrings de module masquees par un `from __future__` place AVANT elles | `diagnostiquer`, `demasquer`, `modules`, `masquees` *(+2)* | 260 |
| `tools/intel/forge_github_intel.py` | Nokido Engrid · Intelligence GitHub ============================================================= fetch_github_intelligence() : extrait l'intelligence publique de GitHub (issues, PRs, discussions, wiki) pour nourrir les shards OSS/Alignement de ForgeEngridEngi | `fetch_github_intelligence` | 251 |
| `tools/nomad/bios_wol_probe.py` | Sonde BIOS/UEFI en LECTURE SEULE, pour le diagnostic Wake-on-LAN | `is_elevated`, `enable_privilege`, `read_uefi_var`, `smbios_wakeup` *(+1)* | 286 |
| `tools/research/forge_gnn.py` | Nokido GNN v3 — Bistable / Neuro-Spin Architecture ==================================================================== v3 : BistableGateLayer inspiré des Magnetic Tunnel Junctions (MTJ) Dynamique bistable : - Double-puit de potentiel : U(m) = -m² + m⁴ (deux é | `BistableGate`, `bistable_gate`, `ForgeGNNLayer`, `VulnGNN` *(+3)* | 423 |
| `tools/research/forge_graph_engine.py` | Nokido Graph Engine v1 ================================================ Convertit les artefacts Nokido en graphes exploitables par le GNN | `code_to_graph`, `file_to_graph`, `network_to_graph`, `rag_to_graph` *(+1)* | 367 |
| `tools/research/forge_inhibition_bus.py` | Nokido Engrid v3 · Sprint 2 ======================================================== InhibitionBus : signalisation latérale entre silos | `VetoSignal`, `CoopSignal`, `InhibitionBus` | 364 |
| `tools/research/forge_native_bridge.py` | Nokido · Zero-Subprocess Docker + Binary Bridge ========================================================================== Remplace subprocess(['docker', 'exec', ...]) par docker-py SDK direct | `DockerBridge`, `BinaryBridge`, `CTFNativeBridge`, `get_docker` | 345 |
| `tools/research/forge_spike_router_lite.py` | SpikeRouter runtime sans PyTorch ============================================================== Utilise uniquement numpy pour l'inférence | `SpikeRouterLite`, `extract_features_light`, `get_router`, `route` | 257 |

## Cognition/Agentique/Raisonnement

*125 modules · 38,248 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_4096d_encoder.py` | __FORGE_COLOR__ = cognition/world-encoder-4096 ENCODEUR 4096D END-TO-END — implemente la recette du debat multi-LLM (blackboard recipe_4096d_encoder_end_to_end), remplace la concatenation "4-facette" | `vicreg_loss`, `effective_rank`, `selftest`, `train_on_real` *(+1)* | 186 |
| `app/forge_active_inference.py` | Friston Free Energy Principle (FEP) simplifié Théorie : le cerveau minimise la surprise (free energy variationnelle) | `predict_signal`, `signal_z`, `observe_signal`, `get_prior` *(+9)* | 547 |
| `app/forge_active_inference_agent.py` | agent inference active Friston | `CyberAgent`, `build_cyber_agent`, `available` | 122 |
| `app/forge_actor.py` | Phase 2 - AMI roadmap: Actor with multi-plan exploration + UCT selection | `decode_action_emb`, `Node`, `gather_context_from_tree`, `generate_candidates` *(+5)* | 459 |
| `app/forge_agency.py` | __FORGE_COLOR__ = cognition/sense-of-agency SENTIMENT D'AGENTIVITE — comparateur efference-copy (modele de Frith/Blakemore) | `forward_predict`, `register`, `evaluate`, `publish` | 144 |
| `app/forge_agent_credential.py` | Credential d'un organe : jeton COURT plutot que secret permanent | `jeton_hub`, `jeton_pour`, `invalider`, `etat` | 438 |
| `app/forge_agent_keys.py` | Ledger d'identite cryptographique — agent_id -> generation -> jkt -> status | `enregistrer`, `transition`, `revoquer_agent`, `cles_acceptees` *(+3)* | 482 |
| `app/forge_agent_lats.py` | LATS-style wrapper généralisé pour tout agent Nokido | `run_with_lats` | 356 |
| `app/forge_benchmark_adapter.py` | lecture programmatique des scores de benchmark (HumanEval / BFCL / SWE-bench) pour le signal de fitness eval-driven | `swebench_dir`, `swebench_cache_dir`, `humaneval_score`, `bfcl_score` *(+4)* | 104 |
| `app/forge_claim_classifier.py` | Step 4 epistemic: classifier is_technical vs is_normative pour claims | `is_technical_keyword`, `is_technical_mlp`, `is_technical`, `main` | 361 |
| `app/forge_clarification.py` | Détecte ambiguïté et demande clarification | `needs_clarification`, `build_clarification_request`, `clarify_or_proceed` | 89 |
| `app/forge_collab.py` | Canal de discussion fichier-partagé multi-agents Pattern : un fichier markdown par sujet dans sandbox/collab/<topic>.md | `append`, `read`, `tail`, `list_topics` | 161 |
| `app/forge_continual_backprop.py` | Continual Backpropagation (Dohare et al., Nature 2024) | `ContinualBackprop` | 122 |
| `app/forge_cowork.py` | collegue IA persistant ("Cowork" souverain internalise) | `init_db`, `create_project`, `get_project`, `list_active` *(+7)* | 577 |
| `app/forge_critical_events.py` | Append-only SQLite log for events qui doivent survivre a un restart hub | `backup`, `rotate_backups`, `persist`, `unprocessed` *(+3)* | 258 |
| `app/forge_debate_roles.py` | RÔLES DIALECTIQUES du débat M2M (organe : cognition) ============================================================================ Complète `forge_roles.ROLES` (rôles d'exécution : PLANNER, EXECUTOR, REVIEWER…) par les rôles de DÉBAT, et s'appuie sur `forge_swa | `DebateRole`, `TourInvalide`, `extract_cot`, `anonymise` *(+2)* | 308 |
| `app/forge_dialogue_outcome.py` | AXE 8 : évaluateur d'issue d'un échange de dialogue | `Outcome`, `evaluate_exchange`, `record_outcome`, `evaluate_and_record` *(+1)* | 201 |
| `app/forge_dim_policy.py` | __FORGE_COLOR__ = cognition/dim-policy POLITIQUE DIMENSIONNELLE HYBRIDE par-organe — formalise la decision (D) du debat 4096D | `tier_for`, `dim_for`, `transmit_compressed`, `policy` | 71 |
| `app/forge_domain_mapper.py` | Du verbe et de la cible au DOMAINE, sans appel LLM | `apprendre`, `deduire_domaines` | 264 |
| `app/forge_dsl.py` | DSL compact Nokido (économie tokens 80-90% vs prompt naturel) | `DSLOp`, `parse_dsl`, `resolve_ref`, `register` *(+4)* | 553 |
| `app/forge_epistemic_veille.py` | __FORGE_COLOR__ : cognition / metacognition (organe) ORGANE : GAP ÉPISTÉMIQUE → VEILLE — « éprouver le besoin de savoir » | `manifold_error`, `coverage_dense`, `coverage_score`, `feel_gap` *(+2)* | 374 |
| `app/forge_explore_rank.py` | classement des extraits de recon AVANT la coupe du digest | `score`, `classer` | 65 |
| `app/forge_flow_control.py` | ÉQUIPE agentique de CONTRÔLE D'ACCÈS & DE FLUX | `flow_contract`, `route_flow`, `gate_flux`, `team` *(+1)* | 176 |
| `app/forge_flow_zone.py` | Pierre-Yves Oudeyer (Inria) Flow Zone Théorie : un agent autonome n'a pas d'objectif, il cherche la zone de difficulté optimale (ni trop facile = ennui, ni trop dur = frustration) | `learning_progress`, `flow_score`, `find_flow_methods`, `find_boredom_zones` *(+1)* | 230 |
| `app/forge_grounder.py` | verbe ground(claim\|task) : grounding QUALIFIE multi-source + verification ADVERSARIALE multi-LLM | `ground` | 238 |
| `app/forge_handler_evolve.py` | Handler @evolve pour Nokido TUI =============================================================== Interface directe avec le Siloed Reasoning Engine | `handle_evolve` | 233 |
| `app/forge_handler_skill.py` | Handler @skill TUI ================================================ Interface Nokido pour le connecteur ClawHub isolé en silo | `handle_skill` | 283 |
| `app/forge_harness_contract.py` | CONTRAT d'execution par etape de la facade harness | `EtapeContrat`, `verdict_etape`, `depuis_trajectory_step`, `ligne` | 154 |
| `app/forge_js_endpoint_extractor.py` | Extracteur d'endpoints JS pour Bug Bounty | `JSEndpointExtractor`, `silo_js_extract` | 139 |
| `app/forge_lats.py` | Language Agent Tree Search (Hassabis, Yao 2024) | `EtatVivant`, `PatchProposal`, `SandboxResult`, `LATSNode` *(+3)* | 700 |
| `app/forge_lats_general.py` | Language Agent Tree Search GENERAL purpose | `MCTSNode`, `lats_solve`, `main` | 277 |
| `app/forge_llm_usage_adapters.py` | Adaptateurs d'usage LLM -- Claude, Codex et AGY dans UNE seule table | `depuis_claude`, `depuis_codex`, `depuis_agy`, `migrer` | 216 |
| `app/forge_llm_usage_event.py` | Contrat canonique d'un evenement d'usage LLM | `ErreurContrat`, `creer`, `context_tokens`, `cle_agregation` *(+1)* | 228 |
| `app/forge_mailbox.py` | Boîtes aux lettres inter-agents à code HMAC ================================================================ Remplace le poll réseau toutes les 15s par un système push/pull protégé par code HMAC dérivé du token agent + timestamp | `verify_code`, `push`, `pull`, `get_code` *(+2)* | 169 |
| `app/forge_mcts_engine.py` | Moteur de réflexion délibérée (System 2 / LLM-MCTS) | `ThoughtNode`, `ConsensusEvaluator`, `TransientCodeEvaluator`, `MCTSEngine` | 228 |
| `app/forge_memoire_active.py` | la MEMOIRE DE TRAVAIL du corps, en strates | `salience_dette`, `dettes_ouvertes`, `ouvrir_dette`, `clore_dette` *(+2)* | 522 |
| `app/forge_metacognition_gate.py` | Nokido Engrid v3 · Couche 1 ============================================================ MetaCognitionGate : filtre intelligent entre le prompt entrant et le backend LLM | `GateDecision`, `GateResult`, `SiloScore`, `ConfidenceScorer` *(+1)* | 629 |
| `app/forge_mpc.py` | Phase 5 - AMI roadmap: Model Predictive Control (closed-loop planning) | `MPCStep`, `MPCResult`, `plan_horizon`, `mpc_step` *(+1)* | 437 |
| `app/forge_mpc_executor.py` | Phase C — MPC real execute_fn | `execute_fn`, `run_real_mpc` | 193 |
| `app/forge_mutation_judge.py` | LE JUGE des mutations — le milieu implacable, sans lequel l'arbre ne vaut rien | `perimetre_immuable`, `mutable`, `patron_sain`, `tracer_bak` *(+11)* | 740 |
| `app/forge_narrator.py` | __FORGE_COLOR__ = cognition/narrative-self NARRATEUR AUTOBIOGRAPHIQUE — tisse les faits isoles en RECIT continu de soi | `weave`, `narrate`, `consolidate`, `inject_into_context` *(+1)* | 279 |
| `app/forge_novelty_organ.py` | Organe de Nouveauté (Autoencoder PyTorch + FlowRegulator) ==================================================================================== Détecte les anomalies par erreur de reconstruction MSE | `NoveltyEngine`, `FlowRegulator`, `AugmentedNovelty` | 146 |
| `app/forge_novelty_search.py` | Novelty Search (Stanley/Lehman 2011) Récompense la NOUVEAUTÉ, pas l'objectif | `compute_novelty`, `archive_behavior`, `is_exploration_mode`, `combined_score` *(+4)* | 384 |
| `app/forge_organ_agents.py` | CENSUS ORGANE×AGENT de l'organisme + câblages essentiels | `phases`, `probe`, `critical_points`, `census` *(+4)* | 400 |
| `app/forge_pillar_arbiter.py` | Arbitre des piliers lourds : la regulation EMANE du corps, le client RECLAME | `reclamer`, `pilier_accorde`, `backends_autorises`, `backend_autorise` *(+2)* | 260 |
| `app/forge_ps_agent.py` | Micro-Agents PowerShell avec déport cognitif ================================================================= 3 méthodes selon le document d'architecture : M1 | `PSAgentBuilder`, `build_agent_for_mcp` | 549 |
| `app/forge_repo_map_tools.py` | outils deterministes view/edit pour agents | `view_file_content`, `edit_file_block`, `insert_at_line`, `restore_backup` | 195 |
| `app/forge_repo_map_ts.py` | symboles TypeScript pour la repo map (proxy_deno, organes Deno) | `disponible`, `parse_tree_sitter`, `parse_lexicale`, `parse_ts` | 153 |
| `app/forge_research_agent.py` | Agent recherche autonome zero token Claude | `research_agent` | 610 |
| `app/forge_retrieval_router.py` | Routeur de recuperation — contrat, observation, et bascule SHADOW/ACTIVE | `mode`, `RouteDecision`, `caracteriser`, `decider` *(+5)* | 367 |
| `app/forge_roles.py` | Système de rôles locaux Nokido ================================================= Chaque rôle est un agent autonome avec : - Un modèle local dédié (Ollama) - Une responsabilité unique - Un Semaphore pour éviter la saturation GPU - Un circuit breaker intégré - U | `best_cloud_for_role`, `CircuitState`, `RoleCircuitBreaker`, `Role` *(+2)* | 477 |
| `app/forge_roles_legacy.py` | roles.py | `AgentRole`, `IntentRouter`, `ModelBenchmark`, `ModelBenchmarker` *(+2)* | 1507 |
| `app/forge_scalable_oversight.py` | __FORGE_COLOR__ : metacognition / gouvernance (organe) ORGANE : SCALABLE OVERSIGHT — « un juge plus fort audite ce qu'un juge plus faible affirme » | `oversee`, `history` | 171 |
| `app/forge_semantic_pressure.py` | Pression sémantique autopoiétique | `compute_cluster_centroids`, `compute_semantic_pressure`, `should_trigger_action`, `autopoiesis_cycle` *(+1)* | 263 |
| `app/forge_skill_curator.py` | Curation autonome de skills depuis execution_traces ============================================================================= Carve-out hermes-agent (cf [[research-hermes-agent]]) : extraction auto de skills depuis trajectoires self-play réussies + boucle | `CuratedSkill`, `extract_skills`, `grade`, `prune` *(+3)* | 518 |
| `app/forge_skill_enricher.py` | Boucle de capitalisation : leçons + topics → skills | `scan_recent_lessons`, `scan_emerging_topics`, `existing_skill_path`, `propose_skill_update` *(+2)* | 397 |
| `app/forge_skill_forge.py` | __FORGE_COLOR__ : digestif/sens (ingestion) + qualité (skills) forge_skill_forge — Génération NATIVE de SKILL.md depuis une source (URL doc / texte) | `forge_skill_from_text`, `forge_skill_from_url`, `install_skill`, `from_url` *(+1)* | 161 |
| `app/forge_skill_policy.py` | Politique centralisée install skills externes Claude Code | `skill_min_ring`, `skill_allowed_for_ring`, `PolicyVerdict`, `audit_plugin` *(+4)* | 405 |
| `app/forge_spatial_reasoning.py` | grid representation RAG (hippocampe-inspired) | `SpatialMap`, `main` | 293 |
| `app/forge_task_duo.py` | DUO planificateur + décomposeur : organise une roadmap en VAGUES PARALLÈLES testables, avant de chaîner les exécuteurs | `waves`, `organize`, `decompose` | 191 |
| `app/forge_tem_factorize.py` | Tolman-Eichenbaum Machine (TEM) pattern factorization | `tem_compose`, `derive_structure_embedding`, `tem_search`, `main` | 169 |
| `app/forge_thought_interceptor.py` | Nokido Capture et indexe la chaîne de raisonnement (CoT) des modèles cloud | `ForgeThoughtInterceptor` | 67 |
| `app/forge_typed_task.py` | ControlFlow-style typed task contract for Nokido | `run_typed_task_async`, `run_typed_task`, `run_typed_schema_async`, `run_typed_schema` *(+1)* | 233 |
| `app/forge_value_net.py` | Value Network (Hassabis / AlphaZero pillar) | `ValueNet`, `train`, `get_model`, `predict_value` | 214 |
| `app/forge_veille_digest.py` | __FORGE_COLOR__ : cognition / metacognition (organe) ORGANE : DIGEST -> SUGGEST — « tirer les leçons de ce qu'on vient d'apprendre » | `noms_organes`, `organes_valides`, `valider_organe`, `tag_complet` *(+16)* | 1119 |
| `app/forge_watch_agent.py` | Veille active intelligente (Watch Agent) PIPELINE N8N-STYLE (reprise possible à chaque étape) : THÈME → [LLM local] génère mots-clés raffinés (step: keywords) → [vérification] pertinence des mots-clés (step: verify_kw) → [SearXNG] recherche par mot-clé (step: | `register_sse_callback`, `verdict_chaine`, `run_watch_job`, `create_job` *(+2)* | 1843 |
| `app/forge_workflow.py` | Workflow SOUVERAIN DÉPORTÉ (équivalent local du tool Workflow) | `run_plan`, `submit` | 189 |
| `tools/agent_notify.py` | Notification inter-agents bidirectionnelle | `resolve_agent`, `send`, `main` | 150 |
| `tools/assign_gemini_tasks.py` | Assign 3 infra tasks to Gemini CLI via hub | `assign` | 89 |
| `tools/check_agent_msg.py` | Check recent agent_messages + hub notify routing for claude | — | 26 |
| `tools/forge_active_inference_homeostat_prototype.py` | Non-intrusive prototype demonstrating adaptive homeostatic limits driven by FEP surprise | `calculate_adaptive_limits`, `main` | 124 |
| `tools/forge_agentic_roles_probe.py` | Quels ROLES AGENTIQUES chaque endpoint peut-il reellement tenir ? Les `use_case` disent QUI REPOND ; les roles disent QUI PEUT FAIRE QUOI dans une boucle d'agent | `fiche_du_modele`, `epreuve_verdict`, `epreuve_etiquette`, `epreuve_plan` *(+2)* | 251 |
| `tools/forge_authority_db_split.py` | Sort `opsec_state` et `forge_tools` de la base RAG vers la base d'AUTORITE | `copier`, `verifier`, `basculer`, `main` | 228 |
| `tools/forge_cognition_retrain_1024.py` | A/B world-model @384 (legacy traces) vs @1024 (traces_rich) | `main` | 150 |
| `tools/forge_cognitive_fitness.py` | __FORGE_COLOR__ = "cognition/fitness" FITNESS COGNITIVE — mesurer COMMENT le systeme raisonne, pas seulement s'il finit par tomber juste | `mesurer`, `emettre`, `main` | 202 |
| `tools/forge_debate_job.py` | ARÈNE DE DÉBAT multi-tour SOUVERAINE (déportable via run_job) | `cristalliser`, `capsule_en_texte`, `ecrire_capsule`, `preflight_providers` *(+3)* | 647 |
| `tools/forge_debate_run_job.py` | worker DEPORTE du debat inter-agents (params-driven) | `main` | 69 |
| `tools/forge_dpo_extractor.py` | Extraction paires DPO depuis execution_traces.db | `load_traces`, `build_pairs`, `export_jsonl`, `run` | 159 |
| `tools/forge_epistemic_calibrate.py` | Step 8 epistemic: calibration coefficients alpha/beta/gamma/delta/epsilon via regression logistique sur dataset historique de claims | `bootstrap_dataset_from_db`, `load_csv_dataset`, `calibrate`, `save_config` *(+1)* | 248 |
| `tools/forge_epistemic_daemon.py` | la SOIF DE CONNAISSANCE, cablee sur les vraies requetes | `run_once`, `run`, `main` | 710 |
| `tools/forge_epistemic_extract_claims.py` | Consolidation epistemique : extraction d'assertions, reevaluation, supersession, porte | `nom_backend`, `extracteur_backend`, `juge_backend`, `process_batch` *(+3)* | 641 |
| `tools/forge_epistemic_recompute.py` | Step 3: cron daily — recalcule epistemic_weight pour chaque chunk actif | `recompute`, `main` | 254 |
| `tools/forge_epistemic_simulator.py` | Epistemic dynamics simulator — visualise trajectoire confidence_score d'un claim dans le temps sous l'effet de l'equation: epistemic_weight(t) = alpha*trust_weight + beta*recency_decay(t) + gamma*citation_norm + delta*peer_review_bonus + epsilon*refutation_pen | `EpistemicChunk`, `epistemic_weight`, `simulate_trajectory`, `scenario_stego` *(+4)* | 281 |
| `tools/forge_gap_direction.py` | croise CE QUI CLOCHE avec CE QU'ON VEUT | `croiser`, `point`, `main` | 302 |
| `tools/forge_gemini_autonomous_agent.py` | GEMINI AUTONOME : daemon qui relève l'inbox postal de l'agent GEMINI, invoque gemini_cli sur chaque courrier, et POSTE la réponse — SANS humain | `tick`, `main` | 625 |
| `tools/forge_gemini_ingress.py` | ingress Gemini Dev/Vertex (generateContent) -> Nokido | `health`, `generate`, `main` | 167 |
| `tools/forge_js_endpoint_extractor.py` | Extract hidden API endpoints from JS bundles | `extract_endpoints` | 60 |
| `tools/forge_lats_debug_debate.py` | debat multi-LLM CIBLE bug actuel LATS | `main` | 247 |
| `tools/forge_lats_smoke.py` | end-to-end smoke test stack repo_map + LATS + tools | `propose_fn`, `main` | 155 |
| `tools/forge_llm_ondemand.py` | Allumer / eteindre A LA DEMANDE les cerveaux souverains locaux | `poser_intention`, `llama_up`, `llama_down`, `lmstudio_up` *(+3)* | 429 |
| `tools/forge_llm_ondemand_traqueur.py` | Traque QUI repose `llama.wanted` en boucle | `main` | 108 |
| `tools/forge_local_explore.py` | MIROIR LOCAL d'un Agent(Explore), 100% souverain | `search`, `synth_local`, `main` | 120 |
| `tools/forge_local_llm_bringup.py` | Lever les serveurs LLM LOCAUX, puis les prouver — pas les promettre | `port_ouvert`, `attendre`, `completer`, `bringup` *(+1)* | 308 |
| `tools/forge_patch_agent_list_task_executor.py` | Ajoute TASK_EXECUTOR à _AGENT_LIST du hub (tools/nokido_hub.py), fichier CRITIQUE | `main` | 64 |
| `tools/forge_patch_tools_list_rolescope.py` | Patch CRITICAL_FILE : `tools/list` peut deriver son perimetre du ROLE | `main` | 131 |
| `tools/forge_place_debate_html.py` | place le template GUI du debat dans app/web_hub | `main` | 28 |
| `tools/forge_recursive_link.py` | runtime SOUVERAIN du RecursiveLink (RecursiveMAS Path 1) | `is_available`, `why_unavailable`, `load`, `latent_hop` *(+3)* | 199 |
| `tools/forge_retrieval_sweep.py` | Balayage MULTI-SURFACE avant toute affirmation d'absence | `verdict_global`, `balayer`, `main` | 336 |
| `tools/forge_router_replay.py` | Replay des observations du routeur — rejoue la DECISION, jamais les signaux | `mesurer_adaptation`, `rejouer`, `diff_ab`, `main` | 269 |
| `tools/forge_savoir_census.py` | OU vit le savoir de Nokido, et par quoi est-il ATTEIGNABLE | `bases`, `tables`, `couverture_par_jointure`, `couverture_fts` *(+2)* | 422 |
| `tools/forge_skill_catalogue.py` | Catalogue CANONIQUE des skills — la table de resolution des identites | `Surface`, `Record`, `Releve`, `canoniser` *(+8)* | 389 |
| `tools/forge_skill_execution.py` | EXECUTION gouvernee d'un plan de skills, et PROVENANCE de la chaine | `Realisation`, `Execution`, `Trace`, `executer_etape` *(+10)* | 667 |
| `tools/forge_skill_migrate.py` | migration skills vers la taxonomie souveraine HYBRIDE (24 -> 14) | `run` | 177 |
| `tools/forge_skill_realisations.py` | Realisations REELLES : ce qui relie une capacite a une route gouvernee | — | 212 |
| `tools/forge_skill_retrieval.py` | RETRIEVAL de skills — quels skills sont pertinents pour un objectif donne | `jetons`, `Candidat`, `Resultat`, `chercher` *(+1)* | 231 |
| `tools/forge_skill_sync.py` | Matérialiseur de skills cross-CLI souverain | `AssetType`, `AssetConfig`, `discover`, `consolidate` *(+7)* | 1066 |
| `tools/forge_skills_reorg.py` | migration namespace skills -> forge-* (NON-DESTRUCTIF, dry-run) | `plan`, `main` | 105 |
| `tools/forge_snn_repo_extract.py` | __FORGE_COLOR__ = "cognition/extraction-snn" EXTRACTEUR du depot public **NokidoSNN** depuis Nokido | `main` | 284 |
| `tools/forge_soif_demo.py` | boucle SOIF complete sur UN gap reel, de bout en bout | `main` | 62 |
| `tools/forge_symptom_index.py` | « SUIS-JE DEJA PASSE PAR LA ? » | `construire`, `construire_rag`, `charger_index`, `demander` *(+1)* | 488 |
| `tools/forge_task_queue_db_split.py` | sortir `task_queue` de la base du RAG | `copier`, `verifier`, `main` | 196 |
| `tools/forge_thought_interceptor.py` | Intercepteur CoT avec GPU Lock + densité cognitive ================================================================================== Capture les balises <think>...</think> des modèles DeepSeek-R1/Qwen-R1 en streaming, avec synchronisation iGPU (FileLock) et c | `ForgeThoughtInterceptor` | 322 |
| `tools/forge_tpm_agent_keys.py` | provisionne les cles TPM PAR AGENT (geste owner) | `etat_des_cles`, `main` | 400 |
| `tools/forge_vault_mint_agent_token.py` | FRAPPE un jeton d'agent au coffre | `main` | 137 |
| `tools/forge_vault_seed_agent_tokens.py` | Vault seeding agent tokens | `main` | 345 |
| `tools/forge_veille_codex_run.py` | veille déportée : écosystème OpenAI/Codex | — | 18 |
| `tools/forge_veille_depouillement.py` | Suivi du DEPOUILLEMENT de la moisson de veille -- ce qu'il reste a lire | `noter`, `id_page`, `famille_page`, `familles` *(+7)* | 463 |
| `tools/forge_veille_gemini_run.py` | veille approfondie déportée : écosystème Gemini/Gemma | — | 19 |
| `tools/forge_watch_agent_worker.py` | daemon supervisor pour la veille active | `main` | 231 |
| `tools/forge_wheel_probe.py` | Probe critical wheels on the active Python | `probe`, `main` | 126 |
| `tools/gemini_oauth_refresh.py` | Refresh Google OAuth token for Gemini CLI Generated by Groq Llama-3.3-70B, corrected by Claude | `refresh` | 112 |
| `tools/gemini_resume.py` | Relance Gemini CLI avec la derniere session du projet courant | `find_project_dir`, `get_sessions`, `main` | 121 |
| `tools/send_agent_task.py` | Envoie une tâche dans agent_messages | `send` | 51 |
| `tools/spawn_brain_worker_npu.py` | Spawn brain_worker.py avec env NPU ryzen-ai-1.7.0 en process détaché caché | `main` | 117 |
| `tools/start_litellm_proxy.py` | Lance LiteLLM Proxy sur 127.0.0.1:4000 ====================================================================== Bind local uniquement — jamais exposé réseau | `load_keys`, `main` | 116 |

## Qualite/Build/Spec

*106 modules · 27,780 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_dep_manager.py` | Dependency auto-management pour code généré extract imports → check missing → pip install → verify | `extract_imports`, `check_missing`, `paquets_declares`, `filtrer_autorises` *(+3)* | 242 |
| `app/forge_dep_manager_auto.py` | Runtime automatic dependency recovery | `safe_import`, `auto_deps`, `test_safe_import_existing`, `test_safe_import_returns_same_module` *(+3)* | 149 |
| `app/forge_diff_analyzer.py` | Détecteur breaking changes vs codebase Nokido ======================================================================== Compare les nouvelles releases (RAG domain=watch_alerts) avec les imports et usages réels dans le code Nokido pour identifier les impacts pot | `scan_imports`, `scan_function_calls`, `get_breaking_changes`, `extract_deprecated_symbols` *(+5)* | 318 |
| `app/forge_meta_tools.py` | Nokido v18.5 ===================================== 8 méta-outils MCP pour réduire 88% des tokens payload LLM | `is_safe_autonomous`, `get_tool_schema`, `get_filtered_schemas`, `token_estimate` *(+1)* | 745 |
| `app/forge_panorama_builder.py` | ========================= Scan AST de app/forge_*.py pour extraire le vrai graphe d'imports internes, puis genere un panorama Mermaid data-driven via forge_mermaid_gen | `scan_forge_modules`, `compute_orphans`, `build_mermaid_from_graph`, `build_panorama_via_llm` *(+1)* | 222 |
| `app/forge_prompt_builder.py` | Constructeur de prompts enrichis par le RAG Nokido =================================================================================== Rôle : permettre à des LLMs moins puissants (Llama 8B, qwen, mistral) d'atteindre la qualité d'un LLM de haut niveau en leur | `PromptBuilder` | 234 |
| `app/forge_quality_gate.py` | Quality gate bloquant avant commit (software creator) AST parse + pylint score + pytest coverage + TODO CRITICAL check | `GateResult`, `QualityGateError`, `QualityGate`, `block_if_failing` *(+3)* | 186 |
| `app/forge_resolver.py` | RÉSOLVEUR : pré-vol + résolution d'erreurs des flux | `live_providers`, `writable_path`, `ring_ok`, `resolve_provider_panel` | 143 |
| `app/forge_spec_clarifier.py` | Clarification dialogue structuré (software creator gap#7) spec ambiguë → questions ciblées → spec YAML formalisée | `detect_ambiguities`, `generate_questions`, `formalize_spec`, `ClarificationDialog` | 102 |
| `tools/_invalidate_dt_model.py` | Invalide le modèle DT sauvegardé (FEATURE_DIM 34→35) | — | 10 |
| `tools/ast_surgery.py` | Injection chirurgicale de type hints via AST ==================================================================== Au lieu de demander au LLM de réécrire tout le fichier (troncation), on extrait les signatures sans corps, on envoie au LLM, et on fusionne les an | `extract_signatures`, `count_nodes`, `merge_annotations`, `ast_surgery` | 242 |
| `tools/bench_chain.py` | A/B benchmark chain_executor pipeline pur (mock LLM) | `main` | 316 |
| `tools/bench_multithread.py` | Vrai bench multi-thread Python (vrai test free-threading) | `fib`, `workload_pure_python`, `workload_numpy`, `workload_ami_nmlp` *(+1)* | 176 |
| `tools/bench_qdrant_veracrypt.py` | Benchmark d'empreinte disque et latence mmap NVMe à travers VeraCrypt | `print_progress`, `generate_synthetic_chunk`, `run_benchmark` | 221 |
| `tools/check_gemini_inbox.py` | Check gemini inbox by rowid (insertion order) to avoid UTC/local timestamp issue | — | 31 |
| `tools/check_lazy_cycles.py` | Linter: verifie que tous les cycles d imports restent LAZY (dans fonctions), jamais au niveau MODULE | `collect_module_level_imports`, `check_cycles`, `main` | 83 |
| `tools/ci_local.py` | miroir LOCAL COMPLET des GitHub Actions | `marque_resume`, `phrase_non_mesures`, `verdict_bloc`, `verdict_suite` *(+13)* | 5878 |
| `tools/forge_aer_sparsity_bench.py` | __FORGE_COLOR__ = "regulation/aer-evenementiel" BANC DE SPARSITE AER — chiffrer le gain evenementiel sur l'historique REEL | `main` | 253 |
| `tools/forge_archi_lint.py` | lint architectural Nokido via Semgrep (Golden Rules) | `main` | 159 |
| `tools/forge_ax17_backtest_job.py` | backtest DEPORTE de l'axe 17 (graphe de signaux) | `main` | 58 |
| `tools/forge_axis_backtest.py` | BACKTEST d'un axe de detection de regression | `commits_de_correction`, `fichiers_cibles`, `fichiers_py`, `blob` *(+10)* | 688 |
| `tools/forge_bench_all.py` | Benchmark exhaustif providers LLM (locaux + cloud free) | `post_json`, `bench_openai_compat`, `bench_ollama_native`, `main` *(+1)* | 348 |
| `tools/forge_bench_auto_trigger.py` | Auto-trigger promptfoo benchmarks on config/model file changes | `run_bench`, `parse_pass_rate`, `write_log`, `write_alert` *(+1)* | 134 |
| `tools/forge_bench_autotrigger.py` | Auto-trigger promptfoo benchmarks on hot-file changes | `BenchResult`, `run_bench`, `check_and_trigger` | 67 |
| `tools/forge_bench_beir.py` | Benchmark retrieval BEIR-style sur l'echantillon Nokido | `main` | 228 |
| `tools/forge_bench_engine.py` | Bench du RAGEngine REEL (FAISS+BM25+RRF+rerank) | `main` | 121 |
| `tools/forge_bench_get_reranker.py` | Telecharge le GGUF du reranker bge-reranker-v2-m3 | `main` | 51 |
| `tools/forge_bench_groq_test.py` | Diagnostic acces cle groq pour le benchmark | — | 47 |
| `tools/forge_bench_http.py` | couche HTTP commune des runners de bench | `http_post` | 31 |
| `tools/forge_bench_hybrid.py` | Compare retrieval dense / BM25 / hybride RRF | `main` | 134 |
| `tools/forge_bench_misses.py` | Analyse des echecs de retrieval BEIR | `main` | 145 |
| `tools/forge_bench_questions.py` | Question-set BEIR via llama.cpp Vulkan (:8091) | `main` | 107 |
| `tools/forge_bench_rerank.py` | Benchmark retrieval dense vs dense+reranker | `main` | 195 |
| `tools/forge_bench_sample.py` | Echantillon stratifie du VRAI corpus Nokido | `main` | 85 |
| `tools/forge_bench_segment.py` | Metriques BEIR segmentees par type de gold | `main` | 125 |
| `tools/forge_bisect.py` | recherche binaire du commit coupable, sur critere REEL | `construire_commande`, `CompositionInstable`, `executer`, `main` | 266 |
| `tools/forge_capteur_dense_apport_bench.py` | Le flux RESEAU ajoute-t-il ce que les 4 scalaires n'ont pas ? Trois bancs ont montre que rien ne bat le seuil sur les vitals : ni un LIF regle, ni une tete lineaire apprise, ni le SpikingMLP de production entraine (perte finale 0,677 pour ln(2)=0,693 — il conv | `charger_reseau`, `traits_reseau`, `mesurer`, `main` | 191 |
| `tools/forge_cartouches_concordance.py` | les cartouches du README face aux clefs du coffre | `clefs_coffre`, `cartouches`, `concordance`, `main` | 176 |
| `tools/forge_ci_check.py` | etat de la CI apres push | `lignes_utiles`, `journal_echecs`, `tests_rouges`, `couverture_des_rouges` *(+7)* | 679 |
| `tools/forge_ci_lock.py` | le lock des outils de CI, et la RECONCILIATION avec l'installe | `normaliser`, `fermeture`, `hash_lock`, `rendu` *(+2)* | 214 |
| `tools/forge_ci_pin_actions.py` | Epingle les actions GitHub des workflows sur un SHA, au lieu d'un tag mobile | `main` | 127 |
| `tools/forge_ci_profil.py` | Profil et comparaison sequentiel/parallele de la suite pure de `ci_local` | `selection_pure`, `construire`, `bilan_junit`, `comparer_collecte` *(+1)* | 261 |
| `tools/forge_ci_proof.py` | transformer un verdict de CI en PREUVE PORTABLE | `hash_canonique`, `hash_plan`, `hash_contrat`, `empreinte_substrat` *(+5)* | 304 |
| `tools/forge_ci_quand_ram_dispo.py` | Attend que la RAM redescende, puis lance la CI | `main` | 160 |
| `tools/forge_ci_selection.py` | ne rejouer que les tests QUE LE DIFF PEUT AVOIR CASSES | `fichiers_modifies`, `liste_depuis_fichier`, `selectionner`, `etat_suite` *(+1)* | 214 |
| `tools/forge_ci_stop_hook.py` | Stop hook : surface le verdict CI de la branche en fin de tour | `main` | 169 |
| `tools/forge_council_bias_bench.py` | Banc de mesure : l'anonymisation change-t-elle le verdict de NOS juges ? Question posee | `RamInsuffisante`, `prompt_proposition`, `prompt_classement`, `campagne` *(+1)* | 342 |
| `tools/forge_cycle_verdict.py` | Certifier un cycle de dev collaboratif : le NR fait foi, pas le rapport de l'agent | `scorecard`, `empreinte`, `lire_junit`, `mesurer` *(+2)* | 221 |
| `tools/forge_demo_manus_feed.py` | workflow demo : declenche un orchestrate task et montre les events Manus 6-step streamer en live dans /forge/feed (:7400) | `main` | 130 |
| `tools/forge_demo_record_all.py` | record TOUS les workflow demos browser via Playwright record_video_dir, puis convert WebM -> GIF optimise via ffmpeg | `scene_debate`, `scene_swarm`, `scene_graph`, `scene_rag_stream` *(+6)* | 362 |
| `tools/forge_deno_check.py` | type-check d'un fichier Deno/TS via `deno check` | `main` | 81 |
| `tools/forge_deno_typecheck.py` | Typecheck des sources Deno AVANT restart du superviseur | `deno_path`, `check`, `main` | 98 |
| `tools/forge_dep_detector.py` | scan Python imports, detect missing packages | `scan_imports`, `check_installed`, `suggest_install`, `scan_dir` | 87 |
| `tools/forge_dep_manager.py` | Dependency graph analyser for Nokido forge_*.py modules | `build_dep_graph`, `detect_cycles`, `detect_missing`, `export_dot` | 76 |
| `tools/forge_docs_chemins_morts.py` | une page de doc ne renvoie pas vers du vide | `classer`, `scanner`, `main` | 156 |
| `tools/forge_docs_datation.py` | chaque page de doc DIT quand elle a ete revue | `date_du_dernier_commit`, `note`, `traiter`, `main` | 227 |
| `tools/forge_docs_relink.py` | reprefixe les liens RELATIFS d'un document deplace | `reprefixer`, `verifier`, `main` | 152 |
| `tools/forge_dup_detector.py` | duplication de code, par STRUCTURE | `empreinte`, `collect`, `est_adaptateur_entree`, `scanner` *(+2)* | 319 |
| `tools/forge_exporter.py` | ForgeProjectExporter — Pack de survie pour migration locale | `ForgeProjectExporter` | 289 |
| `tools/forge_generation_inscrire.py` | Inscrit les generations DEPOSEES dans l'arbre versionne | `inscrire`, `main` | 152 |
| `tools/forge_golden_rules_ast.py` | moteur NATIF des Golden Rules Nokido | `charger_apprises`, `scan_file`, `scan_source`, `collect` *(+1)* | 906 |
| `tools/forge_golden_state.py` | l'etat de REFERENCE, et de quoi mesurer sa derive | `relever`, `capturer`, `verifier`, `main` | 217 |
| `tools/forge_heldout_gate.py` | garde HELD-OUT pour le code auto-genere (Phi_T, Metal-Sci) | `freeze_fixture`, `check_embedder`, `validate_file`, `block_if_regressed` *(+1)* | 162 |
| `tools/forge_lecture_json.py` | Lecture d'un JSON en TROIS etats — LU / ABSENT / ILLISIBLE | `lire` | 44 |
| `tools/forge_mutation_classifier.py` | Classifieur ML de succès de mutation ==================================================================== Prédit si une mutation va réussir AVANT de la lancer | `MutationClassifier` | 395 |
| `tools/forge_mutation_predictor.py` | Classifieur ML de succès de mutation ================================================================== RandomForest entraîné sur experience_memory.jsonl (F1=0.937) | `MutationPredictor` | 304 |
| `tools/forge_mutation_test.py` | mutation testing natif : tester les TESTS | `executer`, `main` | 305 |
| `tools/forge_npu_bench.py` | Le NPU XDNA travaille-t-il VRAIMENT ? — banc de mesure, pas de declaration | `main` | 191 |
| `tools/forge_npu_static_bench.py` | Le NPU refuse-t-il le modele a cause de ses formes DYNAMIQUES ? Dix variantes (2 SDK x 5 firmware/overlay) rendent toutes le debit du CPU pur, warmup <= 2 s : la chaine ne partitionne jamais vers les tuiles AIE | `main` | 190 |
| `tools/forge_nr_instables.py` | rejoue N fois des NR cibles et NOMME ceux dont le verdict change | `issues_junit`, `comparer`, `rejouer`, `main` | 111 |
| `tools/forge_nr_socle.py` | gele la dette de tests existante, pour ne plus l'aggraver | `modules`, `main` | 59 |
| `tools/forge_post_commit.py` | Automatisation post-git-commit Nokido ==================================================================== Déclenché par .git/hooks/post-commit après chaque commit | `modules_a_instrumenter`, `should_use_hub`, `reponse_refusee`, `get_changed_files` *(+4)* | 822 |
| `tools/forge_pypi_amorce.py` | le namespace doit etre atteignable DES LE DEMARRAGE | `a_une_amorce_racine`, `candidats`, `traiter`, `main` | 235 |
| `tools/forge_pypi_codemod.py` | PHASE 5 : reecrire les imports plats, par FAMILLES | `carte_modules`, `cible_namespace`, `rediriger_cible`, `decider` *(+2)* | 383 |
| `tools/forge_pypi_contrat.py` | ce que « Nokido est installable depuis PyPI » veut dire | `temoin_publication_vierge`, `gate_testpypi`, `verdict_vierge`, `trancher` *(+4)* | 240 |
| `tools/forge_pypi_patch_tests.py` | rendre leur PRISE aux tests qui simulent une panne | `carte`, `jumeau`, `viser_la_cible`, `fichiers_candidats` *(+2)* | 342 |
| `tools/forge_pypi_prototype.py` | PHASE 4 : prouver la CHAINE avant de migrer le corps | `semer`, `verdict_prototype`, `main` | 260 |
| `tools/forge_pypi_prototype_layout.py` | PHASE 4b : le layout REEL, sans deplacer un fichier | `semer`, `verdict_layout`, `main` | 316 |
| `tools/forge_pypi_wheel.py` | construire la distribution, puis l'OUVRIR | `fuites`, `preparer_source`, `paquets_declares`, `paquets_de_la_wheel` *(+2)* | 250 |
| `tools/forge_qdrant_bench.py` | banc qualite AVANT de basculer la recherche sur Qdrant | `main` | 111 |
| `tools/forge_quality_gate.py` | Quality check statique d'un fichier Python | `quality_check` | 79 |
| `tools/forge_recover_from_branch.py` | recuperer un fichier d'une branche | `main` | 70 |
| `tools/forge_rename_debt_inventory.py` | INVENTAIRE READ-ONLY de la dette du renommage LaForge -> Nokido | `walk`, `read`, `rel`, `main` | 186 |
| `tools/forge_repo_lang_stats.py` | Octets trackes par langage (ce que voit linguist) | `main` | 45 |
| `tools/forge_repro_temoin.py` | P4_REPRO_WITNESS — ce qu'un inconnu obtient vraiment en clonant ce depot | `rediger`, `classer_echec_install`, `construire` | 232 |
| `tools/forge_restore_from_revert.py` | reprend ce qu'un revert a emporte PAR ERREUR | `blocs_supprimes`, `point_insertion`, `main` | 151 |
| `tools/forge_retire_artefact.py` | retirer un artefact NON TRACKE, sans le detruire | `main` | 120 |
| `tools/forge_ruff_quick.py` | Run ruff check + stats privileged (bypass sandbox subprocess block) | `main` | 36 |
| `tools/forge_scalene_demo.py` | Cible de DEMONSTRATION pour scalene — a profiler, pas a importer | `boucle_cpu`, `alloc_memoire`, `calcul_numpy`, `main` | 49 |
| `tools/forge_scalene_optimize.py` | l'optimisation IA de scalene, EN CLI SOUVERAIN | `main` | 338 |
| `tools/forge_snn_entraine_vitals_bench.py` | Le SNN ENTRAINE bat-il le seuil sur les vitals reels ? (mesure manquante) Ce que les bancs precedents ont fait, et pourquoi ca ne suffisait pas | `main` | 191 |
| `tools/forge_stream_mutation.py` | _V1 ========================================================== Streaming live du ParallelMutationWorker avec : - Ring buffer (50 lignes max) - Filtre sémantique sur tags [AST:OK] [RESULT:*] [BILAN] etc | `poll_state`, `print_state`, `stream_worker`, `main` | 244 |
| `tools/forge_suite_pure_triage.py` | qui, parmi les tests exclus, pourrait rentrer ? POURQUOI | `trier`, `valider`, `main` | 186 |
| `tools/forge_suite_pure_valider.py` | execute chaque candidat SEUL, ecrit le verdict | `main` | 58 |
| `tools/forge_tenns_multicanal_bench.py` | TENNs multi-canal : la correlation entre canaux bat-elle un seuil par canal ? La question laissee ouverte le 2026-08-04 | `selectionner_canaux`, `stats_robustes`, `traits`, `cibles` *(+7)* | 384 |
| `tools/forge_vitalite_inscrire.py` | Inscrit le registre de vitalite DEPOSE dans l'arbre versionne | `main` | 150 |
| `tools/forge_wasm_selftest.py` | vérifie la voie wasm NATIVE de forge_wasm_cervelet | `main` | 45 |
| `tools/forge_wiki_align.py` | aligne les noms de modules ET de commandes du wiki sur le code | `scripts_declares`, `commandes_sures`, `main` | 121 |
| `tools/forge_wip_rescue.py` | Snapshot NON-DESTRUCTIF de tout l'uncommitted (tracked + untracked) vers une branche wip/rescue-<suffix>, SANS toucher au working tree ni à l'index réel | `main` | 67 |
| `tools/forge_worktree.py` | isolation PHYSIQUE par agent (git worktree) = fin du clobber multi-surface | `create`, `proof_path`, `create_scratch`, `create_proof` *(+7)* | 319 |
| `tools/generate_stub.py` | Génère les signatures (squelette) d'un fichier Python | `generate_stub` | 41 |
| `tools/hook_posttool_validate.py` | PostToolUse hook (Write\|Edit) | `main` | 128 |
| `tools/nokido_cutover_verify.py` | GATE de securite du rename protege | `count`, `main` | 81 |
| `tools/nr_reporter.py` | Rapports NR persistants + ingestion RAG ========================================================= Chaque run_fast() / run_all() produit : 1 | `NRSuiteResult`, `NRReport`, `NRRunner` | 421 |
| `tools/test_software_creator_e2e.py` | Pipeline software creator E2E test | `stage1_spec_clarifier`, `stage2_generate_and_write`, `stage3_quality_gate`, `stage4_commit_guard` *(+1)* | 420 |
| `tools/verify_gain_gate.py` | vérif RÉELLE du gain-gate sur un vrai fichier | `main` | 48 |

## Observabilite/Trace

*102 modules · 28,482 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_anatomy_state.py` | Snapshot état anatomique Nokido pour Deno WebHub | `get_anatomy_state` | 617 |
| `app/forge_audit.py` | orchestrateur Ultra-Review local (ForgeAudit) | `changed_lines_from_diff`, `enclosing_targets`, `run_forge_audit` | 89 |
| `app/forge_audit_log.py` | Phase 29 (2026-05-25) Audit append-only + W3C trace_id | `init_db`, `gen_trace_id`, `gen_span_id`, `parse_traceparent` *(+5)* | 226 |
| `app/forge_audit_personas.py` | system prompts des 4 prismes ForgeAudit (Ultra-Review local) | `build_persona`, `all_personas` | 117 |
| `app/forge_audit_reducer.py` | filtre déterministe anti-hallucination + agrégation (ForgeAudit) | `symbol_matches`, `reduce_findings`, `render_markdown` | 108 |
| `app/forge_audit_worker.py` | worker de revue READ-ONLY (ForgeAudit) | `audit_file` | 38 |
| `app/forge_conversation_logger.py` | Mémoire conversationnelle vivante Sprint : système nerveux — capture des échanges humain↔agent PRINCIPE AUTOPOÏÉTIQUE : Un organisme qui ne se souvient pas de ses interactions avec son environnement ne peut pas évoluer | `log_turn`, `get_context_window`, `search_past_exchanges`, `get_session_stats` | 276 |
| `app/forge_db_observatoire.py` | rendre VISIBLE ce que chaque requete coute | `ConnexionObservee`, `ouvrir`, `bilan`, `lire_journal` *(+1)* | 300 |
| `app/forge_execution_tracer.py` | Phase 0 | `init_db`, `record_trace`, `get_traces`, `count_traces` | 172 |
| `app/forge_langfuse_hook.py` | émission fail-open des appels LLM vers Langfuse | `emit`, `status` | 123 |
| `app/forge_lifecycle_audit.py` | journal UNIQUE des actions de cycle de vie de Nokido | `record`, `tail` | 168 |
| `app/forge_m2m_conformance.py` | compteur de conformite M2M (OBSERVATION SEULE) | `pointer_statut`, `noter`, `etat`, `reinitialiser` | 203 |
| `app/forge_port_callers.py` | __FORGE_COLOR__ = "regulation/qui-appelle-quoi" QUI APPELLE QUOI -- attribution des connexions locales a leur service appelant | `echantillon`, `canaux`, `rapport` | 241 |
| `app/forge_sensor_fusion_probe.py` | __FORGE_COLOR__ : proprioception / observabilite (organe, READ-ONLY) ORGANE : FUSION MULTI-CAPTEURS — « ce service est-il vivant ? » demande a TROIS sources, et NOMME leurs desaccords au lieu de trancher en silence | `probe`, `probe_all`, `coverage` | 546 |
| `app/forge_service_capabilities.py` | __FORGE_COLOR__ : proprioception / SSoT (organe, READ-ONLY) ORGANE : QUE PORTE CE SERVICE ? — la source qui manquait | `capabilities_of`, `is_critical`, `why_critical`, `nature_de` *(+5)* | 329 |
| `app/forge_signal_atlas.py` | ATLAS DU CABLAGE : module -> signal -> module | `frontiere`, `atlas`, `receveur_declare`, `findings` *(+5)* | 923 |
| `app/forge_signal_coupling.py` | Couplage EMETTEUR <-> CONSOMMATEUR : detecter les signaux orphelins | `emit_signal`, `emetteurs`, `transduce_signal`, `observe_signal` *(+4)* | 570 |
| `app/forge_span.py` | context manager `span()` : call-flow IMBRIQUÉ, souverain | `current_span_id`, `span`, `traced` | 179 |
| `app/forge_tool_efficiency.py` | Comparaison périodique d'efficacité des tools | `metrics_token_usage`, `metrics_network_log`, `detect_degradations`, `rank_by_use_case` *(+2)* | 265 |
| `app/forge_trace_spine.py` | CONTRAT DE PROVENANCE des traces — l'etape qui doit preceder toute centralisation | `Provenance`, `declarer`, `Relation`, `est_causale` *(+11)* | 724 |
| `app/forge_videur_audit.py` | vue d'audit AGREGEE du videur (OBSERVATION SEULE) | `noter`, `vue`, `reinitialiser` | 295 |
| `tools/_dump_batch13_full.py` | Dump full result text for each unique agent from batch13 | — | 36 |
| `tools/audit_ui_consistency.py` | Audit cohérence graphique : chaque page d'interface tuilée charge-t-elle le DS unifié (nokido.css / tokens lf- / --bg-0) ? Login admin (cookie serveur) | `sonde` | 143 |
| `tools/audit_ui_endpoints.py` | câblage RÉEL des GUIs (démo-vs-fonctionne) | — | 82 |
| `tools/forge_alignment_shadow_audit.py` | Harness d'audit sémantique & alignement SHADOW | `run_audit` | 303 |
| `tools/forge_alignment_trace.py` | P1 du homeostat axiologique : observabilite des flux internes auto-generes (service mesh d'alignement, le CAPTEUR) | `emit`, `emit_introspection`, `recent`, `emit_fail_count` *(+2)* | 193 |
| `tools/forge_arbitre_entrees_audit.py` | A0-3 — chaine de preuve des ONZE entrees de `arbitrer_pression` | `audit`, `journal`, `main` | 328 |
| `tools/forge_archaeology.py` | archeologie fonctionnelle (Phase 1, LECTURE SEULE) | `head_basenames`, `deleted`, `classer`, `main` | 187 |
| `tools/forge_archaeology_conversations.py` | Phases 3 & 4 : intentions <-> code <-> archeologie | `phase3_intentions`, `crosswalk`, `main` | 186 |
| `tools/forge_archaeology_enrich.py` | Phases 2 & 5 : que faisait chaque vestige, et lequel vaut d'etre recupere | `enrichir`, `main` | 200 |
| `tools/forge_archeo_socle.py` | socle commun des outils d'archeologie et d'audit | `git`, `git_rc`, `bruit_motifs`, `est_bruit` *(+8)* | 208 |
| `tools/forge_audit_copies_hors_depot.py` | Audit des EXECUTABLES hors depot — ce que `C:\tmp` peut piloter en silence | `lignes_de_docstring`, `repli_declare`, `code_de_sortie`, `scanner_references` *(+2)* | 406 |
| `tools/forge_audit_findings_validate.py` | Valide les artefacts d'audit contre le validateur du skill Cloudflare | `outillage_disponible`, `valider_fichier`, `recenser`, `main` | 196 |
| `tools/forge_audit_perimetre.py` | materialise un perimetre d'audit ATTRIBUABLE | `sha_courant`, `fichiers_du_sha`, `divergents`, `materialiser` *(+1)* | 180 |
| `tools/forge_audit_sortie_bornee.py` | __FORGE_COLOR__ = 'immunitaire/egress' forge_audit_sortie_bornee — enveloppe qui EMPECHE structurellement un outil d'audit de faire sortir une donnee issue du contenu brut d'un artefact sensible | `FuiteRefusee`, `est_empreinte`, `est_nom_de_cle`, `borner` *(+1)* | 167 |
| `tools/forge_bench_corpus_audit.py` | Audit composition du tier chaud du RAG | `categorize`, `main` | 77 |
| `tools/forge_body_regulation_audit.py` | AUDIT D'AUTOREGULATION, module par module | `load_organ_map`, `load_supervision`, `scan_imports`, `scan_references` *(+5)* | 759 |
| `tools/forge_capability_audit.py` | le README declare, le CODE decide | `c_nom_paquet`, `c_entrypoints`, `c_extras`, `c_taille_corpus` *(+14)* | 677 |
| `tools/forge_capability_contracts.py` | contrat par capacite de la surface Nokido | `verifier_une`, `verifier`, `main` | 170 |
| `tools/forge_capability_crosswalk.py` | CAP-* : une capacite, ses quatre preuves | `croiser`, `actions_prouvees`, `annotation_preference`, `main` | 365 |
| `tools/forge_capability_execution_trace.py` | ou meurt une capacite provider | `tracer`, `main` | 131 |
| `tools/forge_capability_freshness.py` | Fraicheur des observateurs de capacite -- rejoue les instruments EXISTANTS | `lancer`, `main` | 116 |
| `tools/forge_capability_lineage.py` | Phase 7 : LIGNEE de chaque constituant | `evenements`, `analyser`, `main` | 267 |
| `tools/forge_capability_ratchet.py` | cliquet de CAPACITES sur la matrice observee | `mesurer`, `main` | 380 |
| `tools/forge_capability_recovery.py` | remonter les capacites perdues | `sha_suppression`, `decrire`, `recuperer`, `main` | 216 |
| `tools/forge_config_refs_audit.py` | traque les REFERENCES MORTES dans les configs | `scan` | 189 |
| `tools/forge_constituent_archaeology.py` | Phase 6 : archeologie des CONSTITUANTS | `est_depot`, `noms_vivants`, `supprimes`, `classer_constituant` *(+4)* | 407 |
| `tools/forge_deadzone_scan.py` | audit des ZONES MORTES du joignable (skills/hooks) | `scan_skills`, `scan_hooks`, `scan`, `main` | 132 |
| `tools/forge_demo_anatomy_stress.py` | workflow demo : declenche un stress hormonal (adrenaline + cortisol) et montre /anatomy (:7400) reagir en live | `main` | 117 |
| `tools/forge_directive_audit.py` | consignes owner données en session mais JAMAIS consignées | `messages_owner`, `empreinte`, `directives`, `couverture` *(+2)* | 471 |
| `tools/forge_docs_port_annotate.py` | annote les docs qui citent un port ARRETE | `ports_muets`, `encadre`, `traiter`, `main` | 142 |
| `tools/forge_effet_reel_audit.py` | l'ecart entre un mecanisme et son EFFET | `signaux_sans_emetteur`, `compter_services`, `interrupteurs_sans_motif`, `artefacts_a_preexister` *(+6)* | 441 |
| `tools/forge_embolie_scanner.py` | __FORGE_COLOR__ : observabilité / SN végétatif (diagnostic anatomique) forge_embolie_scanner — SCANNER D'EMBOLIES par SYSTÈME ANATOMIQUE | `scan`, `main` | 192 |
| `tools/forge_engrid_audit.py` | Audit forge_engrid_bridge.py + forge_engrid_engine.py integration | `audit_imports`, `audit_fallback`, `audit_task_mapping`, `audit_engrid_engine` *(+1)* | 107 |
| `tools/forge_event_mesh_audit.py` | Audit event bus existants pour event_mesh roadmap | `scan_python_event_buses`, `scan_deno_event_buses`, `estimate_event_throughput`, `detect_redundancy` *(+2)* | 200 |
| `tools/forge_fast_logger.py` | Logger haute performance non-bloquant pour Nokido ========================================================================= Remplace les print() synchrones dans les boucles d'évolution par un système bufferisé + thread dédié qui n'interrompt jamais l'inférence | `FastForgeLogger`, `get_fast_logger` | 228 |
| `tools/forge_feature_checklist.py` | la CHECKLIST des fonctionnalites EXPOSEES, verifiee | `add`, `section_cli_entrypoints`, `section_cli_nokido`, `section_tools_cli` *(+10)* | 1144 |
| `tools/forge_full_audit.py` | AUDIT COMPLET consolide de Nokido (owner 2026-07-24) | `audit` | 204 |
| `tools/forge_history_census.py` | Phase 7 : census de l'HISTOIRE (pas des cadavres) | `decouvrir`, `censer`, `focus`, `main` | 393 |
| `tools/forge_log_surface.py` | CENSUS de la surface d'observation de Nokido — ce qu'on peut voir, et d'ou | `census`, `fusion`, `main` | 309 |
| `tools/forge_m2m_audit.py` | Qui touche `agent_messages`, et sur QUELLE base — lecture seule | `classer`, `auditer`, `main` | 92 |
| `tools/forge_module_cards.py` | Proprioception COMPORTEMENTALE (couche statique) | `sig_of`, `card_for`, `build_cards`, `load_cards` *(+6)* | 401 |
| `tools/forge_module_census.py` | Census anatomique des modules Nokido | `nature`, `organ`, `purpose`, `loc` *(+2)* | 485 |
| `tools/forge_module_wiring.py` | chaque module : DEFINI, BRANCHE, TESTE | `modules`, `scanner`, `main` | 429 |
| `tools/forge_mpc_seed_traces.py` | amorce N transitions self-play synthetiques | `main` | 118 |
| `tools/forge_nosology.py` | NOSOLOGIE de Nokido : symptome -> pathologie -> gravite -> remede, et la douleur recoit une GRAVITE au lieu d'un mot | `classify`, `escalate`, `triage`, `main` | 252 |
| `tools/forge_observatory.py` | Neural Swarm Observatory : node-graph LIVE du flux de réflexion Nokido (inspiré Netron : DAG layout propre) | `main` | 171 |
| `tools/forge_organ_declare.py` | Declarer l'organe d'un lot de modules (`__FORGE_COLOR__`), en masse et sans casser | `organe_reconnu`, `point_insertion`, `declarer`, `main` | 198 |
| `tools/forge_organ_smoke_audit.py` | audit d'INTEGRATION des organes | `check`, `main` | 130 |
| `tools/forge_orphan_branches.py` | le patrimoine coince dans les branches | `decouvrir`, `principale`, `analyser`, `recenser` *(+1)* | 141 |
| `tools/forge_otel_export.py` | export OTLP des spans Nokido → Jaeger (Gantt distribué) | `export_span`, `status` | 103 |
| `tools/forge_patch_router_observation.py` | Poser l'observation du routeur shadow SUR SON CANAL — `handle_rag` action=search | `main` | 94 |
| `tools/forge_pip_audit_mesure.py` | Produit un rapport pip-audit DATE, la ou le reseau existe | `enveloppe_meta`, `main` | 176 |
| `tools/forge_probe_update.py` | Probe RCA writes fantomes (2026-07-06) : dans l'env exact du drain (py314 + run_job offline), un UPDATE rag_chunks matche-t-il ? SELECT 1 id -> UPDATE marqueur -> rowcount -> readback (meme conn + conn neuve) -> revert | — | 41 |
| `tools/forge_process_inventory.py` | QUI TOURNE, ET QUI FAIT QUOI | `collect`, `main` | 358 |
| `tools/forge_profiler_hooks.py` | profilers SUR ÉVÉNEMENT / À LA DEMANDE (jamais continu) | `profile_if_slow`, `treesitter_gate`, `uprof_snapshot`, `viztrace` *(+1)* | 173 |
| `tools/forge_pyspy_profiler.py` | profiling runtime du hub (saturation / timeouts) | `find_pyspy`, `cmd_install`, `get_hub_pid`, `cmd_check` *(+4)* | 269 |
| `tools/forge_recurrence_audit.py` | POURQUOI LES MEMES ERREURS REVIENNENT | `scan_corpus`, `scan_memoires`, `croiser`, `scan_sessions` *(+4)* | 793 |
| `tools/forge_repo_settings_audit.py` | Audit des reglages GitHub qui GOUVERNENT une branche — ce que le clone ne voit pas | `audit`, `protect_branch`, `set_meta`, `meta` *(+1)* | 366 |
| `tools/forge_route_authz_audit.py` | matrice d'autorisation des routes HTTP du hub | `classer_garde`, `classer_exposition`, `sonder_exposition`, `auditer` *(+4)* | 870 |
| `tools/forge_rules_deport_section.py` | deporter UNE section de regles hors du noyau resident | `decouper`, `trouver`, `deporter`, `main` | 209 |
| `tools/forge_service_import_check.py` | diagnostic NON-LEAK des services quarantinés : importe chaque module d'entrée (sans lancer le daemon) -> capture les bugs d'IMPORT (cffi, deps manquantes, syntaxe) | `main` | 40 |
| `tools/forge_stack_presence_audit.py` | inventaire PRESENCE + VIVACITE des capacites implementees (demande owner 2026-07-25 : « assure-toi que wasm ainsi que tout ce qui a ete implemente est bien present : qdrant, wasmedge, fts, mcts, bm25 etc ») | `probe_qdrant`, `probe_wasm`, `probe_fts`, `probe_bm25` *(+4)* | 267 |
| `tools/forge_token_meter.py` | Compteur et Agrégateur de Dépense Tokens par CLI ======================================================================== Agrège en temps réel la consommation de tokens et les coûts (USD) par agent (CLAUDE, GEMINI, ANTIGRAVITY, CODEX...) à partir de la table t | `aggregate_by_agent`, `get_agent_usage`, `format_meter_report`, `main` | 145 |
| `tools/forge_trace_collector_rich.py` | collecteur PARALLÈLE de traces riches (text-first) | `init_db`, `run`, `reencode_pending` | 251 |
| `tools/forge_trace_convert_384.py` | convertit les anciennes traces 384d -> 1024d (pont) | `main` | 70 |
| `tools/forge_trace_replay.py` | AMI — Experience Replay: parse mcp_audit.log historical entries → execution_traces.db | `configurer_journal`, `parse_audit_log`, `build_transitions`, `main` | 230 |
| `tools/forge_trace_sidecar.py` | Phase A — AMI trace acceleration | `configurer_journal`, `demarrer`, `succes_de`, `main` | 470 |
| `tools/forge_trace_ui.py` | interface web SOUVERAINE de visualisation observabilité | `main` | 147 |
| `tools/forge_trace_unifiee.py` | tout ce qui entre et sort, et ce qu'on NE trace PAS | `main` | 200 |
| `tools/forge_trace_viz.py` | IRM fonctionnelle : call-flow RUNTIME depuis un trace_id | `exec_load_spans`, `exec_list_traces`, `exec_diag`, `load_spans` *(+7)* | 349 |
| `tools/forge_uprof_apu.py` | collecte des compteurs APU via AMD uProf CLI | `find_cli`, `cmd_check`, `cmd_collect`, `main` | 98 |
| `tools/forge_veille_audit.py` | audit DETERMINISTE des veilles passees (0 LLM, 0 token cloud) | `audit_watch_jobs`, `audit_biblio`, `main` | 205 |
| `tools/forge_veille_serving_audit.py` | SERVING AUDIT : prouver, source par source, qu'une veille est RECUPERABLE | `auditer_source`, `auditer` | 214 |
| `tools/forge_vitals_retro_join.py` | Retro-join : reconstitue les canaux EVENEMENTIELS sur l'historique DEJA ecrit | `charger_blackbox`, `charger_metriques`, `enrichir`, `main` | 267 |
| `tools/forge_wiki_modules.py` | reference des modules, GENEREE depuis le code | `collecter`, `organes`, `sha_du_depot`, `empreinte_du_corpus` *(+12)* | 974 |
| `tools/generate_autopoiese.py` | Carte Autopoïèse Nokido Chaque module code → analogie biologique, organisé en cycles de self-production | `system_center`, `avg_pos` | 352 |
| `tools/generate_body_anatomy.py` | Corps Nokido, A4 lisible Silhouette humaine + zones biologiques groupées, fontsize ≥9 | `body`, `organs`, `callout` | 477 |
| `tools/nokido_acl_observabilite.py` | Accorde aux trois comptes de service la LECTURE des journaux de prothese | `main` | 166 |
| `tools/nokido_nssm_path_audit.py` | quels services nomment le dossier du depot | `scan` | 147 |
| `tools/nokido_status.py` | Outil CLI montrant l usage de NokidoFacade | `print_section`, `cmd_domains`, `cmd_agents`, `cmd_rag` *(+4)* | 155 |
| `tools/nokido_statusline.py` | Statusline Nokido -- affiche la depense, et l'ENREGISTRE au passage | `main` | 231 |

## Locomoteur/Orchestration

*94 modules · 32,068 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_bounded_queue.py` | Bounded queue avec backpressure + leptin release | `BoundedQueue`, `EcrivainDiffere` | 270 |
| `app/forge_cli_harness.py` | generic unattended harness for arbitrary CLI processes | `kill_tree`, `CliHarness`, `agent_bin`, `harness_for` | 309 |
| `app/forge_cost_module.py` | Phase 1 — AMI roadmap: Cost Module | `intrinsic_cost`, `intrinsic_cost_wired`, `task_cost`, `epistemic_cost` *(+2)* | 178 |
| `app/forge_dag_runner.py` | Nokido v18.5 ======================================== Exécution parallèle des plans agent_tasks en DAG | `DAGRunner`, `log_concurrent`, `execute_task_plan` | 255 |
| `app/forge_dispatchers.py` | Branchage des organes réels sur forge_trajectory dispatch | `register_all` | 715 |
| `app/forge_durable.py` | durable execution (Temporal pattern) on Nokido SQLite | `DurableError`, `DurableWorkflow`, `recover_chain_nodes`, `run_steps` *(+1)* | 270 |
| `app/forge_edge_fleet.py` | Edge Inference Fleet POC | `register_edge`, `list_edges`, `sert_le_chat`, `recoit_le_world_vector` *(+16)* | 791 |
| `app/forge_goap_intuition.py` | heuristique d'INTUITION (Système 1) pour le planner GOAP | `keyword_affinity`, `intuition_rank`, `make_value_provider`, `default_embed_fn` *(+4)* | 264 |
| `app/forge_handoff.py` | __FORGE_COLOR__ = "#fb923c" # orange — multi-agent handoff orchestrator forge_handoff — Minimal multi-agent Handoff orchestrator (Swarm pattern) | `ResourceExhausted`, `NoHealthyEndpoint`, `Agent`, `Transfer` *(+15)* | 1696 |
| `app/forge_handoff_compress.py` | context compression entre agents | `compress_for_handoff`, `format_compressed_for_prompt`, `main` | 267 |
| `app/forge_homeostasis_orchestrator.py` | Chef d'orchestre biomimétique Nokido | `FlowRegulator`, `tick`, `main` | 894 |
| `app/forge_job_runner.py` | backend partagé des jobs détachés longue-durée | `params_depuis_corps`, `launch_job`, `read_job`, `reconcile_jobs` *(+1)* | 492 |
| `app/forge_jobid.py` | Phase 2.2 JobID standardization ================================================= "Hémoglobine" du Nokido | `generate_job_id`, `JobContext`, `trace_link`, `persist_job` *(+2)* | 220 |
| `app/forge_local_inference_pool.py` | pool d'inférence locale (ForgeSwarm M3) | `estimate_tokens`, `dynamic_n_ctx`, `make_openrouter_free_backend`, `warm_models` *(+3)* | 462 |
| `app/forge_lock_manager.py` | Phase 2.3 Lock Manager sémantique ========================================================== "Enzymes de régulation" du cytoplasme Nokido | `cle_workdir_agy`, `etat_holder`, `LockState`, `LockManager` *(+1)* | 473 |
| `app/forge_mutation_controller.py` | le KERNEL DE MUTATION (brief §6, §9, §11) | `cycle`, `main` | 73 |
| `app/forge_nlgraph_runner.py` | NLGraph Benchmark Runner for Nokido =============================================================== Tests LLM graph reasoning across 8 tasks of increasing complexity | `TestCase`, `GraphGenerator` | 209 |
| `app/forge_orchestration_gate.py` | classifieur de VOIE du Gate d'orchestration | `Lane`, `Action`, `Decision`, `classify` *(+3)* | 323 |
| `app/forge_orchestrator.py` | Nokido Engrid v3 · Couche 2 ====================================================== ForgeOrchestrator : chaîne complète multi-silos | `LatencyMetric`, `SiloResult`, `OrchestratorResult`, `PromptSegmenter` *(+3)* | 811 |
| `app/forge_plan_validator.py` | Nokido v18.5 ======================================== Validation stricte des plans agent_tasks | `PlanValidationResult`, `PlanValidator`, `get_plan_validator` | 277 |
| `app/forge_pluripotent_workers.py` | Cellules souches logicielles différenciables | `Role`, `PluripotentWorker`, `main` | 336 |
| `app/forge_python_runner.py` | Pool de workers Python pre-warmed ========================================================== Remplace `subprocess.run([python, "-c", code])` par un pool de workers long-lived | `PythonRunner`, `get_runner`, `shutdown_runner` | 378 |
| `app/forge_python_runtime.py` | Python runtime introspection (3.12 / 3.13 / 3.14 / 3.14t) | `runtime_summary`, `recommended_worker_count`, `check_gil_state`, `install_runtime_audit` *(+3)* | 189 |
| `app/forge_python_worker.py` | Worker subprocess pour PythonRunner ============================================================ Process long-lived qui execute du code Python via JSON-RPC sur stdin/stdout | `main` | 158 |
| `app/forge_runtime_observer.py` | ORGANE SENSORIEL en lecture seule | `observer`, `observer_tout` | 204 |
| `app/forge_scorecard.py` | bulletin d'evaluation multidimensionnel | `ExecutionState`, `QualityGrade`, `ScoreMetrics`, `Scorecard` *(+8)* | 638 |
| `app/forge_silo_engine.py` | Siloed Reasoning Engine v1.0 ======================================================== Nokido comme Cerveau Souverain : décompose une intention en silos indépendants, chacun assigné au meilleur modèle local sans jamais exposer le contexte global | `SiloDomain`, `Silo`, `SiloTask`, `KnowledgeGuardian` *(+3)* | 1066 |
| `app/forge_swarm_agents.py` | Catalogue d Agents specialises par provider+use-case | `key_present_for`, `code_groq`, `code_cerebras`, `code_sambanova` *(+14)* | 405 |
| `app/forge_swarm_blackboard.py` | Tableau noir zoné souverain du swarm | `init_db`, `apply_fact`, `read_zone`, `list_zones` *(+1)* | 375 |
| `app/forge_swarm_bus.py` | bus side-channel des événements de collaboration swarm | `subscribe`, `unsubscribe`, `publish`, `subscriber_count` | 138 |
| `app/forge_swarm_context.py` | contexte STÉRILE par worker (ForgeSwarm, M1) | `ScopeViolation`, `sterile_read`, `assert_writable`, `build_worker_context` | 123 |
| `app/forge_swarm_evidence.py` | le swarm compte des PREUVES, pas des voix | `classer_erreur`, `strategie_reprise`, `famille_modele`, `groupe_independance` *(+5)* | 405 |
| `app/forge_swarm_orchestrator.py` | orchestrateur Map-Reduce (ForgeSwarm M5) | `run_forge_swarm` | 100 |
| `app/forge_swarm_patch.py` | Search/Replace applier + VFS overlay (ForgeSwarm) | `PatchError`, `parse_sr_blocks`, `apply_sr`, `VFSOverlay` | 160 |
| `app/forge_swarm_router.py` | SERVING : Couche de routage Swarm (intelligence x cadre) | `route_subtask`, `score_de`, `cout_de`, `gain_collectif` *(+1)* | 422 |
| `app/forge_swarm_validator.py` | Gatekeeper pré-vol déterministe (ForgeSwarm M0) | `validate_swarm_plan` | 136 |
| `app/forge_swarm_worker.py` | worker éphémère (ForgeSwarm M2) | `run_worker` | 109 |
| `app/forge_tag_dispatch.py` | route a task to fleet peers chosen by label/purpose | `dispatch`, `main` | 85 |
| `app/forge_task_queue.py` | File d attente persistante pour les rôles ================================================================ Remplace l envoi de 18 tâches en batch par un système de queue | `enqueue`, `enqueue_many`, `queue_status`, `get_results` *(+3)* | 309 |
| `app/forge_task_router.py` | v2 - Orchestrateur taches zero-token Claude Exploite TOUS les providers Nokido disponibles | `status`, `select_provider`, `route` | 468 |
| `app/forge_trajectory.py` | Structured Agentic Trajectory Implémentation du pattern JSON-RPC inter-agent strict (vs prose chatbot) | `IntentValidationError`, `parse_intent`, `validate_intent`, `correction_prompt` *(+9)* | 633 |
| `app/forge_transient_executor.py` | PREMIER executor deterministe de preuve | `capacite_de`, `etat_llm_local`, `executer`, `verifier` | 442 |
| `app/forge_viable_system.py` | Organisateur cybernétique (VSM) + orchestrateur multi-pool | `level_of`, `assign_provider`, `plan_orchestration`, `publish_plan` *(+7)* | 337 |
| `tools/_batch10_send.py` | Batch 10 | — | 54 |
| `tools/_batch11_send.py` | Batch 11 — T8 nervous_system, T6 graph-dim verify, graph improvements, TUI, GOAP | — | 155 |
| `tools/_batch12_send.py` | Batch 12 | — | 84 |
| `tools/_batch13_send.py` | Batch 13 | `send` | 177 |
| `tools/_batch5_send.py` | Batch 5 | — | 68 |
| `tools/_batch6_send.py` | Batch 6 | — | 84 |
| `tools/_batch7_send.py` | Batch 7 | — | 80 |
| `tools/_batch8_send.py` | Batch 8 | — | 111 |
| `tools/_batch9_send.py` | Batch 9 | — | 23 |
| `tools/_batch_send.py` | One-shot: send batch 4 of delegation tasks | — | 80 |
| `tools/_run_batch11.py` | Run batch11: git commit sambanova fix + dispatch all tasks | — | 19 |
| `tools/_wait_batch13.py` | Wait until all 9 batch13 tasks have a result, then print summary | — | 50 |
| `tools/delegate_tasks.py` | Délègue les tâches CTF paliers + embed aux LLMs appropriés via hub | `hub` | 102 |
| `tools/fast_test_runner.py` | FORGE_PERF_TEST_V2 ================================================ Selective Regression Testing (SRT) + Streaming + Chaînage mutations Stratégies : 1 | `get_changed_files`, `select_tests_from_diff`, `run_tests`, `chain_mutations` *(+2)* | 356 |
| `tools/forge_ami_strategist.py` | coordinateur AMI subtasks via swarm | `Subtask`, `hub_ask`, `build_prompt`, `extract_first_block` *(+2)* | 674 |
| `tools/forge_benchmark_runner.py` | Golden Dataset benchmark runner | `dispatch_task`, `poll_result`, `score`, `run` | 233 |
| `tools/forge_bfcl_runner.py` | Berkeley Function Call Leaderboard v4 runner pour Nokido | `ensure_dataset`, `call_llm`, `run` | 830 |
| `tools/forge_circadian_runner.py` | declenche la phase circadienne courante | `main` | 85 |
| `tools/forge_cli_swarm.py` | Swarm multi-CLI SOUVERAIN, appelé depuis Nokido | `swarm`, `main` | 126 |
| `tools/forge_collective_gain.py` | ce que le collectif APPORTE, et ce qu'il RETIRE | `verificateur_humaneval`, `mesurer`, `agreger`, `main` | 216 |
| `tools/forge_demo_runner_admin_ui.py` | paced Playwright headed demo of /admin/providers for screen recording (ScreenToGif, ShareX, Win+G) | `main` | 144 |
| `tools/forge_demo_runner_debate.py` | ouvre /forge/debate dans Chromium headed, les 3 providers (ollama_local / groq / cerebras) repondent en parallele au meme prompt, panneaux side-by-side affichent en typewriter | `main` | 53 |
| `tools/forge_demo_runner_hub_tour.py` | paced Playwright headed tour de toutes les UI graphiques Nokido atteignables, pour screen recording | `scene_providers`, `scene_rag`, `scene_network`, `scene_watch` *(+3)* | 207 |
| `tools/forge_demo_runner_terminal.py` | paced Nokido terminal demo for screen recording | `banner`, `typed`, `seq_intro`, `seq_health` *(+5)* | 228 |
| `tools/forge_durable_workflow.py` | PoC durable execution event-sourced (replay-on-restart) | `WorkflowPaused`, `WorkflowStore`, `WorkflowContext`, `durable_run` *(+1)* | 186 |
| `tools/forge_dynamic_tool_runner.py` | Runner ISOLÉ pour outils forgés (sandbox-forced-default) | `main` | 48 |
| `tools/forge_fleet_router.py` | routeur de flotte Nokido (role-clustering + Context Anchoring) | `Node`, `FleetRouter`, `main` | 173 |
| `tools/forge_goap_hub_bridge.py` | GOAP planner wired to Nokido hub MCP API | `Goal`, `Action`, `GOAPPlanner`, `read_task_scorecard` *(+2)* | 563 |
| `tools/forge_goap_online_launch.py` | exécute le planner GOAP en contexte RÉSEAU + DB-write pour que (a) le value_net ONLINE (HF MiniLM 384D aligné) soit live dans l'intuition, (b) les trajectoires soient PERSISTÉES dans execution_traces.db (keystone self-play) | `plan_online`, `run_and_record` | 99 |
| `tools/forge_handoff_worker.py` | worker AUTONOME de dispatch multi-agents (py314t) | `taille_pool`, `free_threading_actif`, `valider_enveloppe`, `depiler_postal` *(+3)* | 280 |
| `tools/forge_harness_worker.py` | fleet worker that drives real CLI agents via the harness | `process_job`, `main` | 187 |
| `tools/forge_humaneval_runner.py` | HumanEval benchmark runner pour Nokido | `ensure_dataset`, `call_llm`, `run` | 891 |
| `tools/forge_mutation_ratchet.py` | cliquet de mutation sur les surfaces critiques | `mesurer`, `main` | 223 |
| `tools/forge_mutation_run.py` | lanceur de la boucle d'auto-amelioration | `main` | 129 |
| `tools/forge_orchestrate_loop.py` | Autonomous agentic loop via GOAP Uses forge_goap.GoalPlanner + execute_plan + hub dispatch | `durable_run_status`, `run_loop` | 347 |
| `tools/forge_orchestrate_react.py` | ReAct agentic loop for Nokido Uses Ollama qwen3:8b with native function calling | `get_tools_schema`, `run_react` | 154 |
| `tools/forge_planbench_runner.py` | PlanBench benchmark runner pour Nokido | `BWState`, `ensure_dataset`, `call_llm`, `run` | 639 |
| `tools/forge_purge_redteam_runtime.py` | Purge du runtime offensif residuel — inventaire d'abord, retrait ensuite | `inventaire`, `appliquer`, `main` | 313 |
| `tools/forge_reflexion_cli.py` | Visu CLI live du FLUX DE RÉFLEXION Nokido | `main` | 187 |
| `tools/forge_runtime_smoke.py` | le hub DEMARRE-t-il, et REPOND-il ? La chaine de publication prouve qu'un paquet s'installe, s'importe et que ses entrypoints repondent | `smoke`, `main` | 257 |
| `tools/forge_scorecard_judge_job.py` | batch judge pour Scorecards UNRATED | `scan_unrated`, `judge_one`, `main` | 143 |
| `tools/forge_strategy_swarm.py` | planification multi-swarm SOUVERAINE d'une stratégie "vivre le corps" | `run`, `main` | 132 |
| `tools/forge_swarm_debate.py` | débat SWARM 3 tours, pool de spécialistes diversifiés | `main` | 119 |
| `tools/forge_swebench_lats_runner.py` | runner SWE-bench avec stack LATS | `process_instance`, `run_generate_lats`, `main` | 1288 |
| `tools/forge_swebench_runner.py` | SWE-bench runner pour Nokido | `ensure_dataset`, `call_llm`, `generate_patch`, `generate_patch_best_of_n` *(+4)* | 3084 |
| `tools/forge_terminal_bench_runner.py` | Terminal-Bench 2.0 pour Nokido | `call_llm`, `run_task`, `run` | 891 |
| `tools/forge_turbo_runner.py` | Exécuteur de tests parallélisé pour Ryzen 8700G ======================================================================== Utilise pytest-xdist pour distribuer les tests sur les 8 cœurs (16 threads) du Ryzen 8700G | `run_turbo`, `main` | 245 |
| `tools/hook_gate_orchestrator.py` | Gate d'orchestration muet (Phase B) | `main` | 52 |
| `tools/hub_swarm_patch.py` | Patch Hub : route /swarm + /team ============================================================= Expose l état du swarm et la config team en temps réel via le Hub | `patch_app` | 167 |
| `tools/patch_trajectory_offensive_redteam.py` | Sort les intents OFFENSIFS (ring >= 3) du coeur (owner 2026-09-26) | `main` | 123 |
| `tools/resume_chain.py` | Resume chain nodes by chain_id | — | 44 |

## Metabolisme LLM (routage/backends)

*74 modules · 20,467 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_artificialanalysis.py` | Wrapper API ArtificialAnalysis.ai ================================================================ Fetch metrics fraiches pour modeles LLM (pricing, speed, quality scores) depuis https://artificialanalysis.ai/api-reference | `fetch_llms`, `get_model_metrics`, `get_provider_metrics`, `get_pricing` *(+9)* | 493 |
| `app/forge_baml_adapter.py` | LLM structured outputs avec retry intelligent | `structured_call`, `main` | 227 |
| `app/forge_cascade_oracle.py` | Oracle CE pour décision S1/S2 ========================================================= Implémentation de la décision hybride basée sur le score CrossEncoder | `RetrievalResult`, `CascadeOracle` | 352 |
| `app/forge_coagulation_cascade.py` | Isolation localisée des crashes workers (cascade fibrinogène) | `detect_breaches`, `capture_state`, `open_clot`, `check_embolie` *(+4)* | 353 |
| `app/forge_contract_net.py` | Élection de worker style Contract-Net (switchboard backlog) | `collect_bids`, `elect_worker` | 123 |
| `app/forge_conv_indexer.py` | Indexation conversations CLI (Claude + Gemini) dans RAG ================================================================================ Transforme les sessions JSONL/JSON des CLIs en chunks RAG searchables | `racines_couvertes`, `fichiers_couverts`, `iter_claude_chunks`, `iter_agy_chunks` *(+12)* | 937 |
| `app/forge_dspy_router.py` | DSPy Signatures pour rendus structures | `signature_call` | 165 |
| `app/forge_dt_router.py` | DT router: SpikeRouter SNN -> cognitive pipeline hookup | `DTResult`, `dt_route` | 75 |
| `app/forge_frugal_cascade.py` | Cascade LLM small→large pattern FrugalGPT (Chen et al | `cascade`, `main` | 371 |
| `app/forge_jwt_router.py` | Middleware JWT HS256 + routage par aud ============================================================ 4 piliers de sécurité : 1 | `has_perm`, `forge_frame_token`, `verify_frame_token`, `jwt_routing_middleware` *(+1)* | 218 |
| `app/forge_litellm_router.py` | Façade litellm.Router (PR-C switchboard) | `build_model_list`, `build_router`, `get_router` | 99 |
| `app/forge_llamacpp.py` | Moteur LLM local via llama-cpp-python OU llama-server HTTP =============================================================================== Priorité 1 : llama-cpp-python pip (in-process) Priorité 2 : llama-server HTTP fallback (port 8080, Vulkan 780M) Config No | `get_llm`, `strip_think`, `is_available`, `llamacpp_call` *(+3)* | 416 |
| `app/forge_llm_budget.py` | budget_manager + cooldown_per_provider | `BudgetManager`, `wrap_llm_call`, `main` | 278 |
| `app/forge_llm_router_dt.py` | Routeur LLM par DecisionTree sklearn ============================================================= Couche additionnelle AU-DESSUS de forge_task_router | `TextFeatureExtractor`, `predict`, `log_decision`, `update_provider_health` *(+2)* | 778 |
| `app/forge_llm_transport.py` | Socle commun de transport LLM Nokido v18.5 ==================================================================== Centralise les appels HTTP (urllib) vers tous les providers | `LLMTransport` | 248 |
| `app/forge_md_router.py` | __FORGE_COLOR__ = "#a78bfa" # purple — semantic router for Markdown docs Markdown Semantic Router for Nokido — BAML-backed lazy loader | `build_index`, `route_query`, `extract_adr`, `extract_spec` *(+4)* | 532 |
| `app/forge_npu_direct.py` | Wrapper direct ONNX VitisAI NPU (sans brain_worker ZMQ) | `encode` | 110 |
| `app/forge_oauth_mutex.py` | Mutex=1 STRICT pour les appels OAuth-CLI (anti-collision entonnoir Hub) | `lane_of`, `mutex_acquire`, `oauth_mutex` | 191 |
| `app/forge_perception_vlm.py` | Perception multimodale (VLM local via Ollama) | `get_vlm_model`, `capture_screen`, `analyze_image`, `scan_environment` *(+2)* | 320 |
| `app/forge_prompt_cache.py` | Prompt caching pour Nokido Anthropic (via OpenRouter) : cache_control = {"type": "ephemeral"} - Cache write : 1.25x base (TTL 5min) ou 2.0x (TTL 1h) - Cache hit : 0.10x base (-90%) - Min tokens : 1024 - TTL default : 5 min, se rafraichit a chaque hit Gemini (i | `build_cached_system`, `build_cached_messages`, `start_keepalive`, `stop_keepalive` *(+2)* | 242 |
| `app/forge_provider_admin.py` | Web UI admin pour LLM providers | `list_providers`, `set_provider_key`, `delete_provider_key`, `etat_des_acces` *(+17)* | 1106 |
| `app/forge_provider_alias.py` | la verite a UNE adresse : `forge_agent_proxy.ask` | `refus_de_resolution`, `resoudre`, `diagnostic` | 248 |
| `app/forge_provider_quota.py` | Quota tracker + cascade gate ======================================================= Suit la consommation par provider et bloque les appels qui depasseraient le quota mensuel (cf | `usage_this_month`, `usage_today`, `quota_status`, `check_quota` *(+5)* | 244 |
| `app/forge_provider_specs.py` | Catalogue specifications providers Nokido ===================================================================== Source de verite pour : - Tier (local / free / subscription_quota / paid_api) - Quota mensuel/quotidien (post 2026-06-15 Agent SDK quota) - Speciali | `get_spec`, `get_tier`, `is_free`, `is_subscription_quota` *(+6)* | 502 |
| `app/forge_provider_watcher.py` | Daemon surveillance providers (on-demand) Session 5 | `start`, `stop` | 104 |
| `app/forge_quota_manager.py` | Gestion dynamique quota Gemini CLI ============================================================ RÈGLE FONDAMENTALE : - 0% vu dans /model CLI = vraiment disponible (pool propre) - None (pas de logs) = inconnu → ne pas assumer disponible - 100% = épuisé → skip P | `fetch_live_quota`, `read_gemini_logs`, `get_pool_usage`, `is_available` *(+4)* | 262 |
| `app/forge_quota_tracker.py` | Tracker quota multi-provider unifie ============================================================= Recolte la metrique de quota/usage par provider depuis 3 sources : 1 | `record_response_headers`, `record_429`, `get_quota`, `get_all_quotas` *(+1)* | 400 |
| `app/forge_retry_strategies.py` | Strategies de retry LLM-aware pour Nokido =========================================================================== Trois additions a tenacity pour les appels cloud (Groq/Gemini/OpenRouter) : wait_retry_after : lit le header HTTP Retry-After de la reponse 42 | `wait_retry_after`, `wait_rpm_budget`, `retry_if_rate_limited`, `wait_exp_jitter` *(+1)* | 336 |
| `app/forge_self_mutation.py` | boucle d'auto-amelioration, remise en service | `fichier_protege`, `MutationGuard`, `MutationCycle` | 320 |
| `app/forge_semantic_route.py` | Routage sémantique text → use_case (bge-m3) | `build_centroids`, `semantic_route` | 200 |
| `app/forge_semantic_routes.py` | embedding route-matcher with threshold optimization | `Route`, `SemanticRouter`, `intent_router` | 220 |
| `app/forge_tokenizer.py` | Multi-provider tokenizer dispatcher | `count_tokens`, `available_tokenizers`, `display_summary` | 414 |
| `tools/_start_llamacpp.py` | Lance llama-server directement (sans NSSM admin) | — | 26 |
| `tools/auto_retrain_dt.py` | Retrain DT router si assez de nouvelles donnees | `main` | 79 |
| `tools/download_phi35.py` | Télécharge Phi-3.5-mini-instruct-onnx (variante DirectML) depuis HuggingFace | — | 37 |
| `tools/forge_ami_train_cycle.py` | 1 vrai cycle entrainement AMI prod | `run_cycle`, `main` | 171 |
| `tools/forge_anthropic_ingress.py` | ingress Anthropic Messages API (/v1/messages) -> Nokido | `health`, `list_models`, `messages`, `main` | 161 |
| `tools/forge_backend_power.py` | START / STOP / STATUS des backends LLM locaux (économie ressources) | `warm`, `status`, `start`, `stop` *(+7)* | 407 |
| `tools/forge_bitnet_loader.py` | Détecteur de modèles BitNet ternaire (1.58-bit) locaux | `detect_bitnet_models`, `suggested_llama_args`, `summary` | 140 |
| `tools/forge_card_summarize.py` | DEFINITIONS grounded des modules sans docstring | `targets`, `run`, `main` | 160 |
| `tools/forge_cli_route.py` | toggle ON/OFF du routage des CLI agentiques via les ingress Nokido | `cmd_status`, `cmd_toggle`, `cmd_isolate`, `cmd_launch` *(+1)* | 298 |
| `tools/forge_deep_doc_enricher.py` | Enrich docs/**/*.md + *.pdf into RAG with LLM metadata | `process_documents` | 162 |
| `tools/forge_endpoint_commun.py` | Socle commun des sondes d'endpoints — interroger, lister, trier | `requete`, `lire`, `catalogue`, `taille_apparente` *(+2)* | 95 |
| `tools/forge_endpoint_profiling.py` | Quelle est la SPECIALITE de chaque endpoint, et quel role lui confier ? Le routeur attribue aujourd'hui ses `use_case` par habitude : les chaines ont ete ecrites en avril et jamais confrontees a ce que les endpoints font REELLEMENT | `mesurer`, `role_propose`, `quota`, `main` | 190 |
| `tools/forge_hf.py` | Client Hugging Face SOUVERAIN Nokido | `whoami`, `upload`, `download`, `submit_job` *(+4)* | 161 |
| `tools/forge_hf_free_scan.py` | Hugging Face : le champ `is_free` existe-t-il, et que vaut-il pour nous ? Une analyse externe affirme que HF publie un champ `is_free` dans son catalogue de providers, qu'un compte gratuit recoit $0,10 de credits mensuels, et qu'un modele marque `is_free` ne l | `essayer`, `main` | 162 |
| `tools/forge_hf_providers_bge.py` | QUI sert reellement `BAAI/bge-m3` derriere le routeur HF | `catalogue_siliconflow`, `main` | 144 |
| `tools/forge_hot_load_manager.py` | Gestion keep-alive Ollama + tracking quotas Cloud ============================================================================== Maintient les modèles locaux "chauds" en VRAM pour éliminer le cold-start (~5s) et surveille les quotas Free Tier des APIs cloud (G | `ProviderQuotaTracker`, `ForgeHotLoadManager`, `get_hot_load_manager` | 439 |
| `tools/forge_kv_keepalive.py` | KV Cache Keep-alive OpenRouter ============================================================== Envoie un ping léger toutes les 30s pour maintenir le contexte du modèle chaud côté serveur OpenRouter | `start_background`, `stop`, `status` | 222 |
| `tools/forge_llama_reconcile.py` | Reconcilie les llama-server DUPLIQUES | `main` | 70 |
| `tools/forge_llama_worker_isolated.py` | Wrapper Win32 Job Object pour llama-server.exe | `IO_COUNTERS`, `JOBOBJECT_BASIC_LIMIT_INFORMATION`, `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`, `create_job_with_mem_cap` *(+5)* | 279 |
| `tools/forge_llamaedge_bringup.py` | monte le serveur LlamaEdge WASM (/v1 OpenAI-compat) | — | 86 |
| `tools/forge_lmstudio_server.py` | maintient le serveur LMStudio (:1234) UP, comme ollama/llamacpp | `main` | 77 |
| `tools/forge_local_llm.py` | résolution + appel d'un LLM LOCAL qualifié, à la demande | `list_ollama_models`, `pick_ollama_model`, `chat` | 128 |
| `tools/forge_lora_trainer.py` | Fine-tuning LoRA de qwen2.5-coder:7b sur corpus Nokido ================================================================================= Entraîne un adaptateur LoRA (Low-Rank Adaptation) sur le corpus Nokido : - Paires instruction → code documenté (docstrings | `build_dataset`, `train`, `test_inference` | 441 |
| `tools/forge_mesure_journaux.py` | Mesure AVANT / APRES du switch des journaux : la grosse base CESSE-T-ELLE de recevoir ? __FORGE_COLOR__ = 'metabolisme/mesure : ecritures des journaux sur la base RAG, par fenetre' Contrat owner du 2026-09-19 : « on ne deplace pas des tables, on RETIRE DES ECR | `compter`, `ecarts`, `fenetre`, `main` | 179 |
| `tools/forge_night_trainer.py` | Trainer nocturne : backprop global + DPO LoRA | `phase1_pytorch_training`, `phase2_dpo_extraction`, `phase3_lora_finetune`, `anchor_results` *(+3)* | 338 |
| `tools/forge_openai_proxy.py` | OpenAI-compatible bridge for LobeHub / Cline / others | `load_token`, `hub_call`, `health`, `list_models` *(+4)* | 1597 |
| `tools/forge_provider_catalogue.py` | Quels modeles ce fournisseur autorise-t-il A CETTE CLE ? Un `403` ou un `404` sur un appel de generation a deux causes tres differentes, et les confondre coute des heures : la cle est morte, ou le MODELE demande a ete retire | `interroger`, `modeles_cables`, `candidates_du_clair`, `main` | 250 |
| `tools/forge_provider_reachability.py` | dimension REACHABILITY des providers | `analyser`, `main` | 187 |
| `tools/forge_pytorch_nets.py` | ValueNet + PolicyNet + CostNet PyTorch autograd | `ValueNetPT`, `PolicyNetPT`, `CostNetPT`, `get_value_net_pt` *(+6)* | 466 |
| `tools/forge_route_solver.py` | allocation tâche→provider sous contraintes DURES (anti-Goodhart) | `critical_capable_providers`, `solve_route`, `selftest` | 117 |
| `tools/forge_router_slots_probe.py` | Chaque slot du routeur est-il REELLEMENT appelable ? Le 2026-08-18 on a decouvert que les 7 slots `github_*`, ajoutes en avril avec la mention « 7 modeles testes OK », pointent sur un backend que GitHub a RETIRE (410 Gone, mesure y compris sur une inference re | `slots_routeur`, `runtimes`, `correspondance`, `main` | 247 |
| `tools/forge_swe_provider_test.py` | Teste call_llm (du runner SWE) pour chaque provider DANS le contexte trusted (= contexte du runner détaché) -> voir le retour réel (ERR/firewall/token/code) | — | 15 |
| `tools/forge_tinygrad_poc.py` | PoC tinygrad sur iGPU AMD 780M (Windows, sans DirectML) | `log`, `phase_check`, `phase_install`, `phase_enum` *(+2)* | 162 |
| `tools/forge_token_optimizer.py` | Compression de prompts pour économiser les tokens ============================================================================= Réduit la taille des prompts envoyés aux LLMs (Groq/Ollama/Gemini) de 20-40% via trois stratégies : 1 | `ForgeTokenOptimizer`, `get_optimizer` | 208 |
| `tools/forge_tool_call_probe.py` | Quels endpoints savent VRAIMENT appeler un outil ? Le profilage attribuait `tool_call` sur `supported_parameters`, c'est-a-dire sur une DECLARATION du catalogue | `interroger`, `fusionner`, `main` | 245 |
| `tools/forge_wake_llama_native.py` | Reveil RUNTIME de NokidoLlamaNative (:8091) sans toucher disabled=true | `make_lite`, `resolve`, `health`, `main` | 285 |
| `tools/forge_warm_code_model.py` | rend le modele de CODE resident, en detache | `residents`, `main` | 81 |
| `tools/llama_cli.py` | nokido CLI — interface terminal pour llama-server :8091 + Nokido hub :8766 | `cmd_chat`, `cmd_ask`, `cmd_models`, `cmd_status` *(+9)* | 699 |
| `tools/llama_proxy.py` | shim: delegates to forge_demand_proxy --service llama | — | 11 |
| `tools/make_tiny_onnx.py` | generate a trivial ONNX model (Y = X plus one) to test if WinML loads and runs inside the Xbox UWP AppContainer | — | 34 |
| `tools/nokido_llamacpp_ui_patcher.py` | patch UI llama.cpp → français + branding Nokido | `fetch_html`, `patch_html`, `main` | 270 |
| `tools/ollama_graceful_stop.py` | ============================== Ferme Ollama proprement : 1 | `unload_models` | 57 |

## Digestif/Sens (ingestion/web)

*70 modules · 17,762 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_auto_ingest_daemon.py` | Periodic Auto-Ingest ====================================================== Démon qui surveille data/rag_files/ et ingère les nouveaux fichiers toutes les 5 minutes | `run_daemon` | 41 |
| `app/forge_browser_tool.py` | Bridge Nokido <-> browser-control-mcp (Firefox) Installe l extension Firefox : https://addons.mozilla.org/firefox/addon/browser-control-mcp/ Lance le MCP server Node : npx @eyalzh/browser-control-mcp --port 3001 (port 3001 pour ne pas conflitter avec Nokido :8 | `get_tabs`, `read_webpage`, `get_history`, `browser_ingest_to_rag` *(+1)* | 164 |
| `app/forge_crawl_tool.py` | Crawl web frugal pour Nokido (déporté dans le hub) | `html_to_markdown`, `firewall_web`, `crawl_url`, `crawl_url_detail` | 431 |
| `app/forge_ingest_pipeline.py` | Pipeline raffinement données -> vecteurs ==================================================================== 3 niveaux (état de l'art 2026) : L1 | `RefinedChunk`, `clean_text`, `estimate_tokens`, `chunk_semantic` *(+7)* | 515 |
| `app/forge_pty_widget.py` | Nokido PTY Textual widget (moderne) =========================================================== Successeur moderne de PTYTerminal (Nokido_v13.6.py L1009-1290) | `PTYConnectError`, `PTYSession`, `LocalPTYSession` | 824 |
| `app/forge_web_fallback.py` | Fallback SearXNG: engines generaux -> duckduckgo -> vide Pas de LLM externe | `web_search_with_fallback`, `format_results` | 79 |
| `app/forge_web_fetch.py` | Fetcher + extracteur texte + ingestion RAG qualifiee Pipeline: URL -> fetch HTML -> extract texte -> chunk -> qualifier -> rag_chunks | `extract_text`, `extract_title`, `classify_url`, `chunk_text` *(+1)* | 233 |
| `tools/check_gitingest_status.py` | Compte gitingest disponibles vs indexés dans RAG | `main` | 33 |
| `tools/extract_js_endpoints.py` | Extrait endpoints depuis bundles JS webpack/vite | `extract_js_endpoints` | 56 |
| `tools/forge_anchor_swebench.py` | Ancre le fix localisation SWE-bench dans Nokido | `main` | 34 |
| `tools/forge_antiregression_full.py` | LA passe | `main` | 185 |
| `tools/forge_audit_swebench.py` | éval grounded de ForgeAudit (ultrareview) via SWE-bench | `gold_old_lines`, `main` | 255 |
| `tools/forge_bulk_import.py` | Import massif de liens dans Nokido | `parse_links`, `dedup`, `insert_bulk`, `main` | 255 |
| `tools/forge_curriculum_ingest.py` | Ingestion de RÉFÉRENCES CANONIQUES par module du cursus IA dans RAG domain='reference' (cercle de savoir, cf gouvernance épistémique) | `fetch_text`, `ingest_module`, `ingest_snippets`, `main` | 254 |
| `tools/forge_dashboard.py` | Dashboard Nokido v17 ========================================== Visualisation temps réel du vault génomique, des métriques et des runs Cerberus | `score_color`, `load_vault`, `load_episodic_stats`, `load_active_runs` *(+5)* | 527 |
| `tools/forge_db_index_advisor.py` | Chaque base indexee POUR SES PROPRES requetes — pas selon un modele generique | `auditer`, `appliquer`, `main` | 388 |
| `tools/forge_doc_ingest.py` | Ingestion d'un fichier .md en chunks RAG | `ingest_file`, `main` | 148 |
| `tools/forge_docset_ingest.py` | ingestion BULK docset Dash/Zeal -> RAG (domain='reference') | `ingest`, `main` | 250 |
| `tools/forge_egress_chokepoint.py` | ou sort reellement une donnee vers un LLM ? Mesure 2026-09-02 : la politique de partage (`forge_share_policy`) a ete branchee dans `forge_swarm_router.route_subtask`, et `router_call` s'est revele atteint par plusieurs AUTRES chemins | `cartographier`, `rapport`, `main` | 181 |
| `tools/forge_fts_trigram.py` | Index TRIGRAM sur le code et les logs — trouver `ErrConnectionReset` par fragment | `construire`, `bench`, `main` | 267 |
| `tools/forge_gitingest_sdk_ingest.py` | Ingest gitingest SDK dumps into Nokido RAG | `ingest_file`, `main` | 256 |
| `tools/forge_ingest_ai_prompts_landscape.py` | Ingest x1xhlol/system-prompts-and-models-of-ai-tools (32 AI tools) into RAG | `ingest`, `verify`, `main` | 421 |
| `tools/forge_ingest_llms_txt.py` | ingere un SITE de documentation via son `llms.txt` | `recuperer_index`, `extraire_pages`, `ingerer`, `main` | 231 |
| `tools/forge_ingest_rfc_run.py` | déporte l'ingestion docset RFC + snippets canoniques | — | 21 |
| `tools/forge_m2m_debate_antiregression.py` | DEBAT M2M (Claude <-> Antigravity <-> panel local) dont l'objet est UNE SEULE chose : une methode de detection de regression qui NE RATE RIEN | `axes_en_production`, `proposition_agy`, `corpus_regressions_connues`, `ssot_lire` *(+5)* | 832 |
| `tools/forge_netcfg_docset_normalize.py` | normalise les references normatives des docsets vendor de netcfg-agent (docs/vendor_knowledge/<vendor>/NN_sujet.md) | `normalise_texte`, `run`, `main` | 203 |
| `tools/forge_patch_crawl_offload.py` | deporte les appels bloquants de handle_crawl | `main` | 84 |
| `tools/forge_playwright_browser.py` | Browser headed isolé + Oracle UI pour Nokido | `inventaire_magasin`, `candidats_lancement`, `choisir_lancement`, `PlaywrightBrowser` *(+1)* | 529 |
| `tools/forge_regression_matrix.py` | Transforme l'historique reel en matrice anti-regression | `cmd_stats`, `cmd_extract`, `cmd_check`, `main` | 443 |
| `tools/forge_regression_sweep.py` | les trois familles que la sentinelle d'ancres ne voit pas | `axe_valeur_et_config`, `axe_imports_orphelins`, `axe_backends_supprimes`, `main` | 450 |
| `tools/forge_reingest_gitingest.py` | Reingestion PROPRE des dumps gitingest : purge -> reingere -> vectorise | `main` | 108 |
| `tools/forge_source_discovery.py` | Enrichissement RAG par découverte web ciblée ========================================================================= Recherche des sources pertinentes sur le web et les injecte dans le RAG de Nokido pour enrichir le contexte des mutations | `ForgeSourceDiscovery` | 1053 |
| `tools/forge_swebench_bg.py` | wrapper SWE-bench pour le hub /admin/run_job | — | 85 |
| `tools/forge_swebench_detach.py` | lance forge_swebench_bg.py DÉTACHÉ | — | 41 |
| `tools/forge_swebench_modal.py` | SWE-bench sur Modal (conteneurs cloud //) | `solve_instance`, `main` | 103 |
| `tools/forge_swebench_repo_cache.py` | pre-calc + cache repo_map des repos cibles SWE-bench | `prepare_instance`, `load_cached_markdown`, `load_cached_manifest`, `cached_repo_path` *(+2)* | 235 |
| `tools/forge_swebench_strategy_debate.py` | debat multi-LLM neuro-symbolique | `run_debate`, `main` | 283 |
| `tools/forge_ui_generator.py` | LLM-generated UI components for Nokido hub | `generate_component`, `list_components`, `main` | 185 |
| `tools/forge_veille_backfill.py` | rattrapage du corpus de veille DEJA ingere (owner 2026-07-25 : « reverifie les veilles passees si elles sont incompletes ») | `main` | 604 |
| `tools/forge_veille_campagne_run.py` | lance la campagne de veille du 2026-08-30 | — | 36 |
| `tools/forge_veille_clone_ingest.py` | veille souveraine sans SearXNG/SDK gitingest | `charger_cibles`, `alias_historiques`, `positionnels`, `selectionner` *(+14)* | 1344 |
| `tools/forge_veille_depollute.py` | retire l'en-tete « [VEILLE] Theme: | `main` | 158 |
| `tools/forge_veille_e2e_check.py` | E2E de la chaine de veille : prothese Docker -> SearXNG -> Crawl4AI -> bail | `etage_prothese`, `etage_service`, `etage_capacite_searxng`, `etage_chaine` *(+1)* | 193 |
| `tools/forge_veille_gap_recover.py` | le trou entre biblio et contenu RAG | `prochain_creneau`, `main` | 415 |
| `tools/forge_veille_gap_run.py` | rattrapage de veille deporte, sans argument | — | 51 |
| `tools/forge_veille_intake_filter.py` | refuser le contenu GENERE a l'entree | `est_genere`, `est_hors_substance`, `resume_hors_substance`, `marqueurs_ver` *(+2)* | 369 |
| `tools/forge_veille_registre.py` | le CONTRAT du registre de cibles de veille | `RegistreInvalide`, `CibleInconnue`, `url_canonique`, `target_id` *(+20)* | 677 |
| `tools/forge_veille_rejeu.py` | rejoue les veilles qui n'ont RIEN rapatrie | `main` | 122 |
| `tools/forge_veille_run.py` | veille approfondie déportée GÉNÉRIQUE : ingère TOUS les modules `*_eco` | — | 24 |
| `tools/forge_veille_u1_run.py` | chantier U1 : les depots de veille JAMAIS ingeres | `charger_absents`, `deja_faits`, `construire_cibles`, `main` | 136 |
| `tools/forge_veille_variete_mesure.py` | MESURER le seuil hors-variete, pas l'inventer | `main` | 175 |
| `tools/forge_veille_variete_organe.py` | qualification par ORGANE, pas par moyenne globale | `main` | 240 |
| `tools/forge_vendor_kb_ingest.py` | Ingest vendor knowledge base into RAG | `VendorChunk`, `parse_frontmatter`, `slug`, `split_by_h2_sections` *(+3)* | 423 |
| `tools/forge_web_egress.py` | Gateway d'egress web firewallé (le "hard hijack" web) | `health`, `fetch_ep`, `main` | 151 |
| `tools/ingest_ami_repos.py` | Gitingest 5 repos AMI-roadmap + lance veille approfondie SearXNG | — | 123 |
| `tools/ingest_gitingest.py` | Ingest gitingest_nokido.txt into RAG domain=nokido_digest | `sha256_id`, `chunk_text`, `main` | 107 |
| `tools/ingest_gitingest_batch.py` | Batch ingest data/gitingest/*.txt into RAG Usage: hub run action=python code="exec(open('tools/ingest_gitingest_batch.py').read())" | `sha256_id`, `chunk_text`, `main` | 106 |
| `tools/ingest_pdf.py` | Ingère un PDF dans le RAG via MarkdownChunker (forge_rag_store) | `extract_text`, `pdf_text_to_markdown`, `main` | 148 |
| `tools/ingest_veille_juicedata.py` | Trigger one-shot de l'ingestion gitingest + verif RAG (juicedata) | `rag_count`, `main` | 42 |
| `tools/nokido_opencode_web.py` | opencode (sst/opencode) servi en LOCAL et sous MOT DE PASSE pour le lanceur :7400 | `service_wcm`, `construire_commande`, `dossier_appdata`, `dossier_localappdata` *(+16)* | 507 |
| `tools/paste_clean.py` | clipboard HTML/text → token-economical Markdown | `read_clipboard`, `write_clipboard`, `html_to_md`, `post_process` *(+1)* | 171 |
| `tools/patch_ingest_repo_fail_open.py` | __FORGE_COLOR__ = "immunitaire/authz-routes" PATCH : `admin_ingest_repo` passe par le garde d'auth CENTRAL | `main` | 77 |
| `tools/relance_25_bruit_weak.py` | Reset 25 jobs BRUIT + WEAK (re-derivation same logic que audit) | `main` | 210 |
| `tools/run_gitingest.py` | Run gitingest on Nokido repo → docs/gitingest_nokido.txt | — | 47 |
| `tools/run_gitingest_index.py` | Indexe docs/gitingest_*.txt dans RAG | `main` | 73 |
| `tools/run_index_background.py` | Launch index_gitingest_rag.py in background, write log to logs/index_gitingest.log | — | 26 |
| `tools/watch_jobs_create_missing_chains.py` | Cree les 7 chain_nodes + agent_chain_context pour les watch_jobs pending qui n'ont aucun chain_node existant (jobs créés mais jamais initialisés) | `main` | 83 |
| `tools/watch_jobs_reset_49_pending.py` | Reset chain_nodes pour les 49 watch_jobs pending : status=pending sur TOUTES les steps (keywords->ingest) pour rerun complet avec patches keywords strict + refine strict | `main` | 64 |
| `tools/watch_jobs_reset_phantoms.py` | Reset les jobs 'completed' fantomes (colonnes vides) a 'pending' step=keywords | `main` | 52 |
| `tools/watch_jobs_reset_truly_empty.py` | Reset UNIQUEMENT les watch_jobs vraiment vides (pas de chunks reels en DB) | `main` | 125 |

## Graph/Connaissances

*42 modules · 12,665 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_ast_index.py` | Index AST code Nokido (ex forge_code_atlas) | `get_index`, `ego`, `summary` | 191 |
| `app/forge_callgraph_jit.py` | Call-graph fonction-level JIT (just-in-time) | `callees`, `definitions`, `ambiguite`, `callers` *(+1)* | 271 |
| `app/forge_coherence_gate.py` | Vérifie l'impact cross-fichiers avant d'écrire du code | `coherence_gate` | 76 |
| `app/forge_cost_net.py` | Learned Cost Function (LeCun AMI: Cost Module appris) | `CostNet`, `train`, `get_model`, `predict_cost` *(+1)* | 222 |
| `app/forge_edge_node.py` | __FORGE_COLOR__ = edge/edge-node-receiver NOEUD EDGE — receveur de world-vector COTE NOEUD (ferme la boucle broadcast->receive) | `serve`, `selftest`, `main` | 241 |
| `app/forge_extern_patterns.py` | Extraction AST de patterns de bibliothèques externes | `extract_file_ast`, `build_ast_compressed`, `query_extern_pattern`, `extract_patterns_from_gitingest` *(+1)* | 429 |
| `app/forge_graph_cve_propagation.py` | Propagation BFS d'une CVE dans le graphe de code | `propagate_cve` | 71 |
| `app/forge_graph_edge_scorer.py` | Calcul unifié scores d'edges dans le graphe de code | `score_edge`, `surprise_score`, `rank_edges_by_surprise` | 173 |
| `app/forge_graph_explorer.py` | Nokido Graph Explorer GUI ===================================================== Application web locale pour l'exploration interactive de graphes | `ping`, `status`, `get_graph`, `load_generator` *(+18)* | 1489 |
| `app/forge_graph_lru.py` | LRU+TTL cache pour GraphLinker | `GraphLRUCache`, `get_cache` | 62 |
| `app/forge_graph_ppr.py` | Personalized PageRank sur graphe de code | `ppr`, `top_k` | 68 |
| `app/forge_graph_studio.py` | Nokido Universal Graph Studio v1 ========================================================== Plateforme générale d'étude de graphes — indépendante du domaine | `GraphStats`, `GraphStudio` | 994 |
| `app/forge_graph_universal.py` | Nokido Universal Graph Engine v2 ============================================================ Module graph généraliste : cyber, documents, science, finance, médecine | `lru_cache_wrapper`, `GraphNode`, `GraphEdge`, `RAGVectorSource` *(+6)* | 603 |
| `app/forge_introspect.py` | UN verbe pour interroger le corps avant d'agir | `introspect`, `noter_consultation`, `consultation_recente`, `noter_edition` *(+4)* | 889 |
| `app/forge_knowledge_concierge.py` | le PORTIER de la recherche interne Nokido | `Kind`, `Source`, `RetrievalPlan`, `classify` *(+2)* | 184 |
| `app/forge_knowledge_distiller.py` | ================================== Distille la connaissance Nokido vers un nouveau projet | `extract_system_rules`, `extract_architecture_patterns`, `extract_best_practices`, `build_primer` *(+2)* | 220 |
| `app/forge_nlgraph_scorer.py` | LLM Scorer + Benchmark Runner for NLGraph ==================================================================== Separated from forge_nlgraph_runner.py for MCP buffer reasons | `LLMScorer`, `BenchReport`, `run_benchmark` | 237 |
| `app/forge_project_state.py` | Snapshot et diff de l'état du projet | `ProjectState`, `snapshot`, `diff`, `ForgeProjectStateGraph` | 198 |
| `app/forge_project_state_graph.py` | Software-creator project state as directed graph | `ModuleNode`, `ProjectStateGraph`, `scan_project` | 206 |
| `app/forge_repo_map.py` | Aider-style compressed repo map | `Symbol`, `parse_file_symbols`, `build_repo_map`, `render_markdown` *(+3)* | 347 |
| `app/forge_wasm_cervelet.py` | Double-cervelet WASM côté Nokido Python Pendant Cervelet Docker (WSL wasmedge :55555) tourne en parallèle, ce module fournit un wrapper Python pour: 1) Charger un .wasm simple via wasmtime-py (sandbox isolation) 2) Forwarder les requests embeddings vers le Cer | `run_wasm_deno`, `health_docker`, `spin_exe`, `health_spin` *(+5)* | 390 |
| `tools/forge_cve_nvd_download.py` | Download NVD CVE 2.0 feed and ingest into RAG embeddings.db | `fetch_recent`, `fetch_year`, `parse_vulns`, `ingest_to_rag` | 183 |
| `tools/forge_cve_osv_fallback.py` | CVE search with NVD primary + OSV.dev fallback | `search_cve`, `enrich_cve`, `batch_enrich` | 150 |
| `tools/forge_cve_propagation_graph.py` | CVE transitive propagation through dependency graph | `CVENode`, `DepNode`, `CVEPropagationGraph`, `load_from_osv` | 166 |
| `tools/forge_edge_scoring.py` | Unified edge scoring for Nokido knowledge graph | `semantic_score`, `temporal_score`, `trust_score`, `cooccurrence_score` *(+3)* | 198 |
| `tools/forge_graph_lru_expand.py` | Graph engine with LRU cache + Personalized PageRank (PPR) | `GraphLRUCache`, `personalized_pagerank`, `top_k_by_ppr`, `ExpandedGraphEngine` | 161 |
| `tools/forge_index_extra_langs.py` | Indexe le code TypeScript / Rust dans le RAG | `main` | 52 |
| `tools/forge_knowledge_overlap.py` | le savoir candidat est-il DEJA digere ? DETECTEUR DE NOUVEAUTE, place AVANT l'ingestion | `normaliser`, `hash_texte`, `requete_fts`, `blob_vers_vecteur` *(+8)* | 393 |
| `tools/forge_knowledge_pack.py` | distribute the RAG DB efficiently (not the raw 16 GB) | `export_pack`, `import_pack`, `rebuild_from_source`, `main` | 216 |
| `tools/forge_knowledge_pack_export.py` | Export Nokido code knowledge pack | `export_pack`, `main` | 259 |
| `tools/forge_knowledge_pack_import.py` | Import Nokido code knowledge pack | `import_pack`, `main` | 230 |
| `tools/forge_library_shifter.py` | Permutation chirurgicale de librairies via AST ========================================================================= Remplace les librairies standard par des alternatives haute-performance validées par benchmark + tests de régression Cerberus | `LibraryShifter` | 267 |
| `tools/forge_mtls_ca.py` | autorite de certification CLIENTE pour le mTLS Nokido | `init_ca`, `issue`, `verify`, `main` | 251 |
| `tools/forge_organ_edges.py` | ARETES du corps : part_of et connected_to, puis « si cet organe tombe, qu'est-ce qui meurt en aval » | `build`, `downstream`, `main` | 264 |
| `tools/forge_reachability_ledger.py` | Phase 8 : registre d'ATTEIGNABILITE | `index_references`, `modules_presents`, `classer_vivant`, `classer_disparu` *(+2)* | 359 |
| `tools/forge_signal_graph.py` | GRAPHE DE SIGNAUX resolu sur l'AST + la config parsee | `build_graph`, `asymetries` | 216 |
| `tools/forge_skill_capability_graph.py` | Graphe de CAPACITES — ce qu'un skill EXIGE, ce qu'il PRODUIT | `Fait`, `Effet`, `Capacite`, `capacite` *(+6)* | 389 |
| `tools/forge_surgical_patcher.py` | Patch chirurgical AST (Pass@1) ================================================================ Moteur de transformation sans regex ni escape hell | `preprocess_py2_text`, `SurgicalPatcher` | 412 |
| `tools/forge_syspath_cartography.py` | pourquoi ce `sys.path` est-il la ? P4.2a a mesure que le corps s'importe A PLAT : 4 449 `import forge_*` et 1 186 `sys.path.insert` | `Site`, `modules_depot`, `classer_source`, `cartographier_textes` *(+2)* | 555 |
| `tools/forge_treesitter_validate.py` | validation structurelle PRÉ-write (multi-langage) | `validate`, `validate_file`, `main` | 126 |
| `tools/forge_warpgrep.py` | recherche de code hybride pour la LOCALISATION | `build_repomap`, `warpgrep_locate` | 195 |
| `tools/nokido_graph_server.py` | Launcher forge_graph_explorer sur port 7420 | `main` | 62 |

## Reseau/Distribue/Sync

*39 modules · 8,486 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_cardiac_node.py` | NOEUD SINUSAL : le corps n'a qu'UN rythme, et il descend | `innervation`, `periode_pour`, `systole`, `lire` *(+1)* | 252 |
| `app/forge_network_dispatch.py` | Registre dynamique 5 topologies × 3 modes ====================================================================== Topologies: UNI Unicast 1→1 direct, adressé MUL Multicast 1→N groupe abonnés d'un groupe/tag BRD Broadcast 1→tous segment complet ANY Anycast 1→1/N | `get_schema`, `dispatch` | 275 |
| `app/forge_network_logger.py` | Bus de logging centralisé Nokido v2.0 ================================================================ v2.0 : Utilise forge_mcp_security.audit() comme backend natif (mcp_audit.log — append-only, non modifiable par l'IA) plutôt qu'une table SQLite séparée | `NetworkChannel`, `Direction`, `net_log`, `net_subscribe_sse` *(+10)* | 586 |
| `app/forge_nokido_packet.py` | Nokido Packet Header v1.0 ===================================================== Format : LF[S][D][R][P][AAA] | `LFPacket`, `parse_header`, `make_header`, `reject_policy` *(+5)* | 266 |
| `app/forge_p2p_protocol.py` | Interface abstraite pour backend P2P RAG ================================================================= Stub d'architecture pour le branchement futur libsql/cr-sqlite P2P | `P2PBackend`, `NullP2PBackend`, `get_p2p_backend` | 86 |
| `app/forge_peer_discovery.py` | peer discovery by tag/purpose (relaydeck P2) | `roster`, `select`, `set_labels`, `main` | 142 |
| `app/forge_policy_net.py` | Policy Network (Hassabis / AlphaZero pillar) | `PolicyNet`, `train`, `get_model`, `propose_action_emb` | 215 |
| `app/forge_ring_buffer.py` | Ring Buffer Rewind pattern (Phase 37, 2026-05-25) | `Event`, `start_recording`, `push`, `dump_window` *(+2)* | 138 |
| `app/forge_sovereign_mapper.py` | Souverainete Symmetrique | `SovereignContextMapper` | 111 |
| `tools/create_sample_network_vsdx.py` | Genere un fichier .vsdx de demonstration pour le dossier Sample Network | `build` | 102 |
| `tools/create_scenario_vsdx.py` | Genere un fichier .vsdx de demonstration croisant Excel + Visio + Inventaire Physique | `build` | 181 |
| `tools/fbxwol.py` | demande a la Freebox d'emettre le paquet magique sur le LAN | `main` | 137 |
| `tools/forge_a2a_card.py` | Agent Card A2A GENEREE depuis l'etat vivant — jamais un fichier statique | `etats`, `carte`, `main` | 198 |
| `tools/forge_a2a_server.py` | Serveur A2A — Tier 1 : `message/send`, `tasks/get`, `tasks/cancel` | `admission`, `traiter`, `serve`, `main` | 249 |
| `tools/forge_acp_adapter.py` | PoC : Nokido comme backend AGENT via ACP (Agent Client Protocol), à côté du serveur MCP | `handle`, `main` | 317 |
| `tools/forge_acp_client.py` | Nokido comme CLIENT/HOST ACP : pilote un agent-CLI externe parlant Agent Client Protocol (ex: `gemini --experimental-acp`) | `ACPClient`, `ask`, `main` | 448 |
| `tools/forge_acp_server.py` | ACP agent-side adapter: exposes the Nokido hub as an Agent Client Protocol (ACP) agent over stdio (NDJSON, JSON-RPC 2.0) | `TurnContext`, `EchoBrain`, `HubBrain`, `StreamingBrain` *(+3)* | 648 |
| `tools/forge_ble_buddy.py` | Nokido = "Hardware Buddy" BLE de Claude Desktop (Couche 7, GOUVERNÉ) | `govern`, `main` | 154 |
| `tools/forge_claude_desktop_sync.py` | IaC Claude Desktop (MCP + mode dev), 100% fichier (headless) | `sync_mcp`, `apply_dev_keys`, `main` | 94 |
| `tools/forge_cross_fs.py` | Skill cross_platform_fs ================================================= Permet de déplacer/copier des fichiers entre l'hôte Windows et les environnements isolés (Docker, WSL) | `copy_to_docker`, `copy_from_docker`, `copy_to_wsl` | 84 |
| `tools/forge_demo_netcfg_topology.py` | Playwright headed sur netcfg-agent :7500 | `main` | 85 |
| `tools/forge_dt_router_wire.py` | Wire Nokido DT router decisions to Deno nervous system | `DTRouterWire`, `mock_routing_decision` | 157 |
| `tools/forge_faiss_sidecar.py` | P1 hub_concurrency : vector-search en PROCESS SÉPARÉ | `load_index`, `serve`, `search_remote`, `sidecar_alive` *(+3)* | 277 |
| `tools/forge_freebox.py` | client Freebox OS souverain (LAN pur, zero cloud) | `FreeboxError`, `pair`, `session`, `cmd_status` *(+9)* | 340 |
| `tools/forge_gemini_models_sync.py` | Confronte les modeles Gemini declares dans le routeur a ceux qui EXISTENT | `modeles_declares`, `catalogue`, `confronter`, `essayer` *(+1)* | 169 |
| `tools/forge_ports.py` | registre CANONIQUE des ports reseau Nokido + audit/logging | `probe`, `owner`, `reserved_collisions`, `for_service` *(+4)* | 180 |
| `tools/forge_qdrant_fill.py` | Remplissage de la collection Qdrant depuis embeddings.db | `fill`, `main` | 96 |
| `tools/forge_qdrant_sidecar.py` | Module Sidecar Qdrant (SSoT RAG Nokido 2026 - Multi-CLI Safe) | `DiskPressureError`, `check_disk_pressure`, `SovereignFileLock`, `get_qdrant_client` *(+9)* | 636 |
| `tools/forge_qdrant_sync_daemon.py` | sync CONTINUE SQLite -> Qdrant (pattern outbox) | `init_schema`, `drain_once`, `run`, `main` | 182 |
| `tools/forge_route_async_bloquante.py` | rendre au serveur ses fils d'execution | `analyser`, `convertir`, `executer`, `main` | 177 |
| `tools/forge_ssh_ops.py` | Executeur SSH souverain — pilote un hote du LAN depuis le contexte trusted | `cmd_keygen`, `cmd_shell`, `cmd_put`, `main` | 141 |
| `tools/forge_sync_branche.py` | integrer les commits distants AVANT publication | `decider_sync`, `main` | 156 |
| `tools/forge_tunnel_client_launch.py` | Lance le relais MCP d'OpenAI avec sa cle lue au COFFRE, jamais depuis un fichier | `magasin`, `binaire_par_defaut`, `config_par_defaut`, `lire_cle` *(+4)* | 163 |
| `tools/forge_vm_dns.py` | accès TRUSTED à la VM StackDNS (AdGuardHome) pour debug/unblock | `main` | 344 |
| `tools/kaggle_sync.py` | Synchronisation notebook + dataset Kaggle ================================================================= Pousse le notebook ET le dataset en une seule commande | `inject_version`, `push_notebook`, `push_dataset` | 133 |
| `tools/nokido_netmap.py` | Nokido Network Map | `parse_scans`, `apply_updates`, `node_pos`, `draw_topology` *(+2)* | 409 |
| `tools/notify_gemini_sync.py` | Envoie un message de sync a Gemini via agent_notify | — | 28 |
| `tools/patch_corrigibility_wire.py` | Patcher one-shot IDEMPOTENT : câble la garde corrigibilité dans le dispatch (forge_mcp_registry.py = CRITICAL_FILE, governed_edit refuse -> trusted_script) | `main` | 61 |
| `tools/watch_jobs_reset_chain_nodes.py` | Reset chain_nodes pour les 45 watch_jobs reset (status=pending+step=keywords) : status=pending pour search/refine/crawl/store/ingest, keep keywords+verify_kw completed | `main` | 69 |

## Interface/UI (peau/expression)

*20 modules · 7,678 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_vitals_tools.py` | __FORGE_COLOR__ = interface/vital-signals SIGNAUX VITAUX — l'anatomie cognitive de Nokido rendue LISIBLE (doc interface §2/§4 P0) | `subjective_tempo`, `affective_state`, `phenomenal_flow`, `parietal_percept` *(+11)* | 212 |
| `tools/apply_nokido_logo.py` | Applique le pack logo Nokido biomimetique dans web_hub/static | `main` | 32 |
| `tools/forge_design_extract.py` | Passe 1 du portage du design system Nokido | `main` | 89 |
| `tools/forge_font_vendor.py` | vendore les webfonts du portail web_hub :7400 en local | `main` | 98 |
| `tools/forge_tui_sonde.py` | sonde HEADLESS des TUI Textual de Nokido (Pilot, aucun terminal) | `texte_rendu`, `marqueurs`, `sonder_tout`, `sonder_chemin_reel` *(+1)* | 411 |
| `tools/forge_tui_textual.py` | la TUI Textual de Nokido, branchee sur le REEL | `collecter`, `instantane`, `main` | 195 |
| `tools/forge_ui_campaign.py` | campagne VALIDATION GRAPHIQUE web_hub :7400 | `texte_porte_valeur`, `mot_d_erreur`, `est_rechargement`, `vue_hub` *(+17)* | 1854 |
| `tools/forge_ui_coherence.py` | une tuile ment-elle sur l'etat du systeme ? Ne verifie PAS que l'UI est jolie : verifie qu'elle DIT VRAI | `analyser`, `main` | 152 |
| `tools/forge_ui_contrat_etats.py` | TEMOIN : le Hub distingue-t-il LOADING, DATA et ERROR ? __FORGE_COLOR__ declare plus bas (le census lit la premiere ligne ancree, pas la docstring) | `juger`, `main` | 386 |
| `tools/forge_ui_delier_cdn.py` | delier les pages servies de tout CDN externe | `fichier_local_pour`, `delier`, `pages`, `executer` *(+1)* | 155 |
| `tools/forge_ui_design_cover.py` | DÉPORTÉ : génère TOUS les composants design_handoff via la moulinette | `main` | 77 |
| `tools/forge_ui_manifest.py` | le MANIFEST vivant de l'interface (keystone) | `manifest`, `main` | 276 |
| `tools/forge_ui_moulinette.py` | moulinette UI souveraine (économie tokens massive) | `skeleton_from_schema`, `schema_from_spec`, `fill_holes`, `form_from_jsonschema` *(+2)* | 299 |
| `tools/forge_ui_nervous_census.py` | le cablage REEL des interfaces, ELEMENT par element | `invisible_agent`, `classer`, `signature_page`, `pages_uniques` *(+5)* | 929 |
| `tools/forge_ui_repo_cover.py` | couvre TOUT le dépôt : 1 form UI fidèle par tool hub | `generate`, `main` | 71 |
| `tools/forge_ui_sweep.py` | BALAYAGE moulinette UI sur TOUT le dépôt (déterministe, 0 token) | `main` | 76 |
| `tools/forge_ui_temoin.py` | UI_ACCEPTANCE_WITNESS — rendre lisible ce qu'une campagne UI a reellement etabli | `construire` | 200 |
| `tools/forge_ui_vitals_cover.py` | MOULINETTE des SIGNAUX VITAUX (couvre le code cognitif) | `generate`, `design_handoff`, `main` | 149 |
| `tools/nokido_tray.py` | Icône tray Windows Nokido ============================================= Lance en arrière-plan au démarrage Windows | `lancer_panneau`, `main` | 593 |
| `tools/nokido_tui.py` | v2 — TUI multi-CLI user (ring 0) Phases 1-6 complètes de docs/roadmap_tui_multi_cli.md | `load_token`, `hub_notify`, `fetch_recent`, `status_services` *(+9)* | 1424 |

## SWE-bench

*5 modules · 741 lines*

| Module | Definition | Public API | LOC |
|---|---|---|---|
| `app/forge_pydantic_tools.py` | schemas Pydantic pour tool calls SWE-bench | `list_tools`, `validate_args`, `call_tool_validated` | 154 |
| `app/forge_swe_ast_whole_func.py` | SWE-bench améliorations Phase 1 : robustesse output via AST whole-function rewrite + linter gate | `extract_function`, `parse_validate`, `lint_function`, `apply_ast_replacement` *(+2)* | 323 |
| `app/forge_swe_multifile.py` | SWE-bench Phase 2 : multi-fichiers via repomap + AST | `build_repomap`, `find_impact`, `generate_multifile_patch`, `main` | 208 |
| `tools/forge_swe_smoke_launch.py` | Lance le smoke SWE-bench n=3 DÉTACHÉ (best-of-N claude_cli/gemini_cli/groq + multivec) | — | 29 |
| `tools/forge_swe_smoke_restart.py` | Kill le smoke hung + relance SANS multivec (le multivec indexe tout le clone + resume LLM/fonction = hang sur gros repo) | — | 27 |

## Modules without a docstring — measured gaps

These modules expose no definition. Nothing is invented for them:
adding a module docstring will make its definition appear here at
the next generation.

| Module | Public API | LOC |
|---|---|---|
| `app/forge_mcp_registry.py` | `check_unicode_concealment`, `resolve_tool_name`, `classer_retour_intent`, `enforce_explanation` | 9335 |
| `app/Nokido.py` | `create_settings`, `run_ssh`, `get_orchestrator`, `looks_like_shell_command` | 4905 |
| `app/forge_agent_proxy.py` | `Provider`, `ClaudeOpenRouter`, `ClaudeGitHub`, `Gemini` | 3791 |
| `app/forge_agents.py` | `AgentRole`, `IntentRouter`, `ModelBenchmark`, `ModelBenchmarker` | 3401 |
| `app/forge_code.py` | `DangerLevel`, `DangerCheck`, `DangerGuard`, `danger_confirmation_message` | 2751 |
| `app/forge_rag_engine.py` | `RAGEngine`, `get_rag`, `run_full_cycle` | 2382 |
| `app/forge_llm_router.py` | `chaine_active`, `repli_oauth_autorise`, `repli_oauth`, `ProviderSlot` | 2076 |
| `app/forge_core_models.py` | `AgentType`, `TaskPriority`, `TTLCache`, `ErrorManager` | 1664 |
| `app/mcp_server_tools.py` | `rag_search`, `rag_ingest_text`, `rag_stats`, `swarm_status` | 1659 |
| `app/brain_worker.py` | `Embedder`, `Generator`, `security_audit`, `analyze_code` | 1614 |
| `app/nokido_core.py` | `CollabMode`, `SecurityRing`, `CoreState`, `StateManager` | 1532 |
| `app/forge_mixin_patch.py` | `shutdown_onnx_backend`, `PatchMixin` | 1407 |
| `app/forge_web_service.py` | `hub_health`, `hub_metrics`, `hub_live_bridge_json`, `hub_live_tasks` | 1342 |
| `app/forge_at_dispatch.py` | `handle_at_ssh`, `handle_at_scan`, `handle_at_ids`, `handle_at_agentic` | 1327 |
| `tools/forge_task_executor.py` | `ensure_lease_schema`, `touch_progress`, `reclaim_expired`, `est_refus_du_modele` | 1306 |
| `app/forge_integrity.py` | `IntegrityRing`, `is_at_least`, `attenuer_ou_refuser`, `CapabilityToken` | 1278 |
| `app/forge_runtime.py` | `BrainClient`, `OnnxEmbedder`, `OnnxGenerator`, `init_onnx_backend` | 1222 |
| `app/forge_handlers.py` | `do_scan`, `do_scan_basic`, `run_collaboration`, `run_comite` | 1194 |
| `app/forge_rag_truth.py` | `TruthState`, `ValidationSignature`, `est_valide_a`, `filtrer_as_of` | 1193 |
| `app/forge_self_correction.py` | `preflight_check`, `preflight_check_verbose`, `anchor_error`, `anchor_solution` | 1183 |
| `app/forge_ssh.py` | `PTYTerminal`, `SSHWizardScreen`, `handle_ssh`, `handle_set_ssh_mode` | 1183 |
| `app/forge_swarm_team.py` | `Participant`, `SwarmTeam`, `LeadOrchestrator`, `get_team` | 1167 |
| `tools/forge_llama_keeper.py` | `tick`, `main` | 1116 |
| `app/patch.py` | `python_interpreter`, `file_read`, `file_write`, `file_explore` | 1067 |
| `tools/gemini_poll_daemon.py` | `log`, `load_token`, `mcp_call`, `poll_notifications` | 1049 |
| `app/forge_semantic_firewall.py` | `PreFlightResult`, `PostFlightResult`, `redact_tool_output`, `redact_text` | 1044 |
| `tools/forge_services_launcher.py` | `port_is_listening`, `http_ok`, `log`, `wait_for_port` | 1044 |
| `app/forge_chain_executor.py` | `ChainExecutor` | 964 |
| `app/forge_mixin_ui.py` | `init_onnx_backend`, `init_registry`, `UiMixin` | 961 |
| `app/forge_agent_roles.py` | `AgentRole` | 929 |
| `app/forge_versioning.py` | `SurgeryResult`, `CodeSurgeon`, `ForgeSaveOrchestrator`, `VersionManager` | 926 |
| `app/skilltree.py` | `detect_skills`, `get_dependencies`, `get_subtree`, `SkillState` | 914 |
| `app/forge_goap.py` | `SubGoal`, `PlanTree`, `GOAPError`, `GoalPlanner` | 911 |
| `app/forge_health.py` | `CheckResult`, `check_imports`, `check_registry`, `check_database` | 911 |
| `app/forge_ollama_bridge.py` | `build_capability_string`, `build_late_binding_doc`, `OllamaBridge`, `get_bridge` | 900 |
| `app/forge_commit_intel.py` | `risk_level`, `CommitIntel`, `get_bug_history`, `analyze_commit` | 868 |
| `tools/multi_llm_daemon.py` | `call_ollama`, `call_llamacpp`, `call_lmstudio`, `call_groq` | 851 |
| `app/forge_orchestrator_scaller.py` | `Recommendation`, `scan`, `scan_and_store`, `list_pending` | 842 |
| `app/forge_hub_handlers.py` | `handle_ci_remote`, `handle_workflow_hub`, `tui_auto_patch`, `hub_notification_poll` | 839 |
| `app/forge_startup.py` | `load_last_assignment`, `save_last_assignment`, `auto_select_models`, `main` | 815 |
| `app/forge_network.py` | `Device`, `NetworkDiscovery`, `MiniIDSAgent`, `SwitchResult` | 808 |
| `app/forge_snapshot.py` | `get_machine_key`, `derive_backup_salt`, `PreFlightError`, `preflight_check` | 808 |
| `app/forge_openrouter.py` | `budget_status`, `get_daily_usage`, `generate_code`, `generate_code_swarm` | 805 |
| `app/forge_dispatch_ai.py` | `dispatch_ai` | 790 |
| `app/forge_dataset_sync.py` | `gen_is_at_least_matrix`, `gen_integrity_rings`, `gen_integrity_edge_cases`, `gen_behavior_gold` | 779 |
| `app/forge_handler_ci.py` | — | 779 |
| `app/forge_npu.py` | `EP`, `NPUManager`, `OnnxEmbedderNPU`, `get_npu_manager` | 769 |
| `app/forge_settings.py` | `debug_log`, `Settings`, `get_db_path`, `create_settings` | 763 |
| `app/forge_nlu.py` | `IntentVote`, `FeatureExtractor`, `NaiveBayesRouter`, `CorrectionEntry` | 759 |
| `app/forge_db_path.py` | `authority_switch_path`, `authority_db_defaut`, `authority_switch_actif`, `authority_path` | 725 |
| `app/forge_interaction_test.py` | `AgentMessage`, `InteractionResult`, `scenario_ping_pong`, `scenario_debate` | 724 |
| `app/forge_prompt_guard.py` | `InjectionResult`, `ConflictReport`, `detect_injection`, `check_conflict` | 716 |
| `app/forge_web.py` | `is_web_search_enabled`, `toggle_web_search`, `WebSearchEngine`, `get_web_engine` | 710 |
| `app/forge_task_bus.py` | `ensure_schema`, `create_task`, `inject_rag_context`, `claim_task` | 696 |
| `app/forge_git_historian.py` | `CommitIntel`, `get_last_processed`, `extract_commits`, `index_commits` | 694 |
| `app/forge_rag_warmup.py` | `rag_self_warmup`, `index_self_in_rag`, `warmup_rag` | 690 |
| `app/forge_commands.py` | `safe_write`, `dispatch_at` | 660 |
| `app/forge_ui_widgets.py` | `AgentType`, `AgentSelector`, `MetricsPanel`, `SkillNode` | 648 |
| `app/forge_timecode.py` | `now_iso`, `stamp_line`, `stamp_row`, `configure_logging` | 639 |
| `app/forge_app_context.py` | `get_rag`, `get_settings`, `get_ssh`, `get_version_manager` | 623 |
| `app/forge_conv_sanitizer.py` | `sign_message`, `verify_message`, `sanitize_for_agent`, `get_internal_logs` | 615 |
| `app/forge_mcp_security.py` | `SecretGuardViolation`, `check_db_quality`, `safe_path`, `validate_run_action` | 608 |
| `app/mcp_bridge.py` | `handle_list_tools`, `handle_call_tool`, `main` | 608 |
| `app/forge_resonance_filter.py` | `resonance_check`, `create_adr` | 606 |
| `app/forge_swarm.py` | `SwarmState`, `broadcast`, `make_broadcast_listener`, `SwarmStateMachine` | 604 |
| `app/forge_promotion_queue.py` | `PromotionItem`, `restore_from_db`, `PromotionOrchestrator`, `get_orchestrator` | 602 |
| `app/forge_dispatch_network.py` | `handle_scan`, `handle_ids`, `handle_chain`, `handle_switch` | 598 |
| `app/mcp_nr.py` | `run_fast`, `run_all` | 582 |
| `app/forge_graph_linker.py` | `SourceIndex`, `ASTScanner`, `GraphLinker` | 581 |
| `app/forge_env_crypt.py` | `encrypt_value`, `decrypt_value`, `load_secrets`, `set_secret` | 568 |
| `app/forge_heartbeat.py` | `beat_daemon`, `demarrer_pouls_service_http`, `Cadence`, `beat` | 567 |
| `app/forge_rag_store.py` | `MarkerConverter`, `MarkdownChunker`, `QdrantConfig`, `QdrantStore` | 558 |
| `app/forge_handler_rag.py` | — | 553 |
| `app/forge_pty.py` | `configure`, `get_pty_class` | 552 |
| `app/forge_arbitrator.py` | `ConfidenceReport`, `evaluate_confidence`, `build_skeleton_prompt`, `DispatchResult` | 548 |
| `app/forge_llm.py` | `AgentType`, `ollama_parallel`, `IntentClassifier`, `looks_like_shell_command` | 548 |
| `app/forge_tool_forger.py` | `forge_forge_tool`, `forge_call_dynamic`, `forge_list_dynamic_tools` | 546 |
| `app/forge_ingest_self.py` | `force_self_ingestion` | 544 |
| `app/forge_npu_embedder.py` | `detect_hardware`, `embed_via_probe`, `get_embed`, `get_npu_embedder` | 539 |
| `app/forge_services.py` | `ServiceType`, `Protocol`, `ServiceStatus`, `ServiceEndpoint` | 529 |
| `app/forge_anti_ia_traps.py` | `TrapIndicator`, `ValidationResult`, `StaticTrapClassifier`, `forge_validate_challenge` | 527 |
| `app/forge_cognitive_router.py` | `build_proactive_system`, `prune_rag_context`, `route_task` | 521 |
| `app/forge_events.py` | `on_button_pressed`, `poll_tui_notifications`, `action_copy_full_log`, `on_list_view_selected` | 516 |
| `app/forge_prefect.py` | `PrefectManager` | 513 |
| `app/forge_autonomous_orchestrator.py` | `DAGNode`, `DAGGraph`, `DAGBuilder`, `OneMCPMultiplexer` | 498 |
| `app/forge_knowledge_harvester.py` | `KnowledgeEntry`, `ReasoningExtractor`, `TemplateGenerator`, `SilentBenchmark` | 487 |
| `app/forge_event_stream.py` | `Event`, `EventStream`, `AgentLoop`, `gemini_poll_to_event` | 483 |
| `app/forge_ghost_router.py` | `detect_task`, `GhostRouter`, `get_router`, `ghost_generate` | 481 |
| `app/forge_git_egress.py` | `reconstruct`, `load_manifest`, `resolve_profile`, `scan_files` | 476 |
| `app/forge_logging.py` | `ecrire_sans_bloquer`, `debug_log`, `PoseNonBloquante`, `installer_logging_non_bloquant` | 475 |
| `app/forge_ingestion_pipeline.py` | `parse_gitingest_file`, `filter_files`, `compute_centrality`, `score_files` | 474 |
| `app/forge_auto_pilot.py` | `MMapReader`, `AutoPilot`, `start_autopilot`, `stop_autopilot` | 469 |
| `app/forge_unified_discovery.py` | `refine_and_anchor`, `unified_discovery` | 467 |
| `app/forge_rag_qualify.py` | `qualify_chunk`, `migrate_qualify_all`, `trust_weight`, `apply_trust_weight` | 456 |
| `app/forge_recursive_debugger.py` | `parse_errors`, `make_diff`, `StepResult`, `DebugIteration` | 449 |
| `app/forge_gemini_bridge.py` | `GeminiBridge`, `gemini_ask`, `run_mode_gemini_ping`, `get_gemini_bridge` | 445 |
| `app/forge_github_mcp_connector.py` | `GitHubMCPSession`, `GitHubMCPBridge`, `get_bridge`, `github_mcp_status` | 445 |
| `app/forge_safe_integration.py` | `log`, `version_key`, `check_syntax`, `get_version_str` | 443 |
| `app/forge_hot_ingest.py` | `hot_ingest_file`, `hot_ingest_url`, `HotFolderWatcher`, `get_watcher` | 441 |
| `app/forge_registry.py` | `ForgeRegistry`, `get_registry` | 441 |
| `app/forge_mesh_memory.py` | `MeshMemory`, `get_mesh`, `mesh_status` | 426 |
| `app/forge_routing.py` | `build_router`, `reset_router`, `router_status` | 422 |
| `app/forge_memory.py` | `MemSnapshot`, `MemoryMonitor`, `MemoryProfiler`, `MemoryOptimizer` | 417 |
| `app/forge_triad_authority.py` | `TriadStep`, `step_audit`, `step_plan`, `step_execute` | 416 |
| `app/forge_handler_advanced.py` | `handle_optimize_core`, `handle_sprint_refactor`, `handle_app_factory`, `handle_multi_llm` | 415 |
| `app/forge_rag_cache.py` | `RagCache`, `get_rag_cache`, `warm_rag_cache_async` | 414 |
| `app/shredder.py` | `build_import_catalog`, `collect_names_used`, `resolve_imports`, `find_nodes` | 414 |
| `app/forge_loop.py` | `post_loop_safe_check`, `propagate_patch`, `apply_suggestion` | 406 |
| `app/forge_state_manager.py` | `EventBus`, `StateManager`, `get_state_manager` | 406 |
| `app/hardware/allocator.py` | `get_memory_state`, `detect_best_ep`, `compute_optimal_config`, `apply_config` | 401 |
| `app/forge_rag_index_app.py` | `index_file`, `index_app_dir` | 399 |
| `app/forge_pipeline_node.py` | `NodeStatus`, `NodeResult`, `Ring2ADRValidator`, `MMapBuffer` | 393 |
| `app/forge_state.py` | `SharedState`, `publish_health`, `read_health`, `crystallize` | 392 |
| `app/forge_intent_parser.py` | `normaliser`, `racine_verbe`, `verbes_ordonnes`, `ParsedIntent` | 385 |
| `app/forge_agent_authority.py` | `acquire_master_dev`, `release_master_dev`, `force_transfer_master`, `set_orchestrator` | 384 |
| `tools/research/forge_onnx_genai.py` | `get_model`, `is_available`, `onnxgenai_call`, `onnxgenai_stream` | 384 |
| `app/forge_hub_client.py` | `entetes_organe`, `HubClient` | 380 |
| `app/forge_handler_patch.py` | `classify_with_cmd` | 379 |
| `app/forge_mixin_rag.py` | `RAGMixin` | 379 |
| `app/forge_router_gateway.py` | `GenerateRequest`, `AcquireRequest`, `ReleaseRequest`, `TransferRequest` | 369 |
| `app/forge_startup_logger.py` | `BootStep`, `StartupLogger`, `get_boot_logger`, `boot_step` | 369 |
| `app/forge_docker_supervisor.py` | `DockerSupervisorError`, `DockerSupervisor`, `get_supervisor` | 364 |
| `tools/audit_rfc_compliance.py` | `run_audit`, `main` | 363 |
| `tools/bench/forge_dataset_loader.py` | `fetch_url`, `download_tech_docs`, `download_code_pairs`, `download_sysadmin_docs` | 363 |
| `app/forge_handler_agents.py` | `run_collaboration`, `run_comite` | 356 |
| `app/forge_gui_debug.py` | `gui_debug_log`, `gui_debug_clear`, `patch_app_for_debug` | 354 |
| `app/forge_remediation.py` | `check_embed_backlog`, `check_db_contention`, `check_orphans`, `check_phantom_slots` | 351 |
| `app/forge_mmap_context.py` | `AgentContext`, `AgentSnapshot`, `dispatch_with_resonance` | 350 |
| `app/forge_litellm_bridge.py` | `LiteLLMBridge`, `get_litellm_bridge`, `ask` | 348 |
| `app/bootstrap.py` | `run_code`, `run_file` | 347 |
| `app/forge_kaggle_bridge.py` | `KaggleBridge`, `get_bridge`, `kaggle_status` | 342 |
| `app/forge_litellm_connector.py` | `is_proxy_alive`, `complete`, `propose_via_connector`, `start_proxy` | 334 |
| `app/forge_sentinel.py` | `SentinelResult`, `validate_action`, `sentinel_guard`, `is_dev_mode` | 326 |
| `app/forge_disco.py` | `handle_disco` | 324 |
| `app/forge_distiller.py` | `Distiller`, `get_distiller`, `distill`, `ring_from_token` | 324 |
| `app/forge_self_refinement.py` | `RefinementTurn`, `RefinementResult`, `thought_interceptor`, `forge_self_refine` | 323 |
| `app/forge_persona_engine.py` | `PersonaEngine`, `get_persona_engine`, `nokido_system` | 320 |
| `app/forge_user_layer.py` | `generate_totp_secret`, `totp_now`, `verify_totp`, `totp_provisioning_uri` | 317 |
| `app/live_bridge.py` | `LiveBridge` | 317 |
| `app/forge_ollama.py` | `ollama_call`, `ollama_stream` | 314 |
| `app/forge_code_guard.py` | `DangerLevel`, `DangerCheck`, `DangerGuard`, `danger_confirmation_message` | 313 |
| `app/hardware/mem_watchdog.py` | `MemWatchdog`, `get_watchdog`, `mem_checkpoint` | 309 |
| `app/forge_vec_ledger.py` | `hash_vector`, `sign_hash`, `verify_vector`, `sign_and_log` | 304 |
| `app/forge_env_sync.py` | `sync_env`, `env_report` | 292 |
| `app/forge_ollama_memory.py` | `OllamaMemoryManager`, `get_mem_mgr` | 291 |
| `app/forge_metrics.py` | `LLMMetric`, `MetricsCollector`, `get_collector` | 283 |
| `app/forge_mermaid_gen.py` | `validate_mermaid`, `generate_mermaid`, `generate_mermaid_async`, `svc_generate_mermaid` | 279 |
| `app/hardware/idle_watchdog.py` | `IdleWatchdog` | 276 |
| `app/forge_agentic_engine.py` | `SkillEntry`, `AgenticEngine`, `EvolutionOrchestrator` | 270 |
| `app/forge_handler_build.py` | `build_with_retry_loop`, `execute_build_goal`, `handle_build_new_app` | 269 |
| `app/_internal/_sandbox_at_real.py` | `ATTestApp`, `run` | 268 |
| `app/forge_mixin_ai.py` | `AiMixin` | 267 |
| `tools/nokido_mcp_proxy.py` | `ChatMessage`, `ChatCompletionRequest`, `get_local_ollama_models`, `initialize_model_mapping` | 265 |
| `app/semantic_scanner.py` | `extract_nodes`, `ollama_keywords`, `scan_file`, `run` | 259 |
| `app/forge_agentic.py` | `handle_agentic`, `handle_evolve` | 257 |
| `app/forge_meta_evolution.py` | `DaemonHealth`, `MetaSignal`, `forge_meta_scan`, `forge_meta_suggest` | 256 |
| `app/forge_version.py` | `get`, `label`, `semver`, `get_from_manager` | 254 |
| `tools/bench/forge_knowledge_distiller.py` | `extract_system_rules`, `extract_architecture_patterns`, `extract_best_practices`, `build_primer` | 254 |
| `app/forge_code_surgery.py` | `SurgeryResult`, `ts_surgery`, `CodeSurgeon` | 246 |
| `app/laforge_tui/laforge_tui.py` | `NokidoTUI` | 242 |
| `app/forge_agent_hardware.py` | — | 241 |
| `app/forge_renal_clearance.py` | `FiltrationRule`, `FiltrationResult`, `filter_table`, `run_cycle` | 238 |
| `app/forge_hub_worker.py` | `HubWorkerClient`, `get_worker`, `run_in_worker` | 236 |
| `app/forge_parity_gate.py` | `Severity`, `Finding`, `red`, `yellow` | 234 |
| `app/web_hub/forms/run_form.py` | `render_run_form` | 233 |
| `app/forge_hippocampus.py` | `Hippocampus`, `lessons_consolidate`, `forge_distill_session`, `forge_lessons_consolidate` | 230 |
| `app/forge_codeberg_sync.py` | `setup_remote`, `sync_now`, `sync_if_auto`, `status` | 227 |
| `app/netcfg/views.py` | `get_db`, `netcfg_index`, `get_inventory`, `post_preview` | 224 |
| `app/forge_sandbox.py` | `SandboxResult`, `SafeRunner`, `AgentHistory`, `OllamaCodeGen` | 223 |
| `app/legacy/snif.py` | `Device`, `NetworkDiscovery` | 223 |
| `tools/gemini_cli_daemon.py` | `run_daemon` | 222 |
| `app/forge_code_loops.py` | `ErrorMemory`, `LoopIteration`, `LoopState`, `BaseLoop` | 220 |
| `tools/forge_embed_eco.py` | `embed`, `audit`, `verify`, `drain` | 215 |
| `app/forge_self_awareness.py` | `self_snapshot`, `publish_self_state` | 205 |
| `tools/archive_tui/swarm_dashboard_v2.py` | `PseudoTerminal`, `SwarmDashboardV2` | 203 |
| `tools/ollama_cloud_proxy_agent.py` | `execute_local_tool`, `poll_cloud_and_execute` | 203 |
| `app/forge_guarded_mutation_loop.py` | `parse_constitution`, `check_code_violations`, `run_cmd`, `calculate_tests_hash` | 201 |
| `app/_internal/_sandbox_nlu.py` | `AgentType`, `classify` | 200 |
| `tools/archive_tui/swarm_dashboard.py` | `AgentTerminal`, `SwarmDashboard` | 200 |
| `app/forge_runner.py` | `spawn`, `status`, `run_sync` | 198 |
| `app/forge_hybrid_cortex.py` | `HybridCortex`, `get_cortex` | 197 |
| `app/forge_phi3_npu.py` | `is_available`, `get_stats`, `generate`, `purge` | 196 |
| `app/_internal/_sandbox_nokido.py` | `check`, `test_ast`, `test_skilltree_import`, `test_render` | 194 |
| `tools/forge_cmd_compactor.py` | `load_filters`, `match`, `compact`, `main` | 192 |
| `app/forge_boot.py` | `BootResult`, `run_boot`, `inject_boot_globals` | 190 |
| `app/forge_handler_nr.py` | — | 190 |
| `app/forge_context.py` | `set_active_mode`, `get_rag_engine`, `get_version_manager`, `get_settings` | 189 |
| `tools/forge_rfc_ingest.py` | `LocalRFCIngestionTool`, `get_mcp_definition` | 188 |
| `tools/forge_git_proxy.py` | `load_allow`, `GitProxy` | 187 |
| `app/legacy/codetesteur.py` | `Agent`, `Planner`, `RAG`, `OllamaLocal` | 184 |
| `app/forge_internal_sampling.py` | `sample`, `usage` | 179 |
| `app/forge_brain_client.py` | `brain_ssh_run`, `brain_ssh_available` | 178 |
| `app/forge_dispatch.py` | — | 177 |
| `tools/forge_docset_sync.py` | `DocsetAutoSync` | 172 |
| `tools/forge_git_egress_lock.py` | `available`, `run` | 171 |
| `app/forge_cache_aligner.py` | `stabilize`, `prefix_hash`, `align`, `align_messages` | 169 |
| `app/forge_token_watchdog.py` | `TokenWatchdog`, `record_tokens` | 169 |
| `tools/forge_provider_auth_audit.py` | `classify`, `test_one`, `main`, `admin_status` | 169 |
| `app/forge_biblio_schema.py` | `EntrySchema`, `validate_entry`, `to_dict` | 166 |
| `app/web_hub/forms/hub_form.py` | `render_hub_form` | 165 |
| `app/forge_rag_janitor.py` | `RAGJanitor` | 161 |
| `app/hardware/monitor.py` | `detect`, `main` | 161 |
| `app/nokido_proxy_guard.py` | `get_agent_health`, `nokido_guard`, `proxy_chat_completions` | 161 |
| `app/web_hub/forms/netcfg_form.py` | `render_netcfg_form` | 160 |
| `tools/forge_secret_audit.py` | `add_template`, `main` | 160 |
| `app/forge_ingress_adapter.py` | `IngressAdapter`, `get_ingress_adapter` | 157 |
| `tools/intel/forge_git_worker.py` | `GitWorker` | 154 |
| `app/forge_biblio_refine.py` | `parse_lastname`, `refine_query` | 153 |
| `app/forge_npu_env.py` | `conda_run`, `env_exists`, `create_env`, `install_wheels` | 150 |
| `app/forge_hub_storage.py` | `should_ignore`, `atomic_write`, `safe_read`, `scan_with_delay` | 146 |
| `app/forge_spec_formalizer.py` | `parse_baml_spec`, `generate_stubs` | 141 |
| `app/_internal/_sandbox_at.py` | `AtTestApp`, `run_test` | 140 |
| `app/forge_symbiotic_core.py` | `SymbioticCore` | 138 |
| `tools/forge_skill_indexer.py` | `SkillIndexerDaemon` | 136 |
| `app/forge_performance_tuner.py` | `get_http_session`, `prefetch_dns`, `get_cached_mcp_def`, `cache_mcp_def` | 135 |
| `app/forge_biblio_sanitizer.py` | `validate_doi`, `validate_arxiv_id`, `validate_isbn`, `is_url_whitelisted` | 134 |
| `app/forge_code_ast.py` | `analyze_ast`, `validate_python_syntax`, `pylint_score`, `count_real_errors` | 133 |
| `tools/nssm_dedup_audit.py` | `run_nssm_audit` | 133 |
| `app/forge_agents_reasoning.py` | `SupervisorAnalysis`, `RoutingPlan`, `ActionResult`, `SupervisorAgent` | 129 |
| `app/forge_context_steadiness.py` | `update_state`, `get_status_header`, `inject_header`, `get_summary` | 129 |
| `app/forge_provider_canonical.py` | `all_providers`, `provider`, `vault_key_for`, `vault_key_map` | 129 |
| `tools/forge_ui_oracle.py` | `observe`, `verify_gui`, `main` | 127 |
| `tools/forge_video_observe.py` | `extract_keyframes`, `transcribe`, `observe_video`, `main` | 126 |
| `app/legacy/arbre.py` | `RAG`, `Agent`, `Planner`, `main` | 125 |
| `app/forge_port_reconcile.py` | `run_cycle` | 124 |
| `app/forge_coherence_checker.py` | `CoherenceReport`, `check_coherence` | 122 |
| `app/forge_reconstruction_loss.py` | `calculate_jaccard`, `load_golden_tools`, `validate_and_adapt` | 122 |
| `app/forge_lmstudio.py` | `lms_call`, `lms_stream`, `is_available` | 120 |
| `tools/forge_reconcile_test.py` | `t_imports`, `t_router_no_phantom`, `t_router_status`, `t_admin_canonical_merge` | 119 |
| `app/forge_capabilities.py` | `CapabilityRegistry`, `get_caps`, `check` | 113 |
| `app/forge_web_search.py` | `search_tavily`, `search_duckduckgo`, `search_searxng`, `aggregate_search` | 111 |
| `tools/forge_docset_reader.py` | `DocsetReaderTool`, `get_mcp_definition` | 111 |
| `tools/forge_wm_trainer.py` | `main` | 109 |
| `app/forge_utils.py` | `contient_un_mot`, `sha256_fichier`, `safe_shell_run` | 107 |
| `app/legacy/modeplanner.py` | `RAG`, `Agent`, `Orchestrator`, `main` | 106 |
| `tools/forge_jepa_finetune_colab.py` | `to_ds` | 106 |
| `app/forge_llamacpp_scorer.py` | `LlamaCppScorer` | 105 |
| `app/forge_json_query.py` | `JsonQueryTool` | 104 |
| `app/forge_spec_to_stubs.py` | `StubResult`, `spec_to_stubs` | 102 |
| `app/netcfg/core.py` | `Safety`, `VendorTemplate`, `Equipment`, `VendorDetector` | 101 |
| `tools/ingest_litellm_batch.py` | `sha256_id`, `chunk_text`, `main` | 97 |
| `tools/patch_mcp_registry_netcfg.py` | `handle_netcfg_proxy` | 97 |
| `tools/patch_mcp_registry_security.py` | — | 97 |
| `app/forge_local_scout.py` | `ask_local_scout` | 96 |
| `app/agent_sre_observabilit/agent_core.py` | `AgentCore` | 94 |
| `app/forge_compose.py` | `compose` | 94 |
| `app/legacy/skilltree.py` | `SkillNode`, `SkillTree`, `AdvancedRagTUI` | 93 |
| `app/run_nlgraph_full.py` | `main` | 93 |
| `app/web_hub/forms/biblio_form.py` | `render_biblio_form` | 93 |
| `app/agent_actuaire_statisticien/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_administrateur_syst_mes_r_seaux/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_analyste_quantitatif_quant/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_analyste_risques/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_analyste_soc_siem/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_architecte_cloud/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_architecte_dplg_urbaniste/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_architecte_logiciel/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_archiviste_pal_ographe/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_astrophysicien/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_avocat_d_affaires_fiscaliste/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_bio_informaticien/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chasseur_de_t_tes_recruteur/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chef_de_produit_marketing/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chef_de_projet_product_owner/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chercheur_en_math_matiques_pures/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chimiste_organique_inorganique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_chirurgien_sp_cialis/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_climatologue/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_commercial_b2b_key_account_manager/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_concepteur_cao_dao/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_concepteur_micro_lectronique_fpga_asic/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_conducteur_de_travaux/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_consultant_en_strat_gie/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_contr_leur_de_gestion_auditeur_financier/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_criminologue/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_cryptographe/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_d_veloppeur_backend_frontend/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_data_scientist_data_engineer/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_directeur_de_la_supply_chain/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_enseignant_chercheur/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_expert_comptable/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_expert_en_propri_t_intellectuelle_inpi/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_expert_en_r_seaux_lectriques_smart_grids/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_expert_en_structures_g_nie_civil/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_fiabiliste/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_g_n_ticien_biologiste_mol_culaire/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_g_omaticien_cartographe_sig/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_graphiste_directeur_artistique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_infirmier_dipl_m_d_tat/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_agronome/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_du_son_expert_haute_fid_lit_dsp/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_g_nie_m_canique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_maintenance_industrielle/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_nergies_renouvelables/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_sciences_des_mat_riaux/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_thermodynamique_m_canique_des_fluides/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_en_traitement_des_eaux_d_chets/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_lean_manufacturing/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_nucl_aire/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_p_dagogique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_qualit/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_rag_llm/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_syst_mes_embarqu_s_c_rust/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ing_nieur_t_l_coms/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_inspecteur_des_finances_publiques/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_journaliste_fact_checker/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_juriste_en_droit_administratif/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_juriste_en_droit_social_expert_prud_hommes/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_kin_sith_rapeute_ergonome/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_libraire_expert_bibliographique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_logisticien_gestionnaire_de_flux/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_m_decin_g_n_raliste_diagnostiqueur/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_m_t_orologue_agricole/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_mod_lisateur_animateur_3d/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_monteur_vid_o_r_alisateur/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_n_gociateur_immobilier/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_notaire/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_pharmacologue/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_physicien_quantique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_pid_miologiste/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_psychiatre/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_psychologue_cognitif/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_r_dacteur_copywriter/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sociologue_d_mographe/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sommelier_expert_en_gastronomie/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sp_cialiste_optimisation_mat_rielle_acc_l_ration_igpu_npu/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sp_cialiste_robotique_automatisation/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sp_cialiste_vision_par_ordinateur_traitement_du_langage_nlp/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_sre_observabilit/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_strat_ge_seo_trafic_manager/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_tacticien_militaire/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_trader_gestionnaire_de_portefeuille/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_traducteur_litt_raire_technique/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/agent_ux_ui_designer/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/mcp_agent_template/mcp_server.py` | `root`, `mcp_endpoint`, `mcp_sse_endpoint`, `run_server` | 92 |
| `app/test_nokido_convergence.py` | `run_all_tests` | 90 |
| `app/reembed_souverain.py` | `get_embedding`, `main` | 88 |
| `app/forge_orchestration_benchmark.py` | `OrchestrationBenchmark` | 87 |
| `tools/deno_spikerouter_diag.py` | `run_diagnostic` | 87 |
| `app/forge_hw.py` | `hw`, `hw_all`, `hw_ready`, `hw_summary` | 86 |
| `app/forge_ui_autocomplete.py` | `AutocompleteEngine` | 86 |
| `app/netcfg/visio.py` | `VisioParser` | 86 |
| `app/web_hub/forms/task_form.py` | `render_task_form` | 86 |
| `tools/backfill_intent.py` | `log`, `embed`, `main` | 86 |
| `app/forge_failsafe_router.py` | `FailsafeRouter` | 85 |
| `app/forge_handler_network.py` | — | 85 |
| `tools/rotate_snapshots.py` | `log` | 85 |
| `app/stress_test_firewall.py` | `run_red_team_test` | 84 |
| `tools/apply_mcp_buffer_patch.py` | `check`, `apply_patches`, `revert` | 83 |
| `tools/bench_embeddings.py` | `bench_wasm`, `bench_ollama`, `bench_npu`, `run_bench` | 83 |
| `app/web_hub/vitals_panels.py` | `render_subjective_tempo_panel`, `render_affective_state_panel`, `render_phenomenal_flow_panel`, `render_parietal_percept_panel` | 82 |
| `app/legacy/scapyshark.py` | `MiniIDSAgent` | 81 |
| `app/netcfg/migrate.py` | `migrate` | 81 |
| `app/_internal/_sandbox_test.py` | `MiniApp`, `run_once` | 79 |
| `app/agent_actuaire_statisticien/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_administrateur_syst_mes_r_seaux/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_analyste_quantitatif_quant/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_analyste_risques/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_analyste_soc_siem/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_architecte_cloud/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_architecte_dplg_urbaniste/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_architecte_logiciel/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_archiviste_pal_ographe/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_astrophysicien/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_avocat_d_affaires_fiscaliste/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_bio_informaticien/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chasseur_de_t_tes_recruteur/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chef_de_produit_marketing/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chef_de_projet_product_owner/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chercheur_en_math_matiques_pures/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chimiste_organique_inorganique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_chirurgien_sp_cialis/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_climatologue/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_commercial_b2b_key_account_manager/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_concepteur_cao_dao/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_concepteur_micro_lectronique_fpga_asic/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_conducteur_de_travaux/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_consultant_en_strat_gie/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_contr_leur_de_gestion_auditeur_financier/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_criminologue/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_cryptographe/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_d_veloppeur_backend_frontend/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_data_scientist_data_engineer/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_directeur_de_la_supply_chain/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_enseignant_chercheur/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_expert_comptable/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_expert_en_propri_t_intellectuelle_inpi/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_expert_en_r_seaux_lectriques_smart_grids/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_expert_en_structures_g_nie_civil/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_fiabiliste/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_g_n_ticien_biologiste_mol_culaire/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_g_omaticien_cartographe_sig/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_graphiste_directeur_artistique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_infirmier_dipl_m_d_tat/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_agronome/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_du_son_expert_haute_fid_lit_dsp/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_g_nie_m_canique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_maintenance_industrielle/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_nergies_renouvelables/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_sciences_des_mat_riaux/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_thermodynamique_m_canique_des_fluides/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_en_traitement_des_eaux_d_chets/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_lean_manufacturing/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_nucl_aire/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_p_dagogique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_qualit/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_rag_llm/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_syst_mes_embarqu_s_c_rust/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ing_nieur_t_l_coms/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_inspecteur_des_finances_publiques/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_journaliste_fact_checker/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_juriste_en_droit_administratif/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_juriste_en_droit_social_expert_prud_hommes/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_kin_sith_rapeute_ergonome/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_libraire_expert_bibliographique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_logisticien_gestionnaire_de_flux/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_m_decin_g_n_raliste_diagnostiqueur/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_m_t_orologue_agricole/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_mod_lisateur_animateur_3d/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_monteur_vid_o_r_alisateur/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_n_gociateur_immobilier/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_notaire/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_pharmacologue/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_physicien_quantique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_pid_miologiste/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_psychiatre/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_psychologue_cognitif/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_r_dacteur_copywriter/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sociologue_d_mographe/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sommelier_expert_en_gastronomie/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sp_cialiste_optimisation_mat_rielle_acc_l_ration_igpu_npu/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sp_cialiste_robotique_automatisation/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sp_cialiste_vision_par_ordinateur_traitement_du_langage_nlp/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_sre_observabilit/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_strat_ge_seo_trafic_manager/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_tacticien_militaire/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_trader_gestionnaire_de_portefeuille/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_traducteur_litt_raire_technique/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/agent_ux_ui_designer/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `app/mcp_agent_template/mcp_stdio.py` | `run_stdio_loop` | 78 |
| `tools/bench_llamacpp_vs_ollama.py` | `main` | 78 |
| `app/agent_architecte_cloud/agent_core.py` | `AgentCore` | 77 |
| `app/forge_commit_guard.py` | `CommitGuard`, `GuardResult` | 76 |
| `app/web_hub/forms/graph_edge_score_form.py` | `render_graph_edge_score_form` | 75 |
| `app/forge_symbiosis_bridge.py` | `SymbiosisBridge` | 73 |
| `tools/forge_bundle_primitives.py` | `BundleSession` | 73 |
| `tools/forge_router_impact.py` | `rejouabilite`, `couverture`, `charger`, `main` | 73 |
| `app/web_hub/forms/forge_deep_explore_form.py` | `render_forge_deep_explore_form` | 71 |
| `app/web_hub/forms/orchestrate_form.py` | `render_orchestrate_form` | 71 |
| `app/web_hub/forms/blackboard_propose_fact_form.py` | `render_blackboard_propose_fact_form` | 70 |
| `app/web_hub/forms/event_form.py` | `render_event_form` | 70 |
| `app/forge_agent_benchmarker.py` | — | 69 |
| `app/patch_rag_warmup.py` | — | 69 |
| `app/web_hub/forms/cross_platform_fs_form.py` | `render_cross_platform_fs_form` | 68 |
| `app/web_hub/forms/read_form.py` | `render_read_form` | 68 |
| `app/web_hub/forms/skill_form.py` | `render_skill_form` | 68 |
| `tools/_patch_bridge.py` | — | 68 |
| `tools/_trace_daemon.py` | — | 68 |
| `tools/apply_migration.py` | `main` | 68 |
| `app/test_chantier_2.py` | `test_chantier_2` | 67 |
| `app/web_hub/module_card_html.py` | `render_module_card` | 67 |
| `app/web_hub/forms/manage_forge_lifecycle_form.py` | `render_manage_forge_lifecycle_form` | 66 |
| `app/_internal/_launch_brain.py` | — | 64 |
| `app/forge_impact_agent.py` | `analyze_file_structure` | 64 |
| `tools/forge_vision_som.py` | `available`, `detect` | 63 |
| `app/web_hub/forms/governed_edit_form.py` | `render_governed_edit_form` | 62 |
| `app/web_hub/forms/rag_form.py` | `render_rag_form` | 62 |
| `tools/purge_delete_snaps.py` | `log` | 62 |
| `app/forge_collab_modes.py` | — | 61 |
| `app/forge_graph_search.py` | `search`, `stats` | 61 |
| `app/web_hub/forms/agy_config_form.py` | `render_agy_config_form` | 59 |
| `app/web_hub/forms/tool_scope_form.py` | `render_tool_scope_form` | 59 |
| `app/web_hub/forms/ask_form.py` | `render_ask_form` | 55 |
| `app/web_hub/forms/research_agent_form.py` | `render_research_agent_form` | 55 |
| `tools/forge_binary_graph.py` | `BinaryGraph` | 55 |
| `app/agent_actuaire_statisticien/main.py` | `main` | 54 |
| `app/agent_administrateur_syst_mes_r_seaux/main.py` | `main` | 54 |
| `app/agent_analyste_quantitatif_quant/main.py` | `main` | 54 |
| `app/agent_analyste_risques/main.py` | `main` | 54 |
| `app/agent_analyste_soc_siem/main.py` | `main` | 54 |
| `app/agent_architecte_cloud/main.py` | `main` | 54 |
| `app/agent_architecte_dplg_urbaniste/main.py` | `main` | 54 |
| `app/agent_architecte_logiciel/main.py` | `main` | 54 |
| `app/agent_archiviste_pal_ographe/main.py` | `main` | 54 |
| `app/agent_astrophysicien/main.py` | `main` | 54 |
| `app/agent_avocat_d_affaires_fiscaliste/main.py` | `main` | 54 |
| `app/agent_bio_informaticien/main.py` | `main` | 54 |
| `app/agent_chasseur_de_t_tes_recruteur/main.py` | `main` | 54 |
| `app/agent_chef_de_produit_marketing/main.py` | `main` | 54 |
| `app/agent_chef_de_projet_product_owner/main.py` | `main` | 54 |
| `app/agent_chercheur_en_math_matiques_pures/main.py` | `main` | 54 |
| `app/agent_chimiste_organique_inorganique/main.py` | `main` | 54 |
| `app/agent_chirurgien_sp_cialis/main.py` | `main` | 54 |
| `app/agent_climatologue/main.py` | `main` | 54 |
| `app/agent_commercial_b2b_key_account_manager/main.py` | `main` | 54 |
| `app/agent_concepteur_cao_dao/main.py` | `main` | 54 |
| `app/agent_concepteur_micro_lectronique_fpga_asic/main.py` | `main` | 54 |
| `app/agent_conducteur_de_travaux/main.py` | `main` | 54 |
| `app/agent_consultant_en_strat_gie/main.py` | `main` | 54 |
| `app/agent_contr_leur_de_gestion_auditeur_financier/main.py` | `main` | 54 |
| `app/agent_criminologue/main.py` | `main` | 54 |
| `app/agent_cryptographe/main.py` | `main` | 54 |
| `app/agent_d_veloppeur_backend_frontend/main.py` | `main` | 54 |
| `app/agent_data_scientist_data_engineer/main.py` | `main` | 54 |
| `app/agent_directeur_de_la_supply_chain/main.py` | `main` | 54 |
| `app/agent_enseignant_chercheur/main.py` | `main` | 54 |
| `app/agent_expert_comptable/main.py` | `main` | 54 |
| `app/agent_expert_en_propri_t_intellectuelle_inpi/main.py` | `main` | 54 |
| `app/agent_expert_en_r_seaux_lectriques_smart_grids/main.py` | `main` | 54 |
| `app/agent_expert_en_structures_g_nie_civil/main.py` | `main` | 54 |
| `app/agent_fiabiliste/main.py` | `main` | 54 |
| `app/agent_g_n_ticien_biologiste_mol_culaire/main.py` | `main` | 54 |
| `app/agent_g_omaticien_cartographe_sig/main.py` | `main` | 54 |
| `app/agent_graphiste_directeur_artistique/main.py` | `main` | 54 |
| `app/agent_infirmier_dipl_m_d_tat/main.py` | `main` | 54 |
| `app/agent_ing_nieur_agronome/main.py` | `main` | 54 |
| `app/agent_ing_nieur_du_son_expert_haute_fid_lit_dsp/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_g_nie_m_canique/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_maintenance_industrielle/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_nergies_renouvelables/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_sciences_des_mat_riaux/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_thermodynamique_m_canique_des_fluides/main.py` | `main` | 54 |
| `app/agent_ing_nieur_en_traitement_des_eaux_d_chets/main.py` | `main` | 54 |
| `app/agent_ing_nieur_lean_manufacturing/main.py` | `main` | 54 |
| `app/agent_ing_nieur_nucl_aire/main.py` | `main` | 54 |
| `app/agent_ing_nieur_p_dagogique/main.py` | `main` | 54 |
| `app/agent_ing_nieur_qualit/main.py` | `main` | 54 |
| `app/agent_ing_nieur_rag_llm/main.py` | `main` | 54 |
| `app/agent_ing_nieur_syst_mes_embarqu_s_c_rust/main.py` | `main` | 54 |
| `app/agent_ing_nieur_t_l_coms/main.py` | `main` | 54 |
| `app/agent_inspecteur_des_finances_publiques/main.py` | `main` | 54 |
| `app/agent_journaliste_fact_checker/main.py` | `main` | 54 |
| `app/agent_juriste_en_droit_administratif/main.py` | `main` | 54 |
| `app/agent_juriste_en_droit_social_expert_prud_hommes/main.py` | `main` | 54 |
| `app/agent_kin_sith_rapeute_ergonome/main.py` | `main` | 54 |
| `app/agent_libraire_expert_bibliographique/main.py` | `main` | 54 |
| `app/agent_logisticien_gestionnaire_de_flux/main.py` | `main` | 54 |
| `app/agent_m_decin_g_n_raliste_diagnostiqueur/main.py` | `main` | 54 |
| `app/agent_m_t_orologue_agricole/main.py` | `main` | 54 |
| `app/agent_mod_lisateur_animateur_3d/main.py` | `main` | 54 |
| `app/agent_monteur_vid_o_r_alisateur/main.py` | `main` | 54 |
| `app/agent_n_gociateur_immobilier/main.py` | `main` | 54 |
| `app/agent_notaire/main.py` | `main` | 54 |
| `app/agent_pharmacologue/main.py` | `main` | 54 |
| `app/agent_physicien_quantique/main.py` | `main` | 54 |
| `app/agent_pid_miologiste/main.py` | `main` | 54 |
| `app/agent_psychiatre/main.py` | `main` | 54 |
| `app/agent_psychologue_cognitif/main.py` | `main` | 54 |
| `app/agent_r_dacteur_copywriter/main.py` | `main` | 54 |
| `app/agent_sociologue_d_mographe/main.py` | `main` | 54 |
| `app/agent_sommelier_expert_en_gastronomie/main.py` | `main` | 54 |
| `app/agent_sp_cialiste_optimisation_mat_rielle_acc_l_ration_igpu_npu/main.py` | `main` | 54 |
| `app/agent_sp_cialiste_robotique_automatisation/main.py` | `main` | 54 |
| `app/agent_sp_cialiste_vision_par_ordinateur_traitement_du_langage_nlp/main.py` | `main` | 54 |
| `app/agent_sre_observabilit/main.py` | `main` | 54 |
| `app/agent_strat_ge_seo_trafic_manager/main.py` | `main` | 54 |
| `app/agent_tacticien_militaire/main.py` | `main` | 54 |
| `app/agent_trader_gestionnaire_de_portefeuille/main.py` | `main` | 54 |
| `app/agent_traducteur_litt_raire_technique/main.py` | `main` | 54 |
| `app/agent_ux_ui_designer/main.py` | `main` | 54 |
| `app/mcp_agent_template/main.py` | `main` | 54 |
| `app/test_graph_traversal.py` | `test_graph` | 53 |
| `app/web_hub/forms/forge_spawn_swarm_form.py` | `render_forge_spawn_swarm_form` | 53 |
| `app/web_hub/forms/nokido_ensure_service_form.py` | `render_nokido_ensure_service_form` | 53 |
| `app/web_hub/forms/query_form.py` | `render_query_form` | 53 |
| `app/full_reindex_core.py` | `reindex` | 52 |
| `app/legacy/RAGv2.py` | `build_hybrid_rag`, `query_npu` | 52 |
| `app/web_hub/forms/graph_cve_propagate_form.py` | `render_graph_cve_propagate_form` | 52 |
| `app/web_hub/forms/graph_ppr_form.py` | `render_graph_ppr_form` | 52 |
| `tools/deno_audit.py` | `check_health`, `read_log_file`, `grep_brain_ts`, `main` | 52 |
| `app/web_hub/forms/forge_trigger_audit_form.py` | `render_forge_trigger_audit_form` | 51 |
| `tools/nokido_homeostasis.py` | `main` | 51 |
| `app/test_lms_router.py` | `test_lms_integration` | 50 |
| `app/web_hub/forms/blackboard_read_zone_form.py` | `render_blackboard_read_zone_form` | 50 |
| `app/brain_ping.py` | — | 49 |
| `app/diag_nokido.py` | — | 48 |
| `tools/test_intent_negotiation.py` | `test_negotiation_flow` | 48 |
| `app/debug_graph_fix.py` | `debug_one_file` | 46 |
| `app/_internal/_release_tmp.py` | — | 45 |
| `app/web_hub/forms/agy_run_form.py` | `render_agy_run_form` | 44 |
| `app/web_hub/forms/forge_call_dynamic_form.py` | `render_forge_call_dynamic_form` | 44 |
| `app/web_hub/forms/oracle_python_repl_form.py` | `render_oracle_python_repl_form` | 44 |
| `app/web_hub/forms/plan_form.py` | `render_plan_form` | 44 |
| `app/web_hub/forms/route_dt_form.py` | `render_route_dt_form` | 44 |
| `app/web_hub/forms/trigger_autonomous_evolution_form.py` | `render_trigger_autonomous_evolution_form` | 44 |
| `tools/_dump_all_results.py` | — | 44 |
| `app/agent_actuaire_statisticien/agent_core.py` | `AgentCore` | 43 |
| `app/agent_administrateur_syst_mes_r_seaux/agent_core.py` | `AgentCore` | 43 |
| `app/agent_analyste_quantitatif_quant/agent_core.py` | `AgentCore` | 43 |
| `app/agent_analyste_risques/agent_core.py` | `AgentCore` | 43 |
| `app/agent_analyste_soc_siem/agent_core.py` | `AgentCore` | 43 |
| `app/agent_architecte_dplg_urbaniste/agent_core.py` | `AgentCore` | 43 |
| `app/agent_architecte_logiciel/agent_core.py` | `AgentCore` | 43 |
| `app/agent_archiviste_pal_ographe/agent_core.py` | `AgentCore` | 43 |
| `app/agent_astrophysicien/agent_core.py` | `AgentCore` | 43 |
| `app/agent_avocat_d_affaires_fiscaliste/agent_core.py` | `AgentCore` | 43 |
| `app/agent_bio_informaticien/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chasseur_de_t_tes_recruteur/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chef_de_produit_marketing/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chef_de_projet_product_owner/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chercheur_en_math_matiques_pures/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chimiste_organique_inorganique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_chirurgien_sp_cialis/agent_core.py` | `AgentCore` | 43 |
| `app/agent_climatologue/agent_core.py` | `AgentCore` | 43 |
| `app/agent_commercial_b2b_key_account_manager/agent_core.py` | `AgentCore` | 43 |
| `app/agent_concepteur_cao_dao/agent_core.py` | `AgentCore` | 43 |
| `app/agent_concepteur_micro_lectronique_fpga_asic/agent_core.py` | `AgentCore` | 43 |
| `app/agent_conducteur_de_travaux/agent_core.py` | `AgentCore` | 43 |
| `app/agent_consultant_en_strat_gie/agent_core.py` | `AgentCore` | 43 |
| `app/agent_contr_leur_de_gestion_auditeur_financier/agent_core.py` | `AgentCore` | 43 |
| `app/agent_criminologue/agent_core.py` | `AgentCore` | 43 |
| `app/agent_cryptographe/agent_core.py` | `AgentCore` | 43 |
| `app/agent_d_veloppeur_backend_frontend/agent_core.py` | `AgentCore` | 43 |
| `app/agent_data_scientist_data_engineer/agent_core.py` | `AgentCore` | 43 |
| `app/agent_directeur_de_la_supply_chain/agent_core.py` | `AgentCore` | 43 |
| `app/agent_enseignant_chercheur/agent_core.py` | `AgentCore` | 43 |
| `app/agent_expert_comptable/agent_core.py` | `AgentCore` | 43 |
| `app/agent_expert_en_propri_t_intellectuelle_inpi/agent_core.py` | `AgentCore` | 43 |
| `app/agent_expert_en_r_seaux_lectriques_smart_grids/agent_core.py` | `AgentCore` | 43 |
| `app/agent_expert_en_structures_g_nie_civil/agent_core.py` | `AgentCore` | 43 |
| `app/agent_fiabiliste/agent_core.py` | `AgentCore` | 43 |
| `app/agent_g_n_ticien_biologiste_mol_culaire/agent_core.py` | `AgentCore` | 43 |
| `app/agent_g_omaticien_cartographe_sig/agent_core.py` | `AgentCore` | 43 |
| `app/agent_graphiste_directeur_artistique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_infirmier_dipl_m_d_tat/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_agronome/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_du_son_expert_haute_fid_lit_dsp/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_g_nie_m_canique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_maintenance_industrielle/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_nergies_renouvelables/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_sciences_des_mat_riaux/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_thermodynamique_m_canique_des_fluides/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_en_traitement_des_eaux_d_chets/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_lean_manufacturing/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_nucl_aire/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_p_dagogique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_qualit/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_rag_llm/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_syst_mes_embarqu_s_c_rust/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ing_nieur_t_l_coms/agent_core.py` | `AgentCore` | 43 |
| `app/agent_inspecteur_des_finances_publiques/agent_core.py` | `AgentCore` | 43 |
| `app/agent_journaliste_fact_checker/agent_core.py` | `AgentCore` | 43 |
| `app/agent_juriste_en_droit_administratif/agent_core.py` | `AgentCore` | 43 |
| `app/agent_juriste_en_droit_social_expert_prud_hommes/agent_core.py` | `AgentCore` | 43 |
| `app/agent_kin_sith_rapeute_ergonome/agent_core.py` | `AgentCore` | 43 |
| `app/agent_libraire_expert_bibliographique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_logisticien_gestionnaire_de_flux/agent_core.py` | `AgentCore` | 43 |
| `app/agent_m_decin_g_n_raliste_diagnostiqueur/agent_core.py` | `AgentCore` | 43 |
| `app/agent_m_t_orologue_agricole/agent_core.py` | `AgentCore` | 43 |
| `app/agent_mod_lisateur_animateur_3d/agent_core.py` | `AgentCore` | 43 |
| `app/agent_monteur_vid_o_r_alisateur/agent_core.py` | `AgentCore` | 43 |
| `app/agent_n_gociateur_immobilier/agent_core.py` | `AgentCore` | 43 |
| `app/agent_notaire/agent_core.py` | `AgentCore` | 43 |
| `app/agent_pharmacologue/agent_core.py` | `AgentCore` | 43 |
| `app/agent_physicien_quantique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_pid_miologiste/agent_core.py` | `AgentCore` | 43 |
| `app/agent_psychiatre/agent_core.py` | `AgentCore` | 43 |
| `app/agent_psychologue_cognitif/agent_core.py` | `AgentCore` | 43 |
| `app/agent_r_dacteur_copywriter/agent_core.py` | `AgentCore` | 43 |
| `app/agent_sociologue_d_mographe/agent_core.py` | `AgentCore` | 43 |
| `app/agent_sommelier_expert_en_gastronomie/agent_core.py` | `AgentCore` | 43 |
| `app/agent_sp_cialiste_optimisation_mat_rielle_acc_l_ration_igpu_npu/agent_core.py` | `AgentCore` | 43 |
| `app/agent_sp_cialiste_robotique_automatisation/agent_core.py` | `AgentCore` | 43 |
| `app/agent_sp_cialiste_vision_par_ordinateur_traitement_du_langage_nlp/agent_core.py` | `AgentCore` | 43 |
| `app/agent_strat_ge_seo_trafic_manager/agent_core.py` | `AgentCore` | 43 |
| `app/agent_tacticien_militaire/agent_core.py` | `AgentCore` | 43 |
| `app/agent_trader_gestionnaire_de_portefeuille/agent_core.py` | `AgentCore` | 43 |
| `app/agent_traducteur_litt_raire_technique/agent_core.py` | `AgentCore` | 43 |
| `app/agent_ux_ui_designer/agent_core.py` | `AgentCore` | 43 |
| `app/web_hub/forms/get_function_dependencies_form.py` | `render_get_function_dependencies_form` | 43 |
| `app/web_hub/forms/introspect_form.py` | `render_introspect_form` | 43 |
| `app/web_hub/forms/loop_orchestrate_form.py` | `render_loop_orchestrate_form` | 43 |
| `app/web_hub/forms/read_function_body_form.py` | `render_read_function_body_form` | 43 |
| `tools/_gitingest_status.py` | — | 43 |
| `tools/_run_python_new.py` | `sync_run_python` | 43 |
| `app/forge_rag_mixin.py` | `rag_self_warmup` | 41 |
| `tools/_chain_execute2.py` | `main` | 41 |
| `app/audit_embeddings.py` | `audit_missing_embeddings` | 40 |
| `app/mcp_agent_template/agent_core.py` | `AgentCore` | 39 |
| `tools/_ami_ingest_worker.py` | `main` | 39 |
| `tools/_chain_execute3.py` | `main` | 39 |
| `app/forge_capability_benchmark.py` | `CapabilityBenchmarker` | 38 |
| `app/web_hub/forms/docker_action_form.py` | `render_docker_action_form` | 38 |
| `app/web_hub/forms/route_task_form.py` | `render_route_task_form` | 38 |
| `app/web_hub/forms/write_form.py` | `render_write_form` | 38 |
| `tools/read_blackboard.py` | `main` | 38 |
| `app/web_hub/forms/crawl_form.py` | `render_crawl_form` | 37 |
| `app/web_hub/forms/web_search_form.py` | `render_web_search_form` | 37 |
| `app/_internal/_purge_pyc.py` | — | 36 |
| `app/web_hub/forms/bundle_form.py` | `render_bundle_form` | 35 |
| `app/web_hub/forms/dyn_metier_dispatch_form.py` | `render_dyn_metier_dispatch_form` | 35 |
| `app/web_hub/forms/dyn_orchestrate_form.py` | `render_dyn_orchestrate_form` | 35 |
| `app/web_hub/forms/dyn_skill_forge_form.py` | `render_dyn_skill_forge_form` | 35 |
| `app/web_hub/forms/agy_add_dir_form.py` | `render_agy_add_dir_form` | 34 |
| `app/web_hub/forms/get_file_skeleton_form.py` | `render_get_file_skeleton_form` | 34 |
| `tools/_nssm_check.py` | — | 34 |
| `app/_internal/_cmd_rag_patch.py` | — | 33 |
| `tools/launch_netcfg_8768.py` | — | 33 |
| `app/setup_cython.py` | — | 32 |
| `app/web_hub/forms/auto_test_form.py` | `render_auto_test_form` | 31 |
| `tools/_chain_execute.py` | `main` | 31 |
| `app/_internal/_test_terminal.py` | — | 30 |
| `tools/_git_commit_t8.py` | — | 29 |
| `tools/_run_send.py` | — | 29 |
| `app/_internal/_copy_mixins.py` | — | 28 |
| `tools/_check_llamacpp.py` | — | 27 |
| `tools/finalize_gitingest.py` | — | 27 |
| `tools/test_npu_direct.py` | — | 27 |
| `app/debug.py` | — | 26 |
| `tools/_commit_gemini_work.py` | — | 26 |
| `tools/_git_commit_batch11.py` | — | 26 |
| `tools/_read_batch13_results.py` | — | 26 |
| `app/web_hub/forms/forge_list_dynamic_tools_form.py` | `render_forge_list_dynamic_tools_form` | 25 |
| `app/web_hub/forms/forge_stats_form.py` | `render_forge_stats_form` | 25 |
| `app/read_claude_notifs.py` | — | 24 |
| `tools/_commit_batch13_apply.py` | — | 24 |
| `tools/_dump_batch13b.py` | — | 24 |
| `tools/_read_inbox.py` | — | 24 |
| `tools/read_claude_inbox.py` | — | 24 |
| `app/bridge_cmd.py` | — | 23 |
| `tools/_resend_gemini8.py` | — | 23 |
| `tools/read_gemini_messages.py` | — | 23 |
| `tools/_ast_check.py` | — | 22 |
| `tools/_chain_runner.py` | `main` | 22 |
| `tools/_commit_dt_f35.py` | — | 22 |
| `tools/check_forge_tools.py` | — | 21 |
| `tools/merge_gitingest.py` | — | 20 |
| `app/forge_tools_dynamic/tool_skill_forge.py` | `skill_forge` | 19 |
| `tools/_commit_daemon_fix.py` | — | 18 |
| `tools/_check_batch13.py` | — | 17 |
| `tools/_dispatch_cohere.py` | — | 17 |
| `tools/_test_actor.py` | — | 17 |
| `app/setup_cython_simple.py` | — | 16 |
| `tools/_check_git.py` | — | 16 |
| `tools/_daemon_log.py` | — | 16 |
| `tools/_fetch_b8.py` | — | 16 |
| `tools/_git_commit_auto.py` | — | 16 |
| `app/agent_actuaire_statisticien/config.py` | — | 15 |
| `app/agent_administrateur_syst_mes_r_seaux/config.py` | — | 15 |
| `app/agent_analyste_quantitatif_quant/config.py` | — | 15 |
| `app/agent_analyste_risques/config.py` | — | 15 |
| `app/agent_analyste_soc_siem/config.py` | — | 15 |
| `app/agent_architecte_cloud/config.py` | — | 15 |
| `app/agent_architecte_dplg_urbaniste/config.py` | — | 15 |
| `app/agent_architecte_logiciel/config.py` | — | 15 |
| `app/agent_archiviste_pal_ographe/config.py` | — | 15 |
| `app/agent_astrophysicien/config.py` | — | 15 |
| `app/agent_avocat_d_affaires_fiscaliste/config.py` | — | 15 |
| `app/agent_bio_informaticien/config.py` | — | 15 |
| `app/agent_chasseur_de_t_tes_recruteur/config.py` | — | 15 |
| `app/agent_chef_de_produit_marketing/config.py` | — | 15 |
| `app/agent_chef_de_projet_product_owner/config.py` | — | 15 |
| `app/agent_chercheur_en_math_matiques_pures/config.py` | — | 15 |
| `app/agent_chimiste_organique_inorganique/config.py` | — | 15 |
| `app/agent_chirurgien_sp_cialis/config.py` | — | 15 |
| `app/agent_climatologue/config.py` | — | 15 |
| `app/agent_commercial_b2b_key_account_manager/config.py` | — | 15 |
| `app/agent_concepteur_cao_dao/config.py` | — | 15 |
| `app/agent_concepteur_micro_lectronique_fpga_asic/config.py` | — | 15 |
| `app/agent_conducteur_de_travaux/config.py` | — | 15 |
| `app/agent_consultant_en_strat_gie/config.py` | — | 15 |
| `app/agent_contr_leur_de_gestion_auditeur_financier/config.py` | — | 15 |
| `app/agent_criminologue/config.py` | — | 15 |
| `app/agent_cryptographe/config.py` | — | 15 |
| `app/agent_d_veloppeur_backend_frontend/config.py` | — | 15 |
| `app/agent_data_scientist_data_engineer/config.py` | — | 15 |
| `app/agent_directeur_de_la_supply_chain/config.py` | — | 15 |
| `app/agent_enseignant_chercheur/config.py` | — | 15 |
| `app/agent_expert_comptable/config.py` | — | 15 |
| `app/agent_expert_en_propri_t_intellectuelle_inpi/config.py` | — | 15 |
| `app/agent_expert_en_r_seaux_lectriques_smart_grids/config.py` | — | 15 |
| `app/agent_expert_en_structures_g_nie_civil/config.py` | — | 15 |
| `app/agent_fiabiliste/config.py` | — | 15 |
| `app/agent_g_n_ticien_biologiste_mol_culaire/config.py` | — | 15 |
| `app/agent_g_omaticien_cartographe_sig/config.py` | — | 15 |
| `app/agent_graphiste_directeur_artistique/config.py` | — | 15 |
| `app/agent_infirmier_dipl_m_d_tat/config.py` | — | 15 |
| `app/agent_ing_nieur_agronome/config.py` | — | 15 |
| `app/agent_ing_nieur_du_son_expert_haute_fid_lit_dsp/config.py` | — | 15 |
| `app/agent_ing_nieur_en_g_nie_m_canique/config.py` | — | 15 |
| `app/agent_ing_nieur_en_maintenance_industrielle/config.py` | — | 15 |
| `app/agent_ing_nieur_en_nergies_renouvelables/config.py` | — | 15 |
| `app/agent_ing_nieur_en_sciences_des_mat_riaux/config.py` | — | 15 |
| `app/agent_ing_nieur_en_thermodynamique_m_canique_des_fluides/config.py` | — | 15 |
| `app/agent_ing_nieur_en_traitement_des_eaux_d_chets/config.py` | — | 15 |
| `app/agent_ing_nieur_lean_manufacturing/config.py` | — | 15 |
| `app/agent_ing_nieur_nucl_aire/config.py` | — | 15 |
| `app/agent_ing_nieur_p_dagogique/config.py` | — | 15 |
| `app/agent_ing_nieur_qualit/config.py` | — | 15 |
| `app/agent_ing_nieur_rag_llm/config.py` | — | 15 |
| `app/agent_ing_nieur_syst_mes_embarqu_s_c_rust/config.py` | — | 15 |
| `app/agent_ing_nieur_t_l_coms/config.py` | — | 15 |
| `app/agent_inspecteur_des_finances_publiques/config.py` | — | 15 |
| `app/agent_journaliste_fact_checker/config.py` | — | 15 |
| `app/agent_juriste_en_droit_administratif/config.py` | — | 15 |
| `app/agent_juriste_en_droit_social_expert_prud_hommes/config.py` | — | 15 |
| `app/agent_kin_sith_rapeute_ergonome/config.py` | — | 15 |
| `app/agent_libraire_expert_bibliographique/config.py` | — | 15 |
| `app/agent_logisticien_gestionnaire_de_flux/config.py` | — | 15 |
| `app/agent_m_decin_g_n_raliste_diagnostiqueur/config.py` | — | 15 |
| `app/agent_m_t_orologue_agricole/config.py` | — | 15 |
| `app/agent_mod_lisateur_animateur_3d/config.py` | — | 15 |
| `app/agent_monteur_vid_o_r_alisateur/config.py` | — | 15 |
| `app/agent_n_gociateur_immobilier/config.py` | — | 15 |
| `app/agent_notaire/config.py` | — | 15 |
| `app/agent_pharmacologue/config.py` | — | 15 |
| `app/agent_physicien_quantique/config.py` | — | 15 |
| `app/agent_pid_miologiste/config.py` | — | 15 |
| `app/agent_psychiatre/config.py` | — | 15 |
| `app/agent_psychologue_cognitif/config.py` | — | 15 |
| `app/agent_r_dacteur_copywriter/config.py` | — | 15 |
| `app/agent_sociologue_d_mographe/config.py` | — | 15 |
| `app/agent_sommelier_expert_en_gastronomie/config.py` | — | 15 |
| `app/agent_sp_cialiste_optimisation_mat_rielle_acc_l_ration_igpu_npu/config.py` | — | 15 |
| `app/agent_sp_cialiste_robotique_automatisation/config.py` | — | 15 |
| `app/agent_sp_cialiste_vision_par_ordinateur_traitement_du_langage_nlp/config.py` | — | 15 |
| `app/agent_sre_observabilit/config.py` | — | 15 |
| `app/agent_strat_ge_seo_trafic_manager/config.py` | — | 15 |
| `app/agent_tacticien_militaire/config.py` | — | 15 |
| `app/agent_trader_gestionnaire_de_portefeuille/config.py` | — | 15 |
| `app/agent_traducteur_litt_raire_technique/config.py` | — | 15 |
| `app/agent_ux_ui_designer/config.py` | — | 15 |
| `app/mcp_agent_template/config.py` | — | 15 |
| `tools/_commit_coherence_gate.py` | — | 15 |
| `app/forge_tools_dynamic/tool_orchestrate.py` | `orchestrate` | 14 |
| `tools/_check_batch13b.py` | — | 14 |
| `tools/_fix_batch13_status.py` | — | 14 |
| `tools/_check_batch8.py` | — | 13 |
| `tools/bench_fixtures/gd_007_nmlp_shape.py` | — | 12 |
| `tools/_diag_local.py` | — | 11 |
| `tools/_check_batch8b.py` | — | 10 |
| `tools/_push.py` | — | 9 |
| `tools/bench_fixtures/gd_005_train_cost.py` | — | 9 |
| `tools/bench_fixtures/gd_013_git_log.py` | — | 9 |
| `tools/bench_fixtures/gd_019_rag_search.py` | — | 9 |
| `tools/bench_fixtures/gd_006_costnet_params.py` | — | 8 |
| `tools/bench_fixtures/gd_017_vlm_import.py` | — | 8 |
| `tools/diag_emb.py` | — | 8 |
| `tools/bench_fixtures/gd_015_heartbeat.py` | — | 7 |
| `tools/bench_fixtures/gd_002_hub_health.py` | — | 6 |
| `tools/bench_fixtures/gd_008_rag_count.py` | — | 6 |
| `tools/bench_fixtures/gd_009_null_emb.py` | — | 6 |
| `tools/bench_fixtures/gd_010_fts_search.py` | — | 6 |
| `tools/bench_fixtures/gd_011_dpo_count.py` | — | 6 |
| `tools/bench_fixtures/gd_012_traces_count.py` | — | 6 |
| `tools/bench_fixtures/gd_014_nssm_check.py` | — | 5 |
| `tools/bench_fixtures/gd_016_pt_files.py` | — | 5 |
| `tools/bench_fixtures/gd_018_ollama_ping.py` | — | 5 |
| `app/forge_tools_dynamic/__init__.py` | — | 2 |
| `app/services/__init__.py` | — | 2 |
| `tools/__init__.py` | — | 2 |
