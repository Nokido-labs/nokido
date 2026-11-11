# 06 — Plan : items restants de la roadmap

> Genere par `tools/forge_spec_extractor.py` (introspection, aucune valeur recopiee a la main) -- commit `bffa9f1a0`, 2026-11-11 01:34. Ne pas editer : relancer l'extracteur.


<!-- nokido:dynamique -->
189 / 280 CLOS (67.5 %) ; etats : CLOS 189, GELE 1, OUVERT 18, OWNER_PLANIFIE 6, PARTIEL 61, SANS_MARQUEUR 5 (`docs/roadmap_arbre.json`).

## Bloques par un geste ou une decision owner (20)

| Item | Etat | Prio | Reste |
|---|---|---|---|
| `P3_analogie_inverse_code_vers_corps_20261020` | OWNER_PLANIFIE | -- | (non dit) |
| `roadmap_next_20261015` | PARTIEL | -- | verifier les blocs du registre MCP (fichier critique, derogation owner) et le banc de l'intelligence cumulative |
| `P1_audit_analogie_corps_apres_ci_20261020` | OWNER_PLANIFIE | P1 | (non dit) |
| `P1_audit_pair_efficience_A_G_20261019` | PARTIEL | P1 | C (autres cas), D (relecture owner), G, 04, 06, 07 |
| `P1_batch_et_advisor_phases_2_et_3_20261024` | OUVERT | P1 | DECISION OWNER (advisor = API Claude PAYANTE, a l'arrivee du quota API) puis 3-5 taches S tirees du doc, deployer phases 2 et 3 de l'advisor SQL et du batch processing d'appels |
| `P1_contexte_p1b_hygiene_session_20261020` | OWNER_PLANIFIE | P1 | (non dit) |
| `P1_contexte_p1c_instructions_residentes_20261020` | OWNER_PLANIFIE | P1 | (non dit) |
| `P1_ponts_web_chatgpt_gemini_20261018` | PARTIEL | P1 | essai Gemini Chrome des que l'owner a reconnecte l'extension ; pont MCP Gemini web -> vivant (meme contrat que ChatGPT web) |
| `P1_suivi_delegations_tout_cli_20261022` | PARTIEL | P1 | task action=status sans id -> meme vue (allow_critical owner) ; job_5e85fccc agent OPENCODE pending ~26 h sans executeur de ce nom (a reaffecter) ; reaff=INCONNU a distinguer de « aucune » ; constat d |
| `P1_worktree_par_provenance_et_reconciliation_20261018` | PARTIEL | P1 | relance du hub (effet), hub transmet LaForge-Provenance a args._provenance (nokido_hub, derogation), parametre racine de governed_write (aujourd'hui libelle <agent>@worktree), constater sur une vraie |
| `decision_owner_seuils_methodes_20261016` | PARTIEL | P1 | Courir et consigner les lots 2 a 10 de la fenetre (faits bb:discovered_facts/kpi_methode_lot_*), puis trancher avec l'owner : a ce jour 53 % FPY et 15 % RED cites, largement sous les seuils 70 %/90 %. |
| `p1_auto_amelioration_boucle_non_fermee` | PARTIEL | P1 | construire ces modules (ou dater les docs) pour que les dossiers passent RESOLU, porte armee + PARAMS_L1 (owner) pour une 1re experience PROMUE |
| `p1_raffinage_inventaire_2026-10-14` | PARTIEL | P1 | phase 0 sur E: (archive verifiee) puis politique par domaine en observation avec held-out ; purge = decision owner |
| `p1_raffinage_toute_la_base_2026-10-14` | PARTIEL | P1 | phase 0 sur E: (archive verifiee) puis politique par domaine en observation avec held-out ; purge = decision owner |
| `p1_skills_declenchement_au_moment_2026-10-14` | PARTIEL | P1 | derogation outil memory (forge_mcp_registry), --apply des 8 autres jetons, client_configs, sort de forge-core, silos specialises, push + CI (GO owner 19/10 en cours) |
| `roadmap_next_20261013` | PARTIEL | P1 | Retrouver les chemins des exports statiques Claude Desktop et Gemini Web (déplacés/supprimés), miner les consignes owner (forge_intent_miner + forge_intent_verifier) et clore le SSoT sur le corpus com |
| `roadmap_p1_parite_capacites_tous_cli_20261017` | PARTIEL | P1 | sous-agents Vibe INCONNU, mesures --help sur les versions INSTALLEES (profil owner, hors compte du hub) et sondes vivantes par AGY |
| `P2_claude_headless_plafond_mesure_20261022` | OWNER_PLANIFIE | P2 | (non dit) |
| `P2_methode_C_cliquets_hygiene_tests_20261020` | OWNER_PLANIFIE | P2 | (non dit) |
| `roadmap_p2_priorite_hamilton_deux_boucles` | PARTIEL | P2 | poser la couche reflexe Hamilton sur le ByteRouter (pas sur EventStream), flood sur ce canal, puis taus sur mesure ; decision d'architecture a soumettre a l'owner avant tout code |

## Realisables sans l'owner (70)

| Item | Etat | Prio | Reste |
|---|---|---|---|
| `bug_docker_stop_moteur_non_atteint_20261020` | OUVERT | -- | (non dit) |
| `bug_file_accepte_executeur_suspendu_20261020` | PARTIEL | -- | (non dit) |
| `bug_hamilton_oscillation_sleep_wake_20261019` | PARTIEL | -- | (1) prouver que les vecteurs AVANCENT : compter le corpus physiologie vectorise (0/4577 au 20/10) PAR INDEX seulement, EXPLAIN d'abord, a deux instants separes d'au moins un cycle --watch 3600 ; (2) N |
| `bug_skill_curator_quarantaine_faux_crash_20261020` | PARTIEL | -- | (non dit) |
| `constat_demon_gemini_client_mort_actif_20261024` | SANS_MARQUEUR | -- | (non dit) |
| `decision_owner_a_prendre_rejugement_epistemique_20261017` | PARTIEL | -- | rejouer le rejugement qualifie sur des paires de sources DISTINCTES pour une vraie mesure de corroboration |
| `decision_owner_debat_anatomie_A_D_20261015` | PARTIEL | -- | GREEN 931881aea (reaffectation automatique sur NON LIVRE) puis remesure ; relier les refus d'admission et du routeur (id de correlation) avant de les compter |
| `mesure_bancs_gratuits_force_specialite_20261024` | SANS_MARQUEUR | -- | (non dit) |
| `mesure_bancs_proxy_gratuits_20261024` | SANS_MARQUEUR | -- | (non dit) |
| `P0_audit_dist_publique_mesure_20261020` | PARTIEL | P0 | (a) Windows/macOS chiffrement NON_TESTE -> provisionnement CI e7888a61c a publier ; (b) Docker conteneurs VIVANTS + liaison WSL sous Windows ; (c) etape « RAG livre » (couverture par domaine) ; (d) le |
| `P0_jetons_clients_coffre_seul_rfc_20261024` | PARTIEL | P0 | MESURER en sandbox ce que Codex desktop sait lire (bearer_token_env_var seul ? commande/helper ?) AVANT de toucher HKCU, puis retirer FORGE_TOKEN_CODEX de HKCU seulement quand les 2 voies sont prouvee |
| `P0_veille_outils_economie_contexte_20261022` | PARTIEL | P0 | AUCUN GAIN MESURE : rejouer tools/forge_contexte_par_source.py avant/apres P1a (et un filtre de sortie rtk-like) sur une transcription ; non clos. Rapports : sandbox/workspace/rapport_P0_veille_outils |
| `P0_veracrypt_obligatoire_par_defaut_20261020` | PARTIEL | P0 | volume chiffre monte portant data/ ; docs / installateur public ; le bilan (refus_consignes) ne dit pas encore « refus perime » ; effet a la prochaine installation. Rapport : sandbox/workspace/rapport |
| `reprise_session_22_10_matin_pilotage` | OUVERT | P0 | (non dit) |
| `P1_atlas_des_donnees_20261021` | OUVERT | P1 | (non dit) |
| `P1_conformite_mcp_20260728_identite_standard_20261024` | OUVERT | P1 | (non dit) |
| `P1_contexte_p0_mesure_p1a_diete_hooks_20261020` | OUVERT | P1 | (non dit) |
| `P1_cout_tokens_agents_delegues_20261030` | PARTIEL | P1 | reduire le NOMBRE DE TOURS (corps de fonctions precharges dans la consigne), appliquer les reglages documentes par CLI (Gemini CLI model.maxSessionTurns / includeTools a verifier sur agy par sonde), a |
| `P1_depot_long_securise_des_pairs_20261024` | PARTIEL | P1 | verser et securiser le depot long du rapport des pairs (16 Ko) sur alpha |
| `P1_doc_surfaces_ingeree_et_comprise_20261024` | PARTIEL | P1 | APPLIQUER les reglages prouves par CLI avec sonde de cout, fiche « quoi / quand / transposition Nokido » branchee a introspect et aux skills, dedoublonnage advisor-tool (388 morceaux) |
| `P1_enquete_sans_boucle_agent_20261030` | PARTIEL | P1 | modele gratuit FORT disponible (nvidia_nemotron_super 404 a reparer au catalogue, quotas groq/openrouter), puis brancher un mode `enquete` dans l'executeur (taches lecture seule -> cette voie au lieu |
| `P1_identites_distinctes_surfaces_claude_20261022` | PARTIEL | P1 | identite propre par surface Claude Code, boites distinctes, migration lecteurs maitre-seul, RFC 9068 |
| `P1_installeur_cli_gouvernance_propagee_20261024` | OUVERT | P1 | (non dit) |
| `P1_migration_phase_b_primitive_mesure_20261024` | OUVERT | P1 | migrer census, catalogue, juge et essaim vers la primitive Mesure |
| `P1_modulation_effort_modele_par_palier_20261023` | OUVERT | P1 | (non dit) |
| `P1_modulation_effort_modele_par_palier_20261023__decisions` | SANS_MARQUEUR | P1 | (non dit) |
| `P1_moelle_usage_optimal_llm_orchestration_20261024` | SANS_MARQUEUR | P1 | phases B (synthese PAR PAGE) et C (profils consommes) |
| `P1_roadmap_chronologie_20261021` | PARTIEL | P1 | RED 2 08a41dce5 (heritage priorite/echeance = backward pass CPM, aval sans double compte, empreinte fichiers anti-collision, fusions par fichier, Tarjan) -> AGY job_f4359b8c. Tri des propositions Gemi |
| `P1_site_utilisateur_masque_env_certifie_20261021` | OUVERT | P1 | (non dit) |
| `P1_soif_et_auto_amelioration_productives_20261025` | PARTIEL | P1 | 1re PRODUCTION EXPLOITABLE : 0 depuis le 25/10 15 h (0 tache de la soif, 0 SURVIT, 0 REL) -- examen de la soif demande 26/10 ~18 h 30 (--examiner), observe ; puis taux de pertinence (3b0138227) sur le |
| `P1_tous_cli_execution_supervisee_hub_20261024` | PARTIEL | P1 | transposer worktree-de-tache + modele/effort par taille a OpenCode/Codex/Vibe/Claude headless (verifier ACP session/new cwd), tester never en reel sur Vibe, statuer sur Codex/Copilot/Cline et usurpati |
| `P1_utilitarisme_hedoniste_recompense_par_resultat_20261018` | PARTIEL | P1 | tracer le rejet en relecture dans tasks.db ; reevaluer apres 2 semaines (~5/11) |
| `avis_externes_echecs_mesure_convergence_20261024` | OUVERT | P1 | appliquer les remedes convergents aux 16 echecs de mesure (statuts explicites, temoins +/-, OK_DONE != DELIVERED) |
| `bug_homeostat_freine_au_lieu_de_liberer_20261022` | PARTIEL | P1 | OBSERVER apres le prochain redemarrage du hub (spawn_as_sandbox est charge par le hub) : sous pression avec docker_wanted pose, le message du gate doit dire « Docker protege (docker_wanted) ; evince: |
| `decision_owner_partage_travail_agents_20261016` | PARTIEL | P1 | Finir les roadmaps partielles restantes et organiser le partage du travail inter-agents (tâches AGY autonome, paires claude.ai, créneaux courts Codex) selon les enseignements de la veille méthodes de |
| `methodes_adoptees_apres_veille_20261016` | PARTIEL | P1 | cabler les 3 Amigos/ATDD (critere d'acceptation executable avant le code) et la theorie des contraintes (goulot CI ~27 min + hub lent) |
| `p1_digestion_conversations_avancement_2026-10-14` | PARTIEL | P1 | lancer le gel retroactif sur les sessions encore sur disque (requete par PLAGE de source, tours epures ensuite) et lire la mesure par motif de la tache 03:00 (conv_indexer_dernier.json) |
| `p1_l9_rsi_etat_2026-10-15` | PARTIEL | P1 | remesurer le bruit de embed.max_workers (provisoire) |
| `p1_miroirs_publics_systematiques_ci_dist_2026-10-14` | PARTIEL | P1 | Constater un 1er run réussi synchronisant les 4 miroirs publics (Codeberg, GitLab, SourceForge, Hugging Face Spaces) lors de la prochaine publication de version. |
| `p1_toute_la_surface_regulable_2026-10-14` | PARTIEL | P1 | reponse graduee des neverSleep (encore exclus des candidats, forge_resource_manager.py:4034), canal d'acquisition pour run_job, et politique d'armement pilotee par le corps |
| `p1_wiki_sourceforge_quota` | PARTIEL | P1 | a partir du ~20/10 (quota Allura de 50 operations epuise) : creations 22-24-fr, 20 reecritures EN (liens (X.fr)->(X-fr)) et les 4 pages modifiees par 0.20.12 (06-Hub-API-Reference, 20-Modules-Referenc |
| `roadmap_p1_ci_github_apres_0212_20261015` | PARTIEL | P1 | la partie fiabilite de l'ancien reste (menage-preuves sparse, relance de stack) |
| `roadmap_p1_methode_dev_par_couches_20261016` | PARTIEL | P1 | GREEN, branchement sur le retriever REEL (nomme), mesure temoin, 3 mesures espacees de 24 h, NR des instruments couche 2 |
| `roadmap_p1_orchestration_par_nokido_20261017` | PARTIEL | P1 | consignes avec lignes exactes, decoupage en taches < 25 min (2 GREEN et 1 lot ont echoue sur la borne) et routage par fiabilite mesuree (bb:discovered_facts/mesure_fiabilite_executeurs_verif_roadmaps_ |
| `roadmap_p1_quatre_correctifs_prets_apres_ci_20261017` | PARTIEL | P1 | brancher la regle d'or validate_payload(agentique=True) (app/core/payload_validator.py:58, aucun appelant agentique=True) en OBSERVER sur les VRAIS emetteurs agentiques -- forge_handoff (_llm_round), |
| `roadmap_p1_registre_demandes_owner_20261017` | PARTIEL | P1 | ranger chaque [A FAIRE |
| `roadmap_p1_retenu_du_collage_hassabis_lean_20261017` | PARTIEL | P1 | REPL Lean persistant (lean4-repl absent), garde d'émission sur les payloads d'agent (orchestrate, exécuteurs, A2A) en mode observer, seuil de signification fixé avant dans forge_darwinian_arena.evalua |
| `roadmap_p1_voie_longue_embedding_20261008` | PARTIEL | P1 | etape 2 (revectorisation 2048 a la demande quand la RAM le permet) |
| `P2_benchmark_nokido_vs_claude_md_statique_20261026` | OUVERT | P2 | protocole puis mesure : memes taches cross-CLI avec (A) Nokido hub + SSoT et (B) un simple CLAUDE.md / AGENTS.md statique ; metriques tokens, erreurs, rappels de regles, temps ; jeu tenu a part |
| `P2_construire_event_mesh_accelerator_voice_20261019` | PARTIEL | P2 | (non dit) |
| `P2_distribution_winget_npm_20261021` | OUVERT | P2 | (non dit) |
| `P2_docker_macos_runner_mesure_20261020` | PARTIEL | P2 | (non dit) |
| `P2_paliers_internes_cli_veille_20261017` | PARTIEL | P2 | Implémenter d'abord le routage par difficulté entre exécuteurs distincts (P1_routage_executeur_par_difficulte_20261017) avant d'instancier des sous-paliers propres à chaque CLI. |
| `P2_pilote_routage_appris_sur_issue_reelle_20261026` | PARTIEL | P2 | (3) baseline scores_hedonistes_mesure evaluee sur holdout TEMPOREL 15 % ; (4) contexte plus fin que taille x mode seulement si (3) le justifie ; exploiter les REAFFECTATIONS (seules paires contrefactu |
| `P2_rag_fts_optimize_mesure_20261021` | OUVERT | P2 | (non dit) |
| `P2_reparer_modele_nvidia_nemotron_super_20261030` | OUVERT | P2 | remplacer au routeur (app/forge_llm_router.py, entree nvidia_nemotron_super, models nvidia/nemotron-3-super-120b-a12b) l'identifiant retire chez NVIDIA (404 « Function ... Not Found ») par un modele L |
| `P2_rsi_elargissement3_candidats_l1_20261018` | PARTIEL | P2 | construire un instrument par reglage avant toute declaration L1 |
| `P2_snn_mesures_20261021` | PARTIEL | P2 | banc forge_snn_router vs regle simple sur les routages REELS avec jeu tenu a part ; unification surrogate ; attribution du docstring (Neftci 2019 / SpikingJelly) a sourcer. |
| `P2_supersession_rag_dette_60j_20261024` | OUVERT | P2 | purger ou archiver les chunks perimes de plus de 60 jours |
| `P2_taux_autonomie_locale_instrument_20261021` | OUVERT | P2 | (non dit) |
| `lora_signal_usage_cause_2026-10-02` | PARTIEL | P2 | palier 2 (noter() dans _rag_bm25_search + [chunk:id |
| `p2_agy_autonome_repond_par_groq_et_relais_hors_sujet_2026-10-14` | PARTIEL | P2 | Filtrer le sujet dans pat_m2m_debate_relay et éliminer le double consommateur concurrent sur la boîte ANTIGRAVITY (session interactive acquittant sans claim) ; régler l'invite UAC (--sandbox) selon dé |
| `p2_turbo_worker_mort_sans_trace_2026-10-14` | PARTIEL | P2 | temoin positif d'armement (ligne de session ecrite a l'armement) puis attendre une mort de worker reelle -- silence != resolu |
| `roadmap_p2_benchmarks_harness_lift_20261016` | PARTIEL | P2 | identifier le sous-ensemble SCB v2, faisabilite GPU de 2 taches TB, lancer la campagne gratuite |
| `roadmap_p2_convergence_census_matrice_20261015` | PARTIEL | P2 | re-mesurer matrice ET profiling (reseau, leger, hors CI), puis faire consommer le DEBIT (tok/s, seul apport propre du profiling) |
| `roadmap_p2_convergence_sondes_plan_20261015` | PARTIEL | P2 | Faire converger forge_provider_catalogue, forge_tool_call_probe et forge_free_tier_census vers forge_endpoint_commun (lire/catalogue), poser le cliquet interdisant l'appel direct à urllib.request.urlo |
| `roadmap_p2_hamilton_suite_mesuree_20261013` | PARTIEL | P2 | Implémenter la porte temporelle composable (fiche V9) pour l'admission réutilisant le second observateur RAM, formaliser les tables de reprise par phases (fiche V8), valider le repli LLM sur un cycle |
| `roadmap_p2_lora_retrieval_2026-09-27` | PARTIEL | P2 | accumuler le signal ( effet au redemarrage du hub), cabler la verite terrain (citations), puis reranker, embedder cote requete et routeur dans l'ordre recommande |
| `roadmap_p2_sources_de_rel_hors_ci_20261026` | OUVERT | P2 | mesurer d'abord le debit des REL de la CI baseline (d810283fd) avant d'ajouter des sources |

## Clos (189)

- **--** (25) : `a_reveiller_deportembed`, `audit_base_env_470_2026-09-20`, `bug_capteur_oauth_cli_faux_negatif_gh_20261020`, `ci_github_pytest_pur_cause_reelle_2026-09-20`, `current_2026-10-14_midi`, `current_2026-10-14_nuit`, `current_2026-10-14_soir`, `current_jalon_2026-10-02`, `decision_compaction_contexte_api_seulement_20261022`, `decision_owner_codex_autonome_apres_0212_20261015`, `delegate_agy_sans_garde_accuse_2026-09-20`, `dette_D_sans_capteur_2026-09-20`, `enquete_plafond_claude_headless_20261024`, `mesure_ab_local_opencode_20261017`, `mesure_bruit_conv_claude_2026-10-14`, `mesure_repartition_executeurs_par_classe_20261017`, `moisson_veille_relance_accord_owner_2026-09-24`, `roadmap_current_20261008`, `roadmap_current_20261013`, `roadmap_current_20261015`, `roadmap_current_publication_0208`, `roadmap_current_publication_0209`, `roadmap_current_push_9d11208bd_20261015`, `roadmap_installation_complete_noob`, `secu_secrets_cloud_lus_dans_env_37_fichiers_geles_20261016`
- **P0** (17) : `P0_audit_gemini_auto_amelioration_20261018`, `P0_chasse_lectures_massives_20261021`, `P0_chasse_lectures_massives_portee_20261021`, `P0_chasse_lectures_massives_suite_sante_20261021`, `P0_dist_macos_absent_du_manifeste_20261020`, `P0_pack_connaissances_par_source_20261020`, `P0_primitive_mesure_phase_a2_20261024`, `P0_regression_desc_19_nr_rouges_20261024`, `P0_security_md_frontiere_outils_natifs_20261026`, `circadien_tire_dans_le_vide`, `epistemic_soif_victime_verrou_rag_2026-09-20`, `p0_lancement_paquet_pypi_2026-10-13`, `p0_paquet_linux_macos_trousseau_2026-10-14`, `p0_soif_epistemique_morte_depuis_0830`, `revue_t2_opencode_refusee_20261017`, `roadmap_blocker_historique_public`, `roadmap_p0_deport_ch88_fait_2026_09_15`
- **P2** (43) : `P2_bail_non_journalise_au_hub_20261020`, `P2_db_backup_controle_fts_muet_20261021`, `P2_disque_coagulation_vital_30mos_20261020`, `P2_doubles_sys_modules_dependants_ordre_20261020`, `P2_dspy_cache_disque_mitigation_prouvee_20261021`, `P2_ecarts_doc_code_a_construire_20261018`, `P2_etude_managed_agents_relancee_20261024`, `P2_federation_github_claude_20261022`, `P2_feuilles_de_route_gemini_evaluees_20261021`, `P2_guetteur_lit_progres_et_pouls_20261017`, `P2_mammouth_absence_budget_gestion_20261024`, `P2_methode_D_nettoyer_worktrees_perimes_20261020`, `P2_ollama_cloud_absence_cle_gestion_20261024`, `P2_snn_aer_candidature_neuromorphique_a_mesurer_20261021`, `P2_veille_pypi_resume_trop_court_20261018`, `bug_double_none_rend_none_au_lieu_d_importerror_20261022`, `bug_executeur_tache_orpheline_running_apres_relance_20261022`, `bug_fast_test_runner_interpreteur_profil_sbx_20261022`, `bug_juge_failure_avec_livraison_20261022`, `bug_reaffectation_absente_sur_echec_auth_20261020`, `bug_reaffectation_ignore_la_charge_des_files_20261022`, `bug_skill_curator_pidfile_pid_recycle_20261022`, `bug_surcharge_fournisseur_non_reaffectee_20261022`, `bug_tdd_red_non_observe_executeur_20261024`, `bug_veille_candidats_cles_non_ingeres_20261024`, `executif_a_priorites_hamilton_20261016`, `p2_bail_priorite_403_depuis_un_job_2026-10-14`, `p2_capacite_fournisseur_observee_0925`, `p2_commwatch_spawn_interactif_session0_2026-10-14`, `p2_ctl_wake_404_20261018`, `p2_macos_jeton_court_lanceur_intermittent_2026-10-14`, `p2_precontrole_temoin_pip_audit_non_versionne_2026-10-14`, `p2_rescue_auto_notification_par_tour_2026-10-14`, `p2_tests_organisme_vivant_et_subprocess_sans_timeout_2026-10-14`, `p2_veille_clone_garde_disque_timeout_2026-10-14`, `p2_veille_jobs_jamais_clos_2026-10-13`, `roadmap_p2_alias_flash_lite_20261015`, `roadmap_p2_canary_runner_bancs_20261026`, `roadmap_p2_crawl4ai_restart_always_20261015`, `roadmap_p2_gemini_model_deux_verites_20261015`, `roadmap_p2_noeud_running_orphelin_20261015`, `roadmap_p2_purgeurs_web_hub_tests_20261015`, `veille_watch_alerts_gate_denied_2026-09-24`

