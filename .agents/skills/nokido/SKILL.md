---
name: nokido
description: >
  Nokido Sovereign Hub — orchestrateur multi-agents local-first.
  Hub HTTP:8766, bridge stdio, RAG SQLite, 196+ modules forge_*.py,
  7 rôles locaux (Ollama), 8 cloud roles (groq/github/mistral),
  forge_task_queue, forge_roles, forge_trust_score, forge_mailbox.
  Mis à jour automatiquement après chaque git commit.
---

# Nokido — Knowledge Base pour IAs collaboratrices

## Architecture rapide
- Hub : `tools/nokido_hub.py` — Starlette :8766
- Bridge : `tools/mcp_stdio_bridge.py` — stdio → HTTP
- Rôles : `app/forge_roles.py` — PLANNER/EXECUTOR/REVIEWER/ROUTER/SUMMARIZER/SENTINEL/MONITOR
- Queue : `app/forge_task_queue.py` — SQLite persistant, Semaphore(2)
- RAG : `RAG/embeddings.db` — 100K+ chunks bge-m3 1024d
- Rescue : `tools/forge_rescue.py` — canal de secours admin on-demand

## Changelog automatique (post-commit)









































































































































































































































































































































































































































































































































































































































































































































































































































## Commit 0f75b22a — 2026-08-21 23:53
**feat(gui): enveloppe tracable par tuile - state mesure + provenance**

### Modules Python modifiés
- `app/web_hub/app.py`
- `app/web_hub/dashboard_html.py`
- `tests/nr/test_tuile_orpheline_nr.py`


## Commit e706dfa2 — 2026-08-21 23:47
**test(nr): effets forge_bench_http + forge_process_identity (cliquet satisfait)**

### Modules Python modifiés
- `tests/nr/test_bench_http_nr.py`
- `tests/nr/test_process_identity_nr.py`
- `tests/nr/test_tuile_orpheline_nr.py`
- `tools/ci_local.py`


## Commit e4e9a8ca — 2026-08-21 23:39
**feat(gui): gate NR zero tuile orpheline (doctrine live-only, niveau contract)**

### Modules Python modifiés
- `tests/nr/test_tuile_orpheline_nr.py`
- `tools/ci_local.py`


## Commit 6a7bccfe — 2026-08-21 23:34
**refactor(bench): _http_post factorise dans forge_bench_http (cliquet repare)**

### Modules Python modifiés
- `tools/forge_bench_http.py`
- `tools/forge_bfcl_runner.py`
- `tools/forge_humaneval_runner.py`
- `tools/forge_planbench_runner.py`
- `tools/forge_swebench_runner.py`
- `tools/forge_terminal_bench_runner.py`
- `tools/multi_llm_daemon.py`


## Commit 202e263e — 2026-08-21 22:58
**style(gate): marque muet-ok l'except de tri numerique (garde recidive)**

### Modules Python modifiés
- `tools/forge_capability_audit.py`


## Commit b55551e6 — 2026-08-21 22:56
**chore: artefacts auto-generes post-commit (SKILL, vitals gardes, STATS)**

### Documentation mise à jour
- `.agents/skills/nokido/SKILL.md`
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit b55551e6 — 2026-08-21 22:55
**chore: artefacts auto-generes post-commit (SKILL, vitals gardes, STATS)**

### Modules Python modifiés
- `tools/forge_capability_audit.py`


## Commit 73c71bbd — 2026-08-21 22:37
**feat(identite): signature d'appartenance au hub pour chaque process (phase 1)**

### Modules Python modifiés
- `app/forge_job_runner.py`
- `app/forge_process_identity.py`


## Commit d6d9272d — 2026-08-21 22:37
**fix(bench): durcit les runners HumanEval/BFCL contre les pannes mesurees du 21/08**

### Modules Python modifiés
- `tools/forge_bfcl_runner.py`
- `tools/forge_humaneval_runner.py`


## Commit b695a8b0 — 2026-08-21 02:10
**docs(release): env testpypi = regle Branch alpha, pas Tag v***

### Documentation mise à jour
- `docs/RELEASE.md`


## Commit ff1a22fa — 2026-08-21 01:54
**ci(release): repo=nokido, restrictions env, essai a blanc TestPyPI**

### Documentation mise à jour
- `docs/RELEASE.md`


## Commit 0b9116d9 — 2026-08-21 01:21
**fix(hub): timeout semantique RAGManager reellement strict + doc release**

### Modules Python modifiés
- `app/nokido_core.py`
- `tests/nr/test_rag_timeout_reel_nr.py`
- `tools/ci_local.py`

### Documentation mise à jour
- `docs/RELEASE.md`


## Commit 7fb730c1 — 2026-08-21 01:14
**fix(endocrine): release ecrivait dans une AUTRE base que read**

### Modules Python modifiés
- `app/forge_endocrine.py`
- `tests/nr/test_endocrine_multisource_nr.py`
- `tools/ci_local.py`


## Commit 181de06b — 2026-08-21 00:58
**fix(organes): le registre declarait a faire un cablage fait depuis le 29/07**

### Modules Python modifiés
- `app/forge_organ_agents.py`
- `tests/nr/test_organ_registre_nr.py`
- `tools/ci_local.py`


## Commit f3432d27 — 2026-08-21 00:50
**ci: inscrire test_routing_snn_nr dans PURE_TESTS**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit f36207bc — 2026-08-21 00:42
**test(routing): tests NR d'effet pour le contrat et l'etage SNN**

### Modules Python modifiés
- `app/forge_snn_router.py`
- `tests/nr/test_routing_snn_nr.py`


## Commit b4a7ab5d — 2026-08-21 00:34
**fix(snn): figer le backend LIF, un import optionnel changeait la structure**

### Modules Python modifiés
- `app/forge_snn_core.py`
- `app/forge_snn_router.py`


## Commit cf7e5f57 — 2026-08-21 00:28
**feat(routing): etage SNN L1 mesure, et contrat de decision commun**

### Modules Python modifiés
- `app/forge_llm_router_dt.py`
- `app/forge_routing_decision.py`
- `app/forge_snn_router.py`
- `tools/research/forge_spike_router_lite.py`


