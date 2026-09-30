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

























































































































































































































































































































































































































































































































































## Commit fd80ca15f — 2026-09-26 22:19
**chore: marqueurs repli-hors-depot + churn auto**

### Modules Python modifiés
- `tools/forge_local_pool_wake.py`
- `tools/forge_ui_vitals_cover.py`

### Documentation mise à jour
- `README.md`


## Commit 3b60e9aa6 — 2026-09-26 22:17
**docs: purge SKILL.md (lignes vides) + roadmap cognitif**

### Documentation mise à jour
- `docs/roadmap_plan_cognitif_2026-09-13.md`
- `docs/skills/nokido/SKILL.md`


## Commit 80b29be3a — 2026-09-26 22:17
**feat(routing+forms): axe capacite TRANSPORT!=CAPACITE + forms web_hub a jour**

### Modules Python modifiés
- `app/forge_cognitive_router.py`
- `app/forge_task_router.py`
- `app/web_hub/forms/governed_edit_form.py`
- `app/web_hub/forms/query_form.py`
- `app/web_hub/forms/run_form.py`


## Commit fef2c5725 — 2026-09-26 22:15
**fix(gardes): fail-closed 3-etat + balayage elague**

### Modules Python modifiés
- `app/forge_corrigibility.py`
- `app/forge_mcp_rbac.py`
- `app/forge_proprioception.py`
- `app/forge_ps_sandbox.py`
- `tools/forge_governed_edit.py`


## Commit bb4aaa936 — 2026-09-26 20:52
**fix(session-start): exclure blocs [PERIME]/[NOINJECT] de l'injection de boot**

### Modules Python modifiés
- `tools/claude_session_start.py`


## Commit 566bede98 — 2026-09-26 20:17
**chore(redteam): helper de pose du JSON offensif via profil owner (owner-bridge)**

### Modules Python modifiés
- `tools/finish_redteam_intents.py`


## Commit 82e03a1d9 — 2026-09-26 20:15
**refactor(trajectory): intents offensifs (ring>=3) hors du coeur, charges depuis redteam**

### Modules Python modifiés
- `app/forge_trajectory.py`


## Commit 3d07541c0 — 2026-09-26 20:13
**chore(redteam): JSON offensif vers zone inscriptible, override argv[1]**

### Modules Python modifiés
- `tools/patch_trajectory_offensive_redteam.py`


## Commit 75bd8cbad — 2026-09-26 20:12
**chore(redteam): script de sortie des intents offensifs (ring>=3) hors du coeur**

### Modules Python modifiés
- `tools/patch_trajectory_offensive_redteam.py`


## Commit 6af854be3 — 2026-09-26 20:11
**fix(securite): router_call passe le pare-feu ; persona sans instruction de secours**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `app/forge_persona_engine.py`
- `app/tests/test_persona_engine_nokido.py`
- `tests/nr/test_router_call_pare_feu_nr.py`
- `tools/ci_local.py`


## Commit 85e39996f — 2026-09-26 19:47
**fix(swarm): un pas coupe par timeout compte en echec, son dependant est saute**

### Modules Python modifiés
- `app/forge_swarm_orchestrator.py`
- `tests/test_forge_swarm_orchestrator.py`


## Commit 81b21a8f4 — 2026-09-26 19:43
**docs(veilles): fiche v7 orchestration et conscience operationnelle**

### Documentation mise à jour
- `docs/veilles/fiche_v7_orchestration_conscience_operationnelle_2026-09-26.md`


## Commit 567cad4b7 — 2026-09-26 19:21
**fix(tools): 12 outils importaient nokido_agent avant d'amorcer la racine**

### Modules Python modifiés
- `tests/nr/test_points_d_entree_racine_avant_nokido_agent_nr.py`
- `tools/forge_auth_debug.py`
- `tools/forge_auto_evolution_loop.py`
- `tools/forge_generation_inscrire.py`
- `tools/forge_goap_hub_bridge.py`
- `tools/forge_history_census.py`
- `tools/forge_mcp_http.py`
- `tools/forge_memory_forensics.py`
- `tools/forge_rebuild_embeddings.py`
- `tools/forge_repro_temoin.py`
- `tools/forge_ui_coherence.py`
- `tools/quota_hook.py`
- `tools/test_intent_negotiation.py`


## Commit 55bf22ccd — 2026-09-26 19:10
**fix(panneau): restart du hub seul -- jeton du superviseur, un refus n'est pas un silence**

### Modules Python modifiés
- `tests/nr/test_restart_garde_le_hub_nr.py`
- `tools/nokido_launcher.py`


## Commit bd1e51adb — 2026-09-26 18:39
**fix(stack): les jobs detaches (run_job) survivent au restart full-stack**

### Modules Python modifiés
- `tests/nr/test_stop_epargne_les_jobs_detaches_nr.py`
- `tools/ci_local.py`


## Commit fdf3349a1 — 2026-09-26 18:02
**feat(stack): restart du panneau sans couper le MCP -- hub garde, rebond ~9 s**

### Modules Python modifiés
- `tests/nr/test_restart_garde_le_hub_nr.py`
- `tools/ci_local.py`
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit 10f6dce7c — 2026-09-26 18:02
**fix(tools): patchs du hub par ancre -- source unique (cliquet clones)**

### Modules Python modifiés
- `tools/forge_patch_hub_elicitation.py`
- `tools/forge_patch_hub_ordres_bureau.py`
- `tools/forge_patch_hub_sse_conforme.py`


## Commit 604b568d0 — 2026-09-26 17:27
**fix(hub): ouverture SSE en commentaire, plus de data hors JSON-RPC (patch applique)**

### Modules Python modifiés
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit ce975cee1 — 2026-09-26 17:25
**fix(hub): script de patch pour un flux SSE conforme JSON-RPC (+ NR)**

### Modules Python modifiés
- `tests/nr/test_hub_sse_jsonrpc_conforme_nr.py`
- `tools/forge_patch_hub_sse_conforme.py`


## Commit 209e8b871 — 2026-09-26 16:49
**feat(hub): cable redemarrer_stack et ordre_bureau dans le registre (patch applique)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 761e120bd — 2026-09-26 16:48
**feat(bureau): panneau et tray ring 2, redemarrage full-stack confirme par elicitation**

### Modules Python modifiés
- `app/forge_mcp_elicitation.py`
- `app/forge_ordres_bureau.py`
- `app/forge_videur.py`
- `tests/nr/test_ordres_bureau_nr.py`
- `tests/nr/test_patch_hub_ordres_bureau_nr.py`
- `tests/nr/test_stop_epargne_les_ponts_clients_nr.py`
- `tests/nr/test_tray_calque_sur_le_panneau_nr.py`
- `tools/ci_local.py`
- `tools/forge_patch_hub_ordres_bureau.py`
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit 2350793e0 — 2026-09-26 16:15
**feat(ci): l'apercu du push dit si les rouges GitHub sont couverts**

### Modules Python modifiés
- `tests/nr/test_ci_rouges_couverts_nr.py`
- `tools/ci_local.py`
- `tools/forge_ci_check.py`
- `tools/forge_push_sovereign.py`


## Commit 3d5a5ba7f — 2026-09-26 11:23
**test(hooks): sous-processus du NR InstructionsLoaded en errors=replace**

### Modules Python modifiés
- `tests/nr/test_hook_instructions_loaded_nr.py`


## Commit b5534ea7a — 2026-09-26 11:23
**feat(hooks): capteur InstructionsLoaded -- le poids des consignes se lit**

### Modules Python modifiés
- `tests/nr/test_hook_instructions_loaded_nr.py`
- `tools/ci_local.py`
- `tools/hook_instructions_loaded.py`


## Commit 71e2e50e1 — 2026-09-26 11:19
**feat(hub): cable l'elicitation MCP (patch applique par trusted_script)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tests/nr/test_patch_hub_elicitation_nr.py`
- `tools/nokido_hub.py`


## Commit 078b55f1e — 2026-09-26 11:18
**feat(mcp): elicitation -- le hub peut demander une confirmation a l'owner**

### Modules Python modifiés
- `app/forge_mcp_elicitation.py`
- `tests/nr/test_mcp_elicitation_nr.py`
- `tests/nr/test_patch_hub_elicitation_nr.py`
- `tools/ci_local.py`
- `tools/forge_patch_hub_elicitation.py`
- `tools/hub_middleware.py`


## Commit 760c079be — 2026-09-26 10:29
**fix(watch): le bilan d une CI est sa ligne [preuve], pas le premier Traceback imprime**

### Modules Python modifiés
- `tests/nr/test_job_watch_bilan_gradue_nr.py`
- `tools/forge_job_watch_cli.py`


## Commit 3d898cea1 — 2026-09-26 10:24
**docs(skills): rapatrie 9 skills qui n existaient que dans ~/.claude**

### Documentation mise à jour
- `docs/skills/forge-autonomie/SKILL.md`
- `docs/skills/forge-cognitive-sync/SKILL.md`
- `docs/skills/forge-env/SKILL.md`
- `docs/skills/forge-hub/SKILL.md`
- `docs/skills/forge-ops/SKILL.md`
- `docs/skills/forge-pipeline/SKILL.md`
- `docs/skills/forge-quota/SKILL.md`
- `docs/skills/forge-route/SKILL.md`
- `docs/skills/forge-veille-rapide/SKILL.md`


## Commit c6526c705 — 2026-09-26 10:17
**fix(skills): tilde non developpe dans trois snippets executables**

### Documentation mise à jour
- `docs/skills/forge-rescue/SKILL.md`
- `docs/skills/forge-tdd/SKILL.md`
- `docs/skills/forge-veille-approfondie/SKILL.md`


## Commit d4922f057 — 2026-09-26 10:12
**fix(skills): forge_skill_sync ne meurt plus sur la console cp1252 de l owner**

### Modules Python modifiés
- `tests/nr/test_point_entree_par_chemin_nr.py`
- `tools/forge_skill_sync.py`


## Commit 9033d5c0c — 2026-09-26 10:05
**fix(skill-sync): racine importable avant nokido_agent -- l'outil mourait lance par chemin**

### Modules Python modifiés
- `tests/nr/test_point_entree_par_chemin_nr.py`
- `tools/forge_skill_sync.py`


## Commit d62be24b4 — 2026-09-26 10:00
**test(purge): l'assertion de la simulation nomme les entrees au lieu de les compter**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`


## Commit 1661cb79d — 2026-09-26 09:57
**docs(prompts): 2e passe d'audit des surfaces chargees (26/09)**

### Documentation mise à jour
- `CLAUDE.md`
- `docs/skills/forge-anatomy/SKILL.md`
- `docs/skills/forge-android/SKILL.md`
- `docs/skills/forge-marketplace/SKILL.md`
- `docs/skills/forge-models/SKILL.md`
- `docs/skills/forge-skills/SKILL.md`
- `docs/skills/forge-systematic-debugging/SKILL.md`


## Commit cc844930b — 2026-09-26 06:04
**fix(memoire): index (fname, seq) sur le ledger -- hook SessionStart tue a 8 s**

### Modules Python modifiés
- `tests/nr/test_memory_ledger_index_fname_nr.py`
- `tools/ci_local.py`
- `tools/forge_memory_ledger.py`


## Commit 03efe7f2c — 2026-09-26 05:47
**fix(watch): ARRET_GARDE seulement pour un arret en queue de journal**

### Modules Python modifiés
- `tests/nr/test_job_watch_bilan_gradue_nr.py`
- `tools/forge_job_watch_cli.py`


## Commit f16ff19ac — 2026-09-26 05:42
**feat(session): PostModelSwitch suit le modele, et la reprise sur cache expire annonce son cout**

### Modules Python modifiés
- `tests/nr/test_session_start_rappel_audit_nr.py`
- `tools/claude_session_start.py`


## Commit cd85aeead — 2026-09-26 05:22
**fix(pip-audit): un --sortie relatif se resout contre le depot (la mesure NREM1 lisait un echec)**

### Modules Python modifiés
- `tests/nr/test_pip_audit_sortie_relative_nr.py`
- `tools/ci_local.py`
- `tools/forge_pip_audit_mesure.py`


## Commit 2615a3914 — 2026-09-26 05:21
**feat(session): un changement de modele ou de CLI rappelle l'audit de prompts, jusqu'a acquittement**

### Modules Python modifiés
- `tests/nr/test_session_start_rappel_audit_nr.py`
- `tools/ci_local.py`
- `tools/claude_session_start.py`


## Commit 453118206 — 2026-09-26 05:12
**docs(prompts): audit des surfaces toujours chargees (skill claude-api prompt-audit, 26/09)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/claude_session_start.py`
- `tools/forge_tool_gate.py`
- `tools/hook_capability_gate.py`
- `tools/hook_search_guard.py`

### Documentation mise à jour
- `CLAUDE.md`
- `RULES_SHARED.md`


## Commit 45f665945 — 2026-09-26 05:11
**fix(test): le NR usage Groq ne charge plus le vrai openai (CI GitHub rouge, run 36211634261)**

### Modules Python modifiés
- `tests/nr/test_usage_provider_estime_n_est_pas_rapporte_nr.py`


## Commit ca62d7cfa — 2026-09-26 04:53
**chore(patch): patcher des descriptions d'outils MCP (audit de prompts 26/09)**

### Modules Python modifiés
- `tools/patch_audit_prompts_registry.py`


## Commit feff93f93 — 2026-09-26 04:42
**feat(pre-push): les cliquets golden-rules + duplication jouent avant chaque push**

### Modules Python modifiés
- `tests/nr/test_prepush_cliquets_nr.py`
- `tools/ci_local.py`
- `tools/forge_prepush_cliquets.py`


## Commit 4d3950fbf — 2026-09-26 03:41
**test(auth): la suite suit la cloture du 24/09 ; /api/push hors du public (owner)**

### Modules Python modifiés
- `app/forge_authz_shadow.py`
- `tests/nr/test_authz_axes_separes_nr.py`
- `tests/nr/test_authz_shadow_nr.py`
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tests/nr/test_journal_porte_acteur_et_sujet_nr.py`
- `tests/nr/test_revue_identite_et_separation_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tests/nr/test_routes_organes_authentifiees_nr.py`
- `tests/nr/test_tpm_descripteur_lecture_seule_nr.py`


