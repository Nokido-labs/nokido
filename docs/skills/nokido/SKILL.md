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































































































































































































































































































































































































































































































































































































































































































































































































## Commit 7cb421b63 — 2026-10-02 01:36
**docs(agy): la politique fine existe ; decision owner : garder --sandbox**

### Modules Python modifiés
- `tools/forge_task_executor.py`


## Commit 3b6e00612 — 2026-10-01 20:24
**fix(agy): un OK_DONE dont l'artefact declare n'existe pas n'est plus un succes**

### Modules Python modifiés
- `tests/nr/test_agy_worktree_et_effet_nr.py`
- `tools/forge_task_executor.py`


## Commit 4e3573a2e — 2026-10-01 20:03
**fix(agy): un rendu NEED_HUMAN_APPROVAL / NEED_CLARIFY / ERR_* n'est plus transmis en OK_DONE**

### Modules Python modifiés
- `tests/nr/test_agy_worktree_et_effet_nr.py`
- `tools/forge_task_executor.py`


## Commit 10b0afd1b — 2026-10-01 19:52
**fix(embed): decodeur de vecteurs tolerant au JSON, regle unique (decision owner)**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `app/forge_semantic_pressure.py`
- `tests/nr/test_decode_blob_tolerant_nr.py`
- `tools/ci_local.py`


## Commit 9a0acc943 — 2026-10-01 19:43
**fix(agy): comptage des commits en errors=replace (gate firehose)**

### Modules Python modifiés
- `tools/forge_task_executor.py`


## Commit d665c8360 — 2026-10-01 19:43
**fix(agy): la delegation travaille dans le worktree d'AGY ; le resultat porte l'effet observe**

### Modules Python modifiés
- `tests/nr/test_agy_worktree_et_effet_nr.py`
- `tools/ci_local.py`
- `tools/forge_task_executor.py`


## Commit c28886962 — 2026-10-01 19:36
**feat(regeneration): mesure apres application, revert prouve, set_param L1 (rendu claude.ai relu)**

### Modules Python modifiés
- `app/forge_mutation_controller.py`
- `app/forge_proposal_applier.py`
- `tests/nr/test_applicateur_set_param_l1_nr.py`
- `tests/nr/test_controleur_mesure_apres_revert_nr.py`
- `tools/ci_local.py`


## Commit 633cd083d — 2026-10-01 19:33
**test(veille): sous-processus du garde en errors=replace (gate firehose)**

### Modules Python modifiés
- `tests/nr/test_veille_pairs_nr.py`


## Commit ae8e33407 — 2026-10-01 19:33
**fix(gardes): bash_guard accepte Monitor forge_job_watch_cli --pair, forme toujours fermee**

### Modules Python modifiés
- `tests/nr/test_veille_pairs_nr.py`
- `tools/bash_guard.py`


## Commit fbb848e17 — 2026-10-01 19:31
**feat(veille): forge_job_watch_cli --pair -- un rendu de pair cloud reveille la boucle du client**

### Modules Python modifiés
- `tests/nr/test_veille_pairs_nr.py`
- `tools/ci_local.py`
- `tools/forge_job_watch_cli.py`


## Commit a298f7583 — 2026-10-01 19:19
**feat(rsi): premiere capacite mesuree -- retrieval dense sur un examen held-out SCELLE**

### Modules Python modifiés
- `app/forge_generation.py`
- `tests/nr/test_capacite_retrieval_scellee_nr.py`
- `tools/ci_local.py`
- `tools/forge_bench_beir.py`


## Commit 2b95645c5 — 2026-10-01 19:10
**fix(pairs): preuve de traitement = trailer « Traite-pair: <id> », plus jamais un sha ni une mention**

### Modules Python modifiés
- `tests/nr/test_pair_quarantaine_entretien_nr.py`
- `tools/forge_pair_quarantaine.py`


## Commit ae9a54df9 — 2026-10-01 19:07
**feat(pairs): la quarantaine s'entretient seule -- cloture par preuve de commit, expiration des orphelins**

### Modules Python modifiés
- `tests/nr/test_pair_quarantaine_entretien_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_quarantaine.py`
- `tools/forge_post_commit.py`


## Commit 2d027c53c — 2026-10-01 18:54
**chore: Nokido.py (console TUI v13) GELE ; campagne d'embedding Cloudflare d'abord, Modal en relais (decisions owner)**

### Modules Python modifiés
- `app/Nokido.py`
- `tools/forge_embed_modal_campagne.py`


## Commit d2ffaf64a — 2026-10-01 18:51
**fix(rsi): un compte de fichiers ne prouve jamais un gain ; le gain se lit dans les capacites mesurees**

### Modules Python modifiés
- `app/forge_generation.py`
- `tests/nr/test_generation_fitness_pareto_nr.py`


## Commit 7fbba5f8c — 2026-10-01 18:48
**feat(rsi): porte unique de l'evolution autonome -- armement owner, frein, verrou humain**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_guarded_mutation_loop.py`
- `app/forge_mutation_judge.py`
- `tests/nr/test_boucle_raccordee_gain_nr.py`
- `tests/nr/test_juge_zone_evaluateur_nr.py`
- `tests/nr/test_porte_evolution_nr.py`
- `tests/test_evolution_cable.py`
- `tools/ci_local.py`
- `tools/forge_merge_gate.py`


## Commit 2ef3bf74f — 2026-10-01 18:35
**feat(embed): campagne cloud Modal puis Cloudflare (meme modele bge-m3), masquee, cause d'echec dite**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tests/nr/test_modal_envoi_masque_nr.py`
- `tools/forge_embed_modal_campagne.py`


## Commit 1519b85e4 — 2026-10-01 18:30
**fix(embed): le texte envoye a l'endpoint Modal est masque, rien ne part sans masqueur**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `app/forge_semantic_firewall.py`
- `tests/nr/test_modal_envoi_masque_nr.py`
- `tools/ci_local.py`


## Commit 2bf7b96e4 — 2026-10-01 18:13
**fix(rsi): un candidat ne se juge plus avec ses propres tests ; aucun chemin ne contourne le juge**

### Modules Python modifiés
- `app/forge_guarded_mutation_loop.py`
- `app/forge_mutation_judge.py`
- `tests/nr/test_juge_zone_evaluateur_nr.py`
- `tools/ci_local.py`
- `tools/forge_merge_gate.py`
- `tools/forge_self_patcher.py`


## Commit 75a539562 — 2026-10-01 18:08
**fix(soif): un oeil lexical ferme n'est pas un gap (aveugle_lexical_abstention)**

### Modules Python modifiés
- `app/forge_epistemic_veille.py`
- `tests/nr/test_soif_douleur_transition_nr.py`


## Commit b09d2d87c — 2026-10-01 18:07
**fix(soif): lexical classe, panne != lacune, un seul instrument, douleur escaladee sur transition**

### Modules Python modifiés
- `app/forge_epistemic_veille.py`
- `tests/nr/test_soif_douleur_transition_nr.py`
- `tests/test_epistemic_veille.py`
- `tools/ci_local.py`
- `tools/forge_epistemic_daemon.py`


## Commit d2f9ab6be — 2026-10-01 17:52
**fix(superviseur): la rafale RAM deleste par cout et ne fauche plus la regulation**

### Modules Python modifiés
- `tests/nr/test_delestage_ram_par_cout_nr.py`
- `tools/ci_local.py`


## Commit 5b6f39c75 — 2026-10-01 17:34
**fix(purge): le purgeur unique ne supprime que le TRAITE, defini par le postal (decision owner)**

### Modules Python modifiés
- `app/forge_pluripotent_workers.py`
- `app/forge_postal.py`
- `tests/nr/test_purge_m2m_seulement_traites_nr.py`
- `tools/forge_log_retention.py`


## Commit 6f71e3673 — 2026-10-01 17:31
**fix(secrets): le hub charge ses secrets au COFFRE, plus jamais le .env en clair (GO owner allow_critical)**

### Modules Python modifiés
- `tests/nr/test_secrets_noms_env_valeurs_coffre_nr.py`
- `tools/nokido_hub.py`


## Commit 332c7da2a — 2026-10-01 17:30
**feat(coffre): forge_env_to_vault --alias -- neutraliser un nom generique du .env range au coffre sous son vrai nom**

### Modules Python modifiés
- `tests/nr/test_env_alias_coffre_nr.py`
- `tools/ci_local.py`
- `tools/forge_env_to_vault.py`


## Commit a598e90b9 — 2026-10-01 17:15
**fix(api): pont llama.cpp, keeper, replis ollama et rapport distill reecrits (decision owner)**

### Modules Python modifiés
- `app/forge_keeper_base.py`
- `app/forge_llamacpp.py`
- `app/forge_mcp_registry.py`
- `app/forge_ollama.py`
- `tests/nr/test_api_reecrites_nr.py`
- `tools/ci_local.py`


## Commit c4b3fde28 — 2026-10-01 17:10
**fix(securite): la couche reseau MCP est restauree, corrigee, et enfin chargee (decision owner)**

### Modules Python modifiés
- `app/forge_distiller.py`
- `app/forge_gemini_bridge.py`
- `app/forge_mcp_securite_reseau.py`
- `tests/nr/test_mcp_http_identite_nr.py`
- `tests/nr/test_securite_reseau_restauree_nr.py`
- `tools/ci_local.py`
- `tools/forge_mcp_http.py`


## Commit 7243b0065 — 2026-10-01 16:59
**fix(purge): la purge M2M ne vise que le TRAITE, sur la base M2M, et seulement armee (decision owner)**

### Modules Python modifiés
- `app/forge_pluripotent_workers.py`
- `app/forge_postal.py`
- `tests/nr/test_purge_m2m_seulement_traites_nr.py`
- `tools/ci_local.py`


## Commit 1fdbbda10 — 2026-10-01 16:59
**fix(secrets): un secret de Nokido.env se lit au COFFRE, jamais dans le fichier (decision owner)**