## Commit 4d9647ca — 2026-08-21 00:06
**fix(vector_index): metrique FAISS explicite (meme defaut qu'intent_router)**

### Modules Python modifiés
- `app/forge_vector_index.py`


## Commit 9c8f2c5f — 2026-08-21 00:03
**fix(routing): journaliser les chemins d'erreur muets du gate**

### Modules Python modifiés
- `app/forge_llm_router_dt.py`
- `app/forge_spike_router.py`
- `app/services/intent_router.py`


## Commit adff69c7 — 2026-08-21 00:00
**fix(routing): metrique FAISS, provider fantome, index reconstruit**

### Modules Python modifiés
- `app/forge_llm_router_dt.py`
- `app/forge_spike_router.py`
- `app/services/intent_router.py`


## Commit af6e4ad3 — 2026-08-20 13:45
**fix(regulation,rag,docs): reparer 5 NameError, la boucle drain, et brancher Cloudflare**

### Modules Python modifiés
- `app/forge_durable.py`
- `app/forge_embed_router.py`
- `app/forge_job_runner.py`
- `app/forge_llm_router.py`
- `app/forge_mcp_registry.py`
- `app/forge_resource_manager.py`
- `app/forge_service_rss_watch.py`
- `app/web_hub/auth.py`
- `app/web_hub/wired_routes.py`
- `tools/forge_cli_version_watch.py`
- `tools/forge_embed_auto_trigger.py`
- `tools/forge_env_to_vault.py`
- `tools/forge_ingest_github_repo.py`
- `tools/forge_ingest_llms_txt.py`
- `tools/forge_llama_keeper.py`
- `tools/forge_memory_index_compact.py`
- `tools/forge_scalene_optimize.py`
- `tools/forge_task_executor.py`
- `tools/nokido_hub.py`


## Commit d2de7cce — 2026-08-20 00:56
**perf(edge-scoring): cooccurrence via rag_fts indexe au lieu de LIKE full-scan (x69 mesure)**

### Modules Python modifiés
- `tests/nr/test_edge_scoring_cooccurrence_nr.py`
- `tools/forge_edge_scoring.py`


## Commit 61926c59 — 2026-08-20 00:40
**fix(scalene-optimize): run_job-able (intention), source lue du fichier reel, TimeoutError attrape**

### Modules Python modifiés
- `tests/nr/test_scalene_optimize_nr.py`
- `tools/forge_scalene_optimize.py`


## Commit 9a13cada — 2026-08-20 00:17
**feat(ollama): sonde d'inference REELLE (is_inference_alive) -- au-dela de api/tags/ps**

### Modules Python modifiés
- `app/forge_ollama_bridge.py`
- `tests/nr/test_ollama_inference_alive_nr.py`


## Commit c8c5e8c1 — 2026-08-20 00:08
**feat(profiler): scalene-optimize -- filtrer les lignes non-optimisables, envoyer la fonction englobante**

### Modules Python modifiés
- `tests/nr/test_scalene_optimize_nr.py`
- `tools/forge_scalene_optimize.py`


## Commit 2d8ad80a — 2026-08-18 15:10
**feat(routeur): cabler les seize chaines sur la mesure, et factoriser les sondes**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tests/nr/test_census_free_tier_nr.py`
- `tests/nr/test_llm_router_perime_nr.py`
- `tools/forge_endpoint_commun.py`
- `tools/forge_endpoint_profiling.py`
- `tools/forge_local_llm_bringup.py`
- `tools/forge_tool_call_probe.py`


## Commit 1c321ef4 — 2026-08-18 14:26
**feat(outils): mesurer qui APPELLE un outil, pas qui l'annonce**

### Modules Python modifiés
- `tests/nr/test_endpoint_profiling_nr.py`
- `tools/forge_tool_call_probe.py`


## Commit 0c78f115 — 2026-08-18 14:13
**feat(profiling): mesurer la specialite d'un endpoint pour lui proposer un role**

### Modules Python modifiés
- `tests/nr/test_endpoint_profiling_nr.py`
- `tools/forge_endpoint_profiling.py`


## Commit 6f6e2b1b — 2026-08-18 14:10
**feat(hf): trancher is_free par l'appel — le champ existe, aucun modele marque**

### Modules Python modifiés
- `tests/nr/test_census_free_tier_nr.py`
- `tools/forge_hf_free_scan.py`


## Commit 5fd1818b — 2026-08-18 13:54
**feat(census): comparer deux passes et nommer ce qui a bouge**

### Modules Python modifiés
- `tools/forge_free_tier_census.py`


## Commit 80fd7f97 — 2026-08-18 13:50
**feat(census): compter ce qui est joignable en palier gratuit, et suivre les catalogues**

### Modules Python modifiés
- `tools/forge_free_tier_census.py`


## Commit 276c6b50 — 2026-08-18 13:44
**fix(local): prouver la vie avec le modele le plus leger**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit 7c3fcc82 — 2026-08-18 13:34
**fix(local): un modele qui charge n'est pas un modele mort**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit 7c3fcc82 — 2026-08-18 13:33
**fix(local): un modele qui charge n'est pas un modele mort**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit 45059834 — 2026-08-18 13:29
**fix(lmstudio): lire le jeton du coffre, sinon 401 se lit comme une mort**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit 57cee3d0 — 2026-08-18 13:18
**fix(local): ne jamais lancer un serveur en jetant sa sortie**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit ab71a0f8 — 2026-08-18 13:14
**fix(local): borner l'attente, et ne pas confondre chargement et mort**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit ab71a0f8 — 2026-08-18 13:14
**fix(local): borner l'attente, et ne pas confondre chargement et mort**

### Modules Python modifiés
- `tools/forge_local_llm_bringup.py`


## Commit 19ab85d0 — 2026-08-18 13:00
**fix(ollama): le fallback absolu n'existait que s'il avait deja servi**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 1aafe1e0 — 2026-08-18 12:58
**feat(sondes): tester TOUT le parc, pas l'echantillon qui m'arrangeait**

### Modules Python modifiés
- `tools/forge_provider_catalogue.py`
- `tools/forge_router_slots_probe.py`


## Commit 41f0ea0c — 2026-08-18 12:52
**fix(gemini): router vers la seule famille qui repond encore (flash-lite)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_llm_router.py`


## Commit b65b04a8 — 2026-08-18 12:50
**feat(gemini): essayer les autres familles, un 429 vise un modele pas le compte**

### Modules Python modifiés
- `tools/forge_gemini_models_sync.py`


## Commit f038a776 — 2026-08-18 12:49
**feat(catalogue): tester les cles encore en clair avant de les ecrire au coffre**

### Modules Python modifiés
- `tools/forge_provider_catalogue.py`


## Commit 7507d156 — 2026-08-18 12:26
**fix(probe): une reponse vide n'est pas un cadavre**

### Modules Python modifiés
- `tools/forge_router_slots_probe.py`


## Commit 1ad6c02f — 2026-08-18 12:25
**feat(catalogue): rearmer une cle que la sonde vient d'innocenter**

### Modules Python modifiés
- `tools/forge_provider_catalogue.py`


## Commit ba2bea0a — 2026-08-18 12:23
**fix(providers): les cles etaient innocentes, ce sont les modeles qui sont morts**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_llm_router.py`
- `tests/nr/test_vault_outils_nr.py`
- `tools/forge_provider_catalogue.py`


## Commit 0725af74 — 2026-08-18 12:04
**test(vault+gemini): couvrir les deux outils ajoutes, avant le rouge cette fois**

### Modules Python modifiés
- `tests/nr/test_vault_outils_nr.py`


## Commit 6c794ba7 — 2026-08-18 12:02
**feat(vault): poser une CONFIG au coffre, avec refus explicite des secrets**

### Modules Python modifiés
- `tools/forge_vault_set_config.py`


## Commit 041dfe73 — 2026-08-18 11:59
**feat(gemini): confronter les modeles declares au catalogue reel, et les essayer**

### Modules Python modifiés
- `tools/forge_gemini_models_sync.py`


## Commit b652d768 — 2026-08-18 11:55
**fix(probe): ma sonde declarait morts treize providers vivants**

### Modules Python modifiés
- `tools/forge_router_slots_probe.py`


## Commit a7620a53 — 2026-08-18 11:54
**feat(probe): borner la passe live par un budget de temps**

### Modules Python modifiés
- `tools/forge_router_slots_probe.py`


## Commit a040cb7f — 2026-08-18 11:52
**fix(router): cesser de router vers un backend retire (7 slots GitHub Models)**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tests/nr/test_llm_router_perime_nr.py`
- `tools/forge_router_slots_probe.py`


## Commit 2e947020 — 2026-08-18 11:39
**feat(probe): trancher par une inference reelle si GitHub Models repond encore**

### Modules Python modifiés
- `tools/forge_token_probe.py`


## Commit ab2467f0 — 2026-08-18 11:21
**test(vault): couvrir les trois outils de coffre (cliquet NR rouge)**

### Modules Python modifiés
- `tests/nr/test_vault_outils_nr.py`


## Commit f09c59de — 2026-08-18 11:18
**docs(probe): nommer l'angle mort — la colonne models ne discrimine rien**

### Modules Python modifiés
- `tools/forge_token_probe.py`


## Commit 3a7e6e41 — 2026-08-18 11:16
**feat(vault): sonder les droits reels d'un jeton, et le ranger sous son vrai nom**

### Modules Python modifiés
- `tools/forge_token_probe.py`
- `tools/forge_vault_copy_key.py`


## Commit 230f301c — 2026-08-18 10:51
**feat(vault): retirer UNE cle du clair, coffre verifie avant**

### Modules Python modifiés
- `tools/forge_env_drop_key.py`


## Commit fc2de8b1 — 2026-08-18 10:35
**test(dup): ne pas figer l'empreinte, c'est la surface entiere qu'on perd**

### Modules Python modifiés
- `tests/nr/test_dup_detector_nr.py`


## Commit 0a969989 — 2026-08-18 10:26
**test(dup): couvrir filtres, seuils et sortie du detecteur (42,9 -> 100 %)**

### Modules Python modifiés
- `tests/nr/test_dup_detector_nr.py`


## Commit eda8a35f — 2026-08-18 10:23
**test(release-lock): couvrir la LECTURE de la composition (28,6 -> 100 %)**

### Modules Python modifiés
- `tests/nr/test_release_lock_provenance_nr.py`


## Commit 36308c99 — 2026-08-18 10:18
**test(bisect): tester l'EFFET de la sync, pas le texte du code (8,3 -> 100 %)**

### Modules Python modifiés
- `tests/nr/test_bisect_nr.py`


## Commit 1aaa2c22 — 2026-08-18 10:08
**docs(mutation): rejouer le cliquet dans un worktree, sans compte privilegie**

### Modules Python modifiés
- `tools/forge_mutation_ratchet.py`


## Commit 2adad69d — 2026-08-18 09:48
**test(golden): une regle appel_interdit n'a pas besoin de kwarg**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apprises_nr.py`


## Commit 2adad69d — 2026-08-18 09:48
**test(golden): une regle appel_interdit n'a pas besoin de kwarg**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apprises_nr.py`


## Commit 20a52afb — 2026-08-18 09:45
**fix(mutation): juger la surface golden sur TOUTES ses suites**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apoptose_nr.py`
- `tests/nr/test_golden_rules_apprises_nr.py`
- `tools/forge_mutation_ratchet.py`


## Commit 26d9cd23 — 2026-08-18 09:39
**feat(distiller): traiter un LOT de correctifs, et exiger une substitution**

### Modules Python modifiés
- `tests/nr/test_rule_distiller_nr.py`
- `tools/forge_rule_distiller.py`


## Commit 76f2cdf6 — 2026-08-18 09:35
**feat(golden): distiller un garde depuis un correctif reel (boucle echec -> garde, 2/2)**

### Modules Python modifiés
- `tests/nr/test_rule_distiller_nr.py`
- `tools/forge_golden_rules_ast.py`
- `tools/forge_rule_distiller.py`


## Commit 4fdc1642 — 2026-08-18 09:30
**feat(golden): appliquer des regles APPRISES declaratives (boucle echec -> garde, 1/2)**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apprises_nr.py`
- `tools/forge_golden_rules_ast.py`


## Commit 95162f44 — 2026-08-18 09:21
**fix(golden): nommer une date de gel illisible et ne calculer les ages qu'une fois**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apoptose_nr.py`
- `tools/forge_golden_rules_ast.py`


## Commit e8ae389b — 2026-08-18 09:19
**chore(golden): marquer muet-ok le chemin d'erreur deja signale en aval**

### Modules Python modifiés
- `tools/forge_golden_rules_ast.py`


## Commit 72ad4a00 — 2026-08-18 09:19
**feat(golden): dater le socle et nommer les regles candidates a l'apoptose**

### Modules Python modifiés
- `tests/nr/test_golden_rules_apoptose_nr.py`
- `tools/forge_golden_rules_ast.py`


## Commit 96cf5fdb — 2026-08-18 09:04
**feat(ci): registre de vitalite des gardes (anti-anergie)**

### Modules Python modifiés
- `tests/nr/test_ci_local_vitalite_nr.py`
- `tools/ci_local.py`


## Commit baa65961 — 2026-08-18 01:42
**fix(mutation): dire POURQUOI une suite est jugee rouge, et lui donner un basetemp propre**

### Modules Python modifiés
- `tools/forge_mutation_test.py`


## Commit 521892c5 — 2026-08-18 01:35
**fix(archeo): NameError a l import de forge_constituent_archaeology + garde d ordre**

### Modules Python modifiés
- `tests/nr/test_archeologie_outils_nr.py`
- `tools/forge_constituent_archaeology.py`


## Commit 13b5dc48 — 2026-08-18 01:28
**fix(nr): errors=replace sur les subprocess git des tests d archeologie**

### Modules Python modifiés
- `tests/nr/test_archeologie_outils_nr.py`


## Commit 466c41ce — 2026-08-18 01:28
**fix(nr): errors=replace sur les subprocess git des tests d archeologie**

### Modules Python modifiés
- `tests/nr/test_archeologie_outils_nr.py`

### Documentation mise à jour
- `.agents/skills/nokido/SKILL.md`
- `README.md`
- `docs/ROADMAP.md`
- `docs/skills/nokido/SKILL.md`


## Commit 6ce255e6 — 2026-08-18 01:27
**fix(ci): reparer les 2 gates rouges (duplication + couverture NR) et le cliquet de mutation mort**

### Modules Python modifiés
- `tests/nr/test_archeologie_outils_nr.py`
- `tools/ci_local.py`
- `tools/forge_archaeology.py`
- `tools/forge_archeo_socle.py`
- `tools/forge_blind_spot_index.py`
- `tools/forge_capability_contracts.py`
- `tools/forge_capability_execution_trace.py`
- `tools/forge_constituent_archaeology.py`
- `tools/forge_history_census.py`
- `tools/forge_memory_compactor.py`
- `tools/forge_memory_forensics.py`
- `tools/forge_mutation_ratchet.py`
- `tools/forge_mutation_test.py`
- `tools/forge_orphan_branches.py`
- `tools/forge_provider_reachability.py`
- `tools/forge_ui_coherence.py`


## Commit 62a531a7 — 2026-08-18 00:48
**feat(capacites): contrat par capacite sur toute la surface atteignable**

### Modules Python modifiés
- `tools/forge_capability_contracts.py`
- `tools/forge_ui_manifest.py`


## Commit 911694df — 2026-08-18 00:41
**feat(ui): distinguer transport, application et capacite (etat degraded)**

### Modules Python modifiés
- `app/web_hub/manifest_cards.py`
- `tools/forge_ui_manifest.py`


## Commit 7e7feb29 — 2026-08-18 00:34
**fix(ui): une action n'est cliquable que si sa destination est verifiee**

### Modules Python modifiés
- `app/web_hub/manifest_cards.py`
- `tools/forge_ui_manifest.py`


## Commit 3a4602a2 — 2026-08-18 00:27
**perf(ui): l'interface ne paie plus 1,8 s de sondes ni une ecriture disque**

### Modules Python modifiés
- `app/web_hub/manifest_cards.py`
- `tools/forge_ui_manifest.py`


## Commit e8150d8a — 2026-08-18 00:25
**feat(ui): garde qui detecte une tuile mentant sur l'etat du systeme**

### Modules Python modifiés
- `tools/forge_ui_coherence.py`


## Commit f8fa6eae — 2026-08-18 00:11
**fix(ui): graph ecoute sur 7474, le manifest sondait 7420**

### Modules Python modifiés
- `tools/forge_ui_manifest.py`


## Commit 94235036 — 2026-08-17 23:20
**fix(hub): soumettre /admin/restart au ring, et cesser de promettre un respawn**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 002d10fe — 2026-08-17 23:17
**refactor(scm): app pointe vers NokidoMCP**

### Modules Python modifiés
- `app/bootstrap.py`
- `app/forge_auto_pilot.py`
- `app/forge_body_world_model.py`
- `app/forge_inspector.py`
- `app/forge_lifecycle_tool.py`
- `app/forge_nervous_map.py`
- `app/forge_ps_agent.py`
- `app/forge_service_capabilities.py`
- `app/forge_service_watchdog.py`
- `app/forge_web_service.py`
- `app/mcp_bridge.py`
- `app/mcp_server_tools.py`


## Commit 002d10fe — 2026-08-17 23:14
**refactor(scm): app pointe vers NokidoMCP**

### Modules Python modifiés
- `tools/apply_mcp_buffer_patch.py`
- `tools/build_bge_m3_dml.py`
- `tools/forge_db_compact_full.py`
- `tools/forge_ensure_service.py`
- `tools/forge_gen_tls_cert.py`
- `tools/forge_hub_reload.py`
- `tools/forge_install_boot_mount.py`
- `tools/forge_log_guard.py`
- `tools/forge_mcp_proxy.py`
- `tools/forge_nssm_env_fix.py`
- `tools/forge_process_manager.py`
- `tools/forge_pyspy_profiler.py`
- `tools/forge_rescue.py`
- `tools/forge_setup_exegol_token.py`
- `tools/mcp_stdio_bridge.py`
- `tools/nokido_cutover_verify.py`
- `tools/nokido_deep_rename.py`
- `tools/nokido_hub.py`
- `tools/nokido_launcher.py`
- `tools/nokido_rename.py`

### Documentation mise à jour
- `tools/SERVICES.md`


## Commit b7b35161 — 2026-08-17 23:07
**feat(rename): mode cible sur un seul terme, avec remplacement explicite**

### Modules Python modifiés
- `tools/nokido_deep_rename.py`


## Commit 7a77f313 — 2026-08-17 23:04
**chore(rename): lever la protection de LaForgeMCP, devenue caduque**

### Modules Python modifiés
- `tools/nokido_deep_rename.py`


## Commit da1f30e1 — 2026-08-17 22:59
**fix(stack): le Restart attend la fin REELLE du stop, plus la chute d'un port**

### Modules Python modifiés
- `tools/nokido_launcher.py`


## Commit 38b12f1c — 2026-08-17 22:31
**chore(retention): borner loop_lag.log, 47 Mo sans aucune purge**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit 7e967ab4 — 2026-08-17 22:29
**fix(hub): deporter le dernier chemin d'execution synchrone hors de l'event loop**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit b7b369f2 — 2026-08-17 22:06
**fix(scm): ne plus imprimer en clair les valeurs sensibles recopiees**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit 5784973a — 2026-08-17 21:45
**feat(veille): rattrapage horaire branche sur la boucle autonome**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`


## Commit 636b6acb — 2026-08-17 21:39
**perf(veille): attendre la fin reelle du repos au lieu de bruler des passes**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`
- `tools/forge_veille_gap_run.py`


## Commit a176fd53 — 2026-08-17 21:27
**fix(jobs): ne pas confondre silence legitime et job mort**

### Modules Python modifiés
- `tools/forge_job_liveness.py`


## Commit 66db8f78 — 2026-08-17 21:24
**feat(jobs): controler qu'un job deporte travaille vraiment**

### Modules Python modifiés
- `tools/forge_job_liveness.py`


## Commit 4e4c8f73 — 2026-08-17 21:21
**fix(veille): un domaine au repos n'est plus lu comme un echec de campagne**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit d91bab94 — 2026-08-17 21:17
**chore(veille): journal du rattrapage lisible en direct**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 8c0b0089 — 2026-08-17 21:15
**fix(veille): attendre le verrou d'ecriture au lieu d'abandonner l'ingestion**

### Modules Python modifiés
- `app/forge_web_fetch.py`
- `tools/forge_veille_gap_recover.py`


## Commit 337356cc — 2026-08-17 21:10
**fix(veille): respecter le 429 au lieu de le marteler**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`
- `tools/forge_veille_gap_run.py`


## Commit 162479c0 — 2026-08-17 21:05
**fix(veille): le marquage des URLs mortes ne tue plus le job**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 4bee6b12 — 2026-08-17 20:59
**chore(retention): purger la marque des URLs mortes apres 180 jours**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit a36a5f12 — 2026-08-17 20:56
**fix(veille): une URL morte n'est plus confondue avec un domaine en difficulte**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 6a3e536f — 2026-08-17 20:52
**fix(veille): agent navigateur, les CDN refusaient le fetch direct**

### Modules Python modifiés
- `app/forge_web_fetch.py`


## Commit 6c1b4ecd — 2026-08-17 20:44
**fix(tray): le Start ne se saborde plus en Stop, et l'icone survit au lanceur**

### Modules Python modifiés
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit b5d7289b — 2026-08-17 20:29
**feat(scm): renommer aussi les services sous compte utilisateur, mot de passe saisi par l'owner**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit a14abcf9 — 2026-08-17 20:26
**fix(veille): rotation par domaine et quarantaine, un domaine ne monopolise plus la passe**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 86660589 — 2026-08-17 20:24
**feat(audit): tracer nominativement l'ecriture et l'execution dans le journal du videur**

### Modules Python modifiés
- `app/forge_hub_gate.py`
- `app/forge_videur.py`


## Commit 02290d14 — 2026-08-17 20:02
**chore(tray): marquer les chemins d'erreur best-effort comme deliberes**

### Modules Python modifiés
- `tools/nokido_tray.py`


## Commit c0de2972 — 2026-08-17 20:02
**fix(tray): la raison d'un mode illisible remonte dans le menu**

### Modules Python modifiés
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit e7c0d49c — 2026-08-17 20:01
**fix(tray+launcher): le stop tuait le tray, le mode etait lu sans jeton ni parseur**

### Modules Python modifiés
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit 2d9d4ba5 — 2026-08-17 19:50
**fix(launcher): tray verifie, journalise, et lance avec l'interpreteur du projet**

### Modules Python modifiés
- `tools/nokido_launcher.py`


## Commit e6835ddd — 2026-08-17 19:46
**feat(launcher): logo NOKIDO en ASCII dans le panneau de controle**

### Modules Python modifiés
- `tools/nokido_launcher.py`


## Commit 0d990ca1 — 2026-08-17 19:24
**fix(scm): les dependances suivent le renommage, les fantomes sont signalees**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit 8d049775 — 2026-08-17 19:22
**fix(scm): translater DisplayName et nettoyer le service partiel apres echec**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit 406edd50 — 2026-08-17 19:20
**fix(scm): decodage nssm tranche sur les octets nuls, pas sur un sondage**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit 8b856b30 — 2026-08-17 19:18
**fix(scm): renommage services, sondage d'encodage trace et subprocess tolerant**

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit 15a70c10 — 2026-08-17 19:17
**feat(scm): outil de renommage des services LaForge-* en Nokido-***

### Modules Python modifiés
- `tools/nokido_rename_services.py`


## Commit d70cb541 — 2026-08-16 21:06
**feat(archeologie): couverture FTS reelle -- 39 pourcent de l index pointe dans le vide**

### Modules Python modifiés
- `tools/forge_rag_coverage_audit.py`


## Commit 9d351e35 — 2026-08-16 21:00
**fix(archeologie): la jointure FTS demandait 107 heures**

### Modules Python modifiés
- `tools/forge_rag_coverage_audit.py`


## Commit ce4fc20d — 2026-08-16 20:55
**fix(veille): les pages courtes ne pouvaient PAS etre rattrapees par crawl**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 9fa678f2 — 2026-08-16 20:47
**fix(memoire): huit modules declares perdus avaient seulement demenage**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 8dca66d5 — 2026-08-16 20:44
**feat(archeologie): audit de couverture du RAG -- ce que le corpus porte vraiment**

### Modules Python modifiés
- `tools/forge_rag_coverage_audit.py`


## Commit 5020d02c — 2026-08-16 20:30
**fix(capacites): la preuve historique rendait zero en silence**

### Modules Python modifiés
- `tools/forge_capability_crosswalk.py`


## Commit 84d42167 — 2026-08-16 20:28
**feat(capacites): crosswalk CAP-* -- capacite, handler, ring, test, commit**

### Modules Python modifiés
- `tools/forge_capability_crosswalk.py`


## Commit cd99adf5 — 2026-08-16 20:23
**fix(gardes): trois gardes qui savaient sans pouvoir le dire, ou l inverse**

### Modules Python modifiés
- `app/forge_lane_admission.py`
- `app/forge_mcp_registry.py`
- `app/forge_snapshot.py`
- `tools/bash_guard.py`
- `tools/forge_governed_edit.py`
- `tools/hook_capability_gate.py`


## Commit 7890c207 — 2026-08-16 20:05
**perf(veille): borne de debit sur le rattrapage (1 s entre crawls)**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit d617413d — 2026-08-16 19:26
**fix(hub): list_providers gelait l event-loop -- ~300 lectures de coffre synchrones**

### Modules Python modifiés
- `app/forge_key_rotation.py`
- `app/forge_llm_router.py`
- `app/forge_mcp_registry.py`


## Commit 98610cfd — 2026-08-16 18:54
**fix(memoire): la compaction datait les lecons par le fichier lie, pas par le libelle**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit af24a5b7 — 2026-08-16 18:45
**feat(veille): le job de rattrapage enchaine ses passes jusqu a epuisement**

### Modules Python modifiés
- `tools/forge_veille_gap_run.py`


## Commit e2018b48 — 2026-08-16 18:44
**fix(veille): rattrapage bloque par le gate et masque par un verdict menteur**

### Modules Python modifiés
- `tools/forge_memory_staleness.py`
- `tools/forge_veille_gap_recover.py`


## Commit 18472858 — 2026-08-16 18:41
**feat(memoire): detecteur de memoire perimee par confrontation au reel**

### Modules Python modifiés
- `tools/forge_memory_staleness.py`


## Commit 7c81f54c — 2026-08-16 18:34
**fix(memoire): ledger resolvable hors HOME + garde anti-faux-positif renommage**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`
- `tools/forge_memory_ledger.py`


## Commit 6de0cedb — 2026-08-16 18:13
**feat(memoire): forensics des .md — perdues, orphelines, recuperables**

### Modules Python modifiés
- `tools/forge_memory_forensics.py`


## Commit 0bf86de5 — 2026-08-16 17:57
**perf(hook): le stop-hook CI ne sonde plus l API sur un HEAD non pousse**

### Modules Python modifiés
- `tools/forge_ci_stop_hook.py`


## Commit b67fc5b3 — 2026-08-16 17:02
**feat(veille): wrapper detache pour le rattrapage de veille**

### Modules Python modifiés
- `tools/forge_veille_gap_run.py`


## Commit 4dbe4feb — 2026-08-16 17:00
**perf(veille): scan du gap en une requete, plus 2408 LIKE**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit c8ae32f5 — 2026-08-16 16:57
**fix(veille): router le crawl de rattrapage via le verbe MCP du hub**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit 7327304a — 2026-08-16 16:52
**fix(veille): posseder une source = en avoir le CONTENU, pas la fiche biblio**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 5d4319c2 — 2026-08-16 16:49
**feat(veille): detecter et recuperer le contenu de veille manquant en RAG**

### Modules Python modifiés
- `tools/forge_veille_gap_recover.py`


## Commit bb748906 — 2026-08-16 14:51
**feat(archeologie): Capability Execution Trace — ou meurt une capacite**

### Modules Python modifiés
- `tools/forge_capability_execution_trace.py`


## Commit 245b3705 — 2026-08-16 14:40
**feat(archeologie): dimension SWARM de la reachability provider**

### Modules Python modifiés
- `tools/forge_provider_reachability.py`


## Commit 8d44fdb1 — 2026-08-16 14:23
**feat(archeologie): dimension REACHABILITY des providers**

### Modules Python modifiés
- `tools/forge_provider_reachability.py`


## Commit 3ca3c572 — 2026-08-16 13:46
**feat(hygiene): raccorder le worktree orphelin laforge-cowork**

### Modules Python modifiés
- `tools/forge_fix_worktree_link.py`


## Commit 3fc2e7e0 — 2026-08-16 13:44
**feat(archeologie): extraire fidelement un fichier d une branche non mergee**

### Modules Python modifiés
- `tools/forge_recover_from_branch.py`


## Commit ff5b3dcc — 2026-08-16 13:06
**fix(archeologie): comparer a la branche courante, pas a main**

### Modules Python modifiés
- `tools/forge_orphan_branches.py`


## Commit ba3161bc — 2026-08-16 13:04
**feat(archeologie): traquer le patrimoine coince dans les branches non mergees**

### Modules Python modifiés
- `tools/forge_orphan_branches.py`


## Commit a12257d2 — 2026-08-16 13:02
**fix(router): nommer la vraie cause d indisponibilite, pas RPM limit**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit 3736e350 — 2026-08-16 12:57
**fix(post-commit): circuit breaker anti-avalanche vers le hub**

### Modules Python modifiés
- `tests/test_forge_post_commit_breaker.py`
- `tools/forge_post_commit.py`


## Commit 82082612 — 2026-08-16 12:07
**chore(dist): tracker l application desktop forge_desktop pour le distribuable**

### Modules Python modifiés
- `forge_desktop/__init__.py`
- `forge_desktop/core/__init__.py`
- `forge_desktop/core/canvas_nodes.py`
- `forge_desktop/core/desktop_bridge.py`
- `forge_desktop/core/gui_mmap.py`
- `forge_desktop/core/llm_interactions.py`
- `forge_desktop/core/mcp_connector.py`
- `forge_desktop/core/palette_hub_connector.py`
- `forge_desktop/main.py`
- `forge_desktop/views/__init__.py`
- `forge_desktop/views/cerberus_view.py`
- `forge_desktop/views/consciousness_view.py`
- `forge_desktop/views/dashboard_view.py`
- `forge_desktop/views/debate_view.py`
- `forge_desktop/views/debug_loop_view.py`
- `forge_desktop/views/external_forge_view.py`
- `forge_desktop/views/forge_os_canvas.py`
- `forge_desktop/views/graph_canvas_view.py`
- `forge_desktop/views/interaction_view.py`
- `forge_desktop/views/main_window.py`


## Commit 82082612 — 2026-08-16 12:07
**chore(dist): tracker l application desktop forge_desktop pour le distribuable**

### Modules Python modifiés
- `ctf/agents/__init__.py`
- `ctf/agents/ctf_planner.py`
- `ctf/agents/ctf_rag.py`
- `ctf/agents/ctf_validator.py`
- `ctf/agents/forge_adaptive_pwn.py`
- `ctf/agents/forge_ctf_adaptive.py`
- `ctf/agents/forge_ctf_agent.py`
- `ctf/agents/forge_ctf_brain.py`
- `ctf/agents/forge_cyber_pivot.py`
- `ctf/agents/forge_cyber_pivot_engine.py`
- `ctf/auto/auto_Circles.py`
- `ctf/auto/auto_Lost_Mind.py`
- `ctf/auto/auto_No_Time.py`
- `ctf/auto/auto_No_Time_Reg.py`
- `ctf/auto/auto_Python_GC.py`
- `ctf/auto/auto_Save_Tristate.py`
- `ctf/auto/auto_circles2.py`
- `ctf/auto/auto_circles_ocr.py`
- `ctf/auto/auto_circles_pix.py`
- `ctf/auto/auto_jack_test.py`

### Documentation mise à jour
- `ctf/README.md`


## Commit 28991cc5 — 2026-08-16 12:06
**chore(dist): exclure 8 solvers CTF casses du distribuable**

### Modules Python modifiés
- `ctf/fixes/_patch_py2fixes.py`
- `ctf/solvers/last3_Lottery.py`
- `ctf/solvers/mr_rusty_road.py`
- `ctf/solvers/r4_rusty_road.py`
- `ctf/solvers/r6_rusty_road.py`
- `ctf/solvers/r_feather.py`
- `ctf/solvers/runner_almost_xor.py`
- `ctf/tests/verify_mental_poker.py`


## Commit c9e94ec5 — 2026-08-16 11:28
**fix(mutation): attendre la coroutine du backend souverain**

### Modules Python modifiés
- `app/forge_self_mutation.py`


## Commit adafb1c1 — 2026-08-16 11:27
**fix(mutation): appel local direct quand aucun slot n est eligible**

### Modules Python modifiés
- `app/forge_self_mutation.py`


## Commit 93a16eaf — 2026-08-16 11:22
**fix(mutation): imposer le local pour generer les mutations**

### Modules Python modifiés
- `app/forge_self_mutation.py`


## Commit dcadefd4 — 2026-08-16 11:00
**fix(backends): normaliser l adresse Ollama et nommer la vraie cause**

### Modules Python modifiés
- `tools/forge_mutation_run.py`
- `tools/forge_warm_code_model.py`


## Commit 672e6d5f — 2026-08-16 10:59
**feat(backends): chargement detache du modele de code**

### Modules Python modifiés
- `tools/forge_warm_code_model.py`


## Commit b3585b8d — 2026-08-16 10:54
**feat(backends): commande warm — rendre un modele resident**

### Modules Python modifiés
- `tools/forge_backend_power.py`


## Commit 1218c546 — 2026-08-16 10:48
**feat(mutation): remettre en service la boucle d auto-amelioration**

### Modules Python modifiés
- `app/forge_self_mutation.py`
- `tests/test_forge_self_mutation.py`
- `tools/forge_mutation_run.py`


## Commit 62153fbb — 2026-08-16 10:38
**feat(archeologie): cibler un sous-chemin, pas seulement une racine**

### Modules Python modifiés
- `tools/forge_blind_spot_index.py`


## Commit 734a9d97 — 2026-08-16 10:37
**feat(archeologie): qualifier nominativement le code non versionne**

### Modules Python modifiés
- `tools/forge_blind_spot_index.py`


## Commit a0a822db — 2026-08-16 10:34
**feat(archeologie): rendre visible l angle mort et remonter les capacites perdues**

### Modules Python modifiés
- `tools/forge_blind_spot_index.py`
- `tools/forge_capability_recovery.py`
- `tools/forge_history_census.py`


## Commit c8de41fd — 2026-08-16 10:23
**feat(archeologie): capturer le motif de chaque suppression**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit 1e1c336c — 2026-08-16 10:21
**feat(archeologie): classer les capacites perdues par cout investi**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit 4dcba13d — 2026-08-16 10:18
**fix(archeologie): un clone accessible prime sur un chemin refuse**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit 2bcb9e8c — 2026-08-16 10:08
**fix(archeologie): la migration n est pas une mort**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit bc98a7bd — 2026-08-16 10:05
**feat(archeologie): taux de survie par mois + depots refuses declares**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit dd60f4f6 — 2026-08-16 10:03
**fix(archeologie): focus par date d auteur, pas date de committer**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit 98c3d418 — 2026-08-16 10:02
**feat(archeologie): census Phase 7 de l histoire git complete**

### Modules Python modifiés
- `tools/forge_history_census.py`


## Commit fa1d0a27 — 2026-08-16 09:43
**fix(archeologie): trois faux positifs mesures, dont une borne qui coupait le present**

### Modules Python modifiés
- `tests/nr/test_constituent_archaeology_nr.py`
- `tools/forge_capability_lineage.py`
- `tools/forge_constituent_archaeology.py`
- `tools/forge_reachability_ledger.py`


## Commit b66dd9eb — 2026-08-16 09:39
**feat(archeologie): Phases 7 et 8 - lignees chronologiques et registre d'atteignabilite**

### Modules Python modifiés
- `tests/nr/test_capability_lineage_nr.py`
- `tests/nr/test_constituent_archaeology_nr.py`
- `tests/nr/test_reachability_ledger_nr.py`
- `tools/forge_capability_lineage.py`
- `tools/forge_constituent_archaeology.py`
- `tools/forge_reachability_ledger.py`


## Commit 1e4739fd — 2026-08-16 09:27
**fix(bridge): chaque agent stdio presente SON jeton, plus celui de BRIDGE**

### Modules Python modifiés
- `tests/nr/test_bridge_identite_nr.py`
- `tools/mcp_stdio_bridge.py`


## Commit 9f981112 — 2026-08-16 09:16
**fix(archeologie): plus aucun chemin d'erreur muet dans la Phase 6**

### Modules Python modifiés
- `tools/forge_constituent_archaeology.py`


## Commit 41f65aa6 — 2026-08-16 09:15
**feat(archeologie): Phase 6 - archeologie des CONSTITUANTS, pas des fichiers**

### Modules Python modifiés
- `tests/nr/test_constituent_archaeology_nr.py`
- `tools/forge_constituent_archaeology.py`


## Commit ffab00ac — 2026-08-16 09:06
**fix(anti-regression): une forme d'erreur ne vaut pas contrat qui bascule**

### Modules Python modifiés
- `tools/forge_capability_ratchet.py`


## Commit 57c9dbc5 — 2026-08-16 08:48
**fix(anti-regression): une action de tool n'est pas une capacite muette**

### Modules Python modifiés
- `tests/nr/test_capability_ratchet_nr.py`
- `tools/forge_capability_ratchet.py`


## Commit 84654187 — 2026-08-16 08:45
**test(anti-regression): socle de 166 capacites + preuve par regression injectee**

### Modules Python modifiés
- `tests/nr/test_capability_ratchet_nr.py`


## Commit 47c8cea5 — 2026-08-16 08:43
**fix(anti-regression): garanti = nom du tool ET usage etabli**

### Modules Python modifiés
- `tools/forge_capability_ratchet.py`


## Commit ec550de7 — 2026-08-16 08:42
**feat(anti-regression): cliquet de capacites sur les contrats deja enregistres**

### Modules Python modifiés
- `tools/forge_capability_ratchet.py`


## Commit 0c776ceb — 2026-08-15 22:01
**fix(recon): retire vraiment le hook recon_silo fantome de _post_scan**

### Modules Python modifiés
- `app/forge_dispatch_network.py`


## Commit eb31670a — 2026-08-15 21:57
**fix(recon,ctf): retire le hook recon_silo fantome + dit la vraie raison launcher**

### Modules Python modifiés
- `app/web_hub/launcher.py`


## Commit 32f6389c — 2026-08-15 21:44
**fix(test): rends le test axe4 hermetique (arbre synthetique, ROOT deplace)**

### Modules Python modifiés
- `tests/nr/test_antiregression_outils_nr.py`


## Commit 611c8a92 — 2026-08-15 21:32
**style(sweep): marque muet-ok les skips de fichiers illisibles (gate recidive)**

### Modules Python modifiés
- `tools/forge_regression_sweep.py`


## Commit e66fe60e — 2026-08-15 21:31
**feat(sweep): axe 4 - backend cable supprime (angle mort import dynamique)**

### Modules Python modifiés
- `tests/nr/test_antiregression_outils_nr.py`
- `tools/forge_regression_sweep.py`


## Commit 0f799235 — 2026-08-15 20:14
**fix(ui): corriger le pretexte perime 'Exegol absent' pour CTF/recon**

### Modules Python modifiés
- `app/web_hub/manifest_cards.py`


## Commit 7657446c — 2026-08-15 19:54
**feat(archeologie): Phases 3 et 4 -- crosswalk intention <-> code <-> vestige**

### Modules Python modifiés
- `tests/nr/test_archaeology_conversations_nr.py`
- `tools/forge_archaeology_conversations.py`


## Commit 204931ae — 2026-08-15 19:34
**fix(archeologie): resorber le clone _git -- le cliquet duplication avait raison**

### Modules Python modifiés
- `tests/nr/test_archaeology_nr.py`
- `tools/forge_archaeology_enrich.py`


## Commit ce9ef410 — 2026-08-15 19:29
**fix(archeologie): taire les SyntaxWarning du vieux code d archive parse**

### Modules Python modifiés
- `tools/forge_archaeology_enrich.py`


## Commit 0acc4127 — 2026-08-15 19:28
**feat(archeologie): Phases 2 et 5 -- que faisait chaque vestige, lequel recuperer**

### Modules Python modifiés
- `tests/nr/test_archaeology_enrich_nr.py`
- `tools/forge_archaeology_enrich.py`


## Commit b0bc27a3 — 2026-08-15 19:20
**fix(archeologie): detecter un depot par rev-parse (inclut les submodules)**

### Modules Python modifiés
- `tools/forge_archaeology.py`


## Commit cbad3980 — 2026-08-15 19:19
**feat(archeologie): Phase 1 -- extraction du patrimoine enfoui, lecture seule**

### Modules Python modifiés
- `tests/nr/test_archaeology_nr.py`
- `tools/forge_archaeology.py`


## Commit bce7f8fe — 2026-08-15 18:31
**feat(web_hub): routes /organs -- anatomie vivante deduite du manifest**

### Modules Python modifiés
- `app/web_hub/app.py`


## Commit 96f3500b — 2026-08-15 18:30
**feat(ui): brique 2 -- dashboard anatomique consommant le manifest**

### Modules Python modifiés
- `app/web_hub/manifest_cards.py`
- `tests/nr/test_manifest_cards_nr.py`
- `tools/forge_patch_organs_route.py`


## Commit 67779a98 — 2026-08-15 18:22
**feat(ui-manifest): keystone d une UI qui se deduit du corps (capacite-driven)**

### Modules Python modifiés
- `tests/nr/test_ui_manifest_nr.py`
- `tools/forge_ui_manifest.py`


## Commit 242d3ba1 — 2026-08-15 15:21
**feat(proposeur): preparer l ACT (etapes 1-4), passif sous barriere humaine**

### Modules Python modifiés
- `tests/nr/test_regulation_proposer_nr.py`
- `tools/forge_regulation_proposer.py`


## Commit 2d2e3814 — 2026-08-15 15:08
**feat(learner): recompense non-circulaire (baseline gelee) + apprentissage par etat**

### Modules Python modifiés
- `tests/nr/test_regulation_learner_nr.py`
- `tools/forge_physiology.py`
- `tools/forge_regulation_learner.py`


## Commit 58014299 — 2026-08-15 13:56
**fix+test(regulation-learner): la valeur apprise persiste entre les runs**

### Modules Python modifiés
- `tests/nr/test_regulation_learner_nr.py`
- `tools/forge_regulation_learner.py`


## Commit 271e497d — 2026-08-15 13:54
**feat(regulation-learner): fermer la moitie apprentissage de la boucle (pivot B)**

### Modules Python modifiés
- `tools/forge_physiology.py`
- `tools/forge_regulation_learner.py`


## Commit 2dda26e3 — 2026-08-15 13:51
**test(nr): baseline physiologique reelle + logique des constantes**

### Modules Python modifiés
- `tests/nr/test_physiology_nr.py`


## Commit 233bdca6 — 2026-08-15 13:50
**feat(physiologie): cadrer les constantes physiologiques mesurables (pivot A)**

### Modules Python modifiés
- `tools/forge_physiology.py`


## Commit 48f8d51c — 2026-08-15 13:31
**feat(composition): Composition Integrity Gate -- DRIFTED des qu un gitlink != HEAD**

### Modules Python modifiés
- `tests/nr/test_composition_gate_nr.py`
- `tools/forge_release_lock.py`


## Commit acf9c5b2 — 2026-08-15 13:27
**ci: armer le cliquet de mutation, bloquant sur toute nouvelle faiblesse**

### Modules Python modifiés
- `tests/nr/test_mutation_ratchet_nr.py`
- `tools/ci_local.py`


## Commit e67b4674 — 2026-08-15 13:21
**feat(mutation-ratchet): cliquet bloquant sur les surfaces critiques**

### Modules Python modifiés
- `tools/forge_mutation_ratchet.py`


## Commit fad5f695 — 2026-08-15 13:15
**fix(bisect): worktree dans un scratch durable gitignore, jamais le temp systeme**

### Modules Python modifiés
- `tests/nr/test_bisect_nr.py`
- `tools/forge_bisect.py`


## Commit 8bad6d72 — 2026-08-15 13:12
**fix(bisect): la sync des sous-depots est une precondition DURE du verdict**

### Modules Python modifiés
- `tests/nr/test_bisect_nr.py`
- `tools/forge_bisect.py`


## Commit ad380541 — 2026-08-15 12:56
**fix(provenance): cle TPM inaccessible = INDETERMINE, jamais INVALIDE**

### Modules Python modifiés
- `tests/nr/test_release_lock_provenance_nr.py`
- `tools/forge_release_lock.py`


## Commit 2934e9a9 — 2026-08-15 12:28
**fix(provenance): cle TPM MACHINE pour une verif cross-compte + test du patch**

### Modules Python modifiés
- `tests/nr/test_patch_crawl_offload_nr.py`
- `tools/forge_release_lock.py`


## Commit c680cd7b — 2026-08-15 12:23
**test(nr): sceller, verifier et detecter la falsification du verrou**

### Modules Python modifiés
- `tests/nr/test_release_lock_provenance_nr.py`


## Commit f4c2dbc7 — 2026-08-15 12:21
**feat(livraison): provenance cryptographique locale du verrou de composition**

### Modules Python modifiés
- `tools/forge_release_lock.py`


## Commit c0eab08c — 2026-08-15 12:19
**fix(hub): handle_crawl ne gele plus l event-loop (RCA hub mort 13 min)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 7552e520 — 2026-08-15 12:18
**fix(hub): patch de deport du crawl bloquant hors event-loop**

### Modules Python modifiés
- `tools/forge_patch_crawl_offload.py`


## Commit a942bdce — 2026-08-15 11:41
**feat(bisect): recherche binaire du commit fautif, sur critere deja outille**

### Modules Python modifiés
- `tests/nr/test_bisect_nr.py`
- `tools/forge_bisect.py`


## Commit 65c14928 — 2026-08-15 11:16
**ci: armer le gate duplication, le bruit ayant ete mesure**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit f6565092 — 2026-08-15 11:14
**feat(duplication): racine surchargeable, pour rejouer le detecteur sur le passe**

### Modules Python modifiés
- `tests/nr/test_mutation_test_nr.py`
- `tools/forge_dup_detector.py`


## Commit 904bc754 — 2026-08-15 11:12
**fix(mutation): 0 mutant etait mon propre faux-vert**

### Modules Python modifiés
- `tools/forge_mutation_test.py`


## Commit 6911befc — 2026-08-15 11:11
**fix(mutation): lancer les tests avec un interpreteur qui existe**

### Modules Python modifiés
- `tools/forge_mutation_test.py`


## Commit 109a9774 — 2026-08-15 11:11
**fix(mutation): un git qui refuse de repondre n est pas un fichier sale**

### Modules Python modifiés
- `tools/forge_mutation_test.py`


## Commit 60eee19a — 2026-08-15 11:10
**feat(mutation): mutation testing natif -- tester les tests, pas le code**

### Modules Python modifiés
- `tools/forge_mutation_test.py`


## Commit 64cff641 — 2026-08-15 11:09
**fix(cycle de vie): ne plus declarer demarre un service qui n existe pas**

### Modules Python modifiés
- `tests/nr/test_observabilite_nr.py`
- `tools/forge_ensure_service.py`


## Commit a53691ac — 2026-08-15 10:54
**ci: brancher la duplication, en WARN et en le disant**

### Modules Python modifiés
- `tests/nr/test_dup_detector_nr.py`
- `tools/ci_local.py`


## Commit aa4cea77 — 2026-08-15 10:52
**fix(duplication): le code genere n est pas de la dette**

### Modules Python modifiés
- `tools/forge_dup_detector.py`


## Commit aa4cea77 — 2026-08-15 10:52
**fix(duplication): le code genere n est pas de la dette**

### Modules Python modifiés
- `tools/forge_dup_detector.py`


## Commit 8043d25d — 2026-08-15 10:50
**feat(duplication): detecteur de clones par structure AST**

### Modules Python modifiés
- `tools/forge_dup_detector.py`


## Commit 5afdbf89 — 2026-08-15 10:49
**fix(sante): la sonde du graph explorer visait le port de Neo4j**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `tests/nr/test_observabilite_nr.py`


## Commit 76f992fa — 2026-08-15 10:45
**test(nr): couvrir le moteur Golden Rules -- le cliquet de couverture m a repris**

### Modules Python modifiés
- `tests/nr/test_golden_rules_ast_nr.py`


## Commit e60d446d — 2026-08-15 10:39
**ci: armer les Golden Rules -- premier gate doctrinal reellement bloquant**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit 6824e97e — 2026-08-15 10:38
**fix(golden-rules): survivre a une cible hors du volume C:**

### Modules Python modifiés
- `tools/forge_golden_rules_ast.py`


## Commit 99c253fa — 2026-08-15 10:37
**feat(golden-rules): cliquet sur la dette, blocage sur la nouveaute**

### Modules Python modifiés
- `tools/forge_golden_rules_ast.py`


## Commit 52a4036e — 2026-08-15 10:37
**fix(golden-rules): ne pas accuser ce qu on ne peut pas lire**

### Modules Python modifiés
- `tools/forge_golden_rules_ast.py`


## Commit a02fc229 — 2026-08-15 10:36
**feat(golden-rules): moteur AST natif, pour que l invariant ne depende plus d un binaire**

### Modules Python modifiés
- `tools/forge_golden_rules_ast.py`


## Commit 4e1a9537 — 2026-08-15 10:33
**fix(archi-lint): choisir le binaire qui demarre, pas celui qui existe**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit b605bb32 — 2026-08-15 10:32
**fix(archi-lint): le gate rendait une coche verte sans lire un seul fichier**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit 5677869c — 2026-08-15 10:13
**chore(etat): publier la carte des IAs enfin realimentee**

### Documentation mise à jour
- `.agents/skills/nokido/SKILL.md`
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 74e0b896 — 2026-08-15 10:05
**fix(skills): le hook post-commit alimentait un dossier fantome**

### Modules Python modifiés
- `tools/forge_post_commit.py`

### Documentation mise à jour
- `README.md`


## Commit f756591b — 2026-08-11 15:54
**docs(veille): dire la verite sur la dependance Docker du pipeline**

### Documentation mise à jour
- `docs/skills/forge-veille-approfondie/SKILL.md`


## Commit cc301ae9 — 2026-08-11 15:40
**fix(diagnostic): cesser de declarer morts des backends vivants**

### Modules Python modifiés
- `tools/forge_provider_auth_audit.py`
- `tools/forge_services_launcher.py`


## Commit c458ebcf — 2026-08-11 15:12
**fix(launcher): separer le port de LM Studio de celui de llama.cpp**

### Modules Python modifiés
- `tools/forge_services_launcher.py`


## Commit 8924aced — 2026-08-11 11:53
**fix(cutover): une tache ACTIVE omet la balise Enabled, et couper les tenants survivants**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit e825e543 — 2026-08-11 11:46
**fix(cutover): neutraliser le planificateur, ne relancer que ce qui tournait, nommer les tenants**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit efe34081 — 2026-08-11 11:38
**fix(cutover): attendre que les enfants des services meurent avant de refuser**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit 285dfac5 — 2026-08-11 11:34
**fix(cutover): le generateur tronque ses lignes, les motifs ne peuvent pas exiger leur fin**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit 12a24a8e — 2026-08-11 11:22
**fix(cutover): le profil PowerShell est une surface, et CRLF faussait le tri**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit 4c85d85b — 2026-08-11 11:21
**docs(cutover): runbook regenere sous le compte owner, 0 reference morte**

### Documentation mise à jour
- `docs/cutover_runbook.md`


## Commit 587c0509 — 2026-08-11 11:19
**fix(cutover): trier le depot sale entre travail humain et artefacts regeneres**

### Modules Python modifiés
- `tools/nokido_cutover_owner.py`


## Commit 37023bca — 2026-08-10 19:07
**refactor(paths): deriver la racine dans les 22 scripts restants**

### Modules Python modifiés
- `tools/backfill_intent.py`
- `tools/bench_embeddings.py`
- `tools/cleanup_nokido.py`
- `tools/cleanup_recycle.py`
- `tools/deno_spikerouter_diag.py`
- `tools/deploy_hub_bundle.py`
- `tools/diag_emb.py`
- `tools/dump_hub_routes.py`
- `tools/forge_backup_hotswap.py`
- `tools/forge_db_clean_install.py`
- `tools/forge_db_instant_swap.py`
- `tools/forge_db_postswap.py`
- `tools/forge_db_restore_chunks.py`
- `tools/forge_db_swap.py`
- `tools/forge_debate_job.py`
- `tools/forge_docker_boot_audit.py`
- `tools/forge_docset_reader.py`
- `tools/forge_embed_backfill_jina.py`
- `tools/forge_kaggle_cfg_from_env.py`
- `tools/forge_kaggle_embed_export.py`


## Commit 1e1c3209 — 2026-08-10 19:01
**refactor(paths): deriver la racine du fichier au lieu de l ecrire en dur**

### Modules Python modifiés
- `app/forge_python_runner.py`
- `tools/forge_client_bootstrap.py`
- `tools/forge_code_reindex.py`
- `tools/forge_db_preflight.py`
- `tools/forge_goap_hub_bridge.py`
- `tools/forge_index_tools.py`


## Commit 543df750 — 2026-08-10 18:18
**docs(manifesto): actualiser la carte des organes, perimee depuis le 25 juin**

### Documentation mise à jour
- `MANIFESTO.md`


## Commit a4891ce9 — 2026-08-04 21:59
**feat(capteur): derive memoire PAR SERVICE nomme, branchee sur le sampler**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `app/forge_service_rss_watch.py`


## Commit 0283d3c2 — 2026-08-04 20:00
**feat(capteur): mesurer l'APPORT du flux reseau avant de le cabler**

### Modules Python modifiés
- `tools/forge_capteur_dense_apport_bench.py`


## Commit f7172895 — 2026-08-04 19:00
**fix(snn): encodage rate-code en [0,1] + deballage du tuple forward**

### Modules Python modifiés
- `tools/forge_snn_entraine_vitals_bench.py`


## Commit f1a25103 — 2026-08-04 18:58
**feat(snn): banc du SNN ENTRAINE sur vitals reels (mesure manquante)**

### Modules Python modifiés
- `tools/forge_snn_entraine_vitals_bench.py`


## Commit e8c594d2 — 2026-08-04 18:30
**feat(obs): network_log nomme le service au lieu d'exposer un PID nu**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit a9c97453 — 2026-08-04 18:29
**feat(obs): jointure PID -> nom de service via le registre du superviseur**

### Modules Python modifiés
- `tools/forge_patch_hub_service_par_pid.py`


## Commit 21f385d3 — 2026-08-04 17:14
**fix(state): Bearer manquant — cause des 114406 rejets 401 du hub**

### Modules Python modifiés
- `app/forge_state_encoder.py`


## Commit 4c14470b — 2026-08-04 17:07
**fix(obs): refroidissement du cache d'origine arme sur succes seulement**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 5a08e3d4 — 2026-08-04 17:06
**fix(obs): le cache de resolution bloquait l'identification qu'il servait**

### Modules Python modifiés
- `tools/forge_patch_hub_origine401_v2.py`


## Commit a180da00 — 2026-08-04 16:57
**feat(obs): le journal dit enfin QUI emet les requetes rejetees en 401**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 47119ecd — 2026-08-04 16:56
**feat(obs): patch pour identifier l'emetteur des 401 du hub**

### Modules Python modifiés
- `tools/forge_patch_hub_origine_401.py`


## Commit e921004d — 2026-08-04 13:11
**feat(tenns): banc multi-canal, la question laissee ouverte**

### Modules Python modifiés
- `tools/forge_tenns_multicanal_bench.py`


## Commit fb459d53 — 2026-08-04 13:03
**feat(snn): activation REVERSIBLE du capteur via snn.wanted + tir journalise**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `app/forge_signal_coupling.py`


## Commit 307d5084 — 2026-08-04 12:41
**feat(snn): detecteur a noyau polynomial (1er pas TENNs) + verdict**

### Modules Python modifiés
- `tools/forge_snn_vitals_baseline.py`


## Commit 43484e18 — 2026-08-04 12:39
**tune(snn): refractaire 60s -> 1800s, calibre sur 30k vitals reels**

### Modules Python modifiés
- `app/forge_snn_monitor.py`


## Commit 48d5fc5e — 2026-08-04 12:26
**feat(snn): baseline seuil vs LIF sur 30k vitals reels**

### Modules Python modifiés
- `tools/forge_snn_vitals_baseline.py`


## Commit caf1badd — 2026-08-04 12:15
**fix(snn): available() distingue absent et illisible (faux negatif torch)**

### Modules Python modifiés
- `app/forge_snn_core.py`


## Commit c16cb148 — 2026-08-04 12:00
**refactor(bench): reutiliser _call_model et assign_roles du collegial**

### Modules Python modifiés
- `tools/forge_council_bias_bench.py`


## Commit d3892a6a — 2026-08-04 11:23
**fix(bench): chemins d'erreur non muets + budget calibre sur la mesure**

### Modules Python modifiés
- `tools/forge_council_bias_bench.py`


## Commit f5c2bfeb — 2026-08-04 10:48
**perf(bench): grouper les appels par juge (1 chargement au lieu de N)**

### Modules Python modifiés
- `tools/forge_council_bias_bench.py`


## Commit a4a703aa — 2026-08-04 10:28
**fix(bench): ecarte les endpoints non generatifs, borne la RAM**

### Modules Python modifiés
- `tools/forge_council_bias_bench.py`


## Commit 97d3917b — 2026-08-04 10:25
**feat(mesure): banc de biais de juge, anonyme vs nominatif**

### Modules Python modifiés
- `app/forge_code.py`
- `tools/forge_council_bias_bench.py`


## Commit 50385c3d — 2026-08-04 10:09
**feat(debat): classement relatif anonymise + trace mesurable (B3)**

### Modules Python modifiés
- `app/forge_code.py`


## Commit 8bcb4f6e — 2026-08-04 09:59
**perf(ingest): retire un DELETE rag_fts qui full-scannait par chunk**

### Modules Python modifiés
- `tools/forge_ingest_github_repo.py`


## Commit 0db561c4 — 2026-08-04 09:55
**fix(ingest): write_retry fournit la connexion, ne pas en ouvrir une**

### Modules Python modifiés
- `tools/forge_ingest_github_repo.py`


## Commit d6043916 — 2026-08-04 09:53
**fix(ingest): tarball stdlib au lieu de gitingest (absent de l'env du hub)**

### Modules Python modifiés
- `tools/forge_ingest_github_repo.py`


## Commit dbdc1be2 — 2026-08-04 09:50
**feat(ingest): outil parametrable depot GitHub -> RAG**

### Modules Python modifiés
- `tools/forge_ingest_github_repo.py`


## Commit 9cc4ecac — 2026-08-02 01:56
**fix(searxng): keeper ne detruit plus un conteneur sain sur blip probe + mount WSL /mnt/c**

### Modules Python modifiés
- `tools/forge_searxng_keeper.py`


## Commit 8ef7a38d — 2026-08-01 23:42
**wip(docker): pivot Docker Desktop -> dockerd natif WSL Debian + portproxy 2375 (AGY, UNTESTED)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_docker_agent.py`
- `app/forge_exegol_mcp_server.py`
- `tools/forge_docker_keeper.py`
- `tools/forge_ensure_service.py`
- `tools/forge_searxng_keeper.py`


## Commit 0bbf2431 — 2026-07-30 18:48
**security(docs): retire une cle en clair des SKILL.md (rotee le 30/07)**

### Documentation mise à jour
- `docs/skills/forge-core/SKILL.md`
- `docs/skills/forge-env/SKILL.md`


## Commit 9cf8e2fd — 2026-07-30 08:42
**fix(rag): rebuild_fts_index n existait pas, l option rebuild etait dead code**

### Modules Python modifiés
- `app/forge_mutation_judge.py`
- `app/forge_self_correction.py`
- `tools/forge_fts_repair.py`
- `tools/forge_regulation_efficacy.py`


## Commit 45ce572f — 2026-07-30 08:33
**feat(mutation): LE JUGE avant l arbre, trois etages dont la memoire**

### Modules Python modifiés
- `app/forge_mutation_judge.py`


## Commit 833a051f — 2026-07-30 07:19
**feat(veille): auto-amelioration de code par biomimetisme, 4 sources owner**

### Modules Python modifiés
- `tools/forge_curriculum_ingest.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 449aba4f — 2026-07-30 07:12
**chore(retention): declarer les trois tables du couplage de signaux**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit a59b3867 — 2026-07-30 07:11
**fix(biomimetisme): seuil de Hill, recepteur leurre, double validation, plafond PLAUSIBLE**

### Modules Python modifiés
- `app/forge_proposal_applier.py`
- `app/forge_rag_warmup.py`
- `app/forge_signal_coupling.py`
- `tools/forge_regulation_efficacy.py`


## Commit df3afb4d — 2026-07-30 07:06
**feat(applicateur): reflexe medullaire vs decision corticale, desarme par defaut**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_proposal_applier.py`


## Commit 39e111b3 — 2026-07-30 07:02
**feat(correlation): causalite par FLUX de ressource, la regle lache est remplacee**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tools/forge_log_retention.py`
- `tools/forge_regulation_efficacy.py`


## Commit b6fdc775 — 2026-07-30 06:58
**feat(couplage): detecter les signaux orphelins dans les DEUX sens, trophisme gradue**

### Modules Python modifiés
- `app/forge_endocrine.py`
- `app/forge_signal_coupling.py`
- `tools/forge_llm_ondemand.py`


## Commit b4841210 — 2026-07-30 06:16
**feat(auto-amelioration): PRODUIRE des propositions, pas un quatrieme diagnostic**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`


## Commit 16eb31b3 — 2026-07-30 05:38
**fix(autonomous): journal d audit par le writer gouverne, une ecriture perdue etait silencieuse**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`


## Commit d7b66aa6 — 2026-07-30 05:11
**feat(auto-amelioration): consommer les diagnostics que personne ne lisait**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tools/forge_gap_direction.py`


## Commit e1adfa12 — 2026-07-30 04:51
**docs(rules): un garde branche sur un signal que personne n emet**

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit e93c078d — 2026-07-30 04:49
**feat(regulation): refractaire ADAPTATIVE cablee sur le modele du corps**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit eebdbd40 — 2026-07-30 04:45
**fix(intention): declarer llama.wanted au reveil, six reveilleurs pour un seul declarant**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`
- `tools/forge_local_pool_wake.py`
- `tools/forge_wake_llama_native.py`


## Commit 94475523 — 2026-07-30 04:40
**feat(meta-regulation): mesurer si la regulation POMPE, debit REEL vs budget**

### Modules Python modifiés
- `tools/forge_regulation_efficacy.py`


## Commit 33488076 — 2026-07-30 04:03
**feat(endocrine): secreter l insuline de satiete, la glande manquait**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit b853fbcf — 2026-07-30 03:51
**feat(rag): le warm du cache dense refuse sous pression RAM**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 59e03a9d — 2026-07-30 03:50
**feat(satiete): frein sur la construction du cache dense (manque n1 d AGY)**

### Modules Python modifiés
- `tools/forge_patch_dense_satiety.py`


## Commit a10f658e — 2026-07-30 03:43
**feat(autoregulation): periode refractaire sur les recuperateurs (avis AGY)**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit c81f63a9 — 2026-07-30 02:57
**feat(hub): route POST /admin/job/{job_id}/stop**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit e3901441 — 2026-07-30 02:57
**feat(hub): script de patch pour exposer l arret d un job**

### Modules Python modifiés
- `tools/forge_patch_job_stop_route.py`


## Commit 48222b10 — 2026-07-30 02:56
**fix(job_stop): chemins de jobs post-renommage, et API appelable par le hub**

### Modules Python modifiés
- `tools/forge_job_stop.py`


## Commit 4316c814 — 2026-07-30 02:51
**fix(hook): ne balayer que le texte libre, pas les noms d appel**

### Modules Python modifiés
- `tools/hook_recon_first.py`


## Commit 846d67e6 — 2026-07-30 02:50
**fix(audit): un service a port sonde ne meurt pas en silence**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 061386ee — 2026-07-30 02:36
**feat(cognition): croiser les defauts mesures avec la direction voulue**

### Modules Python modifiés
- `tools/forge_gap_direction.py`


## Commit 6e37afd8 — 2026-07-30 02:25
**fix(autoregulation): nommer le proprietaire de l echantillonneur, et le designer**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit 1aafb13b — 2026-07-30 01:49
**feat(autoregulation): rendre les caches meme sous cognition active**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `app/forge_sandbox_exec.py`


## Commit e6314b52 — 2026-07-30 01:40
**feat(rag): le cache dense se declare RAM reclamable**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit e2fdf499 — 2026-07-30 01:38
**feat(autoregulation): rendre sa propre graisse avant d amputer un organe**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `tools/forge_patch_dense_reclaimer.py`


## Commit 6e2e61fc — 2026-07-30 01:15
**feat(session): rafraichir l index d enquetes au demarrage, sans bloquer**

### Modules Python modifiés
- `tools/claude_session_start.py`
- `tools/hook_recon_first.py`


## Commit 7a0038e9 — 2026-07-30 01:13
**fix(conv_indexer): indexer TOUS les projets, pas celui que le hasard designe**

### Modules Python modifiés
- `app/forge_conv_indexer.py`


## Commit 87099397 — 2026-07-30 01:11
**feat(index): recuperer l ere LaForge depuis le RAG, la source qui existe**

### Modules Python modifiés
- `tools/forge_symptom_index.py`


## Commit 354183d6 — 2026-07-30 01:07
**docs(rules): ne jamais conclure d une source qui se tait**

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit 702dfef6 — 2026-07-30 00:54
**fix(index): retenir une session pour ses aveux, et dater par mtime a defaut**

### Modules Python modifiés
- `tools/forge_symptom_index.py`


## Commit ab39a38e — 2026-07-30 00:53
**fix(index): plus aucune session ecartee en silence**

### Modules Python modifiés
- `tools/forge_symptom_index.py`


## Commit 565d4e9f — 2026-07-30 00:51
**fix(couverture): scanner TOUS les projets, pas un seul**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`
- `tools/forge_symptom_index.py`


## Commit 92f253f2 — 2026-07-30 00:43
**fix(hook): un chemin n est pas un symptome, une session sans piege pertinent non plus**

### Modules Python modifiés
- `tools/hook_recon_first.py`


## Commit 6abdfeb1 — 2026-07-30 00:41
**fix(index): chaque piege porte les jetons de son propre paragraphe**

### Modules Python modifiés
- `tools/forge_symptom_index.py`


## Commit 6f802b26 — 2026-07-30 00:39
**feat(hook): consulter l index d enquetes a ma place, puisque je ne le fais pas**

### Modules Python modifiés
- `tools/hook_recon_first.py`


## Commit ac3d136b — 2026-07-30 00:37
**feat(cognition): index symptome -> session, pour ne plus refaire mes enquetes**

### Modules Python modifiés
- `tools/forge_symptom_index.py`


## Commit 3dea1433 — 2026-07-30 00:30
**fix(anti-recidive): denominateur des redites derive, pas choisi**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`


## Commit 3951e31c — 2026-07-30 00:23
**fix(anti-recidive): un indicateur que je ne peux pas biaiser**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`


## Commit 16ab90f7 — 2026-07-29 23:33
**feat(anti-recidive): mesure principale = taux de recadrage owner dans le temps**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`


## Commit 7fab8c94 — 2026-07-29 22:59
**feat(hook): l anti-dup a la creation devient structurel, plus une note**

### Modules Python modifiés
- `tools/hook_recon_first.py`


## Commit 6505453f — 2026-07-29 22:58
**feat(gate): garde anti-recidive sur les 2 motifs mecaniquement detectables**

### Modules Python modifiés
- `tools/forge_git_gate.py`


## Commit 3ef78aea — 2026-07-29 22:34
**fix(anti-recidive): chronologie prise aux memoires, plus a l ingestion**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`


## Commit 3bbe6a86 — 2026-07-29 22:23
**feat(anti-recidive): moulinette des motifs d echec qui reviennent**

### Modules Python modifiés
- `tools/forge_recurrence_audit.py`


## Commit 67971572 — 2026-07-29 00:14
**fix(ci): subprocess errors=replace dans le Stop hook (warn gate anti-regression)**

### Modules Python modifiés
- `tools/forge_ci_stop_hook.py`


## Commit 2b3ce261 — 2026-07-29 00:12
**feat(ci): Stop hook — verdict CI de la branche crie sur rouge en fin de tour**

### Modules Python modifiés
- `tools/forge_ci_stop_hook.py`


## Commit 4e653654 — 2026-07-28 23:37
**fix(watch): create_job via write_retry (veille curiosity perdue sur DB lock)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 43d453d4 — 2026-07-28 23:08
**fix(autonomous): escape circadien anti-famine + fallback ollama pour learners**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`


## Commit 6024ff64 — 2026-07-28 21:08
**feat(wasm): Phase B Pyodide — execute le Python du CLI en WASM, zero disque**

### Modules Python modifiés
- `tools/forge_wasm_sandbox.py`


## Commit 0f4223ff — 2026-07-28 11:31
**fix(ci-check): forcer UTF-8 sur la sortie, la console Windows est en cp1252**

### Modules Python modifiés
- `tools/forge_ci_check.py`


## Commit bdc30ca8 — 2026-07-28 00:07
**fix(curiosity): capitalisation — assouplissement AGY conserve, echec declare exclu, verrou rejoue**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit 9dc37cb4 — 2026-07-27 23:46
**feat(veille): garde de forme contre les listes de references**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit f0f946d3 — 2026-07-27 23:39
**feat(curiosity): capitaliser le savoir retenu en lecon reutilisable**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit a1ead158 — 2026-07-27 23:32
**fix(veille): seuil d ingestion aligne sur celui de la retention**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 1631e292 — 2026-07-27 22:56
**feat(curiosity): veille sur les briques du corps, ancree sur la version installee**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit 714229c0 — 2026-07-27 22:47
**fix(curiosity): requete de soi ancree, sans libelle interne**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit 27de8093 — 2026-07-27 22:40
**fix(docker-keeper): health ok cesse de transporter sa panne**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 1dbcc5c1 — 2026-07-27 22:22
**fix(curiosity): push delegue a create_job, la chaine va enfin au bout**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit 58b5942a — 2026-07-27 22:16
**feat(veille): dedup AMONT, on ne re-telecharge plus ce qu'on possede**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 13a54050 — 2026-07-27 21:49
**fix(veille): le motif de non-retention devient lisible**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 34d65851 — 2026-07-27 20:25
**feat(curiosity): la soif se retourne vers soi, sans dependance cloud**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_curiosity_driver.py`


## Commit dd11d91d — 2026-07-27 20:18
**fix(curiosity): famine de tokens, la vraie cause des 0 theme**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit e183be46 — 2026-07-27 20:06
**feat(intents): rerank.wanted entre au vocabulaire d intention du corps**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit 7ce24977 — 2026-07-27 20:06
**fix(curiosity): parser tolerant, la soif ne jette plus la reponse du LLM**

### Modules Python modifiés
- `app/forge_curiosity_driver.py`


## Commit f08c112f — 2026-07-27 10:43
**fix(soif): passe a blanc muette quand le manque persiste**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit 6c810ea5 — 2026-07-27 10:21
**feat(soif): passe a blanc de la veille d'intention avant armement**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit 92235b20 — 2026-07-27 00:59
**fix: un bloqueur ne disparait plus en vieillissant, une note n'en efface plus une autre**

### Modules Python modifiés
- `app/forge_ssot_maintainer.py`


## Commit a1f13d1b — 2026-07-27 00:54
**fix: refractaire a duree sur l'intention, desarmement des sources arbitraires**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit e4d12ca1 — 2026-07-27 00:51
**feat: le manque d'intention se decide par RANG, le seuil absolu ne voyait que du hors-sujet**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit 0dc2e846 — 2026-07-27 00:44
**feat: l'intention du corps nourrit la soif de connaissance**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit d5b38bed — 2026-07-27 00:41
**fix: la soif de connaissance ne meurt plus en silence, et se souvient enfin**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit 0b651b78 — 2026-07-27 00:24
**fix: zone morte du SSoT rules + derniers caps muets**

### Modules Python modifiés
- `app/forge_ssot_maintainer.py`
- `app/forge_swarm_blackboard.py`


## Commit f8871db3 — 2026-07-27 00:06
**fix: le SSoT ne presente plus une phrase amputee comme une phrase entiere**

### Modules Python modifiés
- `app/forge_ssot_maintainer.py`


## Commit 3d7989f5 — 2026-07-26 23:29
**fix: AGY=GEMINI=ANTIGRAVITY, identifiants VIVANTS + noms AGY_* crees**

### Modules Python modifiés
- `tools/forge_task_executor.py`


## Commit cb1bda98 — 2026-07-26 23:24
**fix: un seul acteur agy/ANTIGRAVITY, Gemini est un nom mort**

### Modules Python modifiés
- `tools/forge_task_executor.py`


## Commit 8bd70e18 — 2026-07-26 22:54
**feat: distinguer agy interactif et agy autonome par identite ET facon d'agir**

### Modules Python modifiés
- `tools/forge_task_executor.py`


## Commit ab89eaa0 — 2026-07-26 22:13
**feat: cle tasks_unclaimed dans le digest whoami**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 64b422d6 — 2026-07-26 22:13
**feat: whoami signale les taches deposees mais jamais reclamees**

### Modules Python modifiés
- `tools/forge_patch_whoami_tasks_unclaimed.py`


## Commit 14f9c80c — 2026-07-26 20:37
**fix: rester dans le job est un choix, il rend l'extinction possible**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`
- `tools/forge_wake_llama_native.py`


## Commit 953775c6 — 2026-07-26 20:36
**fix: qui cree par WMI tue par WMI**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`


## Commit 8e5d4348 — 2026-07-26 20:33
**fix: un cerveau qu'on vient d'allumer est inactif par definition**

### Modules Python modifiés
- `tools/forge_llama_keeper.py`


## Commit a2b246cf — 2026-07-26 20:29
**fix: le keeper fauchait le vivant au nom d'un pid mort**

### Modules Python modifiés
- `tools/forge_llama_keeper.py`
- `tools/forge_llm_ondemand.py`


## Commit 88302dcb — 2026-07-26 20:27
**fix: creation hors Job Object via WMI quand BREAKAWAY est refuse**

### Modules Python modifiés
- `tools/forge_wake_llama_native.py`


## Commit a38d3198 — 2026-07-26 20:23
**fix: la tache PORTE le serveur, elle ne le lance pas puis s'en va**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`
- `tools/forge_wake_llama_native.py`


## Commit cc4bb059 — 2026-07-26 20:18
**fix: le serveur doit sortir du Job Object de la tache planifiee**

### Modules Python modifiés
- `tools/forge_wake_llama_native.py`


## Commit c2dbe622 — 2026-07-26 20:13
**fix: un 401 prouve qu'un serveur est la, il ne prouve pas l'inverse**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`


## Commit fe7ef993 — 2026-07-26 20:11
**fix: LM Studio a deux etages, le demon n'ouvre pas le port**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`


## Commit 206e9f98 — 2026-07-26 20:06
**fix: journaliser le levier, sa sortie est perdue en tache planifiee**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`


## Commit 475dac1e — 2026-07-26 20:06
**fix: ACL lue comme absence + attente de demarrage du demon**

### Modules Python modifiés
- `tools/forge_llm_ondemand.py`


## Commit 34e8d4a4 — 2026-07-26 20:01
**feat: taches Nokido-* d'allumage/extinction + cible perimee du garde**

### Modules Python modifiés
- `tools/bash_guard.py`


## Commit a2b1c8f8 — 2026-07-26 19:58
**feat: allumage/extinction a la demande des cerveaux souverains**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `tools/forge_llm_ondemand.py`


## Commit 614eb5be — 2026-07-26 17:17
**fix: llamacpp_native_start emettait un script PowerShell invalide**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit fdda0b97 — 2026-07-26 17:13
**feat: eviction par capacite conditionnee (avis souverain 2026-07-26)**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit 4fe5575e — 2026-07-26 17:10
**fix: l'accuse M2M n'ecrase plus la reponse complete d'une tache**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 68848e3d — 2026-07-26 17:09
**fix: cause reelle d'indisponibilite provider + patcheur anti-ecrasement**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tools/forge_patch_task_result_clobber.py`


## Commit e6803c39 — 2026-07-26 16:15
**fix(ressources): mesurer la RAM libre au lieu de relire une photo perimee**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit 21e5393b — 2026-07-26 16:05
**feat(docker): relacher Docker quand plus personne ne le reclame**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`
- `tools/forge_regulation_loops.py`


## Commit 2de0035f — 2026-07-26 15:43
**fix(embed): relacher le verrou pendant les calculs d embedding**

### Modules Python modifiés
- `tools/forge_embed_auto_trigger.py`


## Commit 5193de14 — 2026-07-26 15:34
**feat(nosologie): symptome -> pathologie -> gravite -> remede**

### Modules Python modifiés
- `tools/forge_nosology.py`


## Commit c2909021 — 2026-07-26 15:31
**feat(anatomie): aretes part_of/connected_to + qui meurt en aval**

### Modules Python modifiés
- `app/forge_endocrine.py`
- `tools/forge_organ_edges.py`


## Commit 7beb0bd2 — 2026-07-26 15:27
**fix(inspector): netstat errors=replace + retention inspector_log**

### Modules Python modifiés
- `app/forge_inspector.py`
- `tools/forge_log_retention.py`


## Commit 47bb8de6 — 2026-07-26 15:18
**fix(inspector): OOM cooldown 600s + franchissement par urgence mesuree**

### Modules Python modifiés
- `app/forge_inspector.py`
- `tools/forge_regulation_loops.py`


## Commit 47bb8de6 — 2026-07-26 15:18
**fix(inspector): OOM cooldown 600s + franchissement par urgence mesuree**

### Modules Python modifiés
- `app/forge_endocrine.py`


## Commit 08bdf960 — 2026-07-26 15:02
**feat(endocrine): recepteurs declares + emission qui ne se perd plus**

### Modules Python modifiés
- `app/forge_endocrine.py`


## Commit 1d31f15a — 2026-07-26 14:50
**feat(regulation): double refractaire + urgence lue sur le corps**

### Modules Python modifiés
- `tools/forge_regulation_loops.py`


## Commit 5478799f — 2026-07-26 14:43
**feat(regulation): debit maximal de casse des effecteurs vs budget**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`
- `tools/forge_regulation_loops.py`


## Commit fe9f323d — 2026-07-26 14:16
**fix(docker): periode refractaire sur le force-recycle**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 43dbf555 — 2026-07-26 14:13
**fix(docker): daemon off par design n'est pas une panne**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 5da11d49 — 2026-07-26 13:47
**fix(regulation): l antagoniste manquant, et une boucle fermee sur l effet**

### Modules Python modifiés
- `app/forge_rag_warmup.py`
- `tools/forge_orphan_reaper.py`


## Commit dc9494c8 — 2026-07-26 13:37
**feat(nociception): la douleur est graduee, la blessure grave passe devant**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit 0ea14597 — 2026-07-26 13:31
**feat(soif): afference interoceptive, et separation soin de soi / connaissance**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit b279fd45 — 2026-07-26 13:25
**fix(autoregulation): le decharge-inactif avait le bon diagnostic et pas le bras**

### Modules Python modifiés
- `tools/forge_backend_power.py`


## Commit 1c8f9ebe — 2026-07-26 13:19
**feat(horodatage): adoption par la racine + garde qui rend la non-adoption visible**

### Modules Python modifiés
- `app/bootstrap.py`
- `app/forge_health_diagnostic.py`


## Commit 2c1eb791 — 2026-07-26 13:15
**fix(retention): rag_snapshots purgee, global_sequence mesuree et exemptee**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit 1a02f870 — 2026-07-26 13:12
**feat(horodatage): les 4 derniers journaux non dates rejoignent la convention**

### Modules Python modifiés
- `app/forge_videur.py`
- `tools/forge_docker_keeper.py`
- `tools/forge_owner_daemons.py`
- `tools/nokido_mcp_server.py`


## Commit 8b6aea09 — 2026-07-26 13:04
**feat(horodatage): convention unique dans forge_timecode + 3 journaux dates**

### Modules Python modifiés
- `app/forge_loop_sentinel.py`
- `app/forge_timecode.py`
- `tools/forge_coagulation.py`
- `tools/forge_organ_pulse.py`


## Commit 2c3b1350 — 2026-07-26 12:54
**fix(sampler): un seul echantillonneur, le proprietaire ; les autres lisent**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit b5b006c8 — 2026-07-26 12:50
**fix(sante): l audit des vitaux ne cree plus un second echantillonneur**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`


## Commit 747f8967 — 2026-07-26 12:13
**feat(post-mortem): un arret sale se distingue d un redemarrage voulu**

### Modules Python modifiés
- `app/forge_reboot_sentinel.py`
- `tools/forge_orphan_reaper.py`


## Commit 747f8967 — 2026-07-26 12:13
**feat(post-mortem): un arret sale se distingue d un redemarrage voulu**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`


## Commit 8cabe370 — 2026-07-26 12:13
**fix(sampler): la sonde GPU ne spawne plus un PowerShell toutes les 5 s**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit c387791d — 2026-07-26 11:25
**fix(fusion): un heartbeat frais ne prouve pas la vie d un service ARRETE**

### Modules Python modifiés
- `app/forge_sensor_fusion_probe.py`


## Commit 9f310cb0 — 2026-07-26 11:09
**fix(eviction): donner un levier qui MARCHE, via le superviseur et le port servi**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit ad721404 — 2026-07-26 11:04
**fix(reaper): chiffrer chaque abstention, un garde indiscutable finit contourne**

### Modules Python modifiés
- `tools/forge_orphan_reaper.py`


## Commit 8ff55242 — 2026-07-26 11:03
**feat(capabilities): le bus evenementiel Deno declare nervous_system, capacite critique**

### Modules Python modifiés
- `app/forge_service_capabilities.py`


## Commit 22cd250c — 2026-07-26 10:52
**fix(fusion): un pid de lanceur mort n est pas un fantome**

### Modules Python modifiés
- `app/forge_sensor_fusion_probe.py`


## Commit ef1db435 — 2026-07-26 10:40
**feat(fusion): 4e capteur process, les 10 zones aveugles deviennent observables**

### Modules Python modifiés
- `app/forge_sensor_fusion_probe.py`


## Commit 3222e5b9 — 2026-07-26 10:39
**fix(fusion): un service en cours de demarrage n est pas un service malade**

### Modules Python modifiés
- `app/forge_sensor_fusion_probe.py`


## Commit 71373d99 — 2026-07-26 10:38
**fix(fusion): un service en cours de demarrage n est pas un service malade**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_sensor_fusion_probe.py`

### Documentation mise à jour
- `.agents/skills/forge-veille-approfondie/SKILL.md`
- `.agents/skills/laforge/SKILL.md`
- `README.md`
- `docs/skills/laforge/SKILL.md`


## Commit 8327ef7a — 2026-07-25 21:26
**fix(refine): veto d'ancrage -- le LLM ne peut plus faire passer seul un hors-sujet**

### Modules Python modifiés
- `app/forge_chain_executor.py`


## Commit 06219efd — 2026-07-25 21:23
**fix(keeper+veille): wsl shutdown conditionnel + requetes ancrees dans leur domaine**

### Modules Python modifiés
- `app/forge_watch_agent.py`
- `tools/forge_docker_keeper.py`


## Commit ecc46dd8 — 2026-07-25 20:43
**perf(fts): retirer le DELETE du backfill -- il rendait l'insertion quadratique**

### Modules Python modifiés
- `tools/forge_fts_backfill.py`


## Commit efbfcc47 — 2026-07-25 20:23
**fix(fts): le backfill utilise write_retry (il figeait sur son premier lot)**

### Modules Python modifiés
- `tools/forge_fts_backfill.py`


## Commit be897bd2 — 2026-07-25 20:18
**feat(rag): forge_fts_backfill -- rattraper les chunks invisibles au lexical**

### Modules Python modifiés
- `tools/forge_fts_backfill.py`


## Commit bda21126 — 2026-07-25 20:11
**docs(doctrine): DOCTRINE.md -- le lexical prime, regle outillee et opposable**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`
- `tools/forge_post_commit.py`

### Documentation mise à jour
- `DOCTRINE.md`


## Commit 44ac2700 — 2026-07-25 20:06
**fix(doctrine): la doctrine n'etait PAS indexee en lexical (0 chunk FTS)**

### Modules Python modifiés
- `tools/forge_post_commit.py`


## Commit 99a5f6b6 — 2026-07-25 20:04
**feat(corps): ecritures concurrentes reprises + les conteneurs entrent dans la carte**

### Modules Python modifiés
- `app/forge_db_path.py`
- `tools/forge_body_regulation_audit.py`

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit c7af396e — 2026-07-25 19:44
**fix(veille): create_job tenait un verrou implicite -> database is locked**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 22d4a298 — 2026-07-25 19:18
**docs(rules): un module neuf declare son organe (__FORGE_COLOR__)**

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit fc3931f5 — 2026-07-25 19:17
**feat(census): dernier filet = la DECLARATION du module (__FORGE_COLOR__)**

### Modules Python modifiés
- `tools/forge_module_census.py`


## Commit d7f45c74 — 2026-07-25 19:13
**feat(census): dernier filet, l'organe deduit des imports reels**

### Modules Python modifiés
- `tools/forge_module_census.py`


## Commit 6241c503 — 2026-07-25 19:11
**fix(audit): le capteur lisait sa PROPRE sortie (auto-empoisonnement)**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 38ed01e6 — 2026-07-25 19:07
**feat(corps): gaps MESURES par organe + rattachement immediat des nouveaux modules**

### Modules Python modifiés
- `app/forge_organ_agents.py`
- `tools/forge_module_cards.py`


## Commit 0690577f — 2026-07-25 19:05
**feat(census): rattacher CHAQUE module a un organe (nom puis dossier)**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`
- `tools/forge_module_census.py`


## Commit 5124d51c — 2026-07-25 18:52
**docs(audit): ZONE_MORTE n'est pas un permis de supprimer**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 6bb05383 — 2026-07-25 18:48
**fix(typecheck): la cle DENO vit sous [vars] dans services.toml**

### Modules Python modifiés
- `tools/forge_deno_typecheck.py`


## Commit 4a7e118b — 2026-07-25 18:47
**feat(circadien): reconsolidation de la carte de soi en NREM1 + typecheck deno**

### Modules Python modifiés
- `tools/forge_deno_typecheck.py`


## Commit c7d49ad1 — 2026-07-25 18:42
**fix(retention): borner proprioception_snapshots + decodage subprocess**

### Modules Python modifiés
- `app/forge_proprioception.py`
- `tools/forge_log_retention.py`


## Commit c9bcd427 — 2026-07-25 18:38
**feat(proprioception): l'atlas distingue presence et innervation**

### Modules Python modifiés
- `app/forge_proprioception.py`


## Commit c443da35 — 2026-07-25 18:30
**fix(audit): ne plus avaler un echec d'indexation FTS**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit f95de3f6 — 2026-07-25 18:29
**feat(corps): le verdict d'autoregulation entre dans la carte de chaque module**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`
- `tools/forge_module_cards.py`


## Commit 9ba01b6d — 2026-07-25 18:27
**fix(audit): ingestion RAG par defaut -- run_job ignore le parametre args**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 98cf36e1 — 2026-07-25 18:24
**fix(audit): os.walk avec elagage, ne jamais traverser une jonction NTFS**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 4c3aee96 — 2026-07-25 18:21
**perf(audit): borner le scan de references (taille + dossiers lourds)**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit a169c535 — 2026-07-25 18:18
**feat(audit): second regard, invocation par chemin (hook/config/script)**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit 64941670 — 2026-07-25 18:15
**fix(audit): lire la vraie structure du census + restreindre au perimetre du corps**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit ee96bd88 — 2026-07-25 18:14
**feat(corps): audit d autoregulation module par module + ingestion RAG par organe**

### Modules Python modifiés
- `tools/forge_body_regulation_audit.py`


## Commit aebd3978 — 2026-07-25 16:36
**perf(tier): selection des chunks a vectoriser x276 (colonne generee origin + index partiel)**

### Modules Python modifiés
- `tools/forge_embed_auto_trigger.py`
- `tools/forge_tier_policy.py`


## Commit b1e0a14b — 2026-07-25 15:19
**feat(meta): entites typees VERIFIABLES (arxiv_id, annee derivee, doi) dans meta**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 0c21da08 — 2026-07-25 14:50
**docs(capacites): runner CI offline - diagnostic, relance, et gates locaux != CI**

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit 2c22d64b — 2026-07-25 14:17
**fix(backfill): retry sur verrou - une source crawlee ne doit pas etre perdue pour un lock**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`


## Commit ab9c2d3e — 2026-07-25 14:15
**fix(py314t): ne pas forcer PYTHON_GIL=0 - lxml reactive le GIL, gain nul et risque reel**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit 310e0aa9 — 2026-07-25 14:08
**docs(capacites): pip dans un env owner + syntaxe Git Bash (formes mesurees)**

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit 28e6e95b — 2026-07-25 14:00
**feat(backfill): traitement PARALLELE (pool + writer par thread) + capacites a jour**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`

### Documentation mise à jour
- `RULES_SHARED.md`


## Commit ebb68b3b — 2026-07-25 13:49
**feat(db): open_writer partage (autocommit+WAL+busy_timeout) = ecritures concurrentes**

### Modules Python modifiés
- `app/forge_db_path.py`
- `tools/forge_veille_backfill.py`
- `tools/forge_veille_depollute.py`


## Commit a6d25502 — 2026-07-25 13:11
**feat(diag): probe des droits reels sur un process (identite, proprietaire, 3 formes d arret)**

### Modules Python modifiés
- `tools/forge_proc_rights_probe.py`


## Commit 82a6420a — 2026-07-25 13:08
**fix(job_stop): l attente des enfants ne doit pas empecher l arret du parent**

### Modules Python modifiés
- `tools/forge_job_stop.py`


## Commit fd9afbe9 — 2026-07-25 13:07
**feat(job_stop): --force quand la cmdline est illisible et que le hub a identifie le pid**

### Modules Python modifiés
- `tools/forge_job_stop.py`


## Commit 12dabe28 — 2026-07-25 13:06
**fix(forget): oubli semantique par conjonction seuil absolu + outlier bas de la source**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 273ec76e — 2026-07-25 13:04
**fix(backfill): audit qualite en opt-in + outil d arret propre des jobs detaches**

### Modules Python modifiés
- `tools/forge_job_stop.py`
- `tools/forge_veille_backfill.py`


## Commit 38a70d18 — 2026-07-25 12:54
**feat(veille): --resync-fts repare les entrees lexicales obsoletes**

### Modules Python modifiés
- `tools/forge_veille_depollute.py`


## Commit a70e87ce — 2026-07-25 12:54
**fix(veille): rag_fts DELETE+INSERT au lieu de OR IGNORE (le lexical servait l ancien texte)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit b0d8b360 — 2026-07-25 12:36
**refactor(veille): le lexical prime, le vectoriel raffine ensuite (embed inline opt-in)**

### Modules Python modifiés
- `app/forge_watch_agent.py`
- `tools/forge_veille_backfill.py`


## Commit 4b19c6e0 — 2026-07-25 12:34
**fix(veille): retry sur l embed inline (echec transitoire = chunk sans vecteur en silence)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit ba5341af — 2026-07-25 12:28
**feat(veille): remplir le schema (sequence_id, meta/header_path, hash, canonical_id, embedding_model)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 15e3ace2 — 2026-07-25 11:51
**feat(veille): outil de depollution du corpus historique (retire l en-tete theme, re-embedde)**

### Modules Python modifiés
- `tools/forge_veille_depollute.py`


## Commit 3763cc46 — 2026-07-25 11:49
**feat(backfill): mode --redo pour re-traiter apres amelioration de l extraction**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`


## Commit ff380fef — 2026-07-25 11:48
**fix(pdf): x_tolerance=1.5 mesure sur pdfplumber (45 pourcent des mots etaient fusionnes)**

### Modules Python modifiés
- `app/forge_rag_store.py`


## Commit ab91eba6 — 2026-07-25 11:45
**feat(backfill): meme controle qualite que le pipeline vivant (elague les bibliographies)**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`


## Commit 9a47247d — 2026-07-25 11:42
**fix(veille): le theme ne pollue plus le contenu du chunk (provenance = colonnes)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 6b5ef15d — 2026-07-25 11:39
**feat(veille): outil de backfill du corpus deja ingere (dry-run par defaut, borne)**

### Modules Python modifiés
- `tools/forge_veille_backfill.py`


## Commit 626bd7fd — 2026-07-25 11:25
**fix(veille): indexer les chunks dans rag_fts (retrieval hybride complet)**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit 01e2ba2c — 2026-07-25 11:25
**fix(veille): retire l appel orphelin _offtopic (NameError a l ingest) + cap 80**

### Modules Python modifiés
- `app/forge_watch_agent.py`


## Commit f90e72a2 — 2026-07-25 11:21
**feat(veille): chunker le corps au lieu de tronquer + texte integral arxiv/openreview**

### Modules Python modifiés
- `app/forge_crawl_tool.py`
- `app/forge_watch_agent.py`


## Commit ae291ac2 — 2026-07-25 11:11
**fix(skill): identite d'agent parametree dans forge-veille (fin de l'usurpation involontaire)**

### Documentation mise à jour
- `docs/skills/forge-veille-approfondie/SKILL.md`


## Commit 20f6563a — 2026-07-25 10:34
**fix(tail_logs): match motif<->nom normalise (snake vs CamelCase) via patcher en liste**

### Modules Python modifiés
- `tools/forge_patch_tail_logs.py`


## Commit 4c055ea7 — 2026-07-25 10:32
**fix(audit): marqueurs insensibles a la casse, wsl.exe en UTF-16, verdict INCONNU distinct**

### Modules Python modifiés
- `tools/forge_stack_presence_audit.py`


## Commit c7e1e4a6 — 2026-07-25 10:30
**feat(audit): inventaire presence+vivacite des capacites (qdrant/wasm/fts/bm25/mcts)**

### Modules Python modifiés
- `tools/forge_stack_presence_audit.py`


## Commit 10fb6d1b — 2026-07-25 10:09
**fix(searxng): errors=replace sur subprocess docker (anti-regression firehose)**

### Modules Python modifiés
- `tools/forge_searxng_keeper.py`


## Commit 1bad620f — 2026-07-25 10:08
**fix(searxng): monter settings.yml depuis un chemin SANS espace + patcher tail_logs (CRITICAL_FILE)**

### Modules Python modifiés
- `tools/forge_patch_tail_logs.py`
- `tools/forge_searxng_keeper.py`


## Commit f5053f68 — 2026-07-25 10:07
**fix(gate): sonde diagnostic exemptee bornee + ctl restart=stop+start + AUTOLAUNCH docker desarme**

### Modules Python modifiés
- `app/forge_sandbox_exec.py`
- `tools/forge_supervisor_ctl.py`


## Commit 83963c58 — 2026-07-25 09:30
**fix(reaper): epargner seulement les listeners de ports REVENDIQUES (enfant-perdu sur port non revendique = candidat)**

### Modules Python modifiés
- `tools/forge_orphan_reaper.py`


## Commit bb91c044 — 2026-07-25 09:29
**feat(homeostat): moissonneur d'orphelins llama hors-registre + keeper Docker autolaunch (owner)**

### Modules Python modifiés
- `tools/forge_orphan_reaper.py`


## Commit b006ebb3 — 2026-07-25 09:24
**fix(homeostat): eviction ollama in-process + garde anti-sawtooth docker.wanted + rearme evict par capacite**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `tools/forge_ensure_service.py`


## Commit 1139eeca — 2026-07-25 09:05
**chore: absorber la regen post-commit (census SKILL.md + stats README + heartbeats)**

### Documentation mise à jour
- `.agents/skills/laforge/SKILL.md`
- `README.md`
- `docs/skills/laforge/SKILL.md`


## Commit 61720847 — 2026-07-25 01:24
**docs: README + wiki collent au code enrichi (organes gouvernance/cognition/surete)**

### Documentation mise à jour
- `README.md`
- `docs/Nokido_FEATURES.md`
- `docs/wiki/22-Governance-Cognition-Safety.fr.md`
- `docs/wiki/22-Governance-Cognition-Safety.md`
- `docs/wiki/Home.fr.md`
- `docs/wiki/Home.md`


## Commit ab00f3cc — 2026-07-25 00:50
**test(soif): boucle complete de bout en bout sur un gap reel (HNSW recall)**

### Modules Python modifiés
- `tools/forge_soif_demo.py`


## Commit 7f88907e — 2026-07-25 00:41
**feat(safety): cabler le garde held-out dans le hook PostToolUse (embedder)**

### Modules Python modifiés
- `tools/hook_posttool_validate.py`


## Commit baaaaff9 — 2026-07-25 00:34
**feat(safety): garde HELD-OUT deterministe pour le code auto-genere (Phi_T)**

### Modules Python modifiés
- `tools/forge_heldout_gate.py`


## Commit 0a7fb339 — 2026-07-25 00:24
**feat(epistemic): service NokidoEpistemicSoif + filet retention epistemic_seen**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit fb000e5b — 2026-07-25 00:23
**feat(epistemic): cabler la SOIF DE CONNAISSANCE sur les vraies requetes**

### Modules Python modifiés
- `app/forge_epistemic_veille.py`
- `tools/forge_epistemic_daemon