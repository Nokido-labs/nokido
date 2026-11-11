# Campagne d'intégration — réconciliation des lots 5 et 6 (9/11)

**Décision owner 9/11 (choix multiple)** : « trier : sécurité avant, reste après ». Les travaux hors alpha jugés
INTEGRER par le tri délégué (lots 6 01 à 06, preuves vérifiées par `C:\tmp\corrections\lot6_verifier_tri_20261109.py`)
sont TRANCHÉS ainsi :

- **SÉCURITÉ / CORRECTION** : intégrés AVANT la release, en délégué, chacun relu par Claude (NR verts sur alpha).
- **CAMPAGNE** : intégration APRÈS la release. Chaque branche porte le tag annoté `archive/lot6/<branche>`
  « INTEGRER confirmé, campagne post-release » ; branche conservée.
- **Déjà traités par Claude le 9/11** : `tache/opencode_gptoss/654f8898eb47` intégré (5a2f929e9) ;
  `preserve/opencode_defaut4-20261031-140422` NR intégré (03c2db0c1), cache introspect refusé ;
  `tache/opencode_gptoss/9f8a8e8025d6` remplacé par 264434d00 ; `82a63fd0b0de` et `fafe9c80a8e7` défectueux (archivés) ;
  `preserve/mistral-20261019-003551` : volet mint intégré (5322b3372), volet env ACP en campagne.

Reclassements de Claude : `tache/antigravity/ffe82e48cac2` (noms lisibles) passe en CAMPAGNE (affichage, pas
sécurité). Doublons : `preserve/claude_headless-20261027-124619` = `preserve/claude_headless/wip`. Thèmes communs :
prompt_guard « developer mode » (`opencode_defaut2-20261106-233323` + `edf422c5c90d`) ; détresse NON_SOI
(`ce2c7bb5ff6a` + `0f5ed0c44f2a` + test de `opencode_defaut2-20261106-233323`).