## Commit 5a3db0c79 — 2026-09-26 03:41
**test(sauvegarde): cible fixe sans place -- test hermetique**

### Modules Python modifiés
- `tests/nr/test_sauvegarde_cible_fixe_nr.py`


## Commit 7fcaf42e7 — 2026-09-26 03:41
**fix(veille): le clone survit aux chemins profonds (core.longpaths)**

### Modules Python modifiés
- `tools/forge_veille_clone_ingest.py`


## Commit 26d1f6b0c — 2026-09-26 02:48
**test: la suite pure ne meurt plus d'un test lent ; open_path en boucle locale admis**

### Modules Python modifiés
- `tests/nr/test_hub_m.py`
- `tests/nr/test_tui_136_adaptateurs_nr.py`


## Commit 706c68e4a — 2026-09-26 02:06
**refactor: trois groupes de clones factorises (cliquet duplication)**

### Modules Python modifiés
- `app/forge_edge_fleet.py`
- `app/forge_utils.py`
- `app/web_hub/provider_views.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/nokido_opencode_web.py`


## Commit eb8fad0d5 — 2026-09-26 02:05
**fix(ci): la suite pure passe sa liste par fichier @ ; une duree n'est pas un secret**

### Modules Python modifiés
- `tests/nr/test_ci_suite_pure_ligne_de_commande_nr.py`
- `tests/nr/test_golden_secret_env_duree_nr.py`
- `tools/ci_local.py`
- `tools/forge_golden_rules_ast.py`


## Commit f6b3613bb — 2026-09-26 01:32
**fix(veille): le juge de selection peut ecarter, voit le resume, ne double pas**

### Modules Python modifiés
- `app/forge_research_agent.py`
- `tests/nr/test_veille_gel_et_pertinence_nr.py`


## Commit 4fcedde23 — 2026-09-26 01:28
**test(authz): inventaire des ecrivains RAG a jour -- /api/watch/create est GARDE_UI**

### Modules Python modifiés
- `tests/nr/test_ecriture_rag_chemins_connus_nr.py`


## Commit 63d97a300 — 2026-09-26 01:25
**fix(veille): le controle de gel emprunte la cle primaire (+active)**

### Modules Python modifiés
- `app/forge_research_agent.py`
- `tests/nr/test_veille_gel_et_pertinence_nr.py`


## Commit d8a4bfa8b — 2026-09-26 01:23
**fix(veille): la soif respecte le gel et ecarte le hors sujet en le disant**

### Modules Python modifiés
- `app/forge_research_agent.py`
- `tests/nr/test_veille_gel_et_pertinence_nr.py`
- `tools/ci_local.py`


## Commit 559aeadf6 — 2026-09-26 01:04
**fix(veille): les articles arXiv sont lus en /html/ (article, pas resume), sans CSS**

### Modules Python modifiés
- `app/forge_research_agent.py`
- `tests/nr/test_veille_arxiv_html_nr.py`
- `tools/ci_local.py`


## Commit 8e0e6e555 — 2026-09-26 01:00
**feat(evolution): registre d'evolution CHAINE -- l'historique de preuve ne se reecrit plus en silence**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_registre_evolution_chaine_nr.py`
- `tools/ci_local.py`


## Commit 371f17c5c — 2026-09-26 00:57
**feat(generation): le gain est un verdict de Pareto, ajouter des modules n'est plus une victoire**

### Modules Python modifiés
- `app/forge_generation.py`
- `tests/nr/test_generation_fitness_pareto_nr.py`
- `tools/ci_local.py`


## Commit 1b541710c — 2026-09-26 00:52
**fix(veille): des moteurs SearXNG muets ne se lisent plus comme un web vide**

### Modules Python modifiés
- `app/forge_research_agent.py`
- `tests/nr/test_veille_moteurs_muets_nr.py`
- `tools/ci_local.py`


## Commit 5d3bdbae3 — 2026-09-26 00:47
**feat(juge): evaluateur hors de portee des mutations, non-regression PAR test (veille RSI)**

### Modules Python modifiés
- `app/forge_mutation_judge.py`
- `tests/nr/test_juge_evaluateur_hors_portee_nr.py`
- `tools/ci_local.py`


## Commit 59bcd2658 — 2026-09-26 00:33
**fix(evolution): une decision de tri d'un instrument perime est rejugee**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_tri_des_experiences_nr.py`


## Commit 1ea57fc10 — 2026-09-26 00:16
**fix(proxy): une reponse VIDE n'empoisonne plus le fil de conversation**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tests/nr/test_proxy_fil_sans_tour_vide_nr.py`
- `tools/ci_local.py`


## Commit 4c7f6ec00 — 2026-09-26 00:06
**fix(router): repli OAuth -- 403 nu exclu, plafond horaire (consensus debat CLAUDE<->AGY)**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tests/nr/test_router_repli_oauth_capacite_nr.py`


## Commit 347fba119 — 2026-09-25 23:26
**fix(router): repli OAuth (AGY puis Claude Code) sur cascade epuisee par la CAPACITE**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tests/nr/test_router_repli_oauth_capacite_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit de15c7cba — 2026-09-25 22:45
**fix(evolution): capteur unmet_intention en liste BLANCHE de docs d'intention**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_tri_des_experiences_nr.py`
- `tests/nr/test_unmet_intention_liste_blanche_nr.py`
- `tools/ci_local.py`


## Commit 1999e713e — 2026-09-25 20:54
**fix(traces): l'issue d'un appel fournisseur atteint execution_traces**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_autonomous_loops.py`
- `tests/nr/test_proxy_journalise_echec_fournisseur_nr.py`
- `tests/nr/test_trace_mining_emission_n_est_pas_une_issue_nr.py`
- `tests/nr/test_trace_sidecar_issue_cloud_nr.py`
- `tools/ci_local.py`
- `tools/forge_trace_sidecar.py`


## Commit fcbfc4797 — 2026-09-25 20:40
**fix(evolution): une emission CALL n'est pas une issue -- capteur d'usage**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_trace_mining_emission_n_est_pas_une_issue_nr.py`
- `tools/ci_local.py`


## Commit d95a1b8ef — 2026-09-25 20:02
**feat(evolution): le tri re-examine chaque dossier avec l'instrument qui l'a ouvert**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_tri_des_experiences_nr.py`


## Commit 5160354b2 — 2026-09-25 19:57
**fix(diagnostic): une ligne de soin ne porte plus l'age de l'examen**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `tests/nr/test_medecin_lit_les_examens_nr.py`


## Commit 394cbd15f — 2026-09-25 17:24
**feat(evolution): tri a blanc des experiences -- le maillon entre variation et selection**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_tri_des_experiences_nr.py`
- `tools/ci_local.py`


## Commit 19fa34347 — 2026-09-25 17:04
**fix(soif): une intention est un travail INTERNE par defaut -- recidive de 16:58**

### Modules Python modifiés
- `tests/nr/test_soif_choisit_son_traitement_nr.py`
- `tools/forge_epistemic_daemon.py`


## Commit 27000fd80 — 2026-09-25 16:49
**fix(superviseur): le capteur RAM lisait 100 % depuis 20 h -- il endormait tout le corps**

### Modules Python modifiés
- `tests/nr/test_capteur_ram_superviseur_nr.py`
- `tools/ci_local.py`


## Commit a1c8622c7 — 2026-09-25 16:44
**fix(amorce): tri des 66 inversions -- un seul lance ET casse de plus, repare**

### Modules Python modifiés
- `tests/nr/test_pypi_amorce_nr.py`
- `tools/forge_embed_8099_mesure_bornee.py`


## Commit 15185c42f — 2026-09-25 16:41
**fix(regulation): la rafale RAM n'endort plus le regulateur des piliers**

### Modules Python modifiés
- `tests/nr/test_soif_bloquee_par_dependance_nr.py`


## Commit fff0052ce — 2026-09-25 16:28
**fix(examens): deux producteurs d'examens morts a l'import, et l'outil d'amorce qui le cachait**

### Modules Python modifiés
- `tests/nr/test_point_entree_par_chemin_nr.py`
- `tests/nr/test_pypi_amorce_nr.py`
- `tools/forge_capability_execution_trace.py`
- `tools/forge_provider_reachability.py`
- `tools/forge_pypi_amorce.py`


## Commit 6bae36b19 — 2026-09-25 16:23
**feat(diagnostic): le medecin lit les examens des autres organes, et un critique exige deux sondes**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `tests/nr/test_critique_exige_deux_sondes_nr.py`
- `tests/nr/test_medecin_lit_les_examens_nr.py`
- `tools/ci_local.py`
- `tools/forge_epistemic_daemon.py`


## Commit 064425ed3 — 2026-09-25 16:14
**fix(soif): un manque INTERNE ne part plus en veille web -- le diagnostic choisit le remede**

### Modules Python modifiés
- `tests/nr/test_soif_choisit_son_traitement_nr.py`
- `tools/ci_local.py`
- `tools/forge_epistemic_daemon.py`


## Commit 60dff3729 — 2026-09-25 16:02
**fix(soif): le journal dit l'ISSUE de chaque veille, plus seulement son lancement**

### Modules Python modifiés
- `tests/nr/test_soif_bloquee_par_dependance_nr.py`
- `tools/forge_epistemic_daemon.py`


## Commit 701c1c675 — 2026-09-25 15:59
**fix(veille): la veille de la soif passe par le routeur ; plus de modele Groq mort**

### Modules Python modifiés
- `app/forge_epistemic_veille.py`
- `app/forge_research_agent.py`
- `tests/nr/test_veille_modele_vivant_nr.py`
- `tests/test_epistemic_veille.py`
- `tools/ci_local.py`


## Commit 49655c867 — 2026-09-25 15:43
**fix(services): NokidoLlamaKeeper rearme en mode PILIERS SEULS (decision owner)**

### Modules Python modifiés
- `tests/nr/test_soif_bloquee_par_dependance_nr.py`


## Commit 4b99acb1c — 2026-09-25 15:36
**fix(soif): bloquee par dependance, elle le DIT et declare son besoin de reranker**

### Modules Python modifiés
- `app/forge_epistemic_veille.py`
- `tests/nr/test_soif_bloquee_par_dependance_nr.py`
- `tools/ci_local.py`
- `tools/forge_epistemic_daemon.py`


## Commit c8d40aba7 — 2026-09-25 15:17
**fix(coffre): --neutraliser respecte --cles -- ne vide que les cles demandees**

### Modules Python modifiés
- `tests/nr/test_env_neutralisation_coffre_nr.py`
- `tools/forge_env_to_vault.py`


## Commit ee609e569 — 2026-09-25 15:16
**feat(coffre): acces SSH au coffre, saisis sur la page des cles ; plus rien en clair**

### Modules Python modifiés
- `app/Nokido.py`
- `app/brain_worker.py`
- `app/forge_env_sync.py`
- `app/forge_mesh_memory.py`
- `app/forge_provider_admin.py`
- `app/forge_settings.py`
- `app/web_hub/provider_views.py`
- `tests/nr/test_acces_ssh_au_coffre_nr.py`
- `tests/nr/test_env_neutralisation_coffre_nr.py`
- `tools/ci_local.py`
- `tools/forge_env_to_vault.py`


## Commit b4969a7aa — 2026-09-25 14:00
**fix(dlp): l'historique et le flux SSE de net_log ne portent plus la charge brute**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `tests/nr/test_journal_actes_agents_nr.py`


## Commit 49d5f5b16 — 2026-09-25 13:56
**fix(dlp): le journal des actes dit la reponse du hub ; plus de clef en clair**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `tests/nr/test_journal_actes_agents_nr.py`


## Commit 9e529ac46 — 2026-09-25 13:41
**docs(veilles): fiche netcfg jumeau numerique -- 12 depots, Pipeline B**

### Documentation mise à jour
- `docs/veilles/fiche_netcfg_jumeau_numerique_2026-09-25.md`


## Commit 6f13d5dc0 — 2026-09-25 13:14
**fix(usage): les appels alertants n'etaient jamais comptes ; actes lisibles**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `app/forge_token_monitor.py`
- `tests/nr/test_journal_actes_agents_nr.py`
- `tests/nr/test_token_usage_appel_alertant_compte_nr.py`
- `tools/ci_local.py`


## Commit ad6e25589 — 2026-09-25 12:57
**feat(audit): journal des actes -- ce qu'un agent execute est lisible**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `tests/nr/test_journal_actes_agents_nr.py`
- `tools/ci_local.py`


## Commit 0c5624189 — 2026-09-25 12:55
**fix(passerelle): nokido/auto -- repli local candidat, estimation juste**

### Modules Python modifiés
- `tests/nr/test_passerelle_voie_outils_nr.py`
- `tools/forge_openai_proxy.py`


## Commit 89d76d371 — 2026-09-25 12:53
**fix(passerelle): comptage d'usage dit son verdict ; banc sans pollution**

### Modules Python modifiés
- `tests/nr/test_passerelle_voie_outils_nr.py`
- `tools/forge_openai_proxy.py`


## Commit 605ef3205 — 2026-09-25 12:50
**feat(passerelle): nokido/auto -- le routeur choisit, bascule typee**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `app/forge_provider_alias.py`
- `tests/nr/test_passerelle_voie_outils_nr.py`
- `tools/forge_openai_proxy.py`


## Commit 22702ac21 — 2026-09-25 12:06
**feat(sonde-tool-call): modeles forts designes ; 429 = NON_MESURE**

### Modules Python modifiés
- `tests/nr/test_tool_call_probe_modeles_nr.py`
- `tools/ci_local.py`
- `tools/forge_tool_call_probe.py`