### Modules Python modifiés
- `app/bootstrap.py`
- `app/forge_auto_pilot.py`
- `app/forge_llamacpp.py`
- `app/forge_secrets.py`
- `app/forge_settings.py`
- `app/forge_startup.py`
- `app/forge_task_router.py`
- `tests/nr/test_secrets_noms_env_valeurs_coffre_nr.py`
- `tools/forge_auth_debug.py`
- `tools/forge_gemini_mcp_connector.py`
- `tools/forge_gemini_mcp_proxy.py`
- `tools/forge_services_launcher.py`


## Commit b7ec112e9 — 2026-10-01 16:47
**fix(secrets): forge_router_gateway ne recopie plus Nokido.env dans l'environnement ; banc embedder conclu**

### Modules Python modifiés
- `app/forge_router_gateway.py`


## Commit 17b872694 — 2026-10-01 16:24
**perf(ingest): llms.txt telecharge a plusieurs, ecrit seul et dans l'ordre (x4,3 mesure)**

### Modules Python modifiés
- `tests/nr/test_ingest_llms_txt_parallele_nr.py`
- `tests/nr/test_ingest_llms_txt_version_courante_nr.py`
- `tools/ci_local.py`
- `tools/forge_ingest_llms_txt.py`


## Commit 654a82a4c — 2026-10-01 16:18
**fix(imports): cliquet des imports internes morts (socle 57 -> 52) et 5 capacites rebranchees**

### Modules Python modifiés
- `app/forge_anti_ia_traps.py`
- `app/forge_llm_transport.py`
- `app/forge_self_refinement.py`
- `app/forge_tool_forger.py`
- `tests/nr/test_imports_internes_morts_nr.py`
- `tools/ci_local.py`


## Commit e9deccaae — 2026-10-01 16:12
**perf(hub): sortir de la boucle les gels mesures, et mesurer le pool to_thread**

### Modules Python modifiés
- `app/forge_authz_shadow.py`
- `app/forge_loop_sentinel.py`
- `app/forge_mcp_registry.py`
- `app/forge_provider_admin.py`
- `tests/nr/test_boucle_hub_hors_gels_mesures_nr.py`
- `tools/ci_local.py`


## Commit 89afe899b — 2026-10-01 16:00
**perf(hub): la porte d'admission ne dort plus sur la boucle ; l'ecrivain differe reprend le verrou**

### Modules Python modifiés
- `app/forge_bounded_queue.py`
- `app/forge_lane_admission.py`
- `tests/nr/test_admission_mesure_vs_sentinelle_nr.py`
- `tests/nr/test_admission_sans_gel_de_boucle_nr.py`
- `tests/nr/test_ecrivain_differe_reprend_le_verrou_nr.py`
- `tools/ci_local.py`


## Commit eff48d288 — 2026-10-01 15:49
**fix(evenements): comm_watch et presence appelaient emit, absent de forge_critical_events**

### Modules Python modifiés
- `tests/nr/test_blackboard_fait_synchrone_nr.py`
- `tools/forge_comm_watch.py`
- `tools/forge_presence.py`


## Commit a83332982 — 2026-10-01 15:39
**fix(blackboard): six publications vers le tableau noir echouaient depuis toujours**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_keeper_base.py`
- `app/forge_swarm_blackboard.py`
- `tests/nr/test_blackboard_fait_synchrone_nr.py`
- `tools/ci_local.py`
- `tools/forge_comm_watch.py`
- `tools/forge_m2m_debate_antiregression.py`
- `tools/forge_presence.py`


## Commit 8b96f26cb — 2026-10-01 15:16
**fix(logboot): un service qui reemballe stdout ne ferme plus le tampon partage**

### Modules Python modifiés
- `tests/nr/test_logboot_journal_sans_pipe_nr.py`
- `tools/forge_logboot.py`


## Commit 66083d340 — 2026-10-01 14:34
**test(logboot): subprocess en mode texte avec errors=replace (avertissement du gate)**

### Modules Python modifiés
- `tests/nr/test_logboot_journal_sans_pipe_nr.py`


## Commit 595c8381a — 2026-10-01 14:33
**feat(superviseur): journal SANS PIPE pour les services Python (forge_logboot), 3 pilotes**

### Modules Python modifiés
- `tests/nr/test_logboot_journal_sans_pipe_nr.py`
- `tests/nr/test_superviseur_journaux_synchrones_nr.py`
- `tools/ci_local.py`
- `tools/forge_logboot.py`


## Commit cbd864c85 — 2026-10-01 14:07
**fix(hub): dernier INSERT OR IGNORE nu vers rag_chunks migre, cliquet a 0**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit f5f725567 — 2026-10-01 13:52
**fix(superviseur): journaux de service hors pool bloquant ; ctl restart sans course**

### Modules Python modifiés
- `tests/nr/test_ctl_restart_attend_l_arret_nr.py`
- `tests/nr/test_superviseur_journaux_synchrones_nr.py`
- `tools/ci_local.py`
- `tools/forge_supervisor_ctl.py`


## Commit d6c8364a4 — 2026-10-01 13:52
**fix(rag): 24 ecrivains migres hors INSERT OR IGNORE nu, socle 32 -> 1**

### Modules Python modifiés
- `app/forge_conv_indexer.py`
- `app/forge_db_path.py`
- `app/forge_dialogue_outcome.py`
- `app/forge_dispatchers.py`
- `app/forge_extern_patterns.py`
- `app/forge_git_historian.py`
- `app/forge_mailbox.py`
- `app/forge_memory_archival.py`
- `app/forge_postal.py`
- `app/forge_self_correction.py`
- `app/skilltree.py`
- `tests/nr/test_golden_insert_or_ignore_rag_nr.py`
- `tools/forge_auto_compact.py`
- `tools/forge_blind_spot_index.py`
- `tools/forge_broker_base.py`
- `tools/forge_collab_broker.py`
- `tools/forge_cve_nvd_download.py`
- `tools/forge_db_recover_chunks.py`
- `tools/forge_db_restore_chunks.py`
- `tools/forge_deep_doc_enricher.py`


## Commit 98fca0f74 — 2026-10-01 12:48
**fix(golden): socle resserre sur 33 dettes corrigees, le non-lu n'est plus un recul**

### Modules Python modifiés
- `tests/nr/test_golden_socle_non_lu_nr.py`
- `tools/ci_local.py`
- `tools/forge_golden_rules_ast.py`


## Commit 03922c868 — 2026-10-01 12:30
**fix(rag): cliquet INSERT OR IGNORE vers rag_chunks + 3 ingesteurs migres**

### Modules Python modifiés
- `tests/nr/test_golden_insert_or_ignore_rag_nr.py`
- `tests/nr/test_reingestion_garde_le_lexical_nr.py`
- `tools/ci_local.py`
- `tools/forge_docset_ingest.py`
- `tools/forge_gitingest_sdk_ingest.py`
- `tools/forge_golden_rules_ast.py`
- `tools/forge_ingest_github_repo.py`
- `tools/forge_ingest_llms_txt.py`


## Commit dd4452fa7 — 2026-10-01 12:09
**fix(ingest): version courante seule, agregats llms-full ecartes, lexical garde**

### Modules Python modifiés
- `app/forge_rag_truth.py`
- `tests/nr/test_ingest_llms_txt_version_courante_nr.py`
- `tests/nr/test_memory_ingest_volatil_nr.py`
- `tools/ci_local.py`
- `tools/forge_ingest_llms_txt.py`
- `tools/forge_memory_ingest.py`


## Commit 850270044 — 2026-10-01 10:03
**docs(changelog): 9180f8db5..798999b44 (0.20.6 : correctifs de securite des dependances)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 798999b44 — 2026-10-01 10:02
**chore(release): 0.20.6**

### Modules Python modifiés
- `nokido_agent/__init__.py`


## Commit 9180f8db5 — 2026-10-01 02:14
**docs(changelog): fc309c0ab..dbf1ab75d (0.20.5 : doctor --vivant, statut prouve par le depot)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit dbf1ab75d — 2026-10-01 02:13
**chore(release): 0.20.5**

### Modules Python modifiés
- `nokido_agent/__init__.py`


## Commit 123b4f7e0 — 2026-10-01 02:13
**feat(audit): le tableau de statut prouve par le depot, le vivant par le corps**

### Modules Python modifiés
- `tests/nr/test_capability_audit_nr.py`
- `tools/forge_capability_audit.py`

### Documentation mise à jour
- `README.md`
- `docs/i18n/README.ar.md`
- `docs/i18n/README.de.md`
- `docs/i18n/README.es.md`
- `docs/i18n/README.fr.md`
- `docs/i18n/README.ja.md`
- `docs/i18n/README.pt-BR.md`
- `docs/i18n/README.zh-CN.md`


## Commit 1a2a6b273 — 2026-10-01 02:13
**feat(doctor): nokido-doctor --vivant, ce qui bat organe par organe**

### Modules Python modifiés
- `tests/nr/test_doctor_vivant_nr.py`
- `tools/ci_local.py`
- `tools/nokido_doctor.py`


## Commit fc309c0ab — 2026-10-01 00:43
**docs(changelog): 8c20fd918..95dd496af (README au reel, bloc pip, separation)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 95dd496af — 2026-10-01 00:32
**feat(dist): le bloc pip du README suit ce que PyPI sert**

### Modules Python modifiés
- `tests/nr/test_capability_audit_nr.py`
- `tests/nr/test_forge_docs_relink_nr.py`
- `tests/nr/test_readme_install_vcs_nr.py`
- `tests/nr/test_readme_pip_nr.py`
- `tools/ci_local.py`
- `tools/forge_capability_audit.py`
- `tools/forge_dist_publish.py`
- `tools/forge_readme_pip.py`


## Commit 6062a6eed — 2026-10-01 00:32
**docs(readme): ouverture tiree du MANIFESTO, demarrage rapide en tete**

### Documentation mise à jour
- `README.md`
- `docs/i18n/README.ar.md`
- `docs/i18n/README.de.md`
- `docs/i18n/README.es.md`
- `docs/i18n/README.fr.md`
- `docs/i18n/README.ja.md`
- `docs/i18n/README.pt-BR.md`
- `docs/i18n/README.zh-CN.md`


## Commit 1ff01415f — 2026-10-01 00:00
**feat(audit): le tableau de statut du README se confronte a services.toml**

### Modules Python modifiés
- `tests/nr/test_capability_audit_nr.py`
- `tools/forge_capability_audit.py`


## Commit b18b2d779 — 2026-10-01 00:00
**docs(readme): tableau de statut au reel, declare a cote de la preuve**

### Documentation mise à jour
- `MANIFESTO.md`
- `README.md`
- `docs/i18n/README.ar.md`
- `docs/i18n/README.de.md`
- `docs/i18n/README.es.md`
- `docs/i18n/README.fr.md`
- `docs/i18n/README.ja.md`
- `docs/i18n/README.pt-BR.md`
- `docs/i18n/README.zh-CN.md`


## Commit 22c1c0498 — 2026-09-30 23:35
**chore(separation): deporte les plans internes hors de l'atelier**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_docs_deportes_hors_audit_nr.py`