| classe | lot | branche | fichiers | raison du délégué |
|---|---|---|---|---|
| SECURITE | 01 | `agent/antigravity` | app/forge_provider_admin.py, app/web_hub/provider_views.py, tests/nr/test_llm_dashboard_acces_ssh_nr.py | Autorisation ring 2 WEBHUB sur api_list_access et repli gracieux manquants dans alpha. |
| SECURITE | 01 | `preserve/antigravity-20261024-153400` | docs/essais/…, tools/forge_pair_depot_long.py | Scanner enrichi de secrets et liaison au pare-feu sémantique absents de tools/forge_pair_depot_long.py. |
| SECURITE | 02 | `preserve/claude_headless-20261027-124619` (= `preserve/claude_headless/wip`) | .claude_headless_mcp.json, agy_profil_executeur_20261107.md | Test NR test_agy_profil_executeur_distinct_nr.py manquant pour valider l'isolation LAFORGE_AGY_HOME. |
| SECURITE | 02 | `preserve/opencode_defaut2-20261106-233323` | app/forge_prompt_guard.py, tests/nr/test_hamilton_detresse_non_soi_nr.py | Règle squash developer mode absente de app/forge_prompt_guard.py:354. |
| SECURITE | 04 | `tache/antigravity/edf422c5c90d` | app/forge_prompt_guard.py, tests/nr/test_prompt_guard_mode_developpeur_nr.py | Resserrement motif developer mode anti faux-positifs et test NR absents d'alpha. |
| SECURITE | 05 | `tache/mistral/7d91319b79c7` | tools/nokido_hub.py | get_secret pour ROOT/HOST/PORT absent de nokido_hub.py (à lire). |
| SECURITE | 05 | `tache/opencode_glm/1d858135c9b6` | tests/nr/test_ingress_auth_tools_nr.py, tools/ci_local.py | Code ingress auth/tools présent, test NR référencé absent d'alpha. |
| SECURITE | 05 | `tache/opencode_glm/2292487d3545` | app/test_cloisonnement.py, simple_test.py | Tests cloisonnement postal absents (à lire). |
| CORRECTION | 06 | `tache/opencode_glm/ce2c7bb5ff6a` | app/forge_resource_manager.py, tests/nr/test_hamilton_detresse_non_soi_nr.py | Retour `delester_auxiliaires` en détresse NON_SOI absent. |
| CORRECTION | 06 | `tache/opencode_glm/fff65ac2f107` | tools/forge_golden_rappel.py | FileLock et paramètre no_rag_scan absents de golden_rappel. |
| CORRECTION | 06 | `tache/opencode_gptoss/0f5ed0c44f2a` | app/forge_resource_manager.py, tests/nr/test_hamilton_detresse_non_soi_nr.py | Détresse NON_SOI → delester_auxiliaires absente de Hamilton RAM. |
| CORRECTION | 06 | `tache/opencode_gptoss/c7c4d14308f7` | tools/forge_coagulation.py, tests/nr/test_embolie_absence_soignee_nr.py | Routage embolie absence seule → soin absent de coagulation. |
| CAMPAGNE | 02 | `preserve/claude_headless-20261027-010048` | app/forge_resource_manager.py, tests/nr/test_hamilton_reflexe_nr.py | seuils_reflexe absente. |
| CAMPAGNE | 02 | `preserve/claude_headless-20261027-013102` | app/forge_byte_router.py, app/forge_hamilton_reflexe.py | Hook d'observation réflexe absent. |
| CAMPAGNE | 02 | `preserve/claude_headless-20261027-020117` | app/forge_byte_router.py, app/forge_reflexe.py | Hook d'observation réflexe absent. |
| CAMPAGNE | 02 | `preserve/claude_headless-20261027-024648` | tools/forge_mutation_ratchet.py, app/forge_coagulation_cascade.py | mesurer_hygiene absente (gros diff). |
| CAMPAGNE | 02 | `preserve/mistral-20261019-003551` (volet env ACP) | tools/forge_acp_client.py, tests/nr/test_acp_opencode_instance_nr.py | Propagation d'env ACP. |
| CAMPAGNE | 03 | `preserve/opencode_glm-20261019-230953` | app/forge_organ_agents.py, tests/nr/test_organ_registre_nr.py | Câblage forge_quality_gate absent de forge_tool_forger. |
| CAMPAGNE | 03 | `preserve/opencode_glm-20261022-214908` | tests/_doubles.py, tests/nr/test_armement_cle_unique_nr.py | Utilitaire poser_double (doubles sous xdist). |
| CAMPAGNE | 03 | `preserve/opencode_glm-20261025-014129` | app/forge_health_diagnostic.py, tests/nr/test_audit_agy_sessions_nr.py | audit_agy_sessions absente. |
| CAMPAGNE | 03 | `preserve/opencode_glm-20261103-214024` | tools/forge_docker_keeper.py | Persistance atomique de l'état réfractaire Docker. |
| CAMPAGNE | 03 | `preserve/opencode_gptoss-20261019-200808` | tests/nr/test_V1_confiance_etat_nomme_nr.py | NR chute du gate sur trace morte. |
| CAMPAGNE | 03 | `preserve/opencode_gptoss-20261024-185954` | app/forge_chain_executor.py, tests/nr/test_watch_concurrency.py | Concurrence d'un seul job watch. |
| CAMPAGNE | 03/06 | `tache/opencode_gptoss/0a39357e6231` | app/forge_mcp_registry.py | Journal ombre contrat_absent_ombre (CRITICAL_FILE, priorité basse). |
| CAMPAGNE | 04 | `preserve/opencode_nemotron-20261019-140108` | app/forge_tool_forger.py | Porte qualité et boucle de régénération. |
| CAMPAGNE | 04 | `tache/antigravity/1e5e14df33e4` / `ce28e35f523f` | tools/forge_tir_pytest.py, tests/nr/test_tir_pytest_nr.py | forge_tir_pytest (tir pytest unique). |
| CAMPAGNE | 04 | `tache/antigravity/58a472653012` | app/forge_mcp_registry.py, services.toml | Alias VIBE → MISTRAL, exécuteur Cline. |
| CAMPAGNE | 04 | `tache/antigravity/770ce93e95c0` | app/mcp_agent_template/… | Registre déclaratif des agents métier. |
| CAMPAGNE | 04 | `tache/antigravity/891e2ec8b2f5` | tools/forge_docker_keeper.py | forge_memoire_processus + purge EmptyWorkingSet qdrant. |
| CAMPAGNE | 04 | `tache/antigravity/8f307b67366c` / `bf3f3bf7732f` / `d1eb7d6e3da2` | app/forge_mcp_registry.py, tests/nr/test_whoami_trois_etats_nr.py | whoami trois états (eval agents/providers). |
| CAMPAGNE | 04 | `tache/antigravity/aea7d47f4b86` | forge_capability_audit.py | _hors_acp, _nb_phases_sommeil. |
| CAMPAGNE | 04 | `tache/antigravity/bb5953e82cbf` | app/forge_whoami_etats.py | horodatage epoch/ISO robuste. |
| CAMPAGNE | 04 | `tache/antigravity/ffe82e48cac2` | tests/nr/test_nom_lisible_agent_nr.py | forge_nom_lisible (reclassé). |
| CAMPAGNE | 06 | `tache/opencode_gptoss/61461f7823ef` | config/agy_derogation_modele.json | Dérogation modèle AGY par tâche. |
| CAMPAGNE | 06 | `tache/opencode_gptoss/c71b4371526f` | tools/forge_task_executor.py | _fournisseur_de_surface (garde : prouver d'abord QUI marque le fournisseur). |
| CAMPAGNE | 05 | `tache/claude_headless/2ab83967beac` | tools/ci_local.py | Entrée CI du NR profil AGY distinct. |
| CAMPAGNE | 05 | `tache/claude_headless/ace5588531f1` | docs/rapports/roadmap_verif_lot99_20261107.json | Livrables lot99. |
| CAMPAGNE | 05 | `tache/claude_headless/f8f4ad221f13` | tools/forge_task_executor.py, tests/nr/test_capacite_par_fournisseur_nr.py | _repli_vers_fournisseur_epuise. |
| CAMPAGNE | 05 | `tache/mistral/2fbbb3b8775f` · `tache/opencode_defaut2/ad5b6338d05b` · `tache/opencode_defaut3/b8b84e230b71` · `tache/opencode_defaut5/312eb99929b3` | tests/nr/test_*_pool_borne_nr.py | NR pools bornés (source_discovery, mermaid_gen, orchestrator, evolutionary_engine). |
| CAMPAGNE | 05 | `tache/mistral/916176b34988` | app/forge_mcp_registry.py | Avertissement enveloppe M2M forge_postal indisponible. |
| CAMPAGNE | 05 | `tache/opencode_defaut2/f9f43fc95587` | tools/forge_free_tier_census.py | Épuisement free tier journalisé. |
| CAMPAGNE | 05 | `tache/opencode_glm/8c59850bfc8f` | app/forge_mcp_registry.py, services.test.toml | root_dir/_cache. |