## Commit 82e973bb1 — 2026-09-25 11:59
**fix(membrane): l'alias d'un chemin garde sa racine en clair**

### Modules Python modifiés
- `app/forge_sovereign_membrane.py`
- `tests/nr/test_membrane_reversible_nr.py`


## Commit 36298892f — 2026-09-25 11:57
**fix(membrane): mode reversible masque le compte, pas le chemin entier**

### Modules Python modifiés
- `app/forge_sovereign_membrane.py`
- `tests/nr/test_membrane_reversible_nr.py`


## Commit 961629938 — 2026-09-25 11:55
**feat(membrane,passerelle): pseudonymisation reversible ; feed lisible**

### Modules Python modifiés
- `app/forge_silo_fragmenter.py`
- `app/forge_sovereign_membrane.py`
- `tests/nr/test_membrane_reversible_nr.py`
- `tests/nr/test_passerelle_voie_outils_nr.py`
- `tests/nr/test_portail_sans_mojibake_nr.py`
- `tools/ci_local.py`
- `tools/forge_openai_proxy.py`


## Commit 0f32c25b9 — 2026-09-25 11:38
**fix(tui-v13,lanceur): demarrage via bridge :7440 ; journal qui survit**

### Modules Python modifiés
- `app/forge_handler_patch.py`
- `app/forge_startup.py`
- `app/web_hub/launcher_html.py`
- `tests/nr/test_launcher_journal_survit_refresh_nr.py`
- `tests/nr/test_prefect_manager_appel_vivant_nr.py`
- `tests/nr/test_purge_garde_main_nr.py`
- `tools/ci_local.py`


## Commit 13b2efdc0 — 2026-09-25 11:21
**fix(pare-feu,reseau): squashed borne ; scapy charge au premier sniff**

### Modules Python modifiés
- `app/forge_network.py`
- `app/forge_prompt_guard.py`
- `tests/nr/test_network_scapy_paresseux_nr.py`
- `tests/nr/test_squashed_ecart_borne_nr.py`
- `tools/ci_local.py`


## Commit 370cd24f9 — 2026-09-25 10:51
**fix(tui-13.6): adaptateurs charges au lancement reel, absence dite**

### Modules Python modifiés
- `tests/nr/test_tui_136_adaptateurs_nr.py`
- `tools/ci_local.py`
- `tools/forge_tui_sonde.py`
- `tools/nokido_tui.py`


## Commit 68beb360e — 2026-09-25 10:42
**feat(tui-sonde): --pile-apres pour un demarrage muet**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit cd79b28f4 — 2026-09-25 10:41
**feat(tui-sonde): mode --chemin-reel du bridge :7440**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit e89a735f1 — 2026-09-25 10:37
**fix(passerelle): voie outils sans substitution de modele**

### Modules Python modifiés
- `tests/nr/test_passerelle_voie_outils_nr.py`
- `tools/ci_local.py`
- `tools/forge_openai_proxy.py`


## Commit caa85df53 — 2026-09-25 01:49
**fix(ui): diagnostic opencode -- sessions par projet, appels /session, creation par l'API**

### Modules Python modifiés
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/nokido_opencode_web.py`


## Commit c6ee1fe76 — 2026-09-25 01:46
**fix(ui): opencode -- sortie NTSTATUS bornee, diagnostic lit le journal d'opencode**

### Modules Python modifiés
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/nokido_opencode_web.py`


## Commit 962bb2601 — 2026-09-25 01:41
**feat(sec): opencode passe par la passerelle gouvernee :7777, Zen coupe**

### Modules Python modifiés
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/nokido_opencode_web.py`


## Commit c6b8fb95b — 2026-09-25 01:34
**feat(ui): diagnostic en lecture seule du serveur opencode en marche**

### Modules Python modifiés
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/nokido_opencode_web.py`


## Commit 50aec6807 — 2026-09-25 01:20
**feat(sec): opencode s'authentifie au hub selon les regles -- jeton derive, config gouvernee**

### Modules Python modifiés
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/forge_vault_seed_agent_tokens.py`
- `tools/nokido_opencode_web.py`

### Documentation mise à jour
- `config/clients/opencode/README.md`


## Commit bb4dcdb90 — 2026-09-25 01:13
**feat(ui): opencode dans le lanceur :7400, ferme par defaut (choix A de l'owner)**

### Modules Python modifiés
- `app/web_hub/app.py`
- `app/web_hub/launcher.py`
- `tests/nr/test_opencode_web_ferme_nr.py`
- `tools/ci_local.py`
- `tools/nokido_opencode_web.py`


## Commit 69c89f364 — 2026-09-25 00:50
**fix(tui): via le hub, la TUI ne declenche plus l'indexation locale d'app/ et tools/**

### Modules Python modifiés
- `app/forge_rag_warmup.py`
- `tests/nr/test_tui_rag_via_hub_nr.py`


## Commit 08b9593c0 — 2026-09-25 00:49
**fix(ui): page /rag sans 17 s de comptages ; /favicon.ico servi par :7400 et :8766**

### Modules Python modifiés
- `app/web_hub/app.py`
- `app/web_hub/wired_routes.py`
- `tests/nr/test_pages_ui_8766_saines_nr.py`
- `tests/nr/test_rag_stats_instantane_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 5c20ba8e9 — 2026-09-25 00:47
**feat(ui): sonde TUI -- nommer les fils qui retiennent le processus**

### Modules Python modifiés
- `tests/nr/test_forge_tui_sonde_nr.py`
- `tools/forge_tui_sonde.py`


## Commit e45351ed7 — 2026-09-25 00:36
**feat(ui): sonde TUI -- jalons ecrits au fil de l'eau**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit d0f837f7d — 2026-09-25 00:34
**feat(tui): la TUI v13 interroge le RAG du hub (decision owner 1)**

### Modules Python modifiés
- `app/Nokido.py`
- `app/forge_rag_via_hub.py`
- `tests/nr/test_tui_rag_via_hub_nr.py`
- `tools/ci_local.py`


## Commit c5c8f2df1 — 2026-09-25 00:21
**fix(tui): raccourcis de la TUI v13 atteignables (F2/F3/F4/F6)**

### Modules Python modifiés
- `app/Nokido.py`
- `tests/nr/test_tui_raccourcis_atteignables_nr.py`
- `tools/forge_tui_sonde.py`


## Commit d4d2dd542 — 2026-09-25 00:17
**fix(ui): campagne juge desactive et rechargement ; icones /vitals et /forge/rings**

### Modules Python modifiés
- `app/forge_ring_admin.py`
- `app/web_hub/app.py`
- `tools/forge_ui_campaign.py`


## Commit 4ea638d0b — 2026-09-25 00:16
**fix(ui): sonde TUI -- construire la v13 comme son vrai lancement**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit 5f3a6c960 — 2026-09-25 00:15
**feat(ui): sonde TUI --sans-rag, rapport dans le depot**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit 0b223fa6e — 2026-09-25 00:13
**feat(ui): sonde TUI -- cible, rapport sur disque, pile et sortie si montage bloque**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit 060c9ca9a — 2026-09-25 00:10
**fix(ui): sonde TUI -- reinscrire le module v13 apres son import**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit 8393118db — 2026-09-25 00:09
**fix(ui): sonde TUI -- inscrire le module v13 dans sys.modules avant execution**

### Modules Python modifiés
- `tools/forge_tui_sonde.py`


## Commit 8151494df — 2026-09-25 00:08
**feat(ui): tools/forge_tui_sonde.py -- sonde headless des deux TUI**

### Modules Python modifiés
- `tests/nr/test_forge_tui_sonde_nr.py`
- `tools/ci_local.py`
- `tools/forge_tui_sonde.py`


## Commit 6d2475fc9 — 2026-09-25 00:05
**fix(ui): decisions owner (Masquer, lecture seule) + raccourcis TUI atteignables**

### Modules Python modifiés
- `tests/nr/test_hub_persona_masquer_nr.py`
- `tests/nr/test_pages_ui_8766_saines_nr.py`
- `tests/nr/test_tui_raccourcis_atteignables_nr.py`
- `tools/ci_local.py`
- `tools/forge_ui_campaign.py`
- `tools/nokido_hub.py`
- `tools/nokido_tui.py`

### Documentation mise à jour
- `design_handoff_nokido/ui_kits/hub/README.md`
- `docs/tui_user_guide.md`
- `docs/wiki/02-Quick-Start.fr.md`
- `docs/wiki/02-Quick-Start.md`
- `docs/wiki/05-LLM-Providers.fr.md`
- `docs/wiki/05-LLM-Providers.md`
- `docs/wiki/09-TUI-Reference.fr.md`
- `docs/wiki/09-TUI-Reference.md`
- `docs/wiki/17-First-Launch.fr.md`
- `docs/wiki/17-First-Launch.md`


## Commit b4f1b46bd — 2026-09-24 23:50
**fix(ui:8766): polices servies, /forge/network sans TypeError, refus MCP dit**

### Modules Python modifiés
- `tests/nr/test_pages_ui_8766_saines_nr.py`
- `tools/ci_local.py`
- `tools/forge_ui_campaign.py`
- `tools/nokido_hub.py`


## Commit 2d5a84d7b — 2026-09-24 23:43
**fix(tui): l'aide F1 et /help ne sont plus effacees en moins d'une seconde**

### Modules Python modifiés
- `tests/nr/test_tui_aide_reste_visible_nr.py`
- `tools/ci_local.py`
- `tools/nokido_tui.py`


## Commit 946b456ac — 2026-09-24 23:40
**fix(ui): page /epistemic sans balayage + campagne etendue aux vues hub et a :8766**

### Modules Python modifiés
- `app/web_hub/epistemic.py`
- `tests/nr/test_chemin_chaud_sans_balayage_nr.py`
- `tests/nr/test_epistemic_page_sans_balayage_nr.py`
- `tests/nr/test_ui_campagne_couvre_les_vues_hub_nr.py`
- `tools/ci_local.py`
- `tools/forge_ui_campaign.py`


## Commit 42adc4148 — 2026-09-24 23:18
**feat(veilles): usage rendu par Groq enregistre REPORTED, cache compris**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tests/nr/test_usage_provider_estime_n_est_pas_rapporte_nr.py`


## Commit 38ce17520 — 2026-09-24 23:13
**fix(veilles): sondes health en parallele + usage fournisseur declare ESTIMATED**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_health_diagnostic.py`
- `app/forge_sensor_fusion_probe.py`
- `tests/nr/test_fusion_ports_sondes_en_parallele_nr.py`
- `tests/nr/test_health_services_http_en_parallele_nr.py`
- `tests/nr/test_usage_provider_estime_n_est_pas_rapporte_nr.py`
- `tests/test_sensor_fusion_probe.py`
- `tools/ci_local.py`


## Commit 44d4ec62e — 2026-09-24 22:41
**fix(veille): GATE_DENIED classe REJETE, pas INCONNU (C_06b-1)**

### Modules Python modifiés
- `app/forge_rss_watcher.py`
- `tests/nr/test_rss_watcher_ne_perd_plus_d_alerte_nr.py`


## Commit f7642ea3e — 2026-09-24 22:31
**fix(veille): une alerte n'est plus marquee vue sans ingestion prouvee (C_06b)**

### Modules Python modifiés
- `app/forge_rss_watcher.py`
- `tests/nr/test_rss_watcher_ne_perd_plus_d_alerte_nr.py`
- `tools/ci_local.py`


## Commit 5614c863d — 2026-09-24 22:17
**fix(retention): la purge leve l'attribut lecture seule, les refus nomment le fichier**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tools/forge_log_retention.py`


## Commit 5677fa8b3 — 2026-09-24 22:10
**fix(veille): les scans de code du consommateur comptent les fichiers illisibles**

### Modules Python modifiés
- `app/forge_diff_analyzer.py`
- `tests/nr/test_watch_alerts_identite_canonique_nr.py`


## Commit d8602993f — 2026-09-24 22:09
**fix(veille): le consommateur des alertes de version lit enfin les alertes (C_06a, non cable)**

### Modules Python modifiés
- `app/forge_diff_analyzer.py`
- `tests/nr/test_watch_alerts_identite_canonique_nr.py`
- `tools/ci_local.py`


## Commit 2268a0379 — 2026-09-24 22:04
**fix(retention): un dossier sans .git n'est supprime que si git worktree list ne le connait plus**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tools/forge_log_retention.py`


## Commit 67d0662fc — 2026-09-24 22:00
**fix(retention): les dossiers de preuve sans .git sont purges, noms des retires traces**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tools/forge_log_retention.py`


## Commit 4467f2f9c — 2026-09-24 21:34
**fix(retention): racine importable avant le point unique tmp, la purge des preuves lit enfin la racine de la CI**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tools/forge_log_retention.py`


## Commit 672f3d8b0 — 2026-09-24 21:28
**fix(providers): la redirection d'un alias refuse est calculee sur la surface presente**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_provider_alias.py`
- `tests/nr/test_provider_alias_nr.py`


## Commit d5dcd38dc — 2026-09-24 21:23
**fix(providers): pas de substitution silencieuse de modele par alias ; gemini_flash/pro renvoient vers AGY**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_provider_alias.py`
- `tests/nr/test_provider_alias_nr.py`


## Commit 2a42579b3 — 2026-09-24 21:11
**fix(health): un journal illisible est compte, pas saute en silence**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`