### Documentation mise à jour
- `docs/nokido_migration_plan.md`


## Commit 8c20fd918 — 2026-09-30 23:15
**docs(changelog): deef0d10c..c0ffcdfae (soif, effecteurs, separation, dist, liveness)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit c0ffcdfae — 2026-09-30 23:15
**test(liveness): le garde exige un disque PEUPLE de heartbeats declares**

### Modules Python modifiés
- `tests/nr/test_liveness_registre_organes_nr.py`


## Commit d88ab63c4 — 2026-09-30 23:15
**chore(dist): le promoteur vise la vitrine Nokido-labs/nokido (ex-nokido-dist)**

### Modules Python modifiés
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_dist_publish.py`


## Commit c47568f15 — 2026-09-30 23:02
**fix(separation): l'audit doc/code saute les docs deportes (export-ignore)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_docs_deportes_hors_audit_nr.py`
- `tools/ci_local.py`


## Commit 4ac75719a — 2026-09-30 22:40
**feat(evolution): arme les deux effecteurs les plus surs du tri**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tests/nr/test_effecteurs_du_tri_nr.py`
- `tools/ci_local.py`


## Commit f81318822 — 2026-09-30 22:08
**chore(soif): marquer muet-ok l'absence de demande manuelle**

### Modules Python modifiés
- `tools/forge_epistemic_daemon.py`


## Commit e6eaca6a1 — 2026-09-30 22:07
**fix(soif): examen exteroceptif a la demande, piliers reclames ensemble**

### Modules Python modifiés
- `tests/nr/test_soif_bloquee_par_dependance_nr.py`
- `tests/nr/test_soif_choisit_son_traitement_nr.py`
- `tests/nr/test_soif_examen_a_la_demande_nr.py`
- `tools/ci_local.py`
- `tools/forge_epistemic_daemon.py`


## Commit deef0d10c — 2026-09-30 19:59
**docs(changelog): e30bad076..4d2d06496 (egress, renommage atelier, pont)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 4d2d06496 — 2026-09-30 19:58
**fix(pont-github): le pont lit l'atelier nokido-private, la description le nomme**

### Modules Python modifiés
- `tests/nr/test_bridge_habilitation_nr.py`
- `tests/nr/test_github_bridge_mcp_nr.py`
- `tests/nr/test_github_bridge_nr.py`
- `tools/forge_bridge_habilitation.py`
- `tools/forge_github_bridge.py`
- `tools/forge_github_bridge_mcp.py`


## Commit 458f03a4f — 2026-09-30 19:40
**docs(changelog): e30bad076..bfcf49c6d (egress par depot, renommage atelier)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit bfcf49c6d — 2026-09-30 19:40
**chore(repos): outils de dev sur l'atelier nokido-private, liens sur la vitrine**

### Modules Python modifiés
- `app/forge_delivery_integrity.py`
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_ci_check.py`
- `tools/forge_ci_github_log.py`
- `tools/forge_ci_stop_hook.py`
- `tools/forge_dist_publish.py`
- `tools/forge_knowledge_pack_import.py`
- `tools/forge_release_gate.py`
- `tools/forge_repo_settings_audit.py`
- `tools/forge_token_probe.py`

### Documentation mise à jour
- `docs/wiki/16-FAQ.fr.md`
- `docs/wiki/16-FAQ.md`
- `docs/wiki/19-Knowledge-Pack.fr.md`
- `docs/wiki/19-Knowledge-Pack.md`
- `docs/wiki/Home.fr.md`
- `docs/wiki/Home.md`


## Commit e716b1af1 — 2026-09-30 19:39
**fix(egress): une cle owner/nom designe UN depot (vitrine vs atelier)**

### Modules Python modifiés
- `app/forge_git_egress.py`
- `tests/nr/test_egress_profil_public_atteignable_nr.py`


## Commit e30bad076 — 2026-09-30 17:15
**docs(changelog): section 35c3a011f..4607b0612 (promoteur durci, garde par variable)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 4607b0612 — 2026-09-30 17:15
**feat(release): l'editeur se designe par la variable NOKIDO_EDITEUR, plus par un nom**

### Modules Python modifiés
- `tests/nr/test_release_pipeline_graphe_nr.py`


## Commit b7d0f4633 — 2026-09-30 16:34
**fix(dist): nom de machine apres un echappement ou un souligne, SID machine generise**

### Modules Python modifiés
- `tests/nr/test_dist_generisation_owner_path_nr.py`
- `tools/forge_dist_publish.py`


## Commit 6537f925f — 2026-09-30 16:23
**test(dist): subprocess texte avec errors=replace dans le NR du commit force**

### Modules Python modifiés
- `tests/nr/test_outils_publication_effet_nr.py`


## Commit c229fe6f2 — 2026-09-30 16:23
**fix(dist): le commit du snapshot n'ecarte plus les fichiers du .gitignore**

### Modules Python modifiés
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_dist_publish.py`


## Commit 35c3a011f — 2026-09-30 14:46
**docs(changelog): section f891c7bea..7a4d6415a (IP_CLEARANCE)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 7a4d6415a — 2026-09-30 14:46
**feat(publication): IP_CLEARANCE, docs/ip en attente sauf liberation nominative**

### Modules Python modifiés
- `app/forge_git_egress.py`
- `tests/nr/test_dist_publish_politique_nr.py`
- `tests/nr/test_egress_profil_public_atteignable_nr.py`
- `tests/nr/test_wheel_paquets_declares_nr.py`
- `tools/forge_dist_publish.py`


## Commit 11b00d0da — 2026-09-30 14:25
**docs(changelog): section 52ec03a79..f891c7bea (dist pleinement fonctionnel)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit f891c7bea — 2026-09-30 14:25
**feat(publication): dist pleinement fonctionnel, bloque seulement securite et vie privee**

### Modules Python modifiés
- `tests/nr/test_dist_publish_politique_nr.py`
- `tests/nr/test_egress_profil_public_atteignable_nr.py`
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_dist_publish.py`

### Documentation mise à jour
- `docs/launch/CHECKLIST.md`
- `docs/launch/legal_protection.md`