## Commit 260df094c — 2026-09-24 21:10
**fix(health,retention): phase health hors de ses 90 s, et la purge des preuves CI purge enfin**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `tests/nr/test_health_journaux_sans_copies_de_depot_nr.py`
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tools/ci_local.py`
- `tools/forge_log_retention.py`
- `tools/forge_worktree.py`


## Commit 6420a4e93 — 2026-09-24 20:51
**feat(git-gate): soupape anti-perte etroite, le scan de secrets n'est plus enjambable par conseil**

### Modules Python modifiés
- `tests/nr/test_aucun_outil_ne_contourne_les_hooks_git_nr.py`
- `tests/nr/test_git_gate_soupape_etroite_nr.py`
- `tools/ci_local.py`
- `tools/forge_git_gate.py`


## Commit b2c1c9fd7 — 2026-09-24 20:46
**fix(nr): subprocess texte avec errors=replace dans le cliquet --no-verify**

### Modules Python modifiés
- `tests/nr/test_aucun_outil_ne_contourne_les_hooks_git_nr.py`


## Commit 8d458a0bf — 2026-09-24 20:45
**test(nr): aucun outil suivi ne passe --no-verify a git**

### Modules Python modifiés
- `tests/nr/test_aucun_outil_ne_contourne_les_hooks_git_nr.py`
- `tools/ci_local.py`


## Commit 02e8d5e5b — 2026-09-24 20:40
**test(nr): le bail de mission reprend une fois, garde le checkpoint, abandonne apres plafond**

### Modules Python modifiés
- `tests/nr/test_tache_bail_expire_reprise_nr.py`
- `tools/ci_local.py`


## Commit a739eca4c — 2026-09-24 20:37
**feat(qualite): detecteur de NR instables, verdict test par test sur JUnit**

### Modules Python modifiés
- `tests/nr/test_nr_instables_nr.py`
- `tools/ci_local.py`
- `tools/forge_nr_instables.py`


## Commit 9f604cbfd — 2026-09-24 20:35
**test(nr): cliquet des chemins frequents sans balayage de la base RAG**

### Modules Python modifiés
- `tests/nr/test_chemin_chaud_sans_balayage_nr.py`
- `tools/ci_local.py`


## Commit a573459a8 — 2026-09-24 20:28
**fix(providers): ask resout les noms du registre du hub par la table d'alias**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tests/nr/test_provider_alias_nr.py`


## Commit 554f3fc99 — 2026-09-24 20:24
**feat(services): geler QdrantSync, et un service gele n'est plus reveille par la RAM**

### Modules Python modifiés
- `tests/nr/test_service_gele_jamais_reveille_par_la_ram_nr.py`
- `tools/ci_local.py`


## Commit 6a1f7a1bc — 2026-09-24 19:49
**fix(superviseur): boucle de vitalite sans promesse pendue sur le pool sature**

### Modules Python modifiés
- `tests/nr/test_superviseur_boucle_ressources_non_bloquante_nr.py`
- `tests/nr/test_supervisor_authz_contrat_nr.py`
- `tools/ci_local.py`


## Commit 6e8b4f848 — 2026-09-24 19:40
**fix(services): racine importable AVANT nokido_agent dans 6 points d'entree**

### Modules Python modifiés
- `app/forge_gate_consumer.py`
- `app/forge_hebbian_linker.py`
- `tests/nr/test_points_d_entree_racine_avant_nokido_agent_nr.py`
- `tools/ci_local.py`
- `tools/cli_tail_capture.py`
- `tools/forge_gemini_autonomous_agent.py`
- `tools/forge_qdrant_sync_daemon.py`
- `tools/forge_reindex_deport.py`


## Commit 0011cebcd — 2026-09-24 19:27
**fix(veille): la moisson reconnait une VRAIE phrase et l'extrait demarre au corps**

### Modules Python modifiés
- `tests/nr/test_moisson_page_corps_et_sources_propres_nr.py`
- `tools/forge_veille_moisson.py`


## Commit e7f60efba — 2026-09-24 19:09
**feat(superviseur): journal des ordres mutants -- qui endort, reveille, demarre**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `tests/nr/test_superviseur_pas_de_double_demarrage_nr.py`


## Commit 502f78306 — 2026-09-24 19:06
**fix(superviseur): plus de double demarrage (orphelins) + purge auto des worktrees de CI**

### Modules Python modifiés
- `tests/nr/test_purge_worktrees_de_preuve_nr.py`
- `tests/nr/test_superviseur_pas_de_double_demarrage_nr.py`
- `tools/ci_local.py`
- `tools/forge_log_retention.py`


## Commit 3695bac17 — 2026-09-24 17:45
**feat(auto-amelioration): cable l'applicateur de propositions (etage reflexe seul)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_pattern_proposal_applier_nr.py`
- `tools/ci_local.py`


## Commit 00e7ff03c — 2026-09-24 17:33
**fix(sauvegarde): cible fixe -- la preparation se fait SUR LA CIBLE, jamais sur C:**

### Modules Python modifiés
- `tests/nr/test_sauvegarde_cible_fixe_nr.py`
- `tools/forge_backup_hotswap.py`


## Commit 953c21f6d — 2026-09-24 17:26
**fix(sauvegarde): un journal refuse ne tue plus la sauvegarde a l'import**

### Modules Python modifiés
- `tests/nr/test_sauvegarde_cible_fixe_nr.py`
- `tools/forge_backup_hotswap.py`


## Commit 3ba0b05bd — 2026-09-24 17:21
**fix(sauvegarde): cle hors des arguments + cible fixe E: (decision owner)**

### Modules Python modifiés
- `tests/nr/test_sauvegarde_cible_fixe_nr.py`
- `tools/ci_local.py`
- `tools/forge_backup_hotswap.py`


## Commit 958fe3f21 — 2026-09-24 17:05
**feat(auth): arme LAFORGE_ADMIN_TPM_ENFORCE -- preuve TPM exigee sur les routes admin**

### Modules Python modifiés
- `tests/nr/test_admin_preuve_tpm_nr.py`


## Commit 2364685fd — 2026-09-24 16:56
**fix(superviseur): E/S hors du pool bloquant sature -- etat circadien et preuve TPM**

### Modules Python modifiés
- `tests/nr/test_admin_preuve_tpm_nr.py`
- `tools/forge_dpop_tpm_cli.py`


## Commit 5e55b698f — 2026-09-24 16:45
**feat(retention): conversation_log surveille, jamais purge tant que rien n'est distille**

### Modules Python modifiés
- `tests/nr/test_conversation_log_jamais_purge_nr.py`
- `tools/ci_local.py`
- `tools/forge_log_retention.py`


## Commit 470150537 — 2026-09-24 16:28
**fix(superviseur): la preuve TPM est bornee dans le temps -- NREM1 ne se suspend plus en silence**

### Modules Python modifiés
- `tests/nr/test_admin_preuve_tpm_nr.py`


## Commit f2500a597 — 2026-09-24 16:26
**feat(auth): borne du porteur du maitre, armable par l'owner (LAFORGE_MASTER_BORNE=1)**

### Modules Python modifiés
- `app/forge_videur.py`
- `tests/nr/test_maitre_porte_acteur_et_sujet_nr.py`


## Commit ce70f4d4e — 2026-09-24 16:24
**fix(auth): cloture des routes d'organes du hub -- SENSIBLES_CONNUES vide**

### Modules Python modifiés
- `app/agent_sre_observabilit/agent_core.py`
- `app/forge_authz_shadow.py`
- `app/forge_clawhub_bridge.py`
- `app/forge_dsl.py`
- `app/forge_hub_client.py`
- `app/laforge_tui/laforge_tui.py`
- `tests/nr/test_authz_axes_separes_nr.py`
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tests/nr/test_decisions_de_chemin_sur_scope_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tests/nr/test_routes_organes_authentifiees_nr.py`
- `tools/ci_local.py`
- `tools/forge_dt_router_wire.py`
- `tools/forge_route_authz_audit.py`
- `tools/nokido_hub.py`


## Commit ccae2830b — 2026-09-24 16:10
**fix(auth): mutations d'interface fermees par session UI + origine locale (AUTH-3/4/6)**

### Modules Python modifiés
- `app/forge_authz_http.py`
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tests/nr/test_garde_ui_mutation_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/ci_local.py`
- `tools/forge_route_authz_audit.py`
- `tools/nokido_hub.py`


## Commit da55821be — 2026-09-24 15:44
**feat(auth): routes admin — un organe doit prouver sa cle TPM (observation, puis applique)**

### Modules Python modifiés
- `app/forge_dpop.py`
- `tests/nr/test_admin_preuve_tpm_nr.py`
- `tools/ci_local.py`
- `tools/forge_dpop_tpm_cli.py`
- `tools/nokido_hub.py`


## Commit 10611225c — 2026-09-24 15:39
**feat(auth): preuve DPoP adossee au TPM, prouvee sur materiel reel (6/6)**

### Modules Python modifiés
- `app/forge_dpop.py`
- `app/forge_persona_tpm.py`
- `tests/nr/test_dpop_tpm_autorisation_nr.py`
- `tests/nr/test_tpm_isolation_nest_pas_non_exportabilite_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit 1af81abd6 — 2026-09-24 15:29
**fix(auth): #9 — une revue ne s'approuve plus sans separation verifiee (AUTH-6)**

### Modules Python modifiés
- `app/collab_modes/_participants.py`
- `app/collab_modes/mode_auto.py`
- `app/collab_modes/mode_cline.py`
- `app/forge_task_bus.py`
- `tests/nr/test_revue_fail_closed_nr.py`
- `tools/ci_local.py`
- `tools/mcp_nr.py`


## Commit ae1cdec72 — 2026-09-24 15:25
**fix(auth): le lanceur du bureau ne parle plus au hub anonymement ni sous un nom d'emprunt**

### Modules Python modifiés
- `tests/nr/test_lanceur_appels_hub_authentifies_nr.py`
- `tools/ci_local.py`
- `tools/nokido_launcher.py`


## Commit 274fad71d — 2026-09-24 15:15
**feat(auth): le jeton du hub est fourni a la connexion (headersHelper), plus au repos**

### Modules Python modifiés
- `tests/nr/test_mcp_headers_helper_nr.py`
- `tools/ci_local.py`
- `tools/forge_mcp_json_sync.py`


## Commit fc800133a — 2026-09-24 15:13
**fix(scorecard): un echec n'est plus note OPTIMAL 1.0 (veille lot_B_33)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_scorecard.py`
- `tests/nr/test_scorecard_echec_pas_optimal_nr.py`
- `tools/ci_local.py`


## Commit 19e0c4f44 — 2026-09-24 15:06
**fix(auth): le hook post-commit porte son propre jeton (P0, AUTH-2)**

### Modules Python modifiés
- `tests/nr/test_post_commit_jeton_propre_nr.py`
- `tools/ci_local.py`
- `tools/forge_post_commit.py`


## Commit 399527022 — 2026-09-24 15:05
**fix(agy): la delegation n'approuve plus tout par defaut**

### Modules Python modifiés
- `tests/nr/test_agy_delegation_sans_approbation_totale_nr.py`
- `tools/ci_local.py`
- `tools/forge_task_executor.py`


## Commit a2689185a — 2026-09-24 15:00
**fix(rag): l'ingestion llms.txt valide par page, elle ne tient plus le verrou d'ecriture**

### Modules Python modifiés
- `tests/nr/test_ingest_llms_txt_valide_par_page_nr.py`
- `tools/ci_local.py`
- `tools/forge_ingest_llms_txt.py`


## Commit d02edfd09 — 2026-09-24 15:00
**feat(dlp): la copie RAG des conversations masque TOUTES les donnees personnelles**

### Modules Python modifiés
- `app/forge_conversation_logger.py`
- `app/forge_semantic_firewall.py`
- `tests/nr/test_conversation_log_dlp_rag_nr.py`


## Commit b3d27a002 — 2026-09-24 14:44
**fix(dlp): conversation_log masque aussi les cles d'API ; 5 formes ajoutees au scanner sortant**

### Modules Python modifiés
- `app/forge_conversation_logger.py`
- `app/forge_secret_guard.py`
- `tests/nr/test_conversation_log_dlp_rag_nr.py`


## Commit 2b70c6295 — 2026-09-24 14:39
**fix(securite): decider sur scope[path], jamais sur url.path (CVE-2026-48710)**

### Modules Python modifiés
- `app/forge_graph_explorer.py`
- `app/web_hub/app.py`
- `tests/nr/test_decisions_de_chemin_sur_scope_nr.py`
- `tools/ci_local.py`
- `tools/forge_demand_proxy.py`


## Commit c033e2f3d — 2026-09-24 14:37
**perf(contexte): un hook ne reinjecte pas un signal inchange**

### Modules Python modifiés
- `tests/nr/test_inbox_hook_sans_repetition_nr.py`
- `tests/nr/test_memoire_hook_sans_repetition_nr.py`
- `tools/claude_inbox_tick.py`
- `tools/hub_lifecycle_hooks.py`


## Commit 08d71c33b — 2026-09-24 14:37
**feat(veille): surveiller la doc de Claude Code, pas seulement celle de l'API**

### Modules Python modifiés
- `tests/nr/test_veille_cli_couvre_claude_code_nr.py`
- `tools/forge_cli_version_watch.py`


## Commit 0426422ce — 2026-09-24 14:00
**fix(conversation_log): DLP sur la copie RAG des tours, fail-closed, borne dite**

### Modules Python modifiés
- `app/forge_conversation_logger.py`
- `tests/nr/test_conversation_log_dlp_rag_nr.py`
- `tools/ci_local.py`


## Commit d8236b85d — 2026-09-24 13:57
**feat(applicateur): barriere — aucune action ne vise tests, cliquets, gardes ou fichiers critiques**

### Modules Python modifiés
- `app/forge_proposal_applier.py`
- `tests/nr/test_applicateur_ne_touche_pas_aux_gardes_nr.py`
- `tools/ci_local.py`


## Commit 5be77e031 — 2026-09-24 13:55
**fix(hub,ollama): protocolVersion negociee, consignes serveur, decisions sur scope[path], cloud Ollama coupe**

### Modules Python modifiés
- `app/forge_mcp_protocole.py`
- `tests/nr/test_mcp_protocole_nr.py`
- `tests/nr/test_ollama_cloud_coupe_nr.py`
- `tools/ci_local.py`
- `tools/forge_bridge_oauth.py`
- `tools/forge_patch_authz_shadow.py`
- `tools/nokido_hub.py`


## Commit 0b8f4ffa9 — 2026-09-24 13:42
**test(gabarits): cliquet des gabarits de prompt .format() + controle positif du digest 22/07**

### Modules Python modifiés
- `tests/nr/test_gabarits_prompt_format_nr.py`
- `tools/ci_local.py`


## Commit cc0f85a01 — 2026-09-24 13:39
**fix(veille_moisson): corps des pages de doc (pas le menu) + sources de l'owner ecartees**

### Modules Python modifiés
- `tests/nr/test_moisson_page_corps_et_sources_propres_nr.py`
- `tests/nr/test_veille_moisson_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_moisson.py`


## Commit bddb3bc9a — 2026-09-24 13:33
**fix(key_rotation): verrou inter-processus + temporaire unique sur le ledger de sante**

### Modules Python modifiés
- `app/forge_key_rotation.py`
- `tests/nr/test_key_rotation_ledger_concurrent_nr.py`
- `tools/ci_local.py`


## Commit 302c57276 — 2026-09-23 22:09
**fix(embed-backfill): curseur id et borne haute, plus de relecture par lot**

### Modules Python modifiés
- `tests/nr/test_backfill_sans_relecture_nr.py`
- `tools/ci_local.py`
- `tools/forge_embed_backfill_cool.py`


## Commit 3ed161478 — 2026-09-23 20:50
**fix(health): audit RAG sans balayage, echantillon declare, pas de relance**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `tests/nr/test_health_audit_rag_sans_scan_nr.py`
- `tools/ci_local.py`


## Commit 1960757ad — 2026-09-23 20:00
**docs(veille): cartographie de couverture du corpus (4 stocks)**

### Documentation mise à jour
- `docs/veilles/CARTOGRAPHIE_COUVERTURE_2026-09-23.md`


## Commit faec21534 — 2026-09-23 19:24
**docs(veille): registre de substance des veilles (4 etats, mecanismes)**

### Documentation mise à jour
- `docs/veilles/REGISTRE_SUBSTANCE_2026-09-23.md`


## Commit 6d2eff956 — 2026-09-23 19:06
**fix(cards): ingest_cards ne balaie plus rag_fts par carte (reliquat P0 WAL)**

### Modules Python modifiés
- `tests/nr/test_module_cards_sans_scan_nr.py`
- `tools/ci_local.py`
- `tools/forge_module_cards.py`


## Commit c1d3f99f4 — 2026-09-23 18:49
**fix(post-commit): liveness sans balayage, audit_rag_chunks hors du hook**

### Modules Python modifiés
- `tests/nr/test_post_commit_sans_scan_nr.py`
- `tools/ci_local.py`
- `tools/forge_post_commit.py`


## Commit c1d3f99f4 — 2026-09-23 18:49
**fix(post-commit): liveness sans balayage, audit_rag_chunks hors du hook**

### Modules Python modifiés
- `tests/nr/test_post_commit_sans_scan_nr.py`
- `tools/forge_post_commit.py`


## Commit 0690e3a84 — 2026-09-23 18:34
**fix(rag): le repli lexical n'exhume plus les chunks retires (active=0)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tests/nr/test_rag_lexical_exclut_inactifs_nr.py`
- `tools/ci_local.py`


## Commit 0690e3a84 — 2026-09-23 18:19
**fix(rag): le repli lexical n'exhume plus les chunks retires (active=0)**

### Modules Python modifiés
- `tests/nr/test_job_watch_bilan_gradue_nr.py`
- `tools/ci_local.py`
- `tools/forge_job_watch_cli.py`


## Commit 26378647d — 2026-09-23 17:55
**docs(self-audit): capability_contracts porte deja l'echelle de preuve**

### Documentation mise à jour
- `docs/self_audit_etape0_2026-09-23.md`


## Commit 26378647d — 2026-09-23 17:55
**docs(self-audit): capability_contracts porte deja l'echelle de preuve**

### Documentation mise à jour
- `docs/self_audit_etape0_2026-09-23.md`


## Commit 8bcc4bb5e — 2026-09-23 17:21
**docs(veille): typesafe - reranker local bge = BM25 sur CLERC**

### Documentation mise à jour
- `docs/veilles/fiche_typesafe_2026-09-23.md`


## Commit be6b295fe — 2026-09-23 17:16
**docs(veille): typesafe - limites levees (depots lus, 12,2x verifie, BM25 reproduit)**

### Documentation mise à jour
- `docs/veilles/fiche_typesafe_2026-09-23.md`


## Commit 228e652bc — 2026-09-23 17:10
**docs(veille): fiche de sortie TypeSafe / System One**

### Documentation mise à jour
- `docs/veilles/fiche_typesafe_2026-09-23.md`


## Commit 5123bca1f — 2026-09-23 13:25
**fix(veille): refuser un chemin relatif au lecteur, enregistrer des chemins absolus**

### Modules Python modifiés
- `tests/nr/test_veille_refiltrage_local_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 533906af6 — 2026-09-23 13:11
**fix(veille): une source de re-filtrage absente ou vide n'est plus un succes muet**

### Modules Python modifiés
- `tests/nr/test_veille_refiltrage_local_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 5ffe93499 — 2026-09-23 12:38
**feat(veille): re-filtrage LOCAL v3 des dumps v2 sans re-cloner**

### Modules Python modifiés
- `tests/nr/test_veille_refiltrage_local_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 309207aaa — 2026-09-23 12:28
**docs(veilles): fiche V6 infrastructure (SQLite 3.51.1 dans le chemin d'ecriture, pas de sauvegarde prouvee)**

### Documentation mise à jour
- `docs/veilles/fiche_v6_infrastructure_2026-09-23.md`


## Commit 309207aaa — 2026-09-23 12:25
**docs(veilles): fiche V6 infrastructure (SQLite 3.51.1 dans le chemin d'ecriture, pas de sauvegarde prouvee)**

### Documentation mise à jour
- `docs/veilles/fiche_v2_evaluation_2026-09-23.md`


## Commit 80e3a4396 — 2026-09-23 12:18
**docs(veilles): fiche V3 memoire agentique (reinjection VERIFIED, validite temporelle absente)**

### Documentation mise à jour
- `docs/veilles/fiche_v1_m2m_2026-09-23.md`
- `docs/veilles/fiche_v1_observabilite_2026-09-23.md`
- `docs/veilles/fiche_v1_supervision_agents_longs_2026-09-23.md`


## Commit e2bcf20a8 — 2026-09-23 12:12
**docs(veilles): fiches de sortie V1 (M2M, observabilite, supervision + agents longs)**

### Modules Python modifiés
- `tests/nr/test_journaux_ecrivains_migres_nr.py`
- `tests/nr/test_journaux_graphe_acces_nr.py`


## Commit 97d552a90 — 2026-09-23 12:00
**feat(db,rag): WAL qui se retrecit (journal_size_limit), priorite memoire, filtre active**

### Modules Python modifiés
- `app/forge_db.py`
- `app/forge_db_path.py`
- `app/forge_rag_engine.py`
- `tests/nr/test_rag_respecte_active_nr.py`
- `tests/nr/test_wal_journal_size_limit_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`


## Commit fadc6cf45 — 2026-09-23 11:17
**feat(veille): substance seulement + resume de la moelle (filtre v3)**

### Modules Python modifiés
- `tests/nr/test_veille_substance_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/forge_veille_intake_filter.py`


## Commit bd48651d3 — 2026-09-23 11:02
**fix(veille): TRUNCATE a attente courte, un verrou ne tue plus la campagne**

### Modules Python modifiés
- `app/forge_db_path.py`
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit bd394b5e8 — 2026-09-23 10:47
**feat(veille): le job cede la priorite I/O et CPU (NVMe a 100 %)**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit bd394b5e8 — 2026-09-23 10:46
**feat(veille): le job cede la priorite I/O et CPU (NVMe a 100 %)**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit bd394b5e8 — 2026-09-23 10:43
**feat(veille): le job cede la priorite I/O et CPU (NVMe a 100 %)**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_gitingest_sdk_ingest.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 852edd30b — 2026-09-23 05:23
**fix(veille): controle securite avant ingestion EN FLUX (job tue a 7 577 Mo)**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 5880fe827 — 2026-09-23 05:12
**fix(ingest): ingerer un dump EN FLUX (job tue a 7 138 Mo) + garde WAL relu**

### Modules Python modifiés
- `tests/nr/test_gitingest_ingest_flux_nr.py`
- `tests/nr/test_wal_checkpoint_nr.py`
- `tools/ci_local.py`
- `tools/forge_gitingest_sdk_ingest.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 5835a104e — 2026-09-23 04:52
**fix(veille): rendre le WAL au disque (TRUNCATE) entre depots au-dela de 2 Go**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`


## Commit c94e5f855 — 2026-09-23 03:48
**fix(veille): ecrire le dump en flux (job tue a 6 151 Mo de RSS)**

### Modules Python modifiés
- `tests/nr/test_veille_dumps_hors_depot_nr.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/forge_veille_registre.py`


## Commit 062d9b75e — 2026-09-23 02:32
**fix(veille): journal du job ligne a ligne (stdout tamponne = faux FIGE)**

### Modules Python modifiés
- `tools/forge_veille_clone_ingest.py`


## Commit 3b588c3d8 — 2026-09-23 02:15
**chore(veille): marquer muet-ok l'absence normale d'une copie de dump**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_veille_dumps_hors_depot_nr.py`
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/forge_veille_registre.py`


## Commit 3f7aa7632 — 2026-09-23 02:10
**fix(veille): refuser les vecteurs d'auto-lancement (ver Shai-Hulud)**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/forge_veille_intake_filter.py`


## Commit 27b6f2c73 — 2026-09-23 01:52
**feat(veille): dumps hors depot via resolveur unique (sandbox/veille_dumps.dir)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_veille_dumps_hors_depot_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_backlog_github.py`
- `tools/forge_veille_clone_ingest.py`
- `tools/forge_veille_registre.py`


## Commit ce2c2f1c0 — 2026-09-23 01:35
**fix(veille): searxng se clone sous Windows ; les depots critiques restent suivis**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_veille_clone_chemins_windows_nr.py`
- `tests/nr/test_veille_github_critiques_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`


## Commit bde5d1bc5 — 2026-09-23 01:27
**fix(retention): la purge ne tue plus les veilles ratees -- liste BLANCHE**

### Modules Python modifiés
- `tests/nr/test_purge_veille_epargne_les_ratees_nr.py`
- `tools/ci_local.py`
- `tools/forge_log_retention.py`


## Commit 3e5576fcb — 2026-09-23 01:13
**feat(veille): la campagne clone+ingest S'ARRETE sous 30 Go libres**

### Modules Python modifiés
- `tests/nr/test_veille_clone_garde_disque_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_clone_ingest.py`


## Commit 9a03aa546 — 2026-09-23 00:32
**feat(mesure): instrument AVANT/APRES du switch journaux, par fenetre**

### Modules Python modifiés
- `tests/nr/test_mesure_journaux_nr.py`
- `tools/ci_local.py`
- `tools/forge_mesure_journaux.py`


## Commit da7a90a5f — 2026-09-23 00:25
**feat(push): --sha pousse EXACTEMENT le sha certifie par la CI**

### Modules Python modifiés
- `tests/nr/test_push_sovereign_sha_certifie_nr.py`
- `tools/ci_local.py`
- `tools/forge_push_sovereign.py`


## Commit cd0b67a82 — 2026-09-23 00:10
**fix(swarm): une erreur ou un vide n'est plus une reponse ; le recenseur tourne en job**

### Modules Python modifiés
- `tests/nr/test_cli_swarm_faux_succes_nr.py`
- `tests/nr/test_free_tier_census_importe_ses_cles_nr.py`
- `tools/ci_local.py`
- `tools/forge_cli_swarm.py`
- `tools/forge_free_tier_census.py`


## Commit fd499fa24 — 2026-09-22 23:49
**test(regulation): NR d'effet pour forge_ci_quand_ram_dispo**

### Modules Python modifiés
- `tests/nr/test_ci_quand_ram_dispo_nr.py`
- `tools/ci_local.py`


## Commit 68468556c — 2026-09-22 23:16
**fix(journaux): conversation_log RETENU par l'accesseur -- la CI avait raison**

### Modules Python modifiés
- `app/forge_conversation_logger.py`
- `app/forge_db_path.py`
- `tests/nr/test_journaux_ecrivains_migres_nr.py`
- `tests/nr/test_journaux_hors_verrou_rag_nr.py`
- `tools/ci_local.py`


## Commit 4d391e829 — 2026-09-22 22:39
**feat(regulation): attendre la RAM sans bloquer l'humain -- et savoir quel refus on attend**

### Modules Python modifiés
- `tools/forge_ci_quand_ram_dispo.py`


## Commit 869f9de16 — 2026-09-22 21:59
**feat(rag): le graphe entier partage le point de bascule -- 15 sites sur 15**

### Modules Python modifiés
- `app/forge_db_path.py`
- `app/forge_mcp_registry.py`
- `tests/nr/test_journaux_graphe_acces_nr.py`


## Commit 8ddf9d537 — 2026-09-22 21:47
**feat(rag): dix lecteurs sur onze rejoignent le point de bascule**

### Modules Python modifiés
- `app/forge_health_diagnostic.py`
- `app/forge_metabolism.py`
- `app/forge_quota_tracker.py`
- `app/forge_tool_efficiency.py`
- `app/forge_vitals_channels.py`
- `tests/nr/test_journaux_graphe_acces_nr.py`
- `tools/forge_broker_base.py`


## Commit f37b5695e — 2026-09-22 21:24
**feat(rag): le GRAPHE lecteurs+ecrivains, pas seulement les ecrivains -- etapes 1 a 3**