## Commit f86ef8b9d — 2026-09-30 14:04
**docs(changelog): section dda8ed456..52ec03a79 (pseudonyme, garde d'identite)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 52ec03a79 — 2026-09-30 14:04
**feat(publication): pseudonyme partout, garde de l'identite civile au promoteur**

### Modules Python modifiés
- `app/forge_dist_storage.py`
- `app/forge_git_egress.py`
- `app/forge_watch_agent.py`
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_dist_publish.py`
- `tools/forge_kaggle_cfg_from_env.py`
- `tools/forge_knowledge_pack_export.py`
- `tools/kaggle_push.py`
- `tools/kaggle_sync.py`
- `tools/launch_public_mirror.py`

### Documentation mise à jour
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `MANIFESTO.md`
- `SECURITY.md`
- `docs/launch/show_hn.md`
- `docs/wiki/07-Security-Model.fr.md`
- `docs/wiki/07-Security-Model.md`
- `docs/wiki/14-Troubleshooting.fr.md`
- `docs/wiki/14-Troubleshooting.md`
- `docs/wiki/16-FAQ.fr.md`


## Commit a7aefa27b — 2026-09-30 13:31
**docs(changelog): section ea51b9316..dda8ed456 (0.20.4 : wheel complete, fuites dist, PyJWT)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 3a24be590 — 2026-09-30 13:27
**feat(paquet): wheel complete 0.20.4, sans manque ni fuite par les chemins**

### Modules Python modifiés
- `nokido_agent/__init__.py`
- `tests/nr/test_dist_generisation_owner_path_nr.py`
- `tests/nr/test_wheel_paquets_declares_nr.py`
- `tools/forge_dist_publish.py`


## Commit ffbe59fba — 2026-09-30 12:44
**fix(release): l'asset source de la release se tire de D, plus de S**

### Modules Python modifiés
- `tests/nr/test_outils_publication_effet_nr.py`
- `tools/forge_dist_publish.py`
- `tools/forge_release_assets.py`


## Commit c8d34e209 — 2026-09-30 12:37
**fix(dist): le nom de machine en minuscules est generise, la defense le voit**

### Modules Python modifiés
- `tests/nr/test_dist_generisation_owner_path_nr.py`
- `tools/forge_dist_publish.py`


## Commit ea51b9316 — 2026-09-30 11:04
**docs(changelog): section 7028586b4..967418a6a (release 0.20.3, dist editeur TestPyPI)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 967418a6a — 2026-09-30 11:04
**feat(release): le dist devient l'editeur TestPyPI, en declenchement manuel**

### Modules Python modifiés
- `tests/nr/test_outils_publication_effet_nr.py`
- `tests/nr/test_release_pipeline_graphe_nr.py`
- `tools/forge_dist_publish.py`


## Commit cdbb5e667 — 2026-09-30 10:54
**docs(changelog): section 7028586b4..7a5f495d4 (release 0.20.3)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 7a5f495d4 — 2026-09-30 10:54
**chore(release): nokido-agent 0.20.3**

### Modules Python modifiés
- `nokido_agent/__init__.py`


## Commit 7028586b4 — 2026-09-29 23:53
**docs(changelog): section f72859efc..10ebf2dbe (collecte par liste, branches cloud, licences)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 10ebf2dbe — 2026-09-29 23:11
**docs(audit): licences des modeles mesurees en local, tous providers**

### Documentation mise à jour
- `mesures/audits/licences_modeles.md`


## Commit 898a740b1 — 2026-09-29 22:58
**fix(handlers): @loop merge lie save_orchestrator avant son checkpoint**

### Modules Python modifiés
- `app/forge_handlers.py`
- `tests/nr/test_handlers_loop_merge_checkpoint_nr.py`
- `tools/ci_local.py`


## Commit 0194a53b1 — 2026-09-29 22:36
**fix(ci): suite pure collectee par liste, plus en ~900 arguments**

### Modules Python modifiés
- `tests/conftest.py`
- `tests/nr/test_ci_suite_pure_ligne_de_commande_nr.py`
- `tools/ci_local.py`


## Commit f72859efc — 2026-09-29 22:02
**docs(changelog): section du lot ea3c441d0..ae22cc1c9 (77 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit ae22cc1c9 — 2026-09-29 21:57
**fix(docstrings): une seule regle de lecture pour le wiki, introspect et les fiches RAG**

### Modules Python modifiés
- `app/forge_introspect.py`
- `tests/nr/test_docstrings_trois_lecteurs_nr.py`
- `tools/ci_local.py`
- `tools/forge_module_cards.py`
- `tools/forge_wiki_modules.py`


## Commit f44a28bc6 — 2026-09-29 21:51
**fix(at-dispatch): HAS_IDS/HAS_SNIF lus sur le monolithe, plus par sys.modules**

### Modules Python modifiés
- `app/forge_at_dispatch.py`


## Commit c8333d968 — 2026-09-29 21:49
**fix(securite): le serveur MCP HTTP refuse sans jeton et ne se laisse plus dicter l'identite**

### Modules Python modifiés
- `tests/nr/test_mcp_http_identite_nr.py`
- `tools/ci_local.py`
- `tools/forge_mcp_http.py`


## Commit ad67049ae — 2026-09-29 21:49
**fix(securite): l'outil anti-fuite d'export compte la phase C et ne recopie plus ce qu'il trouve**

### Modules Python modifiés
- `tests/nr/test_db_sanitize_verdict_nr.py`
- `tools/ci_local.py`
- `tools/forge_db_sanitize.py`


## Commit ea3c441d0 — 2026-09-29 18:36
**docs(changelog): section du push etendue a f9e438d89..b648f5e23 (6 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit b648f5e23 — 2026-09-29 18:34
**chore(licences): silence voulu du repli sur fichier marque muet-ok**

### Modules Python modifiés
- `tools/forge_license_guard.py`


## Commit 65e36e036 — 2026-09-29 18:33
**feat(licences): le garde juge les dependances DECLAREES ; inventaire hors portail**

### Modules Python modifiés
- `tests/nr/test_license_guard_declarees_nr.py`
- `tools/ci_local.py`
- `tools/forge_license_guard.py`

### Documentation mise à jour
- `NOTICE.md`


## Commit b092caf85 — 2026-09-29 18:33
**test(nr): borne 120 s pour les deux derniers tests a vrai git**

### Modules Python modifiés
- `tests/nr/test_lats_garde_mutation_nr.py`
- `tests/nr/test_veille_clone_chemins_windows_nr.py`


## Commit d9d7a6fd2 — 2026-09-29 17:35
**docs(changelog): section du push f9e438d89..64f9e793e (3 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 64f9e793e — 2026-09-29 17:33
**feat(licences): les 22 fichiers tiers du portail declares, epingles, licencies**

### Modules Python modifiés
- `tests/nr/test_licences_embarquees_nr.py`
- `tools/ci_local.py`
- `tools/forge_license_guard.py`
- `tools/forge_release_assets.py`

### Documentation mise à jour
- `NOTICE.md`
- `licenses/README.md`
- `licenses/alpinejs/LICENSE.md`
- `licenses/normalize.css/LICENSE.md`


## Commit 321aa32b3 — 2026-09-29 17:33
**docs(wiki): reference des modules en paire EN/FR, generee**

### Modules Python modifiés
- `tests/nr/test_wiki_modules_bilingue_nr.py`
- `tools/ci_local.py`
- `tools/forge_wiki_modules.py`

### Documentation mise à jour
- `docs/wiki/20-Modules-Reference.fr.md`
- `docs/wiki/20-Modules-Reference.md`
- `docs/wiki/Home.fr.md`


## Commit d0a365137 — 2026-09-29 17:17
**test(nr): conversation_log borne a 120 s, un verrou echoue en le disant**

### Modules Python modifiés
- `tests/nr/test_conversation_log_jamais_purge_nr.py`


## Commit f9e438d89 — 2026-09-29 14:17
**docs(changelog): section du push etendue a 54b641efa..64cd9e692 (32 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 64cd9e692 — 2026-09-29 14:17
**fix(ci): les deux regressions de la CI de reference 03dab6e22 + boite postale isolee pour TOUS les tests**

### Modules Python modifiés
- `tests/conftest.py`
- `tests/nr/test_pair_mcp_nr.py`
- `tools/forge_pair_mcp.py`
- `tools/forge_patch_hub_ordres_bureau.py`


## Commit 03dab6e22 — 2026-09-29 13:29
**docs(changelog): section du push etendue a 54b641efa..0758bc5d4 (31 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 0758bc5d4 — 2026-09-29 13:29
**test(nr): borne de 120 s pour les deux clones de depot local -- ils ont tue la suite pure sous charge**

### Modules Python modifiés
- `tests/nr/test_veille_intake_autolance_nr.py`
- `tests/nr/test_veille_substance_nr.py`


## Commit 986544878 — 2026-09-29 12:33
**docs(changelog): section du push etendue a 54b641efa..06fef1c75 (30 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit 06fef1c75 — 2026-09-29 12:33
**fix(anatomie): forge_changelog declare un organe du lexique (Observabilite/Trace)**

### Modules Python modifiés
- `tools/forge_changelog.py`


## Commit 50f74655a — 2026-09-29 12:22
**docs(changelog): section du push 54b641efa..e22bf2f7a (29 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit e22bf2f7a — 2026-09-29 12:13
**feat(pairs): les cinq accuses d'un echange -- envoye, recu, lu, repondu, reponse lue -- sur l'agent postal**

### Modules Python modifiés
- `tests/nr/test_pair_accuses_nr.py`
- `tests/nr/test_pair_quarantaine_geste_owner_nr.py`
- `tests/nr/test_pair_quarantaine_nr.py`
- `tests/nr/test_pair_reponses_meme_pair_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`
- `tools/forge_pair_quarantaine.py`


## Commit d612b8a3f — 2026-09-29 11:03
**fix(pairs): un pair lit ses reponses quelle que soit l'inscription OAuth qui les recoit**

### Modules Python modifiés
- `tests/nr/test_pair_reponses_meme_pair_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`


## Commit 7caf00c6e — 2026-09-29 10:46
**fix(pairs): les renouvellements OAuth survivent au redemarrage -- persistes par leur seule empreinte**

### Modules Python modifiés
- `tests/nr/test_bridge_oauth_nr.py`
- `tests/nr/test_oauth_renouvellement_survit_nr.py`
- `tools/ci_local.py`
- `tools/forge_bridge_oauth.py`


## Commit 462676299 — 2026-09-29 10:40
**feat(ordres): hub action=demander_ordre -- accord owner par dialogue pour les pairs, Tailscale par le tray**

### Modules Python modifiés
- `app/forge_mcp_elicitation.py`
- `app/forge_mcp_registry.py`
- `app/forge_ordres_bureau.py`
- `tests/nr/test_demander_ordre_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_quarantaine.py`
- `tools/nokido_launcher.py`
- `tools/nokido_tray.py`


## Commit 3de3902a6 — 2026-09-29 10:04
**feat(pairs): `--repondre ... --texte` -- une reponse a un pair porte un compte rendu court**

### Modules Python modifiés
- `tests/nr/test_pair_repondre_texte_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_quarantaine.py`


## Commit 7423b7bb7 — 2026-09-29 10:03
**fix(design): --ease-in-out et --prov-local-tint alignes sur le hub -- socle de coherence vide**

### Modules Python modifiés
- `tests/nr/test_tokens_coherence_nr.py`


## Commit 56bd065cb — 2026-09-29 09:57
**fix(design): etape 5 -- un seul .lf-btn--danger, bandeau d'erreur au rouge de la palette, grille documentee a 248px**

### Documentation mise à jour
- `design_handoff_nokido/DESIGN_GUIDE.md`
- `design_handoff_nokido/readme.md`


## Commit 79754b70b — 2026-09-29 09:56
**fix(design): un token = une valeur -- hybride, anneau verifie et domaines alignes sur le hub**

### Modules Python modifiés
- `tests/nr/test_tokens_coherence_nr.py`
- `tools/ci_local.py`


## Commit ad61cf9bf — 2026-09-29 09:26
**fix(pairs): la description de soumettre_tache dit la route reelle du genre 'deliberer'**

### Modules Python modifiés
- `tests/nr/test_pair_tache_dit_sa_route_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`


## Commit 2e098ff54 — 2026-09-29 09:07
**fix(webhub): le journal racine ecrit hors de la boucle -- httpx gelait le portail :7400**

### Modules Python modifiés
- `tests/nr/test_webhub_logging_non_bloquant_nr.py`
- `tools/nokido_web_hub.py`


## Commit be893b3ca — 2026-09-29 09:04
**docs(changelog): section du push 54b641efa..ae3eb33e3 (19 commits)**

### Modules Python modifiés
- `app/brain_worker.py`
- `app/collab_modes/__init__.py`
- `app/collab_modes/_arbitration.py`
- `app/collab_modes/_core.py`
- `app/collab_modes/_participants.py`
- `app/collab_modes/dispatch.py`
- `app/collab_modes/legacy.py`
- `app/collab_modes/mode_auto.py`
- `app/collab_modes/mode_chef.py`
- `app/collab_modes/mode_cline.py`
- `app/collab_modes/mode_debat.py`
- `app/collab_modes/mode_ping.py`
- `app/forge_agent_authority.py`
- `app/forge_agent_benchmarker.py`
- `app/forge_agent_hardware.py`
- `app/forge_agent_proxy.py`
- `app/forge_agent_roles.py`
- `app/forge_agentic.py`
- `app/forge_agentic_engine.py`
- `app/forge_anti_ia_traps.py`


## Commit be893b3ca — 2026-09-29 08:57
**docs(changelog): section du push 54b641efa..ae3eb33e3 (19 commits)**

### Documentation mise à jour
- `CHANGELOG.md`


## Commit ae3eb33e3 — 2026-09-29 08:57
**fix(livraison): forge_changelog -- seul docs(changelog) s'exclut, et un refus d'ecriture est dit**

### Modules Python modifiés
- `tests/nr/test_changelog_nr.py`
- `tools/forge_changelog.py`


## Commit 0fa76dcc0 — 2026-09-29 08:55
**docs(readme): cartouche OpenCode (MCP HTTP) et sa ligne dans « Connect an external agent »**

### Documentation mise à jour
- `README.md`


## Commit e0c6cda5a — 2026-09-29 08:44
**docs(docstrings): 3 fichiers CRITIQUES demasques -- commit isole, revertable seul**

### Modules Python modifiés
- `app/forge_corrigibility.py`
- `app/forge_mcp_registry.py`
- `app/forge_mcp_security.py`


## Commit d73a7f4ab — 2026-09-29 08:36
**feat(livraison): forge_changelog -- une section de CHANGELOG par push, tiree des commits**

### Modules Python modifiés
- `tests/nr/test_changelog_nr.py`
- `tools/forge_changelog.py`
- `tools/forge_pre_push_gate.py`


## Commit dfde2cd81 — 2026-09-29 08:30
**fix(qualite): forge_docstring_masquee -- `--limite` borne les ecritures tentees, et chaque refus dit son motif**

### Modules Python modifiés
- `tools/forge_docstring_masquee.py`


## Commit b56fda541 — 2026-09-29 08:29
**feat(qualite): forge_docstring_masquee rend a Python les docstrings masquees par un `from __future__`**

### Modules Python modifiés
- `tools/forge_docstring_masquee.py`


## Commit 42dbd497a — 2026-09-29 08:26
**docs(wiki): note de tete reduite a « Mise à jour : date » sur les 52 pages**

### Documentation mise à jour
- `docs/wiki/01-Installation.fr.md`
- `docs/wiki/01-Installation.md`
- `docs/wiki/02-Quick-Start.fr.md`
- `docs/wiki/02-Quick-Start.md`
- `docs/wiki/03-Architecture.fr.md`
- `docs/wiki/03-Architecture.md`
- `docs/wiki/04-MCP-Clients-Setup.fr.md`
- `docs/wiki/04-MCP-Clients-Setup.md`
- `docs/wiki/05-LLM-Providers.fr.md`
- `docs/wiki/05-LLM-Providers.md`


## Commit e8177e685 — 2026-09-29 08:25
**docs(datation): la note de tete des pages wiki tient en une ligne, « Mise à jour : date »**

### Modules Python modifiés
- `tests/nr/test_docs_datation_nr.py`
- `tools/forge_docs_datation.py`


## Commit 8f5b835dd — 2026-09-29 08:25
**docs(wiki): cartes L2 regenerees par l'owner apres le lot docstrings**

### Documentation mise à jour
- `docs/wiki/20-Modules-Reference.md`


## Commit a695e0973 — 2026-09-29 08:06
**docs(docstrings): API ajoutee depuis le 22/09 decrite dans 38 docstrings de module**

### Modules Python modifiés
- `app/forge_agent_credential.py`
- `app/forge_auth_tokens.py`
- `app/forge_autonomous_loops.py`
- `app/forge_benchmark_adapter.py`
- `app/forge_bounded_queue.py`
- `app/forge_db_path.py`
- `app/forge_diff_analyzer.py`
- `app/forge_dpop.py`
- `app/forge_edge_fleet.py`
- `app/forge_health_diagnostic.py`
- `app/forge_hub_client.py`
- `app/forge_llm_router.py`
- `app/forge_machine_vault.py`
- `app/forge_persona_tpm.py`
- `app/forge_proposal_applier.py`
- `app/forge_provider_admin.py`
- `app/forge_provider_alias.py`
- `app/forge_resource_manager.py`
- `app/forge_secrets.py`
- `app/forge_semantic_firewall.py`


## Commit b93016ac3 — 2026-09-29 07:17
**fix(wiki): l'empreinte du corps (L3) ne mesure plus la version de Python**

### Modules Python modifiés
- `tests/nr/test_empreinte_stable_interpreteur_nr.py`
- `tools/ci_local.py`
- `tools/forge_wiki_modules.py`


## Commit 0d1455d67 — 2026-09-29 07:10
**docs(wiki): 25 pages relues datees du jour -- plus aucune page au-dela de 60 j**

### Documentation mise à jour
- `docs/wiki/01-Installation.fr.md`
- `docs/wiki/01-Installation.md`
- `docs/wiki/02-Quick-Start.fr.md`
- `docs/wiki/02-Quick-Start.md`
- `docs/wiki/03-Architecture.fr.md`
- `docs/wiki/03-Architecture.md`
- `docs/wiki/04-MCP-Clients-Setup.fr.md`
- `docs/wiki/04-MCP-Clients-Setup.md`
- `docs/wiki/05-LLM-Providers.fr.md`
- `docs/wiki/05-LLM-Providers.md`


## Commit ceb1f43d5 — 2026-09-29 07:08
**docs(readme)+feat(docs): README au reel ; datation --relue, le geste explicite de relecture**

### Modules Python modifiés
- `tests/nr/test_note_apres_frontmatter_nr.py`
- `tools/forge_docs_datation.py`

### Documentation mise à jour
- `README.md`


## Commit 149f3efe6 — 2026-09-29 06:52
**docs(wiki): revue des pages > 60 j, lot 3 -- coffre, clients, FR condensees, SearXNG**

### Documentation mise à jour
- `docs/wiki/04-MCP-Clients-Setup.fr.md`
- `docs/wiki/04-MCP-Clients-Setup.md`
- `docs/wiki/06-Hub-API-Reference.fr.md`
- `docs/wiki/08-Vault-and-Secrets.fr.md`
- `docs/wiki/08-Vault-and-Secrets.md`
- `docs/wiki/11-Cross-OS-Notes.fr.md`
- `docs/wiki/11-Cross-OS-Notes.md`
- `docs/wiki/SearXNG-Keeper.md`


## Commit 7e167536f — 2026-09-29 06:47
**docs(wiki): revue des pages > 60 j, lot 2 -- TUI, premier lancement, knowledge pack, gouvernance**

### Documentation mise à jour
- `docs/wiki/07-Security-Model.fr.md`
- `docs/wiki/09-TUI-Reference.fr.md`
- `docs/wiki/09-TUI-Reference.md`
- `docs/wiki/17-First-Launch.fr.md`
- `docs/wiki/17-First-Launch.md`
- `docs/wiki/19-Knowledge-Pack.fr.md`
- `docs/wiki/19-Knowledge-Pack.md`
- `docs/wiki/22-Governance-Cognition-Safety.fr.md`
- `docs/wiki/22-Governance-Cognition-Safety.md`


## Commit 70b77c985 — 2026-09-29 06:39
**docs(wiki): revue des pages > 60 j, lot 1 -- ce que le code dit, pas ce que la page croyait**

### Documentation mise à jour
- `README.md`
- `docs/wiki/01-Installation.fr.md`
- `docs/wiki/01-Installation.md`
- `docs/wiki/02-Quick-Start.fr.md`
- `docs/wiki/02-Quick-Start.md`
- `docs/wiki/04-MCP-Clients-Setup.fr.md`
- `docs/wiki/04-MCP-Clients-Setup.md`
- `docs/wiki/05-LLM-Providers.fr.md`
- `docs/wiki/05-LLM-Providers.md`
- `docs/wiki/07-Security-Model.fr.md`


## Commit 6051e6bfd — 2026-09-29 06:26
**fix(wiki): l'aligneur ne retouche jamais une page generee**

### Modules Python modifiés
- `tests/nr/test_wiki_align_commandes_nr.py`
- `tools/forge_wiki_align.py`


## Commit c754feec1 — 2026-09-29 06:25
**feat(wiki): l'aligneur renomme aussi les commandes du cutover, prouvees par pyproject**

### Modules Python modifiés
- `tests/nr/test_wiki_align_commandes_nr.py`
- `tools/ci_local.py`
- `tools/forge_wiki_align.py`


## Commit 54b641efa — 2026-09-28 17:40
**test(nr): errors=replace sur les subprocess texte du NR bilan coffre (gate firehose)**

### Modules Python modifiés
- `tests/nr/test_superviseur_bilan_coffre_nr.py`


## Commit 5cebe5154 — 2026-09-28 17:40
**test(nr): deux NR du coffre rendus hermetiques (CI 36440801595 : 5 echecs, compte user)**

### Modules Python modifiés
- `tests/nr/test_release_lock_provenance_nr.py`
- `tests/nr/test_superviseur_bilan_coffre_nr.py`


## Commit 0dc24fb86 — 2026-09-28 17:03
**fix(bridge): le pont stdio ne lit plus de jeton dans l'environnement**

### Modules Python modifiés
- `tools/mcp_stdio_bridge.py`


## Commit 83b721ab1 — 2026-09-28 16:42
**docs(wiki): regeneration du 2026-09-28 -- pairs cloud, coffre au repos, resynchro des clients**

### Documentation mise à jour
- `docs/wiki/01-Installation.fr.md`
- `docs/wiki/01-Installation.md`
- `docs/wiki/02-Quick-Start.fr.md`
- `docs/wiki/02-Quick-Start.md`
- `docs/wiki/03-Architecture.fr.md`
- `docs/wiki/03-Architecture.md`
- `docs/wiki/04-MCP-Clients-Setup.fr.md`
- `docs/wiki/04-MCP-Clients-Setup.md`
- `docs/wiki/05-LLM-Providers.fr.md`
- `docs/wiki/05-LLM-Providers.md`


## Commit 49bd0539c — 2026-09-28 16:41
**fix(docs): une note de doc ne se pose jamais au-dessus d'un frontmatter**

### Modules Python modifiés
- `tests/nr/test_note_apres_frontmatter_nr.py`
- `tools/ci_local.py`
- `tools/forge_docs_datation.py`
- `tools/forge_docs_port_annotate.py`


## Commit 25d7339de — 2026-09-28 16:25
**refactor(pairs): un seul chemin pour les outils de pair (clone releve par le cliquet duplication)**

### Modules Python modifiés
- `tools/forge_pair_mcp.py`


## Commit 380c62c6e — 2026-09-28 16:02
**chore(pairs): except voulu de _sid_owner marque muet-ok (profil systeme sans chemin)**

### Modules Python modifiés
- `tools/forge_pair_quarantaine.py`


## Commit 5e9a30285 — 2026-09-28 16:02
**fix(pairs): quarantaine etanche face aux agents locaux -- approbation = owner eleve, intents en liste blanche**

### Modules Python modifiés
- `tests/nr/test_pair_quarantaine_geste_owner_nr.py`
- `tests/nr/test_pair_quarantaine_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`
- `tools/forge_pair_quarantaine.py`


## Commit 0f54d1c1c — 2026-09-28 15:25
**fix(pairs): le Host public du tunnel passe la protection DNS-rebinding de FastMCP**

### Modules Python modifiés
- `tests/nr/test_pair_mcp_hote_public_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`


## Commit 6132f3038 — 2026-09-28 15:02
**feat(pairs): quarantaine owner + deliberation RecursiveMAS + service NokidoPairMCP (coupe)**

### Modules Python modifiés
- `tests/nr/test_lanceur_profil_pair_nr.py`
- `tests/nr/test_pair_quarantaine_nr.py`
- `tools/ci_local.py`
- `tools/forge_bridge_launch.py`
- `tools/forge_pair_quarantaine.py`


## Commit 2a30e2923 — 2026-09-28 14:51
**feat(connecteur): serveur MCP des pairs cloud -- lecture en liste blanche, collaboration en quarantaine M2M**

### Modules Python modifiés
- `tests/nr/test_pair_mcp_nr.py`
- `tools/ci_local.py`
- `tools/forge_pair_mcp.py`


## Commit dbdfd620c — 2026-09-28 14:42
**feat(connecteur): une autorite OAuth parametree par passerelle ; passerelle des pairs cloud**

### Modules Python modifiés
- `tests/nr/test_oauth_par_passerelle_nr.py`
- `tools/ci_local.py`
- `tools/forge_bridge_oauth.py`
- `tools/forge_passerelle_pair.py`


## Commit ce2663508 — 2026-09-28 14:19
**fix(mcp): la synchro de rotation rafraichit Gemini, Antigravity, VS Code natif et Copilot**

### Modules Python modifiés
- `tests/nr/test_mcp_json_sync_clients_http_nr.py`
- `tools/ci_local.py`
- `tools/forge_mcp_json_sync.py`


## Commit 81b6faecf — 2026-09-28 14:13
**fix(coffre): le provisionnement ne dit plus « NON provisionnees » pour un nom ferme present au coffre reserve**

### Modules Python modifiés
- `tests/nr/test_provision_source_retiree_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit c5d2eafc3 — 2026-09-28 14:11
**fix(coffre): le semeur relit la VALEUR ecrite ; plus aucune fin de jeton affichee**

### Modules Python modifiés
- `tests/nr/test_semeur_relit_la_valeur_nr.py`
- `tools/ci_local.py`
- `tools/forge_vault_seed_agent_tokens.py`


## Commit 1f59d7d08 — 2026-09-28 13:59
**feat(at-rest): --rekey-clore efface les sauvegardes d'un changement de cle reussi, sur preuve seulement**

### Modules Python modifiés
- `tests/nr/test_vc_rekey_scripte_nr.py`
- `tools/forge_at_rest_veracrypt.py`


## Commit 091871aed — 2026-09-28 13:58
**fix(at-rest): --rekey relit la VALEUR du coffre reserve (fausse alerte en production le 2026-09-28)**

### Modules Python modifiés
- `tests/nr/test_vc_rekey_scripte_nr.py`
- `tools/forge_at_rest_veracrypt.py`


## Commit 9dc2a2681 — 2026-09-28 13:36
**feat(demarrage): V: se monte par la tache SYSTEM, la cle ne passe plus par la session owner**

### Modules Python modifiés
- `tests/nr/test_demarrage_monte_v_par_system_nr.py`
- `tools/ci_local.py`


## Commit b8c4da9ee — 2026-09-28 13:32
**fix(at-rest): errors='replace' sur l'appel icacls de --rekey (gate anti-regression)**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`


## Commit 38f43af0f — 2026-09-28 13:31
**feat(at-rest): changement du fichier-cle de V: SANS interface graphique (--rekey, --rekey-restaurer)**

### Modules Python modifiés
- `tests/nr/test_vc_rekey_scripte_nr.py`
- `tools/ci_local.py`
- `tools/forge_at_rest_veracrypt.py`


## Commit dab7eedd5 — 2026-09-28 13:27
**chore(at-rest): saut volontaire d'une PRF absente marque muet-ok (gate de recidive)**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`


## Commit ebdcf1c02 — 2026-09-28 13:27
**fix(at-rest): en-tete de V: verifie hors VeraCrypt ; voie graphique du changement de cle retiree**

### Modules Python modifiés
- `tests/nr/test_vc_entete_hors_veracrypt_nr.py`
- `tests/nr/test_vc_rekey_nr.py`
- `tools/ci_local.py`
- `tools/forge_at_rest_veracrypt.py`


## Commit 3b3d42eae — 2026-09-28 13:21
**fix(mcp): la synchro des jetons couvre les portees utilisateur et locale de ~/.claude.json**

### Modules Python modifiés
- `tests/nr/test_mcp_json_sync_portees_claude_nr.py`
- `tools/ci_local.py`
- `tools/forge_mcp_json_sync.py`


## Commit ddfabd32d — 2026-09-28 11:17
**docs(plans): deroule de la fenetre de maintenance du coffre (rotation, fichier-cle, NSSM, redemarrage)**

### Documentation mise à jour
- `plans/fenetre-maintenance-coffre.md`


## Commit fe791ee8b — 2026-09-28 11:16
**feat(coffre): outil de ROTATION des secrets exposes (etape 3), sous SYSTEM -- retire aussi les copies des noms fermes**

### Modules Python modifiés
- `tests/nr/test_coffre_rotation_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_rotation.py`


## Commit 28aba5fea — 2026-09-28 11:14
**feat(superviseur): etape F -- le chargeur de secrets du coffre dit son bilan (noms), prealable au retrait NSSM**

### Modules Python modifiés
- `tests/nr/test_superviseur_bilan_coffre_nr.py`
- `tools/ci_local.py`


## Commit 2f03fea6c — 2026-09-28 11:13
**fix(hub): /api/login/renouveler porte sa borne d'origine dans le handler (regression de 6808a62de)**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 35edce8c8 — 2026-09-28 11:05
**feat(at-rest): changement du fichier-cle VeraCrypt en trois phases gardees (--rekey-*)**

### Modules Python modifiés
- `tests/nr/test_vc_rekey_nr.py`
- `tools/ci_local.py`
- `tools/forge_at_rest_veracrypt.py`


## Commit 2a6f688f4 — 2026-09-28 11:01
**fix(secrets): fichier-cle VeraCrypt FERME hors SYSTEM -- chaque lecteur legitime a sa voie**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`
- `tests/nr/test_fichier_cle_veracrypt_reserve_nr.py`


## Commit 239116a39 — 2026-09-28 10:50
**feat(rmas): capsule cognitive -- le debat se cristallise en une capsule courte et tracable pour les boites noires**

### Modules Python modifiés
- `tests/nr/test_capsule_cognitive_nr.py`
- `tools/ci_local.py`
- `tools/forge_debate_job.py`
- `tools/forge_debate_run_job.py`


## Commit 7d5e03ef7 — 2026-09-28 10:41
**fix(secrets): le fichier-cle VeraCrypt de V: devient un nom reserve (en transition), lu au guichet**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`
- `tests/nr/test_fichier_cle_veracrypt_reserve_nr.py`
- `tools/ci_local.py`
- `tools/forge_at_rest_veracrypt.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit c7b47a756 — 2026-09-28 10:33
**feat(auth): TaskExecutor relit son jeton a chaque appel et recoit le jeton court du lanceur**

### Modules Python modifiés
- `tests/nr/test_task_executor_jeton_par_appel_nr.py`
- `tools/ci_local.py`
- `tools/forge_runas_launcher.py`
- `tools/forge_task_executor.py`


## Commit a199d43f2 — 2026-09-28 10:25
**feat(auth): jeton PROJETE -- le lanceur garde vivant le jeton court du service (motif Kubernetes)**

### Modules Python modifiés
- `app/forge_agent_credential.py`
- `tests/nr/test_jeton_projete_nr.py`
- `tests/nr/test_lanceur_runas_environnement_nr.py`
- `tools/ci_local.py`
- `tools/forge_runas_launcher.py`


## Commit cfd05859d — 2026-09-28 10:17
**fix(secrets): plus aucune cle de chiffrement derivee du maitre ; FORGE_ENCRYPT_KEY et LAFORGE_DB_KEY refermes hors SYSTEM**

### Modules Python modifiés
- `app/forge_db_conn.py`
- `app/forge_encrypt.py`
- `app/forge_secrets.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`
- `tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py`
- `tests/nr/test_pas_de_cle_derivee_du_maitre_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit e44e39a69 — 2026-09-28 10:02
**fix(ctl): nokido_ensure_service remarche -- ctl lance par le hub ne rappelle plus le hub**

### Modules Python modifiés
- `tests/nr/test_ctl_sans_boucle_par_le_hub_nr.py`
- `tools/ci_local.py`
- `tools/forge_ensure_service.py`
- `tools/forge_supervisor_ctl.py`


## Commit e844c80ff — 2026-09-28 09:55
**fix(secrets): FORGE_ENCRYPT_KEY et LAFORGE_DB_KEY remis en transition -- repli silencieux sur une cle derivee du maitre**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`


## Commit 175d8e9a7 — 2026-09-28 09:53
**fix(secrets): LAFORGE_SUPERVISOR_TOKEN remis en transition -- la relance owner du hub prenait 401**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`


## Commit 9278939ae — 2026-09-28 09:45
**feat(auth): etapes D+E -- le lanceur runAs ne transmet plus les secrets du superviseur ; RSSWatcher recoit son jeton court**

### Modules Python modifiés
- `tests/nr/test_lanceur_runas_environnement_nr.py`
- `tools/ci_local.py`
- `tools/forge_runas_launcher.py`


## Commit a0ca3f721 — 2026-09-28 09:33
**feat(auth): etape B -- auxiliaire du lanceur, assertion TPM d'abord (jeton court injecte)**

### Modules Python modifiés
- `tests/nr/test_jeton_lanceur_auxiliaire_nr.py`
- `tools/ci_local.py`
- `tools/forge_jeton_lanceur.py`


## Commit d5a8e50e3 — 2026-09-28 09:30
**feat(auth): etape C -- un service utilise le jeton court de son lanceur et le renouvelle (RFC 8693)**

### Modules Python modifiés
- `app/forge_agent_credential.py`
- `tests/nr/test_jeton_injecte_par_le_lanceur_nr.py`
- `tools/ci_local.py`


## Commit 6808a62de — 2026-09-28 09:26
**fix(auth): le renouvellement des jetons courts devient un echange de jeton RFC 8693**

### Modules Python modifiés
- `app/forge_auth_tokens.py`
- `tests/nr/test_renouvellement_jeton_court_nr.py`
- `tools/nokido_hub.py`


## Commit d3ed4036d — 2026-09-28 09:11
**feat(auth): renouvellement des jetons courts -- etape A du jeton injecte par le superviseur**

### Modules Python modifiés
- `app/forge_auth_tokens.py`
- `app/forge_integrity.py`
- `tests/nr/test_renouvellement_jeton_court_nr.py`
- `tests/nr/test_revocation_chemins_connus_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit dff03d084 — 2026-09-28 09:01
**fix(secrets): 2b-6 -- plus aucun lecteur direct d'un nom reserve au coffre machine**

### Modules Python modifiés
- `app/forge_grounder.py`
- `tests/nr/test_lecteurs_directs_reserves_2b6_nr.py`
- `tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py`
- `tools/ci_local.py`
- `tools/forge_acp_adapter.py`
- `tools/forge_ami_strategist.py`
- `tools/forge_goap_online_launch.py`
- `tools/forge_mcp_json_sync.py`
- `tools/forge_swebench_strategy_debate.py`
- `tools/forge_vscode_mcp_sync.py`


## Commit db2343a46 — 2026-09-28 08:53
**fix(secrets): 2b-6 lot 2 -- HUB_JWT_SECRET et firewall_log_hmac FERMES hors SYSTEM**

### Modules Python modifiés
- `app/forge_secrets.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`


## Commit 8a32b2cae — 2026-09-28 08:41
**fix(secrets): 2b-6 lot 1 -- les noms reserves FERMES ne se lisent plus au coffre machine ni dans Nokido.env**

### Modules Python modifiés
- `app/forge_secrets.py`
- `app/forge_semantic_firewall.py`
- `tests/nr/test_fermeture_replis_reserves_2b6_nr.py`
- `tests/nr/test_secrets_reserves_recensement_nr.py`
- `tools/ci_local.py`
- `tools/forge_reindex_deport.py`
- `tools/forge_supervisor_reconcile.py`


## Commit bcefa5139 — 2026-09-28 08:11
**chore(portail): refus EdDSA volontairement muet, marque muet-ok (pas d'oracle)**

### Modules Python modifiés
- `app/web_hub/auth.py`


## Commit ec0f7310c — 2026-09-28 08:10
**feat(portail): sessions EdDSA verifiees par la cle ENREGISTREE de WEBHUB ; outil de cle du portail**

### Modules Python modifiés
- `app/web_hub/auth.py`
- `tests/nr/test_portail_eddsa_nr.py`
- `tools/ci_local.py`
- `tools/forge_portail_cle.py`


## Commit dba262032 — 2026-09-28 08:04
**fix(cles): le registre des cles publiques d'agents quitte sandbox/ (dossier owner, jamais cree)**

### Modules Python modifiés
- `app/forge_agent_keys.py`
- `tests/nr/test_registre_cles_hors_sandbox_nr.py`
- `tools/ci_local.py`


## Commit 5cd5469f9 — 2026-09-28 07:56
**fix(secrets): cle HMAC d'integrite partagee, source unique, plus jamais de cle devinable**

### Modules Python modifiés
- `app/forge_conv_sanitizer.py`
- `app/forge_secrets.py`
- `app/forge_state_manager.py`
- `app/forge_vec_ledger.py`
- `tests/nr/test_cle_integrite_partagee_nr.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tests/nr/test_maitre_decouple_des_cles_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit 13a8d7383 — 2026-09-28 07:49
**fix(superviseur): ctl lit son jeton au guichet ; hors SYSTEM, mutations via le hub**

### Modules Python modifiés
- `tests/nr/test_supervisor_ctl_via_hub_2b5_nr.py`
- `tests/test_forge_supervisor_ctl.py`
- `tools/ci_local.py`
- `tools/forge_supervisor_ctl.py`


## Commit 3dcacba79 — 2026-09-28 07:35
**feat(credential): jeton_hub(identite) pour les clients du hub ; transition maitre pour tout client du pont ; nom de l'owner hors du code**

### Modules Python modifiés
- `app/forge_agent_credential.py`
- `app/forge_auth_tokens.py`
- `tests/nr/test_connexion_persona_et_maitre_2b1_nr.py`
- `tests/nr/test_jeton_hub_identite_ou_transition_2b5_nr.py`
- `tests/nr/test_pont_stdio_identite_propre_2b5_nr.py`
- `tools/ci_local.py`
- `tools/mcp_stdio_bridge.py`
- `tools/nokido_tui.py`


## Commit 9f468f242 — 2026-09-28 07:11
**fix(pont): le pont stdio presente l'identite PROPRE de chaque client, plus le maitre**

### Modules Python modifiés
- `tests/nr/test_pont_stdio_identite_propre_2b5_nr.py`
- `tools/ci_local.py`
- `tools/mcp_stdio_bridge.py`


## Commit c3ae14f32 — 2026-09-28 06:59
**feat(coffre): 2b-4 jetons courts emis par le hub hors SYSTEM, HMAC conserve**

### Modules Python modifiés
- `app/forge_agent_credential.py`
- `tests/nr/test_cycle_de_vie_jetons_nr.py`
- `tests/nr/test_jeton_court_emis_par_le_hub_2b4_nr.py`
- `tools/ci_local.py`


## Commit f101c675c — 2026-09-28 06:55
**feat(coffre): 2b-3 JWT du hub en EdDSA (Ed25519), cle privee reservee, HS256 en transition**

### Modules Python modifiés
- `app/forge_auth_jwt.py`
- `app/forge_secrets.py`
- `tests/nr/test_jwt_hub_ed25519_2b3_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit 7c1decad1 — 2026-09-28 06:48
**fix(coffre): 2b-2 lot B2 -- le hub rejette les jetons d'une autre famille, proxy MCP sur son jeton propre**

### Modules Python modifiés
- `app/forge_auth_jwt.py`
- `tests/nr/test_admin_jeton_propre_organe_nr.py`
- `tests/nr/test_familles_de_jetons_2b2_nr.py`
- `tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py`
- `tools/ci_local.py`
- `tools/nokido_mcp_proxy.py`


## Commit ee71572a0 — 2026-09-28 06:42
**fix(coffre): 2b-2 lot B1 -- quatre noms reserves de plus, lecteurs au guichet, cliquet**

### Modules Python modifiés
- `app/forge_integrity.py`
- `app/forge_jwt_router.py`
- `app/forge_rbac.py`
- `app/forge_secrets.py`
- `app/forge_semantic_firewall.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tests/nr/test_guichet_seul_2b2_nr.py`
- `tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`
- `tools/forge_privileged_bridge.py`
- `tools/nokido_hub.py`


## Commit 3272f1da3 — 2026-09-28 06:41
**fix(governed_edit): trace de derogation critique dans un journal, plus sur stderr (WEDGE KILL du hub)**

### Modules Python modifiés
- `tests/nr/test_governed_edit_trace_non_bloquante_nr.py`
- `tools/forge_governed_edit.py`


## Commit 49fb8ffe3 — 2026-09-28 06:16
**fix(coffre): suites de 2b-1 -- cle persona jamais recreee, login_agent sans import du hub, garde a bornes de mot**

### Modules Python modifiés
- `app/forge_auth_tokens.py`
- `app/forge_persona_tpm.py`
- `tests/nr/test_connexion_persona_et_maitre_2b1_nr.py`
- `tests/test_tool_gate_env_faux_positif.py`
- `tools/forge_tool_gate.py`


## Commit 69b9df82d — 2026-09-28 06:09
**fix(coffre): 2b-1 cle persona fail-closed, HMAC persona refuse ring<=1, maitre retire comme identite**

### Modules Python modifiés
- `app/forge_auth_tokens.py`
- `app/forge_persona_tpm.py`
- `app/forge_secrets.py`
- `app/tests/test_persona_tpm.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tests/nr/test_connexion_persona_et_maitre_2b1_nr.py`
- `tests/test_capability_tokens.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`
- `tools/forge_release_lock.py`


## Commit a1bbdbb9e — 2026-09-28 05:14
**feat(secrets): etape 2a du correctif du coffre -- coffre RESERVE lu d'abord, repli conserve (go owner)**

### Modules Python modifiés
- `app/forge_machine_vault.py`
- `app/forge_secrets.py`
- `tests/nr/test_coffre_reserve_nr.py`
- `tools/ci_local.py`
- `tools/forge_coffre_reserve_provision.py`


## Commit e736322fc — 2026-09-28 03:12
**feat(secrets): etape 1 du correctif du coffre -- le jeton maitre n'est plus une cle (go owner)**

### Modules Python modifiés
- `app/forge_auth_jwt.py`
- `app/forge_conv_sanitizer.py`
- `app/forge_encrypt.py`
- `app/forge_secrets.py`
- `app/forge_snapshot.py`
- `app/forge_state_manager.py`
- `app/forge_vec_ledger.py`
- `tests/nr/test_maitre_decouple_des_cles_nr.py`
- `tests/test_forge_auth_jwt.py`
- `tools/ci_local.py`


## Commit 1b81b4a50 — 2026-09-28 02:49
**fix(secrets): un recensement direct impossible se compte au lieu de se taire**

### Modules Python modifiés
- `app/forge_machine_vault.py`
- `tests/nr/test_secrets_reserves_recensement_nr.py`


## Commit 4e7530049 — 2026-09-28 02:48
**fix(test): le NR success_oplog suit 5c0044003 -- un test cite n'est rejoue que s'il existe**

### Modules Python modifiés
- `tests/nr/test_success_oplog_nr.py`


## Commit d834b8db8 — 2026-09-28 02:44
**fix(audit): un chemin vers un secret n'est pas un secret -- `_FILE` et `_DIRECTORY`**

### Modules Python modifiés
- `tests/nr/test_secret_source_cliquet_nr.py`
- `tools/forge_secret_source_audit.py`


## Commit 54e2c53d0 — 2026-09-28 02:44
**feat(secrets): etape 0 du correctif du coffre -- recenser qui lit un secret reserve (go owner)**

### Modules Python modifiés
- `app/forge_machine_vault.py`
- `app/forge_secrets.py`
- `tests/nr/test_secrets_reserves_recensement_nr.py`
- `tools/ci_local.py`


## Commit c07a89fc4 — 2026-09-28 01:32
**docs(plans): .github ferme aux sessions cloud, runner self-hosted arrete pendant la phase**

### Documentation mise à jour
- `plans/portabilite-linux.md`


## Commit b08073348 — 2026-09-28 01:20
**docs(plans): suite de tests portable sous Linux, decoupee pour sessions cloud (go owner)**

### Documentation mise à jour
- `plans/portabilite-linux.md`


## Commit 8a3ddaa67 — 2026-09-28 01:06
**docs(plans): connecteur claude.ai en lecture seule -- plan, rien d'expose (owner 28/09)**

### Documentation mise à jour
- `plans/connecteur-claude-ai-lecture-seule.md`


## Commit 5cbb7af49 — 2026-09-28 01:02
**feat(homeostat): un processus sans jeton superviseur DECLARE son besoin de RAM au hub (go owner)**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `tests/nr/test_delegation_ressources_hub_nr.py`
- `tests/nr/test_homeostat_soi_non_soi_nr.py`
- `tests/nr/test_journal_porte_acteur_et_sujet_nr.py`
- `tests/nr/test_routes_organes_authentifiees_nr.py`
- `tools/ci_local.py`
- `tools/nokido_hub.py`


## Commit 2cb5200e5 — 2026-09-28 00:20
**test(garde): NR parite -- subprocess texte avec errors=replace (gate firehose)**

### Modules Python modifiés
- `tests/nr/test_garde_python_parite_shell_nr.py`


## Commit 534ebb5d6 — 2026-09-28 00:19
**fix(garde): action=python a parite avec run shell sous le compte bac a sable (go owner)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_workspace_guard.py`
- `tests/nr/test_garde_python_parite_shell_nr.py`
- `tests/nr/test_workspace_guard_message_nr.py`
- `tools/ci_local.py`


## Commit cab8b5760 — 2026-09-28 00:13
**fix(homeostat): dire QUI porte la pression, et nommer un refus de sommeil au lieu d'un noop**

### Modules Python modifiés
- `app/forge_resource_manager.py`
- `app/forge_sandbox_exec.py`
- `tests/nr/test_homeostat_soi_non_soi_nr.py`
- `tools/ci_local.py`


## Commit 60e062ef2 — 2026-09-28 00:03
**fix(edge): le broadcast world-vector ne vise que les noeuds qui le recoivent**

### Modules Python modifiés
- `app/forge_edge_fleet.py`
- `tests/nr/test_edge_fleet_liste_blanche_nr.py`


## Commit b9681b7d4 — 2026-09-28 00:02
**fix(rag): plus aucune purge rag_fts par colonne UNINDEXED dans le depot (cliquet)**

### Modules Python modifiés
- `app/forge_rag_janitor.py`
- `app/forge_synaptic_plasticity.py`
- `app/forge_watch_agent.py`
- `tests/nr/test_fts_delete_conditionnel_nr.py`
- `tests/nr/test_fts_jamais_purge_par_colonne_unindexed_nr.py`
- `tests/nr/test_veille_backfill_un_chunk_nr.py`
- `tools/ci_local.py`
- `tools/forge_veille_backfill.py`
- `tools/forge_veille_depollute.py`


## Commit 71dc10022 — 2026-09-27 23:44
**fix(rag): l'audit NREM1 ne balaie plus rag_fts sous verrou (hub fige ~1 h chaque soir a 22 h)**

### Modules Python modifiés
- `app/forge_db_path.py`
- `tests/nr/test_audit_regulation_fts_sans_scan_nr.py`
- `tools/ci_local.py`
- `tools/forge_body_regulation_audit.py`
- `tools/forge_post_commit.py`


## Commit d52c23cf7 — 2026-09-27 22:58
**fix(hub): une ecriture SQLite ne fige plus la boucle du hub (1 257 s figees le 27/09)**

### Modules Python modifiés
- `app/forge_bounded_queue.py`
- `app/forge_intention_journal.py`
- `app/forge_promcp_profiler.py`
- `app/forge_timecode.py`
- `tests/nr/test_hub_boucle_jamais_figee_par_ecriture_nr.py`
- `tools/ci_local.py`


## Commit 18c316780 — 2026-09-27 22:23
**fix(edge): la flotte ne choisit qu'un noeud PROUVE servir le chat (liste blanche)**

### Modules Python modifiés
- `app/forge_contract_net.py`
- `app/forge_edge_fleet.py`
- `app/tests/test_contract_net.py`
- `app/web_hub/wired_routes.py`
- `tests/nr/test_edge_fleet_liste_blanche_nr.py`
- `tools/ci_local.py`


## Commit b8cb74e10 — 2026-09-27 22:00
**fix(edge): noeud edge durci avant son premier deploiement LAN (VM StackDNS)**

### Modules Python modifiés
- `app/forge_edge_node.py`
- `tests/nr/test_edge_node_durci_nr.py`
- `tools/ci_local.py`


## Commit 71a91f0f4 — 2026-09-27 21:04
**chore(jepa_dataset): repli SyntaxError annote muet-ok (voulu, la carte garde le texte brut)**

### Modules Python modifiés
- `tools/forge_jepa_dataset.py`


## Commit d8cfd6e9d — 2026-09-27 21:02
**fix(superviseur): la rafale RAM n'endort plus le runner CI en plein job**

### Modules Python modifiés
- `tests/nr/test_runner_ci_pas_endormi_nr.py`
- `tools/ci_local.py`


## Commit 4f06a46a9 — 2026-09-27 20:43
**feat(jepa_dataset): source oplog -- triplets retrieval tires du journal des succes**

### Modules Python modifiés
- `tests/nr/test_jepa_dataset_oplog_nr.py`
- `tools/ci_local.py`
- `tools/forge_jepa_dataset.py`


## Commit acc8cac51 — 2026-09-27 20:18
**test(swebench): sous-processus du NR en errors='replace'**

### Modules Python modifiés
- `tests/nr/test_swebench_hors_rag_nr.py`


## Commit 243298e65 — 2026-09-27 20:17
**fix(swebench): dossier de travail HORS de RAG/, un resolveur unique pour tous les runners**

### Modules Python modifiés
- `app/forge_benchmark_adapter.py`
- `tests/nr/test_swebench_hors_rag_nr.py`
- `tools/ci_local.py`
- `tools/forge_sft_export.py`
- `tools/forge_swebench_lats_runner.py`
- `tools/forge_swebench_modal.py`
- `tools/forge_swebench_repo_cache.py`
- `tools/forge_swebench_runner.py`


## Commit 446730160 — 2026-09-27 19:35
**test(nr_instables): borne dediee de 120 s pour le chemin reel a sous-processus pytest**

### Modules Python modifiés
- `tests/nr/test_nr_instables_nr.py`


## Commit 5d54e9017 — 2026-09-27 19:03
**test(harness): NR du contrat hermetique -- plus d'import d'un module non versionne**

### Modules Python modifiés
- `tests/nr/test_harness_contract_nr.py`


## Commit 5c0044003 — 2026-09-27 17:51
**fix(registry,run_job,invariant): 3 handlers graph morts depuis mai, lane par compte, tests disparus DITS**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tests/nr/test_capacites_touchees_tests_absents_nr.py`
- `tests/nr/test_forge_patch_lane_auto_nr.py`
- `tests/test_forge_mcp_registry_namespace.py`
- `tools/ci_local.py`
- `tools/forge_patch_lane_auto.py`
- `tools/forge_success_oplog.py`


## Commit 344a13eb4 — 2026-09-27 17:26
**fix(registry): un intent GOAP sans outil MCP n'est plus un succes (fail-closed)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tests/nr/test_goap_outil_inconnu_failclosed_nr.py`
- `tools/ci_local.py`


## Commit b9237c062 — 2026-09-27 17:15
**feat(harness): contrat d'execution par etape -- schema pur, verdict par liste blanche**

### Modules Python modifiés
- `app/forge_harness_contract.py`
- `tests/nr/test_harness_contract_nr.py`
- `tools/ci_local.py`


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
- `tests/nr/test_tui_raccourcis_