### Modules Python modifiés
- `app/forge_db_path.py`
- `app/forge_provider_quota.py`
- `app/forge_token_monitor.py`
- `tests/nr/test_journaux_graphe_acces_nr.py`
- `tools/ci_local.py`
- `tools/forge_broker_probe.py`
- `tools/forge_token_meter.py`


## Commit 8752efca9 — 2026-09-22 21:09
**feat(rag): les QUATRE ecrivains des journaux suivent l'interrupteur -- cablage, pas bascule**

### Modules Python modifiés
- `app/forge_conversation_logger.py`
- `tests/nr/test_journaux_hors_verrou_rag_nr.py`
- `tools/ci_local.py`
- `tools/forge_log_retention.py`


## Commit 09b4f27dd — 2026-09-22 18:00
**fix(ci): une ecriture ajoutee dans un chemin deja teste doit etre ISOLABLE**

### Modules Python modifiés
- `tests/nr/test_wiki_origine_et_peremption_nr.py`
- `tools/forge_wiki_modules.py`


## Commit 42ee49414 — 2026-09-22 17:27
**fix(securite): le gate avait raison sur la FORME -- un underscore rendait le coffre invisible**

### Modules Python modifiés
- `app/forge_litellm_connector.py`
- `tests/nr/test_cle_gemini_passe_par_le_coffre_nr.py`


## Commit 10accb244 — 2026-09-22 16:50
**fix(nr): mon test sondait la MACHINE -- unique echec de la CI sur 11 637 tests**

### Modules Python modifiés
- `tests/nr/test_roadmap_statut_declare_nr.py`


## Commit 71d08ba57 — 2026-09-22 16:41
**feat(securite): passe 4 -- R7 largement instruit, et une limite de mon instrument de lecture**

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit c28cc21b9 — 2026-09-22 16:34
**fix(securite): E1 -- la cle Gemini passe par le coffre, et quitte l'environnement apres l'appel**

### Modules Python modifiés
- `app/forge_litellm_connector.py`
- `tests/nr/test_cle_gemini_passe_par_le_coffre_nr.py`
- `tools/ci_local.py`

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit 92b899d54 — 2026-09-22 16:25
**feat(securite): passe 3 -- une cle qui saute deux echelons du coffre, et le second artefact du skill**

### Modules Python modifiés
- `tests/nr/test_audit_findings_conformes_au_skill_nr.py`
- `tools/forge_audit_findings_validate.py`

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit 8c990eaf1 — 2026-09-22 16:10
**feat(ssot): un item de roadmap declare son ETAT, et l'absence de marqueur vaut OUVERT**

### Modules Python modifiés
- `app/forge_ssot_maintainer.py`
- `tests/nr/test_roadmap_statut_declare_nr.py`
- `tools/ci_local.py`


## Commit e65247543 — 2026-09-22 15:42
**feat(securite): le portage du skill Cloudflare avait decroche -- mesure, reparation, cablage**

### Modules Python modifiés
- `tests/nr/test_audit_findings_conformes_au_skill_nr.py`
- `tools/ci_local.py`
- `tools/forge_audit_findings_validate.py`

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit 09a6d2891 — 2026-09-22 15:26
**feat(securite): R7 entame, R5 clos -- et le denominateur d'une sonde n'est pas celui du defaut**

### Modules Python modifiés
- `tests/nr/test_pool_timeout_promesse_non_tenue_nr.py`
- `tools/ci_local.py`

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit 397617669 — 2026-09-22 15:20
**fix(nr): subprocess mode-texte sans errors= -- anti-regression incident 47GB**

### Modules Python modifiés
- `tests/nr/test_forge_dynamique_confinement_nr.py`
- `tests/nr/test_wiki_openwiki_nr.py`
- `tools/ci_local.py`

### Documentation mise à jour
- `docs/AUDIT_SECURITE_REGISTRE.md`


## Commit d111db327 — 2026-09-22 14:42
**feat(m2m): une TACHE reveille la boucle, et son statut ne vaut pas preuve**

### Modules Python modifiés
- `tests/nr/test_watch_tache_m2m_nr.py`
- `tools/bash_guard.py`
- `tools/ci_local.py`
- `tools/forge_job_watch_cli.py`


## Commit 75d633336 — 2026-09-22 14:34
**feat(service): les DRAINS de taches entrent dans la route gouvernee**

### Modules Python modifiés
- `tests/nr/test_drains_sont_gouvernes_nr.py`
- `tools/ci_local.py`
- `tools/forge_ensure_service.py`


## Commit 3f6d9dd59 — 2026-09-22 14:15
**docs(wiki): la reference des modules porte son frontmatter OKF**

### Documentation mise à jour
- `docs/wiki/20-Modules-Reference.md`


## Commit a62d2d0af — 2026-09-22 14:05
**feat(wiki): OKF v0.2 — une provenance que la MACHINE sait verifier**

### Modules Python modifiés
- `tests/nr/test_frontmatter_okf_nr.py`
- `tools/ci_local.py`
- `tools/forge_wiki_modules.py`


## Commit a8e292285 — 2026-09-22 14:00
**docs(wiki): regenerer la reference des modules — PERIME depuis 5 jours**

### Documentation mise à jour
- `docs/wiki/20-Modules-Reference.md`


## Commit 41725f65e — 2026-09-22 13:57
**feat(wiki): une docstring est une AFFIRMATION, son code en est la PREUVE**

### Modules Python modifiés
- `tests/nr/test_docstring_adossee_a_son_code_nr.py`
- `tools/ci_local.py`
- `tools/forge_wiki_modules.py`


## Commit 9c0b108fb — 2026-09-22 13:46
**veille(rag): ajouter langchain-ai/openwiki a la cible de clone_ingest**

### Modules Python modifiés
- `tools/forge_veille_clone_ingest.py`


## Commit 5a115defa — 2026-09-22 13:23
**feat(authz): A2 — /api/recon/run consomme enfin la portee, et le refus EMPECHE l'effet**

### Modules Python modifiés
- `tests/nr/test_contrat_credential_routes_forge_nr.py`
- `tests/nr/test_recon_run_consomme_le_scope_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 0b0286816 — 2026-09-22 13:05
**test(authz): A2 — figer le GAP DE MESURE, ne pas cabler ce qu'on ne saurait certifier**

### Modules Python modifiés
- `tests/nr/test_contrat_credential_routes_forge_nr.py`


## Commit 18c2be921 — 2026-09-22 12:17
**fix(test): la fixture qui bloquait TOUT push depuis 24 h**

### Modules Python modifiés
- `tests/nr/test_audit_sortie_bornee_nr.py`


## Commit e6aec8baf — 2026-09-22 11:00
**test(authz): A1 point 7 — reduire la portee ne degrade pas la liaison TPM**

### Modules Python modifiés
- `tests/nr/test_portee_demandee_et_accordee_nr.py`


## Commit 6b0da7830 — 2026-09-22 10:54
**feat(authz): A1 — une portee se DEMANDE, et l'ecart avec ce qui est accorde se DIT**

### Modules Python modifiés
- `app/forge_auth_tokens.py`
- `app/forge_integrity.py`
- `tests/nr/test_contrat_credential_routes_forge_nr.py`
- `tests/nr/test_portee_demandee_et_accordee_nr.py`
- `tools/ci_local.py`


## Commit bf8787a35 — 2026-09-22 10:41
**test(authz): P1-A — figer le contrat d'entree de /api/recon/run et /api/ctf/run**

### Modules Python modifiés
- `tests/nr/test_contrat_credential_routes_forge_nr.py`
- `tools/ci_local.py`


## Commit 5cbd9631b — 2026-09-22 09:15
**fix(ci): les 11 rouges de l'armement — un defaut d'isolation, deux gardes devenus faux**

### Modules Python modifiés
- `tests/nr/test_maitre_est_attribuable_nr.py`
- `tools/ci_local.py`
- `tools/forge_route_authz_audit.py`


## Commit 4c7346ab0 — 2026-09-22 08:44
**feat(authz): consommer la boite d'un agent exige desormais d'ETRE cet agent**

### Modules Python modifiés
- `app/forge_videur.py`
- `tests/nr/test_inbox_liaison_identite_nr.py`
- `tests/nr/test_inbox_ownership_cycle_nr.py`
- `tests/nr/test_inbox_ownership_route_nr.py`
- `tools/ci_local.py`
- `tools/forge_rotation_proof.py`
- `tools/nokido_hub.py`


## Commit 3be79a764 — 2026-09-22 06:57
**fix(test): un NR devenu rouge sans qu'une ligne de code change — il avait fini de pourrir**

### Modules Python modifiés
- `tests/nr/test_veille_serving_audit_nr.py`


## Commit 2d5a097fe — 2026-09-22 06:48
**test(authz): enregistrer que consommer la boite d'un agent n'exige pas d'ETRE cet agent**

### Modules Python modifiés
- `tests/nr/test_inbox_liaison_identite_nr.py`
- `tools/ci_local.py`


## Commit bc005a01a — 2026-09-22 06:05
**fix(hub): /api/mcp/servers cesse de relayer 19 cles de config owner que personne ne lit**

### Modules Python modifiés
- `tests/nr/test_mcp_servers_ne_relaie_pas_les_preferences_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 9e815686f — 2026-09-22 05:59
**fix(reseau): une route NUE chargeait 102,8 Mo pour rendre 200 lignes**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `tests/nr/test_network_history_lecture_bornee_nr.py`
- `tools/ci_local.py`


## Commit 05f7de17e — 2026-09-22 05:54
**docs(authz): exposition mesuree sur 43 routes — 3 SECRET, 5 CONFIDENTIAL, et 10 retirees du cote rassurant**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 1d62cfa4b — 2026-09-22 05:48
**feat(authz): classer ce qu'une reponse REVELE — compteurs seuls, aucune valeur lue ni rendue**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/forge_route_authz_audit.py`


## Commit 428a1e02e — 2026-09-22 05:41
**feat(authz): cabler SECRET ne sort jamais sur les routes — la regle etait ecrite, aucune porte ne la consultait**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/forge_route_authz_audit.py`


## Commit cfbe20c79 — 2026-09-22 05:38
**docs(authz): classer avec le vocabulaire DU CORPS — trois routes contredisent l'invariant ecrit SECRET ne sort jamais**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 29fd9f8e7 — 2026-09-22 05:31
**docs(authz): les 10 routes loopback classees A/B/C/D — trois sont en classe D et distribuent un porteur**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 65b8183cc — 2026-09-22 05:28
**fix(authz): trois routes comptees GARDEES DISTRIBUENT le porteur au lieu de le verifier**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/forge_route_authz_audit.py`


## Commit fa336178c — 2026-09-22 05:24
**docs(authz): les 37 lectures nues — interne est vrai par CONFINEMENT reseau, et la route la plus grave consomme au lieu de lire**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 3da7123ad — 2026-09-22 05:20
**fix(authz): une borne loopback est une garde — NU n'est pas VOLONTAIREMENT EXEMPTE, et la primitive existait sans etre appelee**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/forge_route_authz_audit.py`


## Commit 914ebddad — 2026-09-22 05:16
**fix(docs): mon verdict confused deputy etait FAUX — le superviseur applique une liste blanche, garder la route ne protegerait rien**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 83a3c051d — 2026-09-22 05:13
**docs(authz): les 2 routes ADMIN nues instruites — une reste nue et c'est justifie, l'autre est un confused deputy bloque par son appelant**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit a0c74e4bc — 2026-09-22 05:07
**docs(authz): matrice de decision des 8 routes MUTANTE nues — deux ne mutent rien, cinq sont bloquees par leur appelant, une seule est prete**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 4465453f7 — 2026-09-22 05:04
**fix(authz): l'audit declarait « aucun appelant » sur onze routes que l'interface du hub appelle**

### Modules Python modifiés
- `app/forge_cognitive_router.py`
- `app/forge_corrigibility.py`
- `app/forge_llm_router.py`
- `app/forge_mcp_rbac.py`
- `app/forge_proprioception.py`
- `app/forge_ps_sandbox.py`
- `app/forge_task_router.py`
- `app/web_hub/forms/governed_edit_form.py`
- `app/web_hub/forms/query_form.py`
- `app/web_hub/forms/run_form.py`
- `tools/forge_governed_edit.py`
- `tools/forge_local_pool_wake.py`
- `tools/forge_ui_vitals_cover.py`

### Documentation mise à jour
- `README.md`
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`
- `docs/roadmap_plan_cognitif_2026-09-13.md`
- `docs/skills/nokido/SKILL.md`


## Commit 4465453f7 — 2026-09-22 05:04
**fix(authz): l'audit declarait « aucun appelant » sur onze routes que l'interface du hub appelle**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/forge_route_authz_audit.py`


## Commit b2dc38636 — 2026-09-22 04:54
**docs(authz): etat des routes au 2026-09-22 — 25 des 83 refusent un appel anonyme, et le mot protege recouvrait trois choses differentes**

### Documentation mise à jour
- `docs/AUTHZ_ROUTES_ETAT_2026-09-22.md`


## Commit 55c7675a6 — 2026-09-22 04:45
**fix(identite): un repli ne doit jamais devenir PERMANENT par mise en cache — 80 % du trafic webhub le prouvait**

### Modules Python modifiés
- `app/web_hub/wired_routes.py`
- `tests/nr/test_webhub_porte_son_propre_credential_nr.py`
- `tools/ci_local.py`


## Commit 10bb653d5 — 2026-09-21 21:40
**feat(obs): le cout d'armer le plancher se COMPTE sur trafic reel, au lieu de s'estimer sur une table**

### Modules Python modifiés
- `app/forge_videur_audit.py`
- `tests/nr/test_vue_compte_l_ecart_de_ring_nr.py`
- `tools/ci_local.py`


## Commit 2a4fe142d — 2026-09-21 20:55
**feat(authz): durcir master_token — l'ATTRIBUTION maintenant, l'AUTORITE quand l'owner aura le chiffre**

### Modules Python modifiés
- `app/forge_videur.py`
- `tests/nr/test_maitre_est_attribuable_nr.py`
- `tests/nr/test_maitre_porte_acteur_et_sujet_nr.py`
- `tools/ci_local.py`


## Commit 976dfb122 — 2026-09-21 20:48
**fix(gate): il annoncait 12 sites muets, il y en avait 22 — une borne doit dire COMBIEN**

### Modules Python modifiés
- `tests/nr/test_gate_borne_dit_combien_nr.py`
- `tools/ci_local.py`
- `tools/forge_git_gate.py`


## Commit 926c74288 — 2026-09-21 20:44
**fix(obs): chemins d'erreur muets du hub — 6 tracés, 5 marqués, aucun laissé au hasard**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 83cec644d — 2026-09-21 20:31
**feat(authz): P1-S — la premiere information perdue est la DECISION, et la provenance n'etait comptee nulle part**

### Modules Python modifiés
- `app/forge_videur_audit.py`
- `tests/nr/test_vue_audit_porte_la_provenance_nr.py`
- `tools/ci_local.py`


## Commit 3095d024d — 2026-09-21 20:07
**test(authz): la portee d'un garde se MESURE — 36 signalements, 34 faux, et 164 closures jamais regardees**

### Modules Python modifiés
- `tests/nr/test_trace_refus_admin_ecrit_vraiment_nr.py`


## Commit 4c4931551 — 2026-09-21 20:03
**test(authz): le detecteur de noms non lies criait faux 32 fois sur 36 — reparé avant d'etre arme**

### Modules Python modifiés
- `tests/nr/test_trace_refus_admin_ecrit_vraiment_nr.py`


## Commit 691d02afc — 2026-09-21 19:57
**fix(authz): la trace des refus admin n'etait JAMAIS ecrite — sept sites morts d'un seul nom**

### Modules Python modifiés
- `tests/nr/test_trace_refus_admin_ecrit_vraiment_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 8a961c5f6 — 2026-09-21 18:25
**test(authz): un test qui lit le SYMBOLE casse au refactoring, un test qui lit la PROPRIETE tient**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 67e6e5f95 — 2026-09-21 18:11
**test(authz): un porteur pose SOUS CONDITION n'est pas un porteur prouve**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 67e6e5f95 — 2026-09-21 18:11
**test(authz): un porteur pose SOUS CONDITION n'est pas un porteur prouve**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`


## Commit 33989cb60 — 2026-09-21 18:04
**test(journal): trois formulations pour un contrat — la bonne est la plus courte**

### Modules Python modifiés
- `tests/nr/test_journal_porte_acteur_et_sujet_nr.py`


## Commit 34cf54049 — 2026-09-21 18:01
**feat(authz): `_admin_tok_ok` trace ses REFUS — et seulement eux**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 4d4e6618f — 2026-09-21 17:46
**test(provenance): le chemin DEGRADE du maitre n'est pas attribue, et l'attribution n'a pas de lecteur**

### Modules Python modifiés
- `tests/nr/test_maitre_est_attribuable_nr.py`


## Commit a41f2760f — 2026-09-21 17:43
**test(journal): le garde qui REFUSE est muet, celui qui laisse passer journalise**

### Modules Python modifiés
- `tests/nr/test_journal_porte_acteur_et_sujet_nr.py`


## Commit 6f4173222 — 2026-09-21 17:35
**test(hub): le garde de la boucle d'evenements tient une deuxieme porte — l'I/O reseau**

### Modules Python modifiés
- `tests/nr/test_hub_pas_d_io_bloquante_dans_la_boucle_nr.py`


## Commit 3192bd2e8 — 2026-09-21 17:20
**fix(authz): trois instruments corriges — le producteur du vocabulaire est la seule source**

### Modules Python modifiés
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tests/nr/test_matrice_loopback_credential_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/ci_local.py`
- `tools/forge_route_authz_audit.py`


## Commit 6e66f7074 — 2026-09-21 16:27
**fix(hub): une garde armee le matin cassait l'UI — l'appelant vivait dans une chaine JS inline**

### Modules Python modifiés
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/nokido_hub.py`

### Documentation mise à jour
- `docs/skills/forge-android/SKILL.md`


## Commit d19862762 — 2026-09-21 12:25
**test(authz): croiser la GARDE de la route et la CAPACITE du module atteint**

### Modules Python modifiés
- `tests/nr/test_capacite_atteinte_sans_garde_nr.py`
- `tools/ci_local.py`


## Commit 813564443 — 2026-09-21 12:20
**perf(hub): rag_stats — une colonne portait 87,1 s sur 87,3 s, et ma description etait fausse**

### Modules Python modifiés
- `tests/nr/test_rag_stats_ne_lit_pas_le_texte_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit b499042ef — 2026-09-21 12:14
**test(revocation): trois maillons separes — la revocation d'identite n'a qu'un recepteur**

### Modules Python modifiés
- `tests/nr/test_revocation_chemins_connus_nr.py`
- `tools/ci_local.py`


## Commit 4e9eb0792 — 2026-09-21 12:08
**fix(hub): le journal d'identite porte l'ACTEUR, et le porteur du maitre cesse d'etre anonyme**

### Modules Python modifiés
- `tests/nr/test_journal_porte_acteur_et_sujet_nr.py`
- `tests/nr/test_maitre_est_attribuable_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit eb650bd7b — 2026-09-21 11:43
**test(rag): proteger une URL ne protege pas une CAPACITE — les chemins d'ecriture sont inventories**

### Modules Python modifiés
- `tests/nr/test_ecriture_rag_chemins_connus_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/ci_local.py`


## Commit e77c304cf — 2026-09-21 10:44
**fix(integrity): le ledger de cles cesse de juger un JKT dont il n'est pas l'autorite**

### Modules Python modifiés
- `app/forge_integrity.py`
- `tools/ci_local.py`


## Commit d4c0bc89d — 2026-09-21 10:00
**fix(hub): six routes MUTANTE de plus exigent un porteur — l'inventaire passe de 18 a 9**

### Modules Python modifiés
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/nokido_hub.py`


## Commit 57b6b6fe1 — 2026-09-21 09:48
**fix(hub): trois routes ecrivaient dans la base RAG sans demander de porteur**

### Modules Python modifiés
- `tests/nr/test_ingestion_exige_un_porteur_nr.py`
- `tests/nr/test_route_authz_inventaire_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 569ddb805 — 2026-09-21 08:26
**fix(nr): docstring RAW — une figure de mise en page salissait la compilation**

### Modules Python modifiés
- `tests/nr/test_hub_pas_d_io_bloquante_dans_la_boucle_nr.py`


## Commit f2d22f4c0 — 2026-09-21 08:22
**fix(hub): trois scans d une base de 25 Go tournaient DANS la boucle d evenements**

### Modules Python modifiés
- `tests/nr/test_hub_pas_d_io_bloquante_dans_la_boucle_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 65ad62093 — 2026-09-21 07:50
**feat(integrity): le chemin LIE consulte le ledger de cles — et personne n'emprunte encore ce chemin**

### Modules Python modifiés
- `app/forge_integrity.py`
- `tests/nr/test_verify_consulte_le_ledger_de_cles_nr.py`


## Commit 8ec31bc62 — 2026-09-21 07:37
**fix(agent-keys): le marqueur s'ancre sur la ligne du `except`, mesure a l'appui**

### Modules Python modifiés
- `app/forge_agent_keys.py`


## Commit 8ec31bc62 — 2026-09-21 07:37
**fix(agent-keys): le marqueur s'ancre sur la ligne du `except`, mesure a l'appui**

### Modules Python modifiés
- `app/forge_agent_keys.py`


## Commit 4ea9c79ee — 2026-09-21 07:33
**feat(agent-keys): le niveau CLE de la revocation existe — 24/24, et personne ne l'appelle encore**

### Modules Python modifiés
- `app/forge_agent_keys.py`


## Commit b4ee5cf8c — 2026-09-21 07:22
**test(agent-keys): figer le maillon `jkt` et le fail-closed — la revocation ne survit pas au restart, c'est MESURE**

### Modules Python modifiés
- `tests/nr/test_agent_keys_ledger_nr.py`


## Commit b7f60cd11 — 2026-09-21 06:57
**feat(authz): l axe TPM de l observation, et le REFUS de conclure d une forme**

### Modules Python modifiés
- `app/forge_authz_shadow.py`
- `tests/nr/test_authz_shadow_axe_tpm_nr.py`
- `tools/ci_local.py`


## Commit aca36f975 — 2026-09-21 06:44
**fix(integrity): une signature TPM demandee et non obtenue ne part plus en silence**

### Modules Python modifiés
- `app/forge_integrity.py`
- `tests/nr/test_tpm_demande_non_obtenue_nr.py`
- `tools/ci_local.py`


## Commit 029e2efef — 2026-09-21 06:31
**feat(tpm): P4.2 — le hub signe avec le TPM, et la privee ne sort pas**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_acl_gouvernee_nr.py`
- `tests/nr/test_tpm_cycle_hub_reel_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit fedb47f2d — 2026-09-21 06:24
**feat(tpm): poser une ACE devient un geste GOUVERNE — ecrit, mais rien n est applique**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_acl_gouvernee_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit 3af369ea7 — 2026-09-21 06:18
**feat(tpm): lire l ACL d une cle TPM, en capturant son etat AVANT toute ecriture**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_descripteur_lecture_seule_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit b48954b1d — 2026-09-21 06:01
**fix(tpm): ABSENTE et REFUSEE appellent des gestes opposes, le wrapper les fusionnait**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_agent_keys_outil_nr.py`
- `tests/nr/test_tpm_etat_cle_trois_etats_nr.py`
- `tests/nr/test_tpm_isolation_nest_pas_non_exportabilite_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit d16fbc4b7 — 2026-09-21 05:53
**feat(securite): un audit ne peut plus devenir un canal d exfiltration**

### Modules Python modifiés
- `tests/nr/test_audit_sortie_bornee_nr.py`
- `tools/ci_local.py`
- `tools/forge_audit_sortie_bornee.py`


## Commit 6b43baa7b — 2026-09-21 05:36
**test(secrets): mesurer ce que _API_KEYS EST, avant de decider ce qu il devient**

### Modules Python modifiés
- `tests/nr/test_api_keys_provenance_et_revocation_nr.py`
- `tools/ci_local.py`


## Commit 77f1f7177 — 2026-09-21 04:51
**fix(ci): les deux gates rouges de la CI de reference, et ils avaient raison tous les deux**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_rotation_proof_garde_nr.py`
- `tools/ci_local.py`


## Commit 2c5ab5799 — 2026-09-21 04:12
**fix(nr): un NR qui asserte sur un cas que l horloge tranche, et le garde d emission de secrets**

### Modules Python modifiés
- `tests/nr/test_revocation_identite_isole_la_cause_nr.py`
- `tests/nr/test_secret_egress_gate_nr.py`
- `tools/ci_local.py`
- `tools/forge_secret_egress_gate.py`


## Commit fdefa7161 — 2026-09-21 03:54
**fix(tpm): l avertissement d usurpation passe du test a la FONCTION, et une sentinelle garde le cablage**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_isolation_nest_pas_non_exportabilite_nr.py`
- `tools/ci_local.py`


## Commit bfaae9292 — 2026-09-21 03:45
**fix(rotation): une revocation cessait de rendre son env GERE, donc se contournait**

### Modules Python modifiés
- `app/forge_key_rotation.py`
- `tests/nr/test_revocation_ne_s_efface_pas_nr.py`


## Commit 312f33dac — 2026-09-21 03:34
**feat(rotation): l outil qui prouve qu une revocation SURVIT AU REDEMARRAGE**

### Modules Python modifiés
- `tools/forge_rotation_proof.py`


## Commit 261b9f80b — 2026-09-21 03:28
**fix(rotation): un echec d ecriture du ledger cesse d etre muet**

### Modules Python modifiés
- `app/forge_key_rotation.py`
- `tests/nr/test_revocation_ne_s_efface_pas_nr.py`


## Commit 261b9f80b — 2026-09-21 03:28
**fix(rotation): un echec d ecriture du ledger cesse d etre muet**

### Modules Python modifiés
- `app/forge_key_rotation.py`
- `app/forge_secrets.py`
- `tests/nr/test_le_guichet_respecte_la_quarantaine_nr.py`
- `tests/nr/test_revocation_ne_s_efface_pas_nr.py`
- `tests/nr/test_revocation_secret_chaine_reelle_nr.py`
- `tools/ci_local.py`


## Commit d0c050afe — 2026-09-21 03:17
**style(nr): le NR d identite passe le gate qualite sans rien perdre de son attaque**

### Modules Python modifiés
- `tests/nr/test_identite_escalade_par_alias_nr.py`


## Commit 96279d4ba — 2026-09-21 03:13
**fix(identite): le ring se lit sur l IDENTITE resolue, et UNKNOWN cesse d etre un ring**

### Modules Python modifiés
- `app/forge_postal.py`
- `tests/nr/test_identite_escalade_par_alias_nr.py`
- `tools/ci_local.py`


## Commit 3988b1859 — 2026-09-21 03:00
**fix(mtls): un jeton lie a un certificat ne passe plus sur un canal sans certificat (RFC 8705)**

### Modules Python modifiés
- `app/forge_integrity.py`
- `tests/nr/test_cert_binding_adversarial_nr.py`
- `tools/ci_local.py`


## Commit 06c0b3edc — 2026-09-21 02:52
**fix(pop): un jeton LIE ne passe plus sans preuve -- le volet symetrique de RFC 9449 §7.1**

### Modules Python modifiés
- `app/forge_integrity.py`
- `tests/nr/test_pop_preuve_liee_a_la_bonne_cle_nr.py`
- `tools/ci_local.py`


## Commit 6d57f0760 — 2026-09-21 02:37
**test(identite): identite revoquee = DENY, et SEULE l identite change**

### Modules Python modifiés
- `tests/nr/test_revocation_identite_isole_la_cause_nr.py`
- `tools/ci_local.py`


## Commit 29968ed67 — 2026-09-21 02:32
**test(secrets): la revocation MORD sur la chaine reelle -- et la fenetre vaut 360 s, pas 300**

### Modules Python modifiés
- `tests/nr/test_revocation_secret_chaine_reelle_nr.py`
- `tools/ci_local.py`


## Commit 92fd5dabe — 2026-09-21 02:26
**fix(circadien): le rythme cesse d appeler NokidoAutoCompact -- dans les DEUX runtimes**

### Modules Python modifiés
- `app/forge_circadian.py`
- `tests/nr/test_autocompact_hors_du_rythme_nr.py`
- `tools/ci_local.py`


## Commit 716e44b44 — 2026-09-21 01:49
**test(veille): le lanceur de campagne est ORPHELIN -- son echec ne doit pas devenir silencieux**

### Modules Python modifiés
- `tests/nr/test_veille_campagne_run_nr.py`
- `tools/ci_local.py`


## Commit 44882c095 — 2026-09-21 01:42
**fix(hub): /admin/run_job passe par le runner gouverne -- et son lecteur cesse de mentir**

### Modules Python modifiés
- `tests/nr/test_admin_run_job_observable_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit d466527bd — 2026-09-21 01:36
**feat(jobs): params_depuis_corps -- le raccord testable entre une requete HTTP et le runner gouverne**

### Modules Python modifiés
- `app/forge_job_runner.py`
- `tests/nr/test_admin_run_job_comportement_nr.py`
- `tools/ci_local.py`


## Commit a678c2dcf — 2026-09-21 01:18
**fix(ci): solder MA dette du 20/09 que deux cliquets ont refusee -- et ne pas maquiller celle des autres**

### Modules Python modifiés
- `tests/nr/test_tpm_agent_keys_outil_nr.py`
- `tools/ci_local.py`
- `tools/forge_tpm_agent_keys.py`


## Commit 0cb9d42b9 — 2026-09-21 00:45
**chore(ci): declarer le NR de quarantaine -- un test non declare ne tourne nulle part**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_le_guichet_respecte_la_quarantaine_nr.py`


## Commit da40fda68 — 2026-09-21 00:41
**feat(secrets): le guichet sait POUR QUI il delivre -- DEMANDE et DELIVRANCE cessent d etre confondues**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_le_guichet_sait_pour_qui_il_delivre_nr.py`
- `tools/ci_local.py`


## Commit 798dea58e — 2026-09-21 00:38
**fix(secrets): la fenetre de contournement d une revocation etait INFINIE -- elle est bornee et observable**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_un_secret_revoque_cesse_d_etre_servi_nr.py`
- `tools/ci_local.py`


## Commit 5222f6e4e — 2026-09-21 00:33
**fix(dev-mode): le refus annoncait un geste INOPERANT -- et la bascule de debug est verrouillee**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_secret_guard.py`
- `tests/nr/test_la_bascule_dev_reste_utilisable_nr.py`
- `tools/ci_local.py`


## Commit 37eacca5b — 2026-09-21 00:29
**feat(secrets): la nature COMMANDE le masquage -- le classement cesse d etre une etiquette**

### Modules Python modifiés
- `tests/nr/test_la_nature_commande_le_masquage_nr.py`
- `tools/ci_local.py`
- `tools/forge_secret_audit.py`
- `tools/forge_secret_source_audit.py`


## Commit 8953deb28 — 2026-09-21 00:21
**test(identite): un NR annonce ROUGE etait en realite SKIPPE -- il ne prouvait rien**

### Modules Python modifiés
- `tests/nr/test_agent_keys_ledger_nr.py`


## Commit 915363fab — 2026-09-21 00:21
**feat(secrets): chaque cle nomme son organe proprietaire, ou dit pourquoi elle ne peut pas**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_provenance_proprietaire_par_cle_nr.py`
- `tools/ci_local.py`
- `tools/forge_secret_source_audit.py`


## Commit 06a3632af — 2026-09-21 00:11
**feat(secrets): un secret n est pas un reglage -- et le motif de detection avait un trou**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_inventaire_cles_demandees_nr.py`
- `tools/forge_secret_source_audit.py`


## Commit 799d3fea9 — 2026-09-21 00:01
**fix(securite): le breakglass exige une ATTESTATION -- une variable d environnement n ouvre plus cinq gardes**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_mcp_security.py`
- `app/forge_secret_guard.py`
- `tests/nr/test_breakglass_exige_une_preuve_nr.py`
- `tests/test_secret_guard_nr.py`
- `tools/ci_local.py`


## Commit d17830cd9 — 2026-09-21 00:01
**feat(secrets): le guichet distingue ABSENT d ILLISIBLE, et l audit cesse de ne voir que sa propre liste**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_inventaire_cles_demandees_nr.py`
- `tests/nr/test_secrets_illisible_nest_pas_absent_nr.py`
- `tools/forge_secret_source_audit.py`


## Commit 41d23f176 — 2026-09-20 23:29
**docs(vault): audit de mesure — 72 % des cles sont invisibles a l audit du coffre**

### Documentation mise à jour
- `docs/AUDIT_VAULT_2026-09-20.md`


## Commit eaa0f4d64 — 2026-09-20 23:25
**test(identite): NR ROUGE — le contrat agent_id -> key_id -> public_key -> generation -> status**

### Modules Python modifiés
- `tests/nr/test_agent_keys_ledger_nr.py`


## Commit 352965bd1 — 2026-09-20 23:23
**feat(identite): outil de provisionnement des cles TPM par agent — le refus DIT la commande qui marche**

### Modules Python modifiés
- `tools/forge_tpm_agent_keys.py`


## Commit 352965bd1 — 2026-09-20 23:20
**feat(identite): outil de provisionnement des cles TPM par agent — le refus DIT la commande qui marche**

### Modules Python modifiés
- `app/forge_m2m_protocol.py`
- `tests/nr/test_registre_identite_unicite_nr.py`
- `tools/ci_local.py`


## Commit 639f86a5e — 2026-09-20 22:58
**feat(identite): le TPM porte UNE CLE PAR AGENT — l attribution cesse d etre une etiquette**

### Modules Python modifiés
- `app/forge_persona_tpm.py`
- `tests/nr/test_tpm_cle_par_agent_nr.py`
- `tools/ci_local.py`


## Commit e45d3fdd1 — 2026-09-20 22:50
**fix(ui): une tuile morte DIT pourquoi — six etats au lieu d un booleen, et une source unique pour les deux renderers**

### Modules Python modifiés
- `app/web_hub/dashboard_html.py`
- `tests/nr/test_tile_state_trois_etats_nr.py`
- `tools/ci_local.py`


## Commit c312e825f — 2026-09-20 22:20
**feat(m2m): un SCEAU d integrite qui DIT ce qu il ne prouve pas**

### Modules Python modifiés
- `app/forge_m2m_protocol.py`
- `tests/nr/test_m2m_sceau_integrite_nr.py`
- `tools/ci_local.py`


## Commit e533dff40 — 2026-09-20 22:14
**feat(m2m): le protocole valide l IDENTITE et porte l INCARNATION — une etiquette n est pas une identite**

### Modules Python modifiés
- `app/forge_m2m_protocol.py`
- `tests/nr/test_m2m_identite_et_incarnation_nr.py`
- `tools/ci_local.py`


## Commit 051f832d2 — 2026-09-20 22:02
**fix(apprentissage): le cycle d entrainement DIT qu il s entraine sur du bruit — il annoncait un apprentissage qui n existait pas**

### Modules Python modifiés
- `tests/nr/test_ami_train_dit_sur_quoi_il_s_entraine_nr.py`
- `tools/ci_local.py`
- `tools/forge_ami_train_cycle.py`


## Commit 3a2cb19a1 — 2026-09-20 21:56
**feat(m2m): l inbox DIT l age, le sha cible et la SURFACE de l expediteur — agy autonome n est pas agy CLI**

### Modules Python modifiés
- `tests/nr/test_inbox_dit_l_age_et_le_sha_nr.py`
- `tools/ci_local.py`
- `tools/claude_inbox_tick.py`


## Commit 67bbf3f13 — 2026-09-20 21:48
**fix(raffinage): le CORPS passe devant dans preflight_check_verbose — le chemin que dix appelants empruntent vraiment**

### Modules Python modifiés
- `app/forge_self_correction.py`
- `tests/nr/test_preflight_verbose_priorise_le_corps_nr.py`
- `tools/ci_local.py`


## Commit 3771eb8fd — 2026-09-20 21:42
**fix(raffinage): une lecon du corps ne vient jamais d un depot tiers — le retrieval sait enfin dire « je ne sais pas »**

### Modules Python modifiés
- `app/forge_self_correction.py`
- `tests/nr/test_preflight_ne_repond_pas_avec_du_code_tiers_nr.py`
- `tools/ci_local.py`


## Commit 82b4ebe41 — 2026-09-20 21:32
**feat(couplage): la differenciation declare ce qu elle lit et ce qu elle fait — QUATRE hormones sortent du silence**

### Modules Python modifiés
- `app/forge_pluripotent_workers.py`
- `tests/nr/test_differenciation_declare_son_couplage_nr.py`
- `tools/ci_local.py`


## Commit d978e4def — 2026-09-20 21:23
**fix(intention): un drapeau CORROMPU se repare, meme sous cooldown — et la synapse rerank se ferme en runtime**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tests/nr/test_drapeau_corrompu_est_reparable_nr.py`
- `tools/ci_local.py`


## Commit b7c47581d — 2026-09-20 21:14
**feat(couplage): le site qui AGIT sur un pilier constate sa transduction — et correction d un diagnostic que j ai publie deux fois**

### Modules Python modifiés
- `tests/nr/test_piliers_constatent_leur_transduction_nr.py`
- `tools/ci_local.py`
- `tools/forge_llama_keeper.py`


## Commit a82bdd683 — 2026-09-20 20:59
**feat(keeper): un mode qui sert les piliers RAG sans toucher au coder — le degel devient sûr**

### Modules Python modifiés
- `tests/nr/test_keeper_piliers_only_nr.py`
- `tools/ci_local.py`
- `tools/forge_llama_keeper.py`


## Commit 3be7814ac — 2026-09-20 20:52
**fix(services): NokidoEpistemicSoif ne depend plus d un port dont le rallumeur est gele**

### Modules Python modifiés
- `tests/nr/test_deps_on_demand_ont_un_rallumeur_vivant_nr.py`
- `tools/ci_local.py`


## Commit 7c81ff4b1 — 2026-09-20 20:43
**fix(intention): une intention posee doit etre RELISIBLE — et cinq NR entrent enfin dans la CI**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tests/nr/test_intention_ecriture_verifiee_nr.py`
- `tools/ci_local.py`


## Commit b4715511f — 2026-09-20 20:12
**feat(memoire): le backlog laisse une trace dans le temps — sans elle, aucun drain n est verifiable**

### Modules Python modifiés
- `app/forge_memory_availability.py`
- `tests/nr/test_backlog_serie_temporelle_nr.py`


## Commit d70f4b4c0 — 2026-09-20 20:07
**test(jobs): NR ROUGE — /admin/run_job fabrique des jobs structurellement inobservables**

### Modules Python modifiés
- `tests/nr/test_admin_run_job_observable_nr.py`


## Commit d568937cf — 2026-09-20 19:59
**fix(hub): /admin reconnait le jeton PROPRE d un organe, et ses 401 deviennent conformes RFC 7235**

### Modules Python modifiés
- `tests/nr/test_admin_jeton_propre_organe_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 7394308b6 — 2026-09-20 19:42
**docs(registre): quatre maillons fermes, trois ouverts avec leur cause, une regression avouee**

### Documentation mise à jour
- `docs/REGISTRE_CHANTIERS_2026-09-20.md`


## Commit c272981e2 — 2026-09-20 19:38
**fix(intention): le poseur commun DECLARE ce qu il ecrit — et reparation d une regression que j ai causee**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tests/nr/test_declare_wanted_declare_son_emission_nr.py`
- `tools/ci_local.py`


## Commit 17ec69165 — 2026-09-20 19:23
**feat(generation): ce qui entre en ATTENTE peut enfin en SORTIR — le pendant du differe**

### Modules Python modifiés
- `app/forge_generation.py`
- `tests/nr/test_generation_promotion_nr.py`


## Commit fb4477c08 — 2026-09-20 19:16
**fix(generation): une capture differee par l ACL se declare, et son gain ne se perd plus**

### Modules Python modifiés
- `app/forge_generation.py`
- `tests/nr/test_generation_differee_reinjecte_nr.py`


## Commit 449fe1a6e — 2026-09-20 18:34
**docs(registre): la veille SakanaAI se clot, et l interface commune des boucles existait deja**

### Documentation mise à jour
- `docs/REGISTRE_CHANTIERS_2026-09-20.md`


## Commit 890446f74 — 2026-09-20 18:24
**ci(pure-tests): declarer le NR d auto-reference, et DIRE pourquoi l autre ne l est pas**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit 890446f74 — 2026-09-20 18:22
**ci(pure-tests): declarer le NR d auto-reference, et DIRE pourquoi l autre ne l est pas**

### Modules Python modifiés
- `tests/nr/test_symptom_index_auto_reference_nr.py`
- `tools/forge_symptom_index.py`


## Commit 520b3181c — 2026-09-20 18:06
**docs(registre): READ-CLOSURE mesure par l instrument qui existait deja, et trois de mes verdicts retires**

### Documentation mise à jour
- `docs/REGISTRE_CHANTIERS_2026-09-20.md`


## Commit 8a65023b2 — 2026-09-20 18:00
**docs(registre): cinq chantiers clos avec leur preuve, six ouverts avec leur cause**

### Documentation mise à jour
- `docs/REGISTRE_CHANTIERS_2026-09-20.md`


## Commit