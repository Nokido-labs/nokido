"""tools/ci_local.py — miroir LOCAL COMPLET des GitHub Actions.

Rejoue en local TOUS les gates des workflows .github/workflows/* pour ne pas
pousser à l'aveugle. Les workflows GitHub-hosted (ci, eco-shield, gitleaks) sont
en workflow_dispatch (quota payant) ; le CI auto = ci-selfhosted.yml (runner
local gratuit) qui lance CE script. Best-effort : outil/fichier absent = SKIP.

Miroir des jobs :
  ci.yml         : lint (flake8 crit BLOQUANT + style WARN), unit-tests (pytest pur
                   BLOQUANT), secrets-scan (gitleaks), license-scan
                   (forge_license_guard BLOQUANT), archi-lint (forge_archi_lint WARN).
  eco-shield.yml : fast-audit (ruff crit BLOQUANT + style + bandit), ast-bunker (BLOQUANT).
  gitleaks.yml   : gitleaks delta (WARN).
  docker-publish : docker build (WARN, --docker).
  release.yml    : uv build + twine check (WARN, --release-build).
  ci-selfhosted  : integration (--integration WARN), build-dist (--build-dist WARN).
  cla.yml        : bot CLA — N/A local.

Usage :
    LAFORGE_PYTHON tools/ci_local.py              # tous les gates always-on
    LAFORGE_PYTHON tools/ci_local.py --fast       # flake8+ruff critique seuls
    LAFORGE_PYTHON tools/ci_local.py --no-tests   # saute pytest
    LAFORGE_PYTHON tools/ci_local.py --integration --build-dist --docker --release-build
    LAFORGE_PYTHON tools/ci_local.py --all        # tout (opt-in inclus)

Exit code = 1 si un gate BLOQUANT échoue. WARN n'échoue jamais le run (comme en CI).

Câblage pre-push (optionnel) :
    # dans .githooks/pre-push :  LAFORGE_PYTHON tools/ci_local.py --fast
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from shutil import which

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Windows (runner GHA) = stdout cp1252 -> box/emoji/ANSI crash print(). Force UTF-8.
# JAMAIS sous pytest : `sys.stdout` y est le flux de CAPTURE, et le reconfigurer le
# referme pour les tests SUIVANTS du meme worker xdist (mesure 2026-09-04 :
# « ValueError: I/O operation on closed file » au setup de tests parfaitement sains).
# Le `try/except` ne protege pas de ce cas -- l'appel REUSSIT, c'est son effet qui
# casse. En sequentiel la CI passe `--capture=no` : il n'y a pas de capture a casser,
# donc le defaut n'apparait qu'en parallele.
if "pytest" not in sys.modules:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # muet-ok : flux non reconfigurable (pipe, redirection)
            # Journaliser ici exigerait le flux qu'on vient d'echouer a preparer.
            pass

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
EXCLUDE = "Nokido.py,legacy,_attic,sandbox,inspirations,_mcp_repos,tmp_*.py"

# Whitelist pytest "pure" (zero service externe).
#
# CETTE LISTE EST LA SOURCE DE VERITE de la CI qui tourne. Le CI auto sur push est
# .github/workflows/ci-selfhosted.yml, qui appelle CE fichier ; ci.yml (GitHub-hosted)
# est passe en workflow_dispatch — fallback MANUEL, pour ne pas cramer le quota.
#
# Le commentaire disait « miroir exact de ci.yml job unit-tests ». Ce n'est plus vrai
# depuis le 20/08 : ci.yml cite 17 fichiers et ignore les quatre ajoutes ce jour-la.
# L'ecart est sans effet tant que ci.yml reste manuel, mais la phrase, elle, envoyait
# chercher la liste au mauvais endroit. Un commentaire perime coute une enquete.
PURE_TESTS = [
    # Verse le 2026-09-20 EN MEME TEMPS que le test : un NR commite mais non
    # declare ici ne tourne dans AUCUNE des deux CI (defaut paye le 19/09). Il
    # est pur : quatre racines de skills factices sous `tmp_path`, aucun service.
    "tests/nr/test_context_budget_portee_skills_nr.py",
    # Verses le 2026-09-20, et c'est `test_suite_pure_ratchet_nr` qui les a
    # reclames : les trois avaient ete commites sans etre declares ici. Le meme
    # defaut que celui corrige le matin meme, pris par l'autre bout — la preuve
    # que le cliquet mord, y compris sur celui qui venait de le citer.
    #
    # Purs, tous les trois : ils substituent le point d'injection (`_lire_racine`,
    # `_jeton_github`) ou rechargent un module sous un environnement modifie.
    # Aucun service, aucun reseau, aucun secret.
    "tests/nr/test_agent_proxy_timeout_reglable_nr.py",
    "tests/nr/test_budget_skills_reproductible_nr.py",
    "tests/nr/test_pip_audit_nomme_son_interpreteur_nr.py",
    # Verse le 2026-09-20 avec son correctif : health_check consultait la
    # politique nulle part, et 92 % du ledger d'evolution etait un faux positif
    # DISABLED_BY_POLICY. Pur : un services.toml fixture sous `tmp_path`, le
    # socket monkeypatche, aucun service externe.
    "tests/nr/test_health_check_politique_avant_panne_nr.py",
    # Verses le 2026-09-17 apres que `test_suite_pure_ratchet_nr` a mordu sur
    # MOI : `test_trace_sidecar_import_inerte_nr.py` avait ete cree sans etre
    # inscrit ici, donc il ne tournait dans AUCUNE CI et ne protegeait rien.
    # Les trois respectent « zero service externe » : AST, fichiers, fixtures.
    "tests/nr/test_trace_sidecar_import_inerte_nr.py",
    "tests/nr/test_wiki_origine_et_peremption_nr.py",
    "tests/nr/test_wiki_modules_bilingue_nr.py",
    "tests/nr/test_licences_embarquees_nr.py",
    "tests/nr/test_license_guard_declarees_nr.py",
    "tests/nr/test_db_sanitize_verdict_nr.py",
    "tests/nr/test_mcp_http_identite_nr.py",
    "tests/nr/test_docstrings_trois_lecteurs_nr.py",
    "tests/nr/test_handlers_loop_merge_checkpoint_nr.py",
    "tests/nr/test_docstring_ratchet_nr.py",
    "tests/nr/test_circadien_producteur_pip_audit_nr.py",
    "tests/nr/test_ui_widgets_repli_immediat_nr.py",
    "tests/nr/test_docs_chemins_morts_nr.py",
    "tests/nr/test_docs_datation_nr.py",
    # Verses le 2026-09-17, DEUXIEME morsure du meme cliquet le meme jour : les
    # NR de la campagne transient (GEN-1..GEN-6) etaient VERSIONNES mais hors
    # suite pure, donc ils ne tournaient dans AUCUNE CI et ne protegeaient rien.
    # Purete VERIFIEE AVANT inscription, poste par poste : `subprocess` et
    # `urllib` n'y apparaissent que comme espions `monkeypatch` qui COUPENT la
    # sortie (`lambda *a, **k: ... or None`), jamais comme appels ; gen3 et
    # test_gate_forme_m2m n'en portent aucun.
    # RESERVE NOMMEE sur gen6 : son espion RELAIE vers la vraie `urlopen` pour
    # les adresses locales. Le relais n'est jamais atteint (`etat_llm_local` y
    # est patche a `port_ouvert: False`, le chemin coupe en amont) et le test
    # passe, mais il n'est pas pur PAR CONSTRUCTION comme les six autres. Ecrit
    # ici plutot que corrige a chaud : on ne modifie pas une preuve pour un
    # risque non realise -- si la CI mord la-dessus, la cause est deja nommee.
    "tests/nr/test_gate_forme_m2m_et_cles_nr.py",
    "tests/nr/test_transient_gen1_observation_nr.py",
    "tests/nr/test_transient_gen2_cablage_nr.py",
    "tests/nr/test_transient_gen3_admission_nr.py",
    "tests/nr/test_transient_gen4_execution_nr.py",
    "tests/nr/test_transient_gen5_seconde_capacite_nr.py",
    "tests/nr/test_transient_gen6_llm_local_nr.py",
    # Contrat de vitalite des tuiles : PAS MESURE -> unknown, JAMAIS live.
    # Pur : charge `dashboard_html` par son FICHIER (pas le portail), et toute
    # sonde reelle est monkeypatchee. Les 7 formes de cible non sondable ne
    # touchent jamais le reseau -- elles sortent avant.
    "tests/nr/test_probe_service_trois_etats_nr.py",
    "tests/nr/test_webhub_veilleur_de_gel_nr.py",
    "tests/nr/test_webhub_logging_non_bloquant_nr.py",
    # Audit securite du 2026-09-18, finding #6 : la provenance de faible confiance
    # (veille web) doit survivre jusqu'au prompt SYSTEME, sinon une page crawlee
    # entre au niveau d'autorite maximal sans rien qui la distingue d'une consigne.
    "tests/nr/test_provenance_veille_dans_prompt_nr.py",
    # Meme jour : quatre livrables de tache faisaient EXACTEMENT 8000 caracteres.
    # Une borne qui ne dit pas combien elle jette fabrique des resultats faux.
    "tests/nr/test_borne_qui_se_nomme_nr.py",
    # Meme audit, finding #11 : le texte de resultat d'une tache declenchait
    # `pip install` dans l'environnement du hub, sans allowlist.
    "tests/nr/test_dep_manager_allowlist_nr.py",
    # Mort du hub le 2026-09-18 a 18:25:17 (WEDGE KILL, boucle gelee 60 s) : un
    # `print(flush=True)` de decoration TUI dans forge_byte_router:133, sur un
    # stdout draine avec 7 min de retard. Meme cause que le gel du webhub.
    "tests/nr/test_sortie_console_non_bloquante_nr.py",
    # 2026-09-18 : 23 decisions de tri ecrites au registre et restees INERTES,
    # parce que sa consultation etait gardee par `verdict == "open"` seule.
    "tests/nr/test_registre_instruction_portee_nr.py",
    # 2026-09-18 : la file de taches ecrivait dans la base RAG de 25 Go — meme
    # fichier physique (`V:` = lecteur substitue), donc meme verrou d'ecriture.
    "tests/nr/test_task_queue_db_isolee_nr.py",
    # 2026-09-18 : l'organe sensoriel doit PROUVER sa lecture seule, pas la
    # declarer dans un dictionnaire. Relecture AST + execution du contrat.
    "tests/nr/test_runtime_observer_lecture_seule_nr.py",
    # 2026-09-18 : la portee du pont est verifiee A LA PORTE, pas par outil.
    # Sain tant qu'il n'y en a qu'une ; une seconde ouvrirait les outils de l'une
    # a un jeton de l'autre. Fil de detente, pas veto.
    "tests/nr/test_pont_portee_par_outil_nr.py",
    # Exige par le cliquet de couverture : un rapport, c'est son CONTENU.
    # Verifie l'EFFET -- voit-il un alias ? -- pas l'import.
    "tests/nr/test_db_contention_report_nr.py",
    # Audit securite 2026-09-18, findings #1 et #3. `forge_docker_agent.decide`
    # est cite par 7 modules et n'avait AUCUN test : le premier a trouve trois
    # defauts preexistants, dont un qui rendait toute detection de bind-mount
    # Windows inoperante.
    "tests/nr/test_audit_findings_1_et_3_nr.py",
    # Audit securite 2026-09-18, finding #9 : la branche `task.review` du garde
    # de separation n'avait aucun appelant parce que la revue ne portait AUCUNE
    # identite. Le NR verifie que le garde REFUSE, pas qu'il existe.
    "tests/nr/test_revue_identite_et_separation_nr.py",
    # Audit securite 2026-09-18, finding #10 : le dispatcher Go etait le SEUL
    # service a ecouter hors de la boucle locale, par un hote OMIS.
    "tests/nr/test_dispatcher_go_boucle_locale_nr.py",
    "tests/nr/test_events_publish_autorite_resolue_nr.py",
    "tests/nr/test_secret_guard_ecriture_table_sensible_nr.py",
    "tests/nr/test_refus_du_modele_pas_un_travail_fait_nr.py",
    "tests/nr/test_cookie_session_exposition_declaree_nr.py",
    "tests/nr/test_webhub_porte_son_propre_credential_nr.py",
    "tests/nr/test_audience_jeton_webhub_nr.py",
    "tests/nr/test_ui_serve_confinement_racine_nr.py",
    "tests/nr/test_fail_closed_sur_le_privilege_nr.py",
    "tests/nr/test_actions_ci_epinglees_nr.py",
    "tests/nr/test_memoire_enquete_partagee_nr.py",
    "tests/nr/test_sentinel_alias_bypass_nr.py",
    "tests/nr/test_pont_runtime_read_nr.py",
    "tests/nr/test_capacite_livree_est_declaree_nr.py",
    "tests/nr/test_prerequis_surface_complete_nr.py",
    # Declares le 2026-09-19. `test_appui_forge_dev_mode_nr` existait depuis le
    # matin SANS etre declare ici : il ne tournait donc NI en CI locale NI en CI
    # GitHub, et les deux gardes dev-mode qu'il protege etaient a nu.
    "tests/nr/test_appui_forge_dev_mode_nr.py",
    "tests/nr/test_hook_integrity_doublon_nr.py",
    "tests/nr/test_deport_regles_sans_perte_nr.py",
    "tests/nr/test_hub_memory_probe_trois_etats_nr.py",
    "tests/nr/test_dist_publish_orphelin_et_verdict_nr.py",
    "tests/nr/test_journaux_hors_verrou_rag_nr.py",
    "tests/nr/test_journaux_ecrivains_migres_nr.py",
    "tests/nr/test_ci_selection_partielle_nr.py",
    "tests/nr/test_gate_impossibilite_mesuree_nr.py",
    "tests/nr/test_bump_superrepo_ordre_nr.py",
    "tests/nr/test_ci_proof_manifeste_nr.py",
    "tests/nr/test_ci_proof_cable_nr.py",
    "tests/nr/test_ci_proof_reachability_nr.py",
    "tests/nr/test_ci_lock_reconciliation_nr.py",
    "tests/nr/test_runtime_smoke_etats_nr.py",
    # Campagne securite + memoire du 2026-09-19. Declares ICI parce qu'un NR
    # hors PURE_TESTS ne tourne pas en CI : il ne protege donc AUCUNE surface,
    # et le cliquet `test_suite_pure_ratchet_nr` a eu raison de le refuser.
    "tests/nr/test_redaction_reponses_erreur_nr.py",
    "tests/nr/test_exec_dynamique_orphelins_nr.py",
    "tests/nr/test_log_redact_porteur_nr.py",
    "tests/nr/test_facade_web_service_gelee_nr.py",
    "tests/nr/test_ssrf_backends_crawl_nr.py",
    "tests/nr/test_deserialisation_gouvernee_nr.py",
    "tests/nr/test_registre_audit_tenu_nr.py",
    "tests/nr/test_ui_campaign_preflight_borne_nr.py",
    "tests/nr/test_precompact_herite_de_l_etat_nr.py",
    "tests/nr/test_continuite_inter_compactions_nr.py",
    "tests/nr/test_outils_publication_effet_nr.py",
    "tests/nr/test_ui_campaign_classes_boutons_nr.py",
    "tests/nr/test_rbac_creation_entite_nr.py",
    "tests/nr/test_provider_admin_ring_nr.py",
    "tests/nr/test_provider_views_auth_nr.py",
    "tests/nr/test_proxy_delie_ressources_tierces_nr.py",
    "tests/nr/test_anatomy_contrat_et_faux_zero_nr.py",
    "tests/nr/test_services_declares_au_boot_nr.py",
    "tests/nr/test_pouls_service_http_nr.py",
    "tests/nr/test_ui_hub_rebuild_garde_nr.py",
    "tests/nr/test_services_ondemand_nr.py",
    "tests/nr/test_providers_fusion_rubriques_nr.py",
    "tests/nr/test_souverainete_reelle_nr.py",
    "tests/nr/test_vues_hub_etats_null_gardes_nr.py",
    "tests/nr/test_introspect_serie_tendance_nr.py",
    "tests/nr/test_directive_audit_volumetrie_nr.py",
    "tests/nr/test_recurrence_audit_suppleant_nr.py",
    "tests/nr/test_roadmap_verify_formes_non_module_nr.py",
    "tests/nr/test_roadmap_verify_gel_instruit_nr.py",
    "tests/nr/test_acp_resolution_binaire_nr.py",
    "tests/nr/test_agy_lot_continu_nr.py",
    "tests/nr/test_acp_drapeau_deprecie_nr.py",
    "tests/nr/test_roadmap_bruit_lexical_nr.py",
    "tests/nr/test_roadmap_instruits_nr.py",
    "tests/nr/test_llm_dashboard_catalogue_complet_nr.py",
    "tests/nr/test_webhub_routes_sans_balayage_nr.py",
    "tests/nr/test_persona_directives_owner_nr.py",
    "tests/nr/test_ui_generate_borne_charge_nr.py",
    "tests/nr/test_hub_vocabulaire_statut_nr.py",
    "tests/nr/test_anatomy_rag_stats_sans_scan_nr.py",
    "tests/nr/test_parietal_percept_trait_unique_nr.py",
    "tests/test_forge_scorecard.py",
    "tests/test_forge_scorecard_symbolic.py",
    "tests/test_forge_scorecard_evaluate_patch.py",
    "tests/test_forge_goap_scorecard_routing.py",
    "tests/test_forge_scorecard_refine_judge.py",
    "tests/test_forge_repo_map.py",
    "tests/test_forge_repo_map_tools.py",
    "tests/test_forge_lats.py",
    "tests/test_forge_pydantic_tools.py",
    "tests/test_forge_circadian.py",
    # Suite NR (2026-08-14). Fichiers CITES UN A UN, jamais le repertoire :
    # 2026-09-03 : ajoute apres que le cliquet `test_suite_pure_ratchet_nr` l'a
    # attrape — ecrit le matin, il n'etait declare nulle part, donc il ne tournait
    # PAS en CI et ne protegeait rien. Un test hors de cette liste est un test qui
    # rassure sans garder.
    "tests/nr/test_provenance_note_agent_nr.py",
    "tests/nr/test_agy_lock_ressource_reelle_nr.py",
    "tests/nr/test_secret_source_cliquet_nr.py",
    # Phase 1 du mandat « organe de secretion » : le guichet doit distinguer
    # ABSENT d'ILLISIBLE, et l'audit du coffre ne plus se borner a sa propre
    # liste codee en dur (26 connues / 78 demandees, mesure du 2026-09-20).
    "tests/nr/test_secrets_illisible_nest_pas_absent_nr.py",
    "tests/nr/test_inventaire_cles_demandees_nr.py",
    # Le breakglass exige desormais une ATTESTATION (jeton signe, TTL, admin)
    # au lieu d'une variable d'environnement. Directive owner 2026-09-20.
    "tests/nr/test_breakglass_exige_une_preuve_nr.py",
    # Phase 3 : chaque cle nomme son organe proprietaire, ou dit pourquoi elle
    # ne peut pas -- et une carte illisible ne fabrique pas des orphelins.
    "tests/nr/test_provenance_proprietaire_par_cle_nr.py",
    # Phase 4 : la nature COMMANDE le masquage. Mesure avant ce maillon : les
    # natures etaient consultees par 0 site hors des modules qui les
    # definissent -- une etiquette, pas une politique.
    "tests/nr/test_la_nature_commande_le_masquage_nr.py",
    # Directive owner 2026-09-21 : « ne casse pas les bascules sur le mode dev
    # en cas de gros debug ». Verrouille AUSSI qu'un refus n'annonce jamais une
    # commande inoperante -- j'avais ecrit `--arm` la ou le CLI prend `arm`.
    "tests/nr/test_la_bascule_dev_reste_utilisable_nr.py",
    # Phase 5/11 : la fenetre de contournement d'une revocation etait INFINIE
    # (cache sans expiration). Elle est desormais bornee ET observable.
    "tests/nr/test_un_secret_revoque_cesse_d_etre_servi_nr.py",
    # Phase 6 : le guichet sait POUR QUI il delivre. Prealable strict a toute
    # politique -- une politique branchee sur un demandeur inconnu ne decide rien.
    "tests/nr/test_le_guichet_sait_pour_qui_il_delivre_nr.py",
    "tests/nr/test_secrets_reserves_recensement_nr.py",
    "tests/nr/test_maitre_decouple_des_cles_nr.py",
    "tests/nr/test_coffre_reserve_nr.py",
    # Etape 2b-1 (2026-09-28) : cle persona fail-closed et reservee, HMAC persona refuse
    # aux rings <= DEV, le maitre n'est plus l'identite de l'owner / MASTER_TOKEN.
    "tests/nr/test_connexion_persona_et_maitre_2b1_nr.py",
    # Etape 2b-2 lot B1 (2026-09-28) : quatre noms reserves de plus, lecteurs au guichet,
    # hub en transition journalisee ; cliquet des lectures hors guichet ; trace critique de
    # governed_edit hors stderr (elle gelait la boucle du hub : 3 WEDGE KILL ce jour-la).
    "tests/nr/test_guichet_seul_2b2_nr.py",
    "tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py",
    "tests/nr/test_governed_edit_trace_non_bloquante_nr.py",
    # 2b-2 lot B2 : un jeton d'une famille ne passe jamais dans une autre (aud rejete par
    # le hub, proxy MCP sur son jeton propre).
    "tests/nr/test_familles_de_jetons_2b2_nr.py",
    # 2b-3 : JWT du hub en EdDSA (cle privee reservee), HS256 en transition fermable.
    "tests/nr/test_jwt_hub_ed25519_2b3_nr.py",
    # 2b-4 : hors SYSTEM, le jeton court est emis par le hub (loopback), plus signe sur place.
    "tests/nr/test_jeton_court_emis_par_le_hub_2b4_nr.py",
    # 2b-5 : le pont stdio presente l'identite PROPRE de chaque client, plus le maitre.
    "tests/nr/test_pont_stdio_identite_propre_2b5_nr.py",
    # 2b-5 : brique jeton_hub (identite propre, sinon maitre en transition dite), TUI branchee.
    "tests/nr/test_jeton_hub_identite_ou_transition_2b5_nr.py",
    # 2b-5 : forge_supervisor_ctl -- jeton au guichet, mutations via le hub hors SYSTEM.
    "tests/nr/test_supervisor_ctl_via_hub_2b5_nr.py",
    # Cle d'integrite partagee (decision owner 2026-09-28) : hors noms reserves, source
    # unique cle_integrite_hmac, plus jamais de cle devinable.
    "tests/nr/test_cle_integrite_partagee_nr.py",
    # Registre des cles publiques d'agents hors sandbox/ (dossier owner, jamais cree).
    "tests/nr/test_registre_cles_hors_sandbox_nr.py",
    # Sessions du portail en EdDSA, verifiees par la cle ENREGISTREE de WEBHUB.
    "tests/nr/test_portail_eddsa_nr.py",
    "tests/nr/test_fermeture_replis_reserves_2b6_nr.py",
    "tests/nr/test_lecteurs_directs_reserves_2b6_nr.py",
    "tests/nr/test_renouvellement_jeton_court_nr.py",
    "tests/nr/test_jeton_injecte_par_le_lanceur_nr.py",
    "tests/nr/test_jeton_lanceur_auxiliaire_nr.py",
    "tests/nr/test_lanceur_runas_environnement_nr.py",
    "tests/nr/test_ctl_sans_boucle_par_le_hub_nr.py",
    "tests/nr/test_pas_de_cle_derivee_du_maitre_nr.py",
    "tests/nr/test_jeton_projete_nr.py",
    "tests/nr/test_task_executor_jeton_par_appel_nr.py",
    "tests/nr/test_fichier_cle_veracrypt_reserve_nr.py",
    "tests/nr/test_capsule_cognitive_nr.py",
    "tests/nr/test_vc_rekey_nr.py",
    "tests/nr/test_superviseur_bilan_coffre_nr.py",
    "tests/nr/test_coffre_rotation_nr.py",
    "tests/nr/test_mcp_json_sync_portees_claude_nr.py",
    "tests/nr/test_vc_entete_hors_veracrypt_nr.py",
    "tests/nr/test_vc_rekey_scripte_nr.py",
    "tests/nr/test_demarrage_monte_v_par_system_nr.py",
    "tests/nr/test_semeur_relit_la_valeur_nr.py",
    "tests/nr/test_provision_source_retiree_nr.py",
    "tests/nr/test_mcp_json_sync_clients_http_nr.py",
    "tests/nr/test_oauth_par_passerelle_nr.py",
    "tests/nr/test_pair_mcp_nr.py",
    "tests/nr/test_pair_quarantaine_nr.py",
    "tests/nr/test_lanceur_profil_pair_nr.py",
    "tests/nr/test_pair_mcp_hote_public_nr.py",
    "tests/nr/test_pair_quarantaine_geste_owner_nr.py",
    "tests/nr/test_note_apres_frontmatter_nr.py",
    "tests/nr/test_wiki_align_commandes_nr.py",
    "tests/nr/test_empreinte_stable_interpreteur_nr.py",
    "tests/nr/test_docstring_masquee_nr.py",
    "tests/nr/test_changelog_nr.py",
    "tests/nr/test_pair_tache_dit_sa_route_nr.py",
    "tests/nr/test_tokens_coherence_nr.py",
    "tests/nr/test_pair_repondre_texte_nr.py",
    "tests/nr/test_demander_ordre_nr.py",
    "tests/nr/test_oauth_renouvellement_survit_nr.py",
    "tests/nr/test_pair_reponses_meme_pair_nr.py",
    "tests/nr/test_pair_accuses_nr.py",
    # Phase 7 niveau C : le guichet respecte la quarantaine du rotateur, et
    # REVOQUE n'est pas ABSENT. Declare dans le commit SUIVANT le sien -- un
    # test non declare ne tourne nulle part, lecon re-payee le 2026-09-21.
    "tests/nr/test_le_guichet_respecte_la_quarantaine_nr.py",
    # V9 phase 3 : la revocation MORD sur la chaine REELLE -- le vrai mark()
    # ecrit un vrai ledger (isole en tmp_path) et get_secret refuse. Il a
    # revele un SECOND cache (_health_cache, 60 s) : la fenetre vaut 360 s,
    # pas 300.
    "tests/nr/test_revocation_secret_chaine_reelle_nr.py",
    # V9 phase 4 : identite revoquee = DENY, et SEULE l'identite change.
    # Mesure aussi la limite : la revocation vit en memoire, donc elle ne
    # survit pas a un redemarrage de process.
    "tests/nr/test_revocation_identite_isole_la_cause_nr.py",
    # V9 P0 : une preuve cryptographiquement VALIDE n'est pas une preuve LIEE.
    # Verrouille aussi le volet symetrique de RFC 9449 §7.1 -- un jeton porteur
    # d'un cnf.jkt ne passe plus sans preuve.
    "tests/nr/test_pop_preuve_liee_a_la_bonne_cle_nr.py",
    # V9 P1 : un certificat VALIDE n'est pas le certificat ATTENDU (RFC 8705).
    # Verrouille le volet symetrique -- un jeton lie a un cert ne passe plus
    # sur un canal qui n'en presente aucun.
    "tests/nr/test_cert_binding_adversarial_nr.py",
    # Dette du 2026-09-20 soldee : forge_tpm_agent_keys avait ete cree sans
    # aucun NR, et le cliquet de couverture l'a refuse 24 h plus tard.
    "tests/nr/test_tpm_agent_keys_outil_nr.py",
    # Maillon 1 du V8 : ce que /admin/run_job doit TRANSMETTRE au runner,
    # prouve par comportement (le NR voisin ne verifie que le texte).
    "tests/nr/test_admin_run_job_comportement_nr.py",
    # Etait hors PURE_TESTS parce qu'il etait ROUGE (3 echecs) : la route ne
    # passait pas par le runner gouverne. Le defaut est corrige, donc il entre
    # -- c'est ainsi qu'un cliquet se solde, en reparant ce qu'il denonce.
    "tests/nr/test_admin_run_job_observable_nr.py",
    # Le lanceur de campagne est ORPHELIN : son organe a ete supprime sur
    # decision owner (fab6fcca5) et lui est reste. Le NR ne celebre pas ce
    # defaut -- il empeche son echec de devenir SILENCIEUX, ce qui ferait
    # rendre « ok » a un job qui meurt a l'import sans rien produire.
    "tests/nr/test_veille_campagne_run_nr.py",
    # Decision owner 2026-09-21 option B : le rythme n'appelle plus
    # NokidoAutoCompact, dans AUCUN des deux runtimes. Ces trois NR etaient
    # ROUGES parce que le defaut existait ; il est corrige, donc ils entrent.
    "tests/nr/test_autocompact_hors_du_rythme_nr.py",
    "tests/nr/test_amorce_namespace_daemons_nr.py",
    "tests/nr/test_circadien_chemin_reel_nr.py",
    # Ce fichier existait depuis longtemps HORS de PURE_TESTS : il ne tournait
    # donc en CI nulle part, et son `test_breakglass` etait rouge sans que
    # personne le voie. Un test non declare ne protege aucune surface.
    "tests/test_secret_guard_nr.py",
    # 2026-09-15 : gate de publication (profil egress public + miroir). Hermetiques --
    # ils lisent .git-publish-rules.json du depot et monkeypatchent `_git`/`lire_blobs` ;
    # aucun port, aucun service, aucune base. Attrapes par test_suite_pure_ratchet_nr :
    # ecrits ce jour, ils n'etaient declares nulle part et ne tournaient donc pas en CI.
    "tests/nr/test_egress_profil_public_atteignable_nr.py",
    "tests/nr/test_miroir_public_lit_la_politique_nr.py",
    # 2026-09-15 : chantier pont ChatGPT (14/09) sans NR declares. Hermetiques --
    # base_publique/reglages sur env monkeypatche, et les fonctions pures du
    # lanceur (decider_lancement/environnement/commande) sur dicts en argument ;
    # aucun coffre, port, service ni reseau. Attrapes par les deux cliquets sur la
    # CI de reference de c96778770.
    "tests/nr/test_bridge_base_publique_nr.py",
    "tests/nr/test_bridge_launch_effet_nr.py",
    # 2026-09-15 : l'assemblage du dist applique blocked_paths (son push contourne
    # le gate egress). Hermetique : arbre en tmp, load_manifest monkeypatche, aucun git.
    "tests/nr/test_dist_publish_politique_nr.py",
    "tests/nr/test_dist_generisation_owner_path_nr.py",
    "tests/nr/test_lane_admission_ip007_nr.py",
    "tests/nr/test_ci_debug_tools_nr.py",
    "tests/nr/test_publication_gate_nr.py",
    "tests/nr/test_esoleau_empreintes_nr.py",
    # 2026-09-13 : tout chemin `github` du registre MCP lit le jeton au COFFRE avant
    # l'environnement. Defaut paye DEUX FOIS sur le meme fichier -- `run action=github`
    # corrige le 03/09, `handle_github` oublie jusqu'au 13/09 -- d'ou un NR qui balaie
    # TOUS les chemins construisant une URL de l'API, pas seulement celui du jour.
    # Hermetique : AST sur la source du depot, aucun reseau, aucune base.
    "tests/nr/test_github_jeton_du_coffre_nr.py",
    # 2026-09-13 : la passerelle GitHub read-only. Hermetique -- l'appel sortant est
    # remplace par une sonde, et les NR verifient AUSSI ce qui n'est PAS appele quand
    # la passerelle refuse. Le module est charge par son CHEMIN (tools/ n'est pas dans
    # le sys.path des tests, et un import par nom pourrait resoudre un homonyme).
    "tests/nr/test_github_bridge_nr.py",
    # 2026-09-14 : l'emetteur d'habilitation. Reclame par le cliquet de couverture,
    # qui a fait rougir la CI parce que le module avait ete livre sans aucun test.
    # Hermetique : coffre double, fichier de sortie detourne vers un tmp -- sans quoi
    # un simple `pytest` ecraserait l'habilitation reellement en service.
    "tests/nr/test_bridge_habilitation_nr.py",
    # 2026-09-14 : l'adaptateur MCP (stdio) des cinq operations. Il ne verifie RIEN --
    # toute l'autorite reste dans `traiter()` -- et les NR verifient precisement cette
    # absence : ni signature, ni liste de depots, ni appel sortant chez lui. Le test du
    # chemin reel construit le serveur et compte ses outils : sans lui, l'adaptateur
    # pourrait passer ses tests et ne pas demarrer du tout.
    "tests/nr/test_github_bridge_mcp_nr.py",
    "tests/nr/test_bridge_oauth_nr.py",
    "tests/nr/test_generation_trois_etats_nr.py",
    "tests/nr/test_m2m_bridge_nr.py",
    # 2026-09-03 (soir) : les deux gardes du retrieval. Hermetiques — le premier
    # ne touche aucun disque (verdicts calcules), le second construit sa base
    # SQLite en memoire et monkeypatche l'amont IETF.
    "tests/nr/test_retrieval_sweep_et_rfc_freshness_nr.py",
    "tests/nr/test_savoir_census_et_comptes_nr.py",
    # Les trois outils d'indexation du 2026-09-03 : advisor, trigram, fingerprint.
    # Hermetiques (base SQLite temporaire, aucun disque de prod touche).
    "tests/nr/test_indexation_gardes_nr.py",
    # NPSC (2026-09-04) : le moteur de conformite normative multi-autorite.
    # Hermetique — registre factice en memoire, aucun reseau, aucune base.
    "tests/nr/test_npsc_nr.py",
    "tests/nr/test_npsc_decouverte_nr.py",
    # RFC 7518 3.2 : longueur minimale de la cle HMAC (2026-09-04, ANTIGRAVITY).
    # Inscrit UNE fois : la livraison M2M l'avait ajoute a deux endroits, ce qui
    # aurait fait tourner le fichier deux fois par run.
    "tests/nr/test_jwt_longueur_cle_nr.py",
    # RFC 9309 : le crawl demande la permission et s'identifie (2026-09-04).
    # Hermetique — urlopen remplace dans chaque cas, aucun reseau.
    "tests/nr/test_robots_rfc9309_nr.py",
    # OpenAPI 3.x 4.8.10 : operationId unique (2026-09-04). Monte l'app web.
    "tests/nr/test_openapi_operationid_unique_nr.py",
    # L'audit de conformite tourne SANS agent, et jamais depuis un test.
    "tests/nr/test_npsc_circadien_nr.py",
    # Le cout des requetes est OBSERVE, et le rapport de sante ne balaie plus
    # 24,9 Go toutes les 7 min (2026-09-04). Hermetique : base en memoire.
    "tests/nr/test_db_observatoire_nr.py",
    # La migration de la memoire episodique ne peut pas la perdre : droits
    # eprouves avant de bouger, copie prouvee, source renommee jamais supprimee.
    "tests/nr/test_memory_junction_nr.py",
    # Les fiches entrent dans un palier VECTORISABLE, et le plan de dedup est
    # verifie avant une passe de masse (sinon 24,9 Go lus par document).
    "tests/nr/test_memory_ingest_nr.py",
    "tests/nr/test_memory_ingest_volatil_nr.py",
    "tests/nr/test_memory_moc_nr.py",
    "tests/nr/test_memory_compactor_reingest_nr.py",
    # Hook SessionStart mort 24 h EN SILENCE (2026-09-11) : l'amorce `sys.path` etait
    # posee APRES l'import du namespace qu'elle repare, donc inoperante. Le premier
    # verrouille le lancement PAR CHEMIN ABSOLU (le mode qui a casse, et que le NR
    # d'appui ne pouvait pas voir puisqu'il posait lui-meme l'amorce) ; le second, le
    # desarmement de la compaction decide par l'owner le meme jour.
    "tests/nr/test_point_entree_par_chemin_nr.py",
    "tests/nr/test_entry_points_synchrones_nr.py",
    "tests/nr/test_gate_ci_online_change_de_compte_nr.py",
    "tests/nr/test_memory_compactor_sans_compaction_nr.py",
    # Le meme hook TUE a 8 s a chaque demarrage (2026-09-26, 47/47) : le ledger
    # balayait sa table une fois par fichier memoire, faute d'index sur `fname`.
    "tests/nr/test_memory_ledger_index_fname_nr.py",
    # ENCORE tue a 8 s apres l'index : sync() ouvrait les 975 fiches, 6 s a froid.
    "tests/nr/test_memory_ledger_sync_rapide_nr.py",
    # Le chemin NON RETENU (export d'index) : conserve comme repli, donc teste.
    # Un repli non teste trahit le jour ou on s'en sert.
    "tests/nr/test_memory_index_export_nr.py",
    # Un 403 imputable au MODELE ne doit pas degrader la CLE (2026-09-03).
    "tests/nr/test_rotation_403_modele_nr.py",
    # Ledger de sante des cles : 6 ecrivains concurrents perdaient 100 marques sur
    # 150, et le 23/09 le fichier est devenu illisible (temporaire FIXE partage).
    # Verrou inter-processus (FileLock) + temporaire unique (veilles B_31/B_32).
    "tests/nr/test_key_rotation_ledger_concurrent_nr.py",
    # La campagne qui pose l'observation du routeur sur son canal reel.
    "tests/nr/test_patch_router_observation_nr.py",
    # P1 de fondation : l'etat de deliberation ne detruit plus son antecedent.
    "tests/nr/test_deliberation_non_destructive_nr.py",
    # A2A Tier 1 : securite fail-closed, cycle de vie, carte honnete.
    "tests/nr/test_a2a_tier1_nr.py",
    # ACP bout en bout : conditionnel (SKIP si le service n'ecoute pas), mais
    # exigences PLEINES quand il tourne. C'est ce test qui autorise la carte a
    # publier `acp.session`.
    "tests/nr/test_acp_session_e2e_nr.py",
    # `tests/nr/` en bloc a fait entrer `test_core_nr.py`, qui interroge la vraie
    # base RAG (1,15 M chunks) et depasse le timeout de 30 s — et qui echouerait
    # de toute facon sur GitHub, ou la base n'est pas versionnee. La whitelist se
    # definit par « zero service externe » : elle ne peut pas s'etendre par
    # repertoire sans trahir sa propre regle.
    # Ceux-ci ne lisent que des fichiers du depot.
    "tests/nr/test_tous_modules_nr.py",
    "tests/nr/test_antiregression_outils_nr.py",
    "tests/nr/test_regulation_catalogue_nr.py",
    "tests/nr/test_nr_coverage_ratchet_nr.py",
    "tests/nr/test_qa_checklist_matrix_nr.py",
    "tests/nr/test_m2m_resonde_wiki_align_nr.py",
    "tests/nr/test_self_correction_roundtrip_nr.py",
    "tests/nr/test_mutation_gain_nr.py",
    # Reparations du 2026-08-28. Inscrits ici parce que le cliquet de purete l'a
    # exige, et il avait raison : ces quatre fichiers passaient en local et ne
    # tournaient PAS en CI -- ils ne gardaient donc rien. Zero service externe :
    # AST, lecture de fichiers du depot, urlopen et _feed remplaces, ecritures
    # confinees a tmp_path.
    "tests/nr/test_sonde_cles_nr.py",
    "tests/nr/test_router_slots_nr.py",
    # Arbitrage des piliers (2026-09-01). Inscrit dans le MEME commit que le code
    # qu'il garde : un test NR hors PURE_TESTS ne protege AUCUNE surface. Zero
    # service externe -- politique jetable en tmp_path, urlopen remplace.
    "tests/nr/test_pillar_arbiter_nr.py",
    # Rattrapage lexical incremental (2026-09-01). Zero service externe : base
    # SQLite jetable en tmp_path, open_writer detourne.
    "tests/nr/test_fts_rattrapage_incremental_nr.py",
    # CA cliente mTLS (2026-09-02) — RFC 8705 / PKIX. Garde surtout qu'un certificat
    # client ne porte QUE `clientAuth` : avec `serverAuth` il pourrait authentifier
    # un faux hub. Signature verifiee cryptographiquement, pas seulement l'emetteur
    # declare. Zero service externe : toute la PKI est redirigee en tmp_path.
    "tests/nr/test_mtls_ca_nr.py",
    # Audience du CapabilityToken (2026-09-02) — RFC 8707 / 9068 / MCP 2026-07-28.
    # Garde surtout qu'une ABSENCE d'audience ne vaut pas correspondance, et que le
    # champ est reellement EMIS : une verification sans emetteur ne garde rien.
    # Zero service externe : secret local, aucun TPM, aucun reseau.
    "tests/nr/test_capability_audience_nr.py",
    # Outils du chantier retrieval (2026-09-01) : reponse au cliquet de couverture,
    # qui a fait rougir la CI du checkpoint 35c992a4b. Les trois modules etaient
    # livres sans qu'aucun test ne les nomme. Zero service externe : journal
    # jetable en tmp_path, routeur d'embedding remplace, depot lu seulement.
    "tests/nr/test_outils_chantier_retrieval_nr.py",
    # Conformite M2M (2026-09-01) : le bus publiait 2836 violations sur deux mois
    # et zero conforme, donc un numerateur sans denominateur. Ce test garde le
    # compteur ET son CABLAGE au point de controle -- un compteur non appele
    # compte zero et se lit comme un trafic parfait. Zero service externe :
    # etat redirige en tmp_path.
    "tests/nr/test_m2m_conformance_nr.py",
    # Noeud sinusal (2026-09-03) : le rythme du corps emane d'un organe unique et
    # les autres s'y accordent. Ce test garde surtout que « denerve » rende le
    # rythme PROPRE et non une extremite -- rendre 0.0 ferait d'une absence de
    # commande une bradycardie decidee -- et que la bradycardie maximale reste sous
    # le seuil du superviseur : au-dela, tous les organes perfuses seraient declares
    # figes D'UN COUP. Zero service externe : pouls jetable en tmp_path (jamais le
    # pouls de production, qui pilote des organes vivants), endocrine injecte.
    "tests/nr/test_cycle_cardiaque_nr.py",
    # Qualification d'activite (2026-09-03), meme commit que le code corrige. Garde
    # l'invariant que le module entier defend : une E/S illisible ne vaut PAS une
    # inertie mesuree. Le defaut existait et rendait `False` sur une demi-mesure ;
    # la branche fautive n'avait jamais ete parcourue. Zero service externe : psutil
    # remplace par un process synthetique, aucun pid reel interroge.
    "tests/nr/test_qualification_activite_nr.py",
    # Temps mort canonique (2026-09-03), meme commit que le module. Garde surtout
    # qu'un cycle INCONNU ne durcisse personne : la premiere version rendait le
    # plancher faute de cycle, ce qui aurait fait passer 24 services sur 36 de 600 s
    # a 90 s d'un coup, le hub compris. Zero service externe : registre synthetique
    # passe en argument, aucun fichier lu.
    "tests/nr/test_temps_mort_canonique_nr.py",
    # Gate world-model etendu au RESTART (2026-09-01), meme commit que le code.
    # Le garde vit dans le CORPS (tools/forge_ensure_service.py), pas dans un
    # hook client : il filtre donc pour Claude, Gemini, Codex et agy a la fois.
    # Zero service externe : world-model remplace, admission et sonde
    # d'installation neutralisees, aucun service reel touche.
    "tests/nr/test_ensure_service_restart_gate_nr.py",
    # Vue d'audit du videur (2026-09-02), meme commit que app/forge_videur_audit.py.
    # Le temoin a preserver est `master_token + X-Agent-Name=VIBE -> impersonation=1` :
    # il mesurera l'effet du futur durcissement du token maitre. Hermetique -- la vue
    # ET le journal sont rediriges en tmp_path, aucun DPAPI, aucun secret lu.
    "tests/nr/test_videur_audit_view_nr.py",
    # Handshake mTLS (2026-09-02). HERMETIQUE : le test fabrique sa propre CA en
    # tmp_path et n'ouvre qu'un port EPHEMERE sur le loopback -- il ne lit jamais
    # sandbox/tls/, sinon il passerait au vert sur une machine sans mTLS. Ce sont
    # les trois REFUS qui protegent (sans cert, autre CA, cert sans sa cle).
    "tests/nr/test_mtls_handshake_nr.py",
    # Liaison certificat <-> token (2026-09-02, RFC 8705 §3.1). Hermetique : CA,
    # certificats et tokens fabriques en memoire. Ce qui protege, ce sont les refus :
    # token non lie, token lie a un AUTRE certificat, sub != agent du certificat,
    # mauvaise audience, EKU serveur, certificat expire ou revoque.
    "tests/nr/test_cert_binding_nr.py",
    # Age des runs CI (2026-09-02) : le calcul melangeait heure locale et UTC et
    # annoncait « queued depuis 3605s, rien ne demarre » sur un run cree a l'instant
    # -- une panne INVENTEE, qui envoie relancer un runner sain. Pur calcul de date,
    # aucun appel reseau : le module est importe, jamais joint a GitHub.
    "tests/nr/test_ci_check_age_fuseau_nr.py",
    # Vocabulaire de REVUE M2M (2026-09-02) : REVIEW_OK / _FINDING / _UNKNOWN, pour
    # que plusieurs agents puissent se contredire utilement. Garde principal :
    # UNKNOWN n'est pas SAFE. Verifie aussi que RULES_SHARED.md suit le dictionnaire
    # -- sans reemanation, les agents lisent un vocabulaire perime. Pur JSON + regex.
    "tests/nr/test_m2m_review_vocabulaire_nr.py",
    # Silence d'un provider (2026-09-02) : un tour de debat sortait ok=True avec un
    # texte VIDE, le drapeau venant du TRANSPORT et non du CONTENU. Un routeur qui
    # choisit ses cerveaux sur ce taux prefererait un provider muet a un provider
    # lent. Hermetique : `_one` est double, aucun appel cloud.
    "tests/nr/test_debat_silence_nr.py",
    # Politique de PARTAGE / egress (2026-09-02) : « ai-je le droit de donner CETTE
    # information a CE cerveau ? ». Invariant teste : la collaboration n'efface
    # jamais la sensibilite (CONFIDENTIAL + SWARM reste local). Le cablage REEL est
    # prouve, pas suppose : en mode error, `router_call` n'est jamais atteint.
    # Hermetique : authorize et router_call sont doubles, aucun appel provider.
    "tests/nr/test_share_policy_nr.py",
    # COUVERTURE du preflight de partage (2026-09-02) : la politique garde UN chemin
    # sur six -- `router_call` est atteint par forge_handoff, forge_internal_sampling,
    # forge_router_gateway et le tool MCP llm_router_call, qui ne la consultent pas.
    # Ce test ne corrige rien : il FIGE la liste et echoue si un nouvel appel direct
    # apparait, pour que la couverture ne se degrade pas en silence. Pure lecture AST.
    "tests/nr/test_share_policy_couverture_nr.py",
    # PREUVE PAR EFFET (2026-09-02) : les 5 chemins sont EXECUTES pour de vrai, seul
    # le fournisseur est double -- le contexte traverse donc tout le code qui le
    # transporte. Complementaire de la preuve structurelle (AST) : un `context=`
    # present dans la source pourrait etre ecrase par une couche intermediaire.
    "tests/nr/test_share_policy_effet_nr.py",
    # Inventaire des ROUTES HTTP et de leurs gardes (2026-09-02). 81 routes, 27
    # gardees ; 19 sensibles (ADMIN/MUTANTE) sans garde detectee sont FIGEES ici.
    # Une route sensible nouvelle sans authentification fait rougir la CI au lieu
    # de s'ajouter en silence. Statique et hermetique : aucune sonde reseau.
    "tests/nr/test_route_authz_inventaire_nr.py",
    # GARDE D'EXPOSITION (2026-09-02) : le hub verifiait HUB_HOST, c'est-a-dire
    # l'INTENTION. Ce garde constate l'EFFET (mapping de conteneur, proxy, socket
    # herite exposent sans toucher la variable). Invariant teste : une sonde
    # aveugle rend INCONNU, jamais « sain ». Hermetique : psutil est double.
    "tests/nr/test_bind_guard_nr.py",
    # Chaine des credentials (2026-09-02). Ces huit fichiers existaient,
    # passaient en local et n'etaient executes NULLE PART : absents de cette
    # liste, ils n'ont jamais tourne dans le gate -- mesure faite ce jour,
    # zero ligne d'execution dans deux logs de CI. Des gardes ecrits, verts
    # chez leur auteur, dormants la ou ils comptent : exactement le motif que
    # plusieurs d'entre eux documentent. Aucun ne charge la pile ML.
    "tests/nr/test_authz_shadow_nr.py",
    "tests/nr/test_cycle_de_vie_jetons_nr.py",
    "tests/nr/test_porteur_capability_nr.py",
    "tests/nr/test_hub_client_jeton_a_bail_nr.py",
    "tests/nr/test_dpop_rfc9449_nr.py",
    "tests/nr/test_jeton_lie_au_porteur_nr.py",
    "tests/nr/test_tpm_trois_etats_nr.py",
    "tests/nr/test_drapeau_env_nr.py",
    # Phase C (2026-09-02) : dix fichiers ecrits ce jour-la, orphelins depuis
    # leur naissance. Le cliquet `test_suite_pure_ratchet_nr` les signalait
    # deja -- son verdict etait MASQUE par le crash de la suite, qui rendait
    # tout le gate sans verdict. Chacun a ete execute SEUL avec la commande
    # exacte du gate avant d'entrer ici, comme le socle l'impose : 192 tests,
    # tous verts. (« Passe seul » autorise le rapatriement, il ne le garantit
    # pas -- cf. l'angle mort consigne au socle le 2026-08-20.)
    "tests/nr/test_authz_axes_separes_nr.py",
    "tests/nr/test_authz_capability_mesuree_nr.py",
    "tests/nr/test_delegation_act_as_nr.py",
    "tests/nr/test_identite_organe_nr.py",
    "tests/nr/test_pair_local_nr.py",
    "tests/nr/test_proxy_identite_prouvee_nr.py",
    "tests/nr/test_route_authz_sonde_nr.py",
    "tests/nr/test_supervisor_authz_contrat_nr.py",
    "tests/nr/test_supervisor_sante_applicative_nr.py",
    "tests/nr/test_tool_annotations_nr.py",
    "tests/nr/test_tool_scope_repli_lexical_nr.py",
    "tests/nr/test_scripts_de_patch_nr.py",
    "tests/nr/test_backlog_qualifie_nr.py",
    "tests/nr/test_organ_demand_nr.py",
    "tests/nr/test_protection_coder_nr.py",
    # BREAKGLASS (2026-09-02) : LAFORGE_AUTHORITY_BYPASS rendait `ok` SANS TRACE,
    # decouvert par audit donc trop tard. Il journalise desormais a chaque appel,
    # est REFUSE si le hub ecoute hors loopback, et ne franchit QUE
    # `_check_authority` -- la capability HMAC reste exigee. Doubles poses sur les
    # modules SOURCES : `_check_authority` importe dans sa fonction, et le vrai
    # chemin FIGE sur un verrou de production (dette consignee).
    # tests/nr/test_breakglass_bruyant_nr.py -- RETIRE de la suite PURE le
    # 2026-09-02, apres l'y avoir ajoute le meme jour (commit 57e9b461f).
    #
    # MESURE, deux runs sur deux sha : arrive a ce fichier, son 7e cas importe
    # `forge_agent_authority`, qui tire `bootstrap` -> `forge_cascade_oracle`
    # -> `sentence_transformers` -> torch. L'interpreteur meurt alors en
    # 0xC0000005 (violation d'acces) AVANT que pytest ecrive son JUnit : la
    # suite entiere devient donc SANS VERDICT, pas rouge -- 6913 tests perdus
    # pour un seul fichier. Sur le sha publie, ou ce fichier n'etait pas
    # declare, la suite va au bout et rend son rapport.
    #
    # Ce n'est PAS le test qui est casse : lance seul avec la commande exacte
    # du gate, il passe 9/9 en 9,8 s. Et l'import de `mcp_server_tools` n'est
    # pas fatal en soi -- quatre autres fichiers de cette liste le font et
    # passent, dont trois juste avant lui. Ce qui tue, c'est de charger la pile
    # ML APRES des milliers de tests, avec l'etat natif deja accumule.
    #
    # D'ou le retrait plutot qu'un correctif : une suite qui s'appelle PURE
    # n'est pas l'endroit ou charger torch, et je ne sais pas reparer un
    # conflit de bibliotheques natives en fin de parcours. A executer
    # separement tant que ce fichier tire la pile ML.
    # REGISTRE UNIQUE (2026-09-02) : quatre registres de fournisseurs coexistent,
    # et les deux principaux ont 3 noms communs sur 39 et 33 -- ils sont quasi
    # DISJOINTS (nommage par famille contre nommage par modele). Cinq passes
    # d'arene perdues a interroger le mauvais. Ce garde exige que le mapping reste
    # COMPLET : une entree ajoutee d'un cote sans alias fait rougir la CI.
    "tests/nr/test_provider_alias_nr.py",
    "tests/nr/test_fts_triggers_source_unique_nr.py",
    "tests/nr/test_memory_availability_nr.py",
    "tests/nr/test_nrem_scheduler_nr.py",
    # P0 securite 2026-09-01 : fail-closed du dispatch sandbox. Importe le registre
    # (0,14 s mesure, imports lazy) et n'instancie pas -- zero service externe.
    "tests/nr/test_sandbox_dispatch_failclosed_nr.py",
    "tests/nr/test_tool_gate_armement_failclosed_nr.py",
    # ─────────────────────────────────────────────────────────────────────────
    # SORTIS DU CANDIDAT le 2026-09-13 — COMPOSITION, pas qualite.
    # Chacun de ces NR teste un module dont des modifications ne sont PAS
    # versionnees (chantiers M0.1 / ACP / autres, ouverts ailleurs). En local ils
    # voient le code modifie ; dans un worktree bati depuis le sha, ils voient la
    # version ANTERIEURE. Mesure : certification d49653340, 33 cas en echec pour
    # ce seul motif, alors que 9596 tests passaient.
    # Le critere est la COHERENCE test <-> code teste <-> candidat, JAMAIS la
    # couleur : quatre d'entre eux etaient VERTS et sortent quand meme, sinon on
    # adopterait la regle « une dependance non versionnee est acceptable si le
    # test passe » -- exactement l'inverse de ce que cette certification a montre.
    # Ils reviennent quand leur chantier versionne son module.
    # 2026-09-13, CORRIGE LE SOIR MEME. J'avais reintegre huit NR apres avoir verifie
    # que leurs IMPORTS etaient tous versionnes et qu'ils passaient en local (87 verts).
    # La CI de reference les a rendus ROUGES : 29 echecs, tous dans ces fichiers. Cause
    # MESUREE : ils visent des ATTRIBUTS (PROMOTION_SEUIL, _classer_routes, mode_valide,
    # _identite_prouvee...) presents sur le DISQUE et absents a HEAD -- 252 fichiers du
    # chantier M0.1 ne sont pas commites. Le module s'importe, donc un controle d'imports
    # est AVEUGLE : c'est l'attribut qui manque. Le controle qui tranche est de rejouer
    # sur `git show HEAD:<module>`, jamais sur l'arbre de travail.
    # Les sept sont au socle (`_rouges_sur_arbre_detache_2026_09_13`) et reviendront ici
    # quand M0.1 sera commite : ils sont justes, c'est leur code qui manque.
    # Seul `test_rbac_indisponible_failclosed_nr` passe sur arbre detache -- il RESTE.
    # "tests/nr/test_capability_gate_promotion_nr.py",
    # NR du chantier M0.1 (autorite / surface d'effet), ecrits le 2026-09-12 et
    # jamais inscrits : le cliquet `test_suite_pure_ratchet_nr` les a nommes le
    # 2026-09-13. Un test hors PURE_TESTS ne tourne pas en CI -- il ne protege
    # aucune surface, quelle que soit sa qualite. Mesure avant inscription :
    # 33 tests, 3,43 s, aucun service externe.
    "tests/nr/test_authority_db_hors_sandbox_nr.py",
    "tests/nr/test_authority_split_refuse_bascule_nr.py",
    "tests/nr/test_gardes_sans_passe_droit_nr.py",
    "tests/nr/test_job_watch_cli_et_verif_restart_nr.py",
    "tests/nr/test_purge_journaux_opsec_nr.py",
    "tests/nr/test_trust_domains_acl_mesuree_nr.py",
    "tests/nr/test_acp_toolcallid_canonique_nr.py",
    "tests/nr/test_acp_authenticate_sans_ceremonie_nr.py",
    "tests/nr/test_ui_campaign_login_non_juge_nr.py",  #      (forge_ui_campaign)
    # RETIRE du candidat le 2026-09-13 -- et le motif compte plus que le retrait :
    # ce NR importe `forge_effect_surface`, module PRESENT dans tools/ de l'arbre
    # partage mais NON VERSIONNE. Il passe donc en local et rend la certification
    # de reference IMPOSSIBLE : sur un worktree bati depuis le sha, l'import echoue
    # et pytest s'interrompt A LA COLLECTE -- 1 erreur, ZERO test execute, soit un
    # verdict UNKNOWN et non un echec (mesure : 217 s de machine pour ne rien juger).
    # Un test versionne dont le module teste ne l'est pas est increcertifiable.
    # Il revient ici le jour ou son chantier (surface d'effet) versionne son module.
    # HORS SUITE, et c'est MESURE, pas un oubli : ce test importe
    # tools/forge_effect_surface.py, qui n'est pas suivi par git. La CI de reference
    # tourne sur un worktree DETACHE ou l'untracked est ABSENT -- l'activer ici le
    # ferait passer en local et mourir sur le worktree. Inscrit dans
    # tests/nr/_socle_suite_pure.json (`_exclusion_2026_09_13`), a solder en
    # versionnant le module avec le chantier M0.1.
    # "tests/nr/test_effect_surface_protected_derive_nr.py",
    "tests/nr/test_trust_domains_m01_nr.py",
    # "tests/nr/test_ps_sandbox_mode_inconnu_failclosed_nr.py",  # (forge_ps_sandbox)
    "tests/nr/test_ps_clm_exige_attestation_dev_nr.py",
    "tests/nr/test_rbac_indisponible_failclosed_nr.py",  #    (forge_mcp_rbac) VERT
    # "tests/nr/test_corrigibilite_failclosed_nr.py",  #        (forge_corrigibility)
    # "tests/nr/test_critical_files_suit_l_autorite_nr.py",  #  (5 modules d'autorite)
    # TESTS DE COMPORTEMENT (skill forge-tdd), pas des NR : ils empruntent le
    # CHEMIN REEL (`ToolRegistry.dispatch`, coroutine de 481 lignes) au lieu
    # d'asserter sur le texte source. Les deux familles sont necessaires — un NR
    # vert sur du texte ne dit rien du comportement, un comportement vert ne
    # verrouille pas l'invariant contre une reecriture. N'executent RIEN :
    # outil inexistant, ou `code` vide qui court-circuite avant tout lancement.
    # "tests/test_dispatch_garde_indisponible.py",           (forge_mcp_rbac) VERT
    # "tests/test_plafond_capacite_ps_side_doors.py",        (forge_mcp_rbac) VERT
    "tests/test_bareme_ring_is_active.py",
    # "tests/test_outil_natif_non_declare.py",               (forge_mcp_rbac)
    # "tests/test_preuve_du_verdict_m01.py",                 (forge_effect_surface) VERT
    "tests/test_ps_clm_plancher_de_ring.py",
    "tests/test_delegation_porte_l_autorite.py",
    # "tests/test_antispoof_survit_a_l_elevation.py",        (forge_videur)
    "tests/test_ensure_service_plancher_ring.py",
    # "tests/nr/test_plancher_antispoof_est_terminal_nr.py",  # (forge_videur)
    "tests/nr/test_autorite_absente_ne_privilegie_pas_nr.py",
    "tests/nr/test_bacs_privilegies_ring_gates_nr.py",
    "tests/nr/test_sentinelle_de_blocage_nr.py",
    # "tests/nr/test_completude_declaration_outils_nr.py",  #   (forge_mcp_rbac)
    # Contrat du tool run (2026-09-01) : `network` declare, `sandbox` ne reintroduit
    # jamais online/trusted. Lit le catalogue declare, zero service externe.
    "tests/nr/test_run_contrat_network_nr.py",
    # Routeur en SHADOW (2026-09-01) : prouve par identite d'objet qu'il ne peut pas
    # modifier le ranking. Zero service externe, aucun import du moteur.
    "tests/nr/test_retrieval_router_shadow_nr.py",
    "tests/nr/test_bascule_routeur_soudee_nr.py",
    "tests/nr/test_journal_shadow_observable_nr.py",
    "tests/nr/test_router_impact_nr.py",
    "tests/nr/test_veille_u1_boucle_nr.py",
    "tests/nr/test_veille_depouillement_nr.py",
    # Moisson : corps des pages de doc (73,2 % de menus mesures le 24/09) et
    # exclusion des sources de l'owner (veilles lot_C_09 / lot_C_05).
    "tests/nr/test_moisson_page_corps_et_sources_propres_nr.py",
    # CVE : forge_cve_rag_ingest GELE (flux NVD 1.1 -> 403, mesure 27/09) ; refus dit avant
    # reseau et base, successeur nomme (forge_cve_nvd_download, API 2.0), __main__ compris.
    "tests/nr/test_cve_ingest_nvd11_gele_nr.py",
    # Joint capability-graph : actions_prouvees croise crosswalk (preuve d'usage) x ALLOWED_METHODS
    # (planifiable) ; DECLARE != INVOCABLE, prouve-hors-whitelist nomme, pre/effet UNKNOWN jamais fabrique.
    "tests/nr/test_capability_graph_joint_nr.py",
    # Vascularisation joint->GOAP : annotation_preference marque au planificateur les methodes
    # EPROUVEES par l'usage en trajectoire (succes effectifs) ; advisory, jamais restrictif.
    "tests/nr/test_goap_preuve_annote_nr.py",
    # Preuve != parole : un OK_DONE/task_result n'est accepte qu'apres resolution+verification de son
    # pointer_ref (verdict_livrable federe arbitrer) ; sans artefact resolu, on s'abstient (cas GEMINI 27/09).
    "tests/nr/test_effet_verifie_avant_ok_done_nr.py",
    # Contrat d'etape de la facade harness : douze colonnes, UNKNOWN dit et jamais fabrique ; liste
    # BLANCHE (ACHIEVED = ALLOW+EFFECT_OBSERVED+preuve accept+effet attendu) ; completed GOAP = ACCEPTED.
    "tests/nr/test_harness_contract_nr.py",
    # Vascularisation GOAP->MCP fail-closed : un intent sans outil MCP homonyme (14/23 mesures) rend
    # "Outil inconnu" -> ERREUR, jamais `completed` ; chemin reel handle_execute + handle_plan.
    "tests/nr/test_goap_outil_inconnu_failclosed_nr.py",
    # Avertissement d'invariant : un test cite par le commit PROUVE mais disparu du depot n'est jamais
    # propose a rejouer ; il est DIT dans tests_absents (cas test_forge_veille_campagne_nr, 27/09).
    "tests/nr/test_capacites_touchees_tests_absents_nr.py",
    # SWE-bench HORS de RAG/ (decision owner 27/09) : un resolveur unique, chaque runner le prend par
    # son point d'entree ; aucun site ne reconstruit "RAG" / "swebench".
    "tests/nr/test_swebench_hors_rag_nr.py",
    # Chantier LoRA retrieval (27/09) : triplets tires du journal des succes -- INFIRME jamais positif,
    # split temporel sans fuite vers le train, ecarts COMPTES ; le mode traces reste le defaut.
    "tests/nr/test_jepa_dataset_oplog_nr.py",
    # Runner CI endormi par la rafale RAM EN PLEIN JOB (27/09, deux runs cancelled) : neverSleep
    # verifie par la cle TOML, sa lecture par le chargeur Deno et la condition de la rafale.
    "tests/nr/test_runner_ci_pas_endormi_nr.py",
    # Noeud edge deploye sur le LAN (27/09, VM DNS) : OTA fermee sans jeton, corps bornes (413),
    # codec importable hors paquet -- par le point d'entree --serve et la disposition deux fichiers.
    "tests/nr/test_edge_node_durci_nr.py",
    # Flotte edge (27/09) : pick_best_edge / contract_net ne choisissent qu'un noeud PROUVE servir le
    # chat (liste blanche) ; heartbeat TIRE des noeuds passifs, un noeud muet vieillit sans mourir.
    "tests/nr/test_edge_fleet_liste_blanche_nr.py",
    # Hub « instable » (27/09) : 1 257 s de boucle figee -- profileur par tool et journal d'intentions
    # ecrivaient embeddings.db DEPUIS la boucle (verrou 5-10 s). Ecrivain differe + schema pose une fois.
    "tests/nr/test_hub_boucle_jamais_figee_par_ecriture_nr.py",
    # Detenteur du verrou RAG a 22 h (27/09) : l'audit NREM1 purgeait rag_fts par
    # `DELETE ... WHERE chunk_id=?` (UNINDEXED = SCAN complet), 17 fois ; purge par MATCH.
    "tests/nr/test_audit_regulation_fts_sans_scan_nr.py",
    # Cliquet DEPOT (27/09) : aucune purge rag_fts par colonne UNINDEXED (chunk_id/source/id)
    # nulle part -- 11 sites trouves, le motif revenait apres chaque correction locale.
    "tests/nr/test_fts_jamais_purge_par_colonne_unindexed_nr.py",
    # Homeostat (28/09) : attribution SOI/NON_SOI/NOYAU de la pression (registre superviseur),
    # refus de sommeil du superviseur NOMME au lieu d'un `['noop']` muet.
    "tests/nr/test_homeostat_soi_non_soi_nr.py",
    # Garde action=python (28/09) : sous-processus a parite avec `run shell` sous le compte
    # bac a sable (decide cote hub), os.system n'est plus une porte ouverte, zones figees.
    "tests/nr/test_garde_python_parite_shell_nr.py",
    # Delegation (28/09) : sans jeton superviseur, un processus DECLARE son besoin de RAM au hub
    # (POST /api/resource/request, identite d'organe, ring <= 3 pour evincer, 403/429 RFC).
    "tests/nr/test_delegation_ressources_hub_nr.py",
    # Registre des dispatchers = coeur DEFENSIF : tout register_dispatcher non garde vise une methode du
    # coeur ; les handlers offensifs (ring>=3) ne se cablent que sous garde ALLOWED_METHODS (charge redteam).
    "tests/nr/test_dispatchers_coeur_defensif_nr.py",
    # Surface MCP presentee au client : la capacite deportee (lab borne) n'est PAS dans le
    # catalogue list_tools par defaut ; le lab explicitement active la re-expose (gel, pas suppression).
    "tests/nr/test_mcp_surface_lab_deportee_gatee_nr.py",
    # Taxonomies/routage du cœur : plus de domaine 'exploit' (silo), catégorie renommee
    # security_audit (configurator), sous-arbre pentest gate (skilltree) ; détection défensive gardée.
    "tests/nr/test_taxonomie_sans_routage_offensif_nr.py",
    # Gabarits de prompt `.format()` : la classe du digest muet du 22/07 (veille lot_B_09).
    "tests/nr/test_gabarits_prompt_format_nr.py",
    # Hub MCP : version negociee (plus d'echo aveugle), consignes serveur courtes,
    # decisions de chemin sur scope["path"] (CVE-2026-48710) — veilles B_15/B_20/B_33.
    "tests/nr/test_mcp_protocole_nr.py",
    "tests/nr/test_mcp_elicitation_nr.py",
    "tests/nr/test_patch_hub_elicitation_nr.py",
    "tests/nr/test_hook_instructions_loaded_nr.py",
    "tests/nr/test_ci_rouges_couverts_nr.py",
    "tests/nr/test_ordres_bureau_nr.py",
    "tests/nr/test_patch_hub_ordres_bureau_nr.py",
    "tests/nr/test_tray_calque_sur_le_panneau_nr.py",
    "tests/nr/test_hub_sse_jsonrpc_conforme_nr.py",
    "tests/nr/test_restart_garde_le_hub_nr.py",
    "tests/nr/test_stop_epargne_les_jobs_detaches_nr.py",
    # Ollama : cloud coupe a la source (le pare-feu le classe LOCAL, sans DLP) — veille B_23.
    "tests/nr/test_ollama_cloud_coupe_nr.py",
    # Applicateur de propositions : barriere avant armement (reward hacking, veille C_12).
    "tests/nr/test_applicateur_ne_touche_pas_aux_gardes_nr.py",
    # Memoire episodique : copie RAG des tours masquee par la DLP, fail-closed (veille B_05).
    "tests/nr/test_conversation_log_dlp_rag_nr.py",
    # CVE-2026-48710 : aucune decision sur le url.path de la requete (contournement d'auth MESURE
    # sous Starlette 0.52.1 sur le webhub et le graph explorer, 24/09).
    "tests/nr/test_decisions_de_chemin_sur_scope_nr.py",
    # Veille des CLI : la doc de CLAUDE CODE (code.claude.com) est surveillee, pas
    # seulement celle de l'API — elle n'avait plus tourne depuis le 20/08 (24/09).
    "tests/nr/test_veille_cli_couvre_claude_code_nr.py",
    # [HOOK:INBOX] : un signal ne se repete pas tant qu'il n'a pas change (524 lignes
    # du meme bloc dans un seul transcript, mesure du 24/09).
    "tests/nr/test_inbox_hook_sans_repetition_nr.py",
    # Strates [memoire:*] du hook de debut de tour : meme regle (58 blocs identiques, 24/09).
    "tests/nr/test_memoire_hook_sans_repetition_nr.py",
    # Ingestion llms.txt : une validation par page, le verrou RAG n'est plus tenu
    # sur tout un site (24/09, avant d'ingerer 208 + 638 pages).
    "tests/nr/test_ingest_llms_txt_valide_par_page_nr.py",
    # Delegation AGY : plus d'approbation totale par defaut (veille lot_B_12, 24/09).
    "tests/nr/test_agy_delegation_sans_approbation_totale_nr.py",
    # Authentification P0 (AUTH-2) : le hook post-commit porte SON jeton (24/09).
    "tests/nr/test_post_commit_jeton_propre_nr.py",
    # Scorecard : un echec n'est plus note OPTIMAL 1.0 (veille lot_B_33 ; patch du module
    # juge pose par l'owner le 24/09, registre branche dessus).
    "tests/nr/test_scorecard_echec_pas_optimal_nr.py",
    # Reglage (c) : le jeton du hub fourni a la connexion (headersHelper), jamais le
    # maitre en repli, jamais reecrit en clair par la synchro (24/09).
    "tests/nr/test_mcp_headers_helper_nr.py",
    # AUTH-1/2/4 : le lanceur du bureau ne parle au hub ni sans jeton ni sous un nom
    # d'emprunt (set_mode partait anonyme, 24/09).
    "tests/nr/test_lanceur_appels_hub_authentifies_nr.py",
    # #9 / AUTH-6 : revue anonyme, auto-revue, executant inconnu -> REFUS (24/09).
    "tests/nr/test_revue_fail_closed_nr.py",
    # Preuve DPoP adossee au TPM : signature seulement pour le porteur du credential
    # propre ; preuve runtime TPM reel 6/6 le 24/09.
    "tests/nr/test_dpop_tpm_autorisation_nr.py",
    # Routes admin : preuve TPM d'un organe (observation -> applique par geste owner).
    "tests/nr/test_admin_preuve_tpm_nr.py",
    # Mutations d'interface : session UI du portail + origine locale, ou jeton admin (AUTH-3/6).
    "tests/nr/test_garde_ui_mutation_nr.py",
    # Cloture des routes d'organes : identite prouvee, porteur sans maitre, publiques sans effet.
    "tests/nr/test_routes_organes_authentifiees_nr.py",
    # 2026-09-20 : RETIRE avec `forge_veille_github_direct`, supprime sur decision
    # owner (« aucune plus value si il ne prend que les titres »). Ce NR gardait un
    # contrat de DOCTRINE et non d'implementation -- « un echec reseau est ILLISIBLE,
    # jamais ABSENT », « le cas MIXTE ne prouve pas l'absence » -- et ce contrat
    # reste A RE-GARDER sur `forge_veille_clone_ingest`, dont le registre porte deja
    # les etats ABSENT / READY / STALE. Ce n'est pas une dette effacee : c'est une
    # dette DITE, qui attend son nouveau sujet.
    "tests/nr/test_AF1_declaration_vs_comportement_nr.py",
    "tests/nr/test_AB4_garde_injection_mord_nr.py",
    "tests/nr/test_AH1_recidive_par_motif_nr.py",
    "tests/nr/test_V1_confiance_etat_nomme_nr.py",
    "tests/nr/test_B4_dense_et_lexical_concurrents_nr.py",
    "tests/nr/test_AK3_baseline_lexicale_chiffrable_nr.py",
    "tests/nr/test_AH4_adaptation_mesuree_nr.py",
    "tests/nr/test_V3_phases_du_cycle_declarees_nr.py",
    # Ecrit plus tot dans cette meme session et JAMAIS inscrit — c'est le cliquet
    # de suite pure qui l'a trouve, en CI de reference, apres les huit livraisons.
    # Deuxieme fois dans la journee que mon propre NR n'est pas inscrit : ecrire
    # le test ne suffit pas, il faut l'INSCRIRE. Garde deja present cote fichier
    # (`pytest.importorskip("hypothesis")`) : un env sans la dependance SKIPPE
    # proprement au lieu d'echouer a la collecte.
    "tests/nr/test_proprietes_generatives_nr.py",
    # Les deux gardes de la PREUVE PAR BLOC, poses le 2026-09-14 apres que ce
    # fichier-la, juste au-dessus, a emporte le rapport JUnit des 9560 autres tests
    # (run 34784517659). Le premier eprouve la classification en cinq etats, le
    # second le mecanisme lui-meme sur de vrais processus -- ils ne se remplacent
    # pas : une classification juste sur un mecanisme absent ne protege rien.
    "tests/nr/test_ci_preuve_par_bloc_nr.py",
    "tests/nr/test_ci_bloc_isole_chemin_reel_nr.py",
    # Ce qui n'est pas dans le commit et entre pourtant dans le verdict : deux
    # runs du sha 714f2694a ont rendu 2 echecs puis 0, pour un `MEMORY.md`
    # reecrit entre les deux. L'empreinte rend la divergence lisible en une diff.
    "tests/nr/test_ci_empreinte_contexte_nr.py",
    # Le garde refuse TOUJOURS un sous-processus -- ces NR le prouvent d'abord,
    # et verifient ensuite que le refus nomme les chemins gouvernes. Un refus qui
    # ne dit pas par ou passer se lit « le systeme ne peut pas » : paye le 14/09.
    "tests/nr/test_workspace_guard_message_nr.py",
    # Le resume ne se contredit plus : un gate NON JUGE ne s'affiche pas vert, et
    # la ligne finale compte les suppleants au lieu de les affirmer. Paye le 14/09
    # sur ma propre certification -- « tous supplees » trois lignes sous « aucun
    # supplement declare ».
    "tests/nr/test_ci_resume_dit_vrai_nr.py",
    # L'arbre est VIVANT pendant le run : l'empreinte des fichiers a fermer est
    # figee au depart et relue avant le `git add`. Sans ce temoin, « on ne commit
    # que ce qui a ete mesure » ne tenait que tant que personne n'ecrivait.
    "tests/nr/test_ci_arbre_fige_pendant_le_run_nr.py",
    # Integrer le distant avant de publier : `git merge` echoue sous le compte
    # sandbox (lecture seule sur l'arbre), le privilege passe par un script revu.
    "tests/nr/test_sync_branche_nr.py",
    "tests/nr/test_sweep_terme_a_tiret_nr.py",
    "tests/nr/test_budget_contexte_nr.py",
    "tests/nr/test_skill_catalogue_canonique_nr.py",
    "tests/nr/test_skill_retrieval_nr.py",
    "tests/nr/test_skill_capability_graph_nr.py",
    "tests/nr/test_skill_execution_nr.py",
    "tests/nr/test_skill_execution_reel_nr.py",
    "tests/nr/test_skill_delegation_retour_nr.py",
    "tests/nr/test_F1_liveness_readiness_nr.py",
    "tests/nr/test_L1_filtrage_sortie_outil_nr.py",
    "tests/nr/test_L4_repli_dlp_sans_local_nr.py",
    "tests/nr/test_router_call_pare_feu_nr.py",
    "tests/nr/test_crawl_sans_troncature_amont_nr.py",
    "tests/nr/test_ingestion_sans_troncature_muette_nr.py",
    "tests/nr/test_intent_multi_verbe_nr.py",
    "tests/nr/test_router_observation_deux_chemins_nr.py",
    # Journal d'usage du RAG HORS base (LoRA retrieval, 2026-10-02) : triplets, rotation, appel
    # unique et garde dans le registre ; le chemin reel saute sans torch, en le disant.
    "tests/nr/test_journal_usage_rag_nr.py",
    "tests/nr/test_job_watch_bilan_gradue_nr.py",
    "tests/nr/test_rag_lexical_exclut_inactifs_nr.py",
    "tests/nr/test_post_commit_sans_scan_nr.py",
    "tests/nr/test_module_cards_sans_scan_nr.py",
    "tests/nr/test_health_audit_rag_sans_scan_nr.py",
    "tests/nr/test_backfill_sans_relecture_nr.py",
    "tests/nr/test_sweep_total_jamais_inconnu_nr.py",
    "tests/nr/test_triage_classifieur_reel_nr.py",
    "tests/nr/test_veille_pages_nr.py",
    "tests/nr/test_job_watch_portes_nr.py",
    "tests/nr/test_ci_gate_borne_duree_nr.py",
    "tests/nr/test_login_css_pourcent_nr.py",
    # Pool OpenRouter gratuit (2026-09-01). Zero service externe : catalogue
    # factice, `urlopen` remplace, slot global restaure apres chaque test.
    "tests/nr/test_openrouter_pool_free_nr.py",
    # Purge offensive + tri de la veille (2026-09-01). Zero service externe :
    # le premier opere sur du texte Python en memoire, le second sur une base
    # SQLite en :memory:. Inscrits ici parce que le cliquet de couverture l'a
    # exige (2 modules neufs sans test) et il avait raison.
    "tests/nr/test_purge_redteam_runtime_nr.py",
    "tests/nr/test_veille_triage_nr.py",
    "tests/nr/test_gardes_du_jour_nr.py",
    "tests/nr/test_generation_et_agy_bin_nr.py",
    "tests/nr/test_consolidation_capacites_nr.py",
    # Contrat intention/objectif + nerf afferent (2026-08-25). Inscrit ici parce que
    # le cliquet de purete l'a exige, et il avait raison : un test hors de cette liste
    # ne tourne PAS en CI, donc il ne protege aucune surface. Zero service externe —
    # il lit `services.toml`, evalue des objectifs en memoire, et n'ECRIT nulle part.
    "tests/nr/test_audit_intention_effet_nr.py",
    "tests/nr/test_observabilite_nr.py",
    "tests/nr/test_symbiose_nr.py",
    # Lot d'archeologie/audit du 18/08 : construit ses propres depots git dans
    # tmp_path, ne sonde que des ports fermes. Zero service externe.
    "tests/nr/test_archeologie_outils_nr.py",
    # Lot du 20/08. INSCRITS ICI SINON ILS NE GARDENT RIEN : ecrits le matin, ils
    # n'ont pas tourne une seule fois en CI de la journee -- la suite pure cite
    # ses fichiers UN A UN, et un test hors liste protege exactement zero surface
    # (meme piege que `forge_mutation_ratchet.SURFACES`, deja paye le 18/08).
    # Les trois respectent la regle « zero service externe » : entrees construites
    # en memoire ou dans tmp_path, aucun port ouvert, aucune base du depot lue.
    "tests/nr/test_lot_20260820_outils_nr.py",
    "tests/nr/test_memory_compactor_datation_nr.py",
    "tests/nr/test_capability_audit_nr.py",
    "tests/nr/test_readme_pip_nr.py",
    "tests/nr/test_doctor_vivant_nr.py",
    # Ingestion de doc (01/10) : version courante seule a la re-ingestion, agregats
    # `llms-full.txt` ecartes, entree lexicale gardee pour un chunk inchange. Base
    # sqlite EN MEMOIRE aux triggers de prod, reseau simule : aucun service.
    "tests/nr/test_ingest_llms_txt_version_courante_nr.py",
    # Cliquet golden `laforge-insert-or-ignore-rag-chunks` (01/10) : sources en memoire.
    "tests/nr/test_golden_insert_or_ignore_rag_nr.py",
    # Re-ingestion d'un depot (01/10) : le lexical garde les chunks inchanges, chemin
    # reel `ingest_file` sur un dump gitingest, sqlite en memoire aux triggers de prod.
    "tests/nr/test_reingestion_garde_le_lexical_nr.py",
    # Cliquet golden : un fichier ou un dossier NON LU n'est pas un recul (01/10).
    "tests/nr/test_golden_socle_non_lu_nr.py",
    # Superviseur (01/10) : ctl restart attend l'arret effectif et mesure l'etat
    # ATTEINT (superviseur et horloge simules) ; journaux de service hors du pool
    # bloquant (garde textuel sur supervisor.ts). Aucun service, aucun reseau.
    "tests/nr/test_ctl_restart_attend_l_arret_nr.py",
    "tests/nr/test_superviseur_journaux_synchrones_nr.py",
    # Journal sans pipe (01/10) : un vrai process Python lance par tools/forge_logboot.py,
    # journal dans tmp_path ; aucun service, aucun reseau.
    "tests/nr/test_logboot_journal_sans_pipe_nr.py",
    # 2026-10-01 : comm_watch et presence importaient `propose_fact`, ABSENT du blackboard
    # (aucun fait publie) ; le NR traverse _alert / _emit_arrival jusqu'a l'ecriture, base
    # dans tmp_path, evenements et journal d'intentions neutralises.
    "tests/nr/test_blackboard_fait_synchrone_nr.py",
    # 2026-10-01 : la porte d'admission dormait 1 s (cpu_percent(interval=1)) sur la boucle
    # du hub -- 77 % des gels sur 7 jours ; elle lit le CPU du sampler. psutil piege.
    "tests/nr/test_admission_sans_gel_de_boucle_nr.py",
    # 2026-10-01 : EcrivainDiffere perdait une ecriture au premier verrou SQLite.
    "tests/nr/test_ecrivain_differe_reprend_le_verrou_nr.py",
    # 2026-10-01 : gels de boucle mesures par la sentinelle (handle_query, list_providers,
    # _all_tools, ancetres authz) + mesure de saturation du pool to_thread.
    "tests/nr/test_boucle_hub_hors_gels_mesures_nr.py",
    # 2026-10-01 : cliquet des imports internes vers un nom ABSENT (61 mesures, 53 sous un try
    # muet) ; socle tests/nr/imports_morts_socle.json, ne peut que descendre.
    "tests/nr/test_imports_internes_morts_nr.py",
    # 2026-10-01 : ingesteur llms.txt -- GET paralleles, ecrivain unique ordonne (x4,3 mesure).
    "tests/nr/test_ingest_llms_txt_parallele_nr.py",
    # 2026-10-01 (decision owner) : un SECRET de Nokido.env se lit au coffre, jamais dans le
    # fichier ; cliquet des boucles qui recopient un .env dans os.environ.
    "tests/nr/test_secrets_noms_env_valeurs_coffre_nr.py",
    # 2026-10-01 (decision owner) : purge M2M = seulement le TRAITE (liste du postal), base M2M,
    # mode rapport tant que l'owner ne l'arme pas.
    "tests/nr/test_purge_m2m_seulement_traites_nr.py",
    # 2026-10-01 (decision owner) : couche reseau de la securite MCP restauree et corrigee
    # (SSRF precis, loopback structure, sentinelles, bearer au coffre) ; ne crie pas a faux.
    "tests/nr/test_securite_reseau_restauree_nr.py",
    # 2026-10-01 (decision owner) : API reecrites -- pont llama.cpp, keeper au tableau noir,
    # replis forge_ollama, rapport distill honnete.
    "tests/nr/test_api_reecrites_nr.py",
    # 2026-10-01 : forge_env_to_vault --alias (nom generique du .env, valeur au coffre sous
    # son vrai nom ; garde = empreinte exacte).
    "tests/nr/test_env_alias_coffre_nr.py",
    # 2026-10-01 : la rafale RAM du superviseur endormait 43 services d'un coup (regulation
    # comprise) et ne reveillait que sous 72 % -- delestage PAR COUT, reveil par cout estime,
    # quatre regulateurs exemptes. Hermetique : lit supervisor.ts / platform.ts / services.toml.
    "tests/nr/test_delestage_ram_par_cout_nr.py",
    # 2026-10-01 : soif -- lexical classe (0/30 de recouvrement avec les meilleurs sur 9 questions
    # reelles), panne RAG != lacune, un seul instrument juge, escalade sur TRANSITION seulement.
    "tests/nr/test_soif_douleur_transition_nr.py",
    # 2026-10-01 : le merge gate jugeait un candidat avec SES PROPRES tests (cwd=worktree) ; zone de
    # l'evaluateur = regle unique (mutable, merge gate, boucle gardee), self-patcher desarme (push).
    "tests/nr/test_juge_zone_evaluateur_nr.py",
    # 2026-10-01 : l'embedding Modal recevait le texte BRUT du tier chaud (memoire, code) --
    # masquage par redact_tool_output (journal=False en lot), refus sans masqueur.
    "tests/nr/test_modal_envoi_masque_nr.py",
    # 2026-10-01 : porte UNIQUE de l'evolution autonome (verrou humain, frein evolution.halt,
    # armement LAFORGE_EVOLUTION_ARMED) sur soumission, fusion appliquee et boucle gardee.
    "tests/nr/test_porte_evolution_nr.py",
    # 2026-10-01 : quarantaine des pairs entretenue automatiquement au post-commit (cloture par
    # preuve de commit, expiration des orphelins), sans jamais livrer un texte externe.
    "tests/nr/test_pair_quarantaine_entretien_nr.py",
    # 2026-10-01 : premiere CAPACITE mesuree de la fitness -- retrieval dense sur l'examen held-out
    # SCELLE (tests/baselines/retrieval_heldout_v1.json), cle examen + corpus, bruit A/A.
    "tests/nr/test_capacite_retrieval_scellee_nr.py",
    # 2026-10-01 : veille des pairs cloud (forge_job_watch_cli --pair) -- un rendu de claude.ai
    # reveille la boucle du client, metadonnees seules, jamais le texte externe.
    "tests/nr/test_veille_pairs_nr.py",
    # 2026-10-01 : AGY delegue travaille dans SON worktree (fin des invites de sortie de bac a
    # sable chez l'owner) et le resultat porte l'effet git observe, pas seulement SUCCESS.
    "tests/nr/test_agy_worktree_et_effet_nr.py",
    # 2026-10-01 : decodeur de vecteurs TOLERANT au JSON (~20 % des vecteurs en base), regle
    # unique (le doublon de forge_semantic_pressure delegue), jamais un vecteur faux.
    "tests/nr/test_decode_blob_tolerant_nr.py",
    # Routage (21/08). La regle d'abstention de l'etage SNN est testee via la
    # fonction pure decide_from_rates : aucun service, aucun reseau, et les
    # tests qui exigent torch se marquent skip si torch manque -- la CI reste
    # verte sur un runner sans torch au lieu de tomber.
    "tests/nr/test_routing_snn_nr.py",
    # Cliquet du registre d'organes (21/08) : confronte forge_organ_agents au code
    # dans les DEUX sens, et fige le cortisol comme modulateur (jamais veto).
    # Seuls des mocks : get_snapshot et forge_endocrine.read sont monkeypatches,
    # aucune ressource reelle n'est lue.
    "tests/nr/test_organ_registre_nr.py",
    # Endocrinien (21/08) : sommation multi-source ET « release ecrit ou read lit ».
    # Redirige forge_endocrine.DB vers tmp_path ; ne lit aucune base du depot.
    "tests/nr/test_endocrine_multisource_nr.py",
    # Timeout sémantique du RAGManager (21/08) : prouve que le fallback keyword
    # prend le relais SANS réattendre le thread lent. Mocks purs, aucun service.
    "tests/nr/test_rag_timeout_reel_nr.py",
    # Le cliquet qui surveille CETTE liste. S'il n'y figurait pas, il se
    # signalerait lui-meme comme orphelin -- et surtout il ne tournerait pas.
    "tests/nr/test_suite_pure_ratchet_nr.py",
    # RAPATRIEMENT 2026-08-20 : 27 fichiers, 250 tests, sortis de la dette gelee.
    # Methode, en deux temps parce que le premier ne suffit pas :
    #   1. tri STATIQUE (`forge_suite_pure_triage`) -> 39 candidats sans marqueur
    #      d'impurete (reseau, socket, port, vraie base RAG, subprocess, docker).
    #   2. execution de chacun SEUL -> 27 verts, 12 rouges. Lances ENSEMBLE, ces
    #      39 rendaient « 45 failed, 31 errors » : la presomption statique se
    #      serait donc traduite en CI rouge. Un fichier n'entre ici que s'il a
    #      PASSE seul, pas s'il en a l'air.
    "tests/nr/test_agentic_roles_nr.py",
    "tests/nr/test_arbitrage_pression_nr.py",
    "tests/nr/test_archaeology_conversations_nr.py",
    "tests/nr/test_archaeology_enrich_nr.py",
    "tests/nr/test_archaeology_nr.py",
    "tests/nr/test_await_async_nr.py",
    "tests/nr/test_bisect_nr.py",
    "tests/nr/test_capability_lineage_nr.py",
    "tests/nr/test_capability_freshness_nr.py",
    "tests/nr/test_capability_ratchet_nr.py",
    "tests/nr/test_composition_gate_nr.py",
    "tests/nr/test_constituent_archaeology_nr.py",
    "tests/nr/test_dup_detector_nr.py",
    "tests/nr/test_git_egress_protection_branche_nr.py",
    "tests/nr/test_repo_settings_audit_nr.py",
    "tests/nr/test_workflow_refs_nr.py",
    "tests/nr/test_hybrid_cortex_nr.py",
    "tests/nr/test_global_incomplet_nr.py",
    "tests/nr/test_golden_rules_apoptose_nr.py",
    "tests/nr/test_hub_envfile.py",
    "tests/nr/test_intention_non_consommee_nr.py",
    "tests/nr/test_manifest_cards_nr.py",
    "tests/nr/test_patch_crawl_offload_nr.py",
    "tests/nr/test_physiology_nr.py",
    "tests/nr/test_reachability_ledger_nr.py",
    "tests/nr/test_regulation_learner_nr.py",
    "tests/nr/test_regulation_proposer_nr.py",
    "tests/nr/test_release_lock_provenance_nr.py",
    "tests/nr/test_scalene_cmd_interpreteur_nr.py",
    "tests/nr/test_secret_migration_nr.py",
    # `test_ui_manifest_nr` est SORTI le 2026-08-20 : il compare l'etat du
    # manifest a la LIVENESS REELLE des services -- « live » sur une machine ou
    # ils tournent, « degraded » sur un runner nu. Il viole donc « zero service
    # externe », et ma validation locale ne pouvait pas le voir : mes services
    # etaient up. Seul un environnement NU tranche ce cas.
    # Couverture des deux outils de triage, exigee par le cliquet de couverture
    # -- qui a mordu sur eux des leur premier run. Le garde a eu raison.
    "tests/nr/test_suite_pure_triage_nr.py",
    "tests/nr/test_isolation_flow_nr.py",
    "tests/nr/test_generation_oplog_nr.py",
    # Retro-jointure des canaux evenementiels (2026-08-23). Pur par construction :
    # les chemins de la boite noire et de la base sont injectes, donc aucun service,
    # aucun reseau, aucune base reelle. Il protege la regle qui compte pour une
    # jointure — un voisin hors tolerance ne remplit RIEN, et absent n'est pas zero.
    "tests/nr/test_vitals_retro_join_nr.py",
    # Canaux evenementiels de la serie vitals (2026-08-23). Purs : fichiers
    # temporaires seuls. Ils gardent la regle du module — trois etats, jamais deux
    # — et la garde ANTI-FUITE du cycle de vie (seul le domaine `gate` est publie,
    # les actions reactives a la RAM contiendraient l'etiquette a predire).
    "tests/nr/test_vitals_channels_evenementiels_nr.py",
    # Contrat de provenance des traces (2026-08-23). Il grave le piege qui a produit
    # un faux negatif le jour meme : deux sources ISO NAIVES, l'une en UTC l'autre en
    # LOCAL, indistinguables a la lecture, 7200 s d'ecart. Une sonde avait conclu
    # « aucun signal » sur des traits decales de deux heures.
    "tests/nr/test_trace_spine_provenance_nr.py",
    # LOT HUB WEB, 116 tests recuperes le 2026-08-20. Ils echouaient tous en 401
    # non par defaut du code, mais parce qu'ils posaient un admin token dans
    # `os.environ` quand `AuthConfig.from_env()` interroge desormais le coffre :
    # ils se mesuraient contre le VRAI secret de la machine. `tests/nr/
    # conftest.py` rebranche le coffre sur l'environnement pour ces fichiers
    # seulement -- 46 echecs tombes a 9.
    "tests/nr/test_hub_auth.py",
    "tests/nr/test_hub_config.py",
    "tests/nr/test_hub_jti_persistence.py",
    "tests/nr/test_hub_jti_revoke.py",
    "tests/nr/test_hub_jwt_rotation.py",
    "tests/nr/test_hub_login_ui.py",
    # Ancien golden fige devenu FOSSILE (dossier `data_nr/` disparu, fixture
    # absente, .pyc d'un ancien depot). Reecrit sur des invariants CALCULES de
    # l'ordre des rings : reflexivite, transitivite, antisymetrie, sens de la
    # relation. Re-generer un golden aurait fige un etat non observe.
    "tests/nr/test_integrity_golden.py",
    # LOT DU 2026-08-20 SOIR : quatre fichiers instruits un par un, pas ecartes.
    # Aucun n'etait « cassé » -- chacun visait une realite qui avait bouge :
    #   - coverage_boost   : app/LaForge.py renomme, forge_core_agents supprime
    #                        en avril et eclate en trois modules. Il a aussi
    #                        revele un VRAI NameError de production.
    #   - mutation_ratchet : une surface peut nommer PLUSIEURS suites.
    #   - hub_launcher / m : le module `recon` a disparu du registre, et le
    #                        module `hub` porte api_managed=False par conception.
    "tests/nr/test_coverage_boost_nr.py",
    "tests/nr/test_mutation_ratchet_nr.py",
    "tests/nr/test_hub_launcher.py",
    "tests/nr/test_hub_m.py",
    # Dernier de la dette instruite : il exigeait `LocalMutationManager.py` a la
    # racine. Ce fichier a ete BALAYE le 2026-03-26, retrouve par le census
    # Phase 7 et remis en service sous `app/forge_self_mutation.py`. Le test
    # reclamait donc le retour d'un NOM ; la capacite, elle, n'avait pas bouge.
    "tests/nr/test_evolutionary_nr.py",
    # LOT BOUCLE D'ÉVOLUTION (2026-08-22). Zéro service externe : extraction de
    # code objet, monkeypatch, stub sys.modules, tmp_path, ou lecture de fichiers
    # du dépôt (services.toml). Inscrits ici SINON ILS NE GARDENT RIEN (même piège
    # que le lot du 20/08). Le module forge_successor_repr est ancré à predict_impact.
    "tests/test_autonomous_loops_ram_gate.py",
    "tests/test_evolution_cable.py",
    "tests/test_self_patcher_thymus.py",
    "tests/test_forge_successor_repr.py",
    "tests/test_predict_impact_sr.py",
    "tests/nr/test_successor_repr_nr.py",
    # Adapter securite (2026-08-22) : borne offensif/defensif, fail-closed par defaut.
    "tests/nr/test_security_lab_adapter_nr.py",
    # SDR encoder (2026-08-22) : intention neuro tendue, ancree a successor_repr.
    "tests/nr/test_sdr_encoder_nr.py",
    # Gate mode CTF du cerveau (2026-08-22) : DEPLACE le 2026-09-04 vers le depot
    # redteam (decision owner, applique par Antigravity) -- sa densite lexicale
    # declenchait le classifieur cyber cote client. Le garde n'est PAS supprime : il
    # vit et s'execute dans cet autre depot. Il est retire d'ICI parce qu'un test
    # declare et absent du disque faisait crier la CI a chaque run (« 1 test DECLARE
    # mais ABSENT »), et un garde qui crie a faux finit par etre ignore. Ne pas le
    # re-inscrire sans l'avoir rapatrie.
    #
    # Un motif de prefixe en LIKE neutralise l'index de la cle (2026-09-04) : SQLite
    # ne peut pas le reecrire en bornes, faute de sensibilite a la casse, et balaie
    # la table entiere malgre un index present. Mesure a l'origine du garde : 24,9 Go
    # lus a chaque ancrage de lecon, d'ou un timeout qui tuait cette suite SANS
    # verdict. `GLOB` est indexable ; le joker en tete reste hors sujet (remede FTS).
    "tests/nr/test_like_prefixe_indexable_nr.py",
    # Instrument de mesure de la CI elle-meme (profil sequentiel / comparaison
    # xdist). Ses deux gardes d'effet : le mode parallele ne passe jamais
    # `--capture=no` (xdist exige la capture, l'oubli se lirait « xdist casse la
    # suite »), et un rapport JUnit absent rend None et non « 0 echec ».
    "tests/nr/test_ci_profil_nr.py",
    # Liveness des organes (2026-09-04) : trois etats jamais deux, et jamais de
    # verdict sur une provenance inconnue. Fige la distinction entre un organe
    # ETEINT PAR DECISION (`disabled = true`) et un organe en PANNE — la moitie
    # des silences mesures ce jour-la etaient voulus.
    "tests/nr/test_liveness_registre_organes_nr.py",
    # Aucun module ne lance un executable depuis une racine temporaire (2026-09-04).
    # Un tel chemin echappe a git, a la CI, au git-gate et au gate de secrets EN MEME
    # TEMPS. Deux fois paye : copie de 6 semaines le 30/07, puis de 77 jours le 04/09
    # dans un autre module. Detection par AST pour ne pas accuser un commentaire.
    "tests/nr/test_aucun_executable_hors_depot_nr.py",
    # L'outil d'audit lui-meme : un audit qui se trompe de classement fait supprimer
    # ce qui sert ou rassure sur ce qui nuit. Fige la couverture multi-volumes, la
    # distinction ABSENT/ILLISIBLE/DIVERGENTE, et la mise en cache de l'index.
    "tests/nr/test_audit_copies_hors_depot_nr.py",
    # Niveaux de preuve d'un service (2026-09-04) : un socket TCP ouvert ne demarre
    # rien. Formalise la semantique deja ecrite dans forge_capability_contracts le
    # 18/08 (TRANSPORT / APPLICATIF / CAPACITE, un 401 comptant comme VIVANT), que
    # quatre sondes violaient faute de la connaitre. Deux formes de conformite :
    # monter au niveau applicatif, ou declarer honnetement le niveau atteint.
    "tests/nr/test_niveaux_de_preuve_service_nr.py",
    # Pas 1 de l'arbre d'evolution : le garde de mutation precede le juge.
    "tests/nr/test_lats_garde_mutation_nr.py",
    # Cycle complet : garde + bac + juge + selection, sur un vrai depot git
    # construit dans tmp_path. Aucun service externe, aucun reseau -- git et
    # pytest sont locaux, comme pour le lot d'archeologie deja whiteliste.
    "tests/nr/test_lats_cycle_complet_nr.py",
    # Table de verite du verdict CI : quatre etats sur cinq interdisent de
    # conclure. Aucun appel reseau -- les reponses GitHub sont fabriquees.
    "tests/nr/test_ci_verdict_nr.py",
    # Swarm a preuves concurrentes (2026-08-20) : un provider qui tombe ne
    # casse plus la tache, un provider qui repond ne devient plus la verite.
    "tests/nr/test_swarm_evidence_nr.py",
    "tests/nr/test_swarm_router_modes_nr.py",
    # Un argument inconnu de governed_edit doit refuser, pas etre absorbe.
    "tests/nr/test_governed_edit_args_nr.py",
    # Forme intacte, politique inversee : le cas que MutationGuard ne voit pas.
    "tests/nr/test_semantic_invariant_nr.py",
    # Gate « zero tuile orpheline » (doctrine GUI live-only, owner 2026-08-21) :
    # bijection SERVICES <-> catalogue live, etats bornes, cibles reelles, anti-demo.
    "tests/nr/test_tuile_orpheline_nr.py",
    # Effets des modules du 21/08 (cliquet couverture) : couche HTTP bench
    # factorisee + signature d'identite process (phase 1).
    "tests/nr/test_bench_http_nr.py",
    "tests/nr/test_process_identity_nr.py",
    # Sonde tuiles (phase 3 live-only) : healthcheck HTTP -> degraded mesure.
    "tests/nr/test_probe_service_nr.py",
    # Infra navigateur/UI-oracle restauree (separation offensif/defensif 2026-08-22,
    # ex-tools/ctf) : effets purs, zero lancement de navigateur, zero service.
    "tests/nr/test_playwright_browser_nr.py",
    # `test_redteam_link_nr.py` a ete RETIRE le 2026-08-25 : ni le test, ni
    # `forge_redteam_link.py`, ni aucun fichier portant « redteam » ne subsiste dans
    # le depot depuis la separation du lab du 22/08. Il restait declare ici, donc
    # filtre en silence a chaque run -- aucune couverture perdue par ce retrait,
    # elle avait deja disparu trois jours plus tot sans que rien ne le dise.
    # Chargement des tokens PyPI au coffre (2026-08-22) : parse pypirc + set_secret
    # mocke. Effets purs, aucun vrai coffre, aucun reseau.
    "tests/nr/test_load_pypi_creds_nr.py",
    # Gardes du watchdog de daemons (2026-08-25) : etat declare, cooldown persiste,
    # post-condition sur la FRAICHEUR du heartbeat, budget puis quarantaine. Plus le
    # capteur d'interpreteur a trois etats. Popen remplace, etat en tmp_path : aucun
    # process lance, le sandbox vivant n'est pas touche.
    "tests/nr/test_watchdog_gardes_nr.py",
    # Post-condition circadienne (2026-08-25) : une phase n'est soldee que si ses
    # actions ont abouti, et JAMAIS depuis un dry-run. Doublures d'actions et d'etat :
    # aucun service redemarre, circadian_state.json jamais touche.
    "tests/nr/test_circadian_postcondition_nr.py",
    # 2026-09-20 : l'index des symptomes ne doit pas indexer son propre
    # vocabulaire. Ses 4 jetons les plus frequents etaient lui-meme et son
    # garde (826 occurrences), ce qui faisait de toute session editant le garde
    # un faux voisin de toutes les autres -- 4 refus a tort le meme jour.
    # Le NR du chemin REEL du circadien (test_circadien_chemin_reel_nr) n'est
    # deliberement PAS declare ici : il reste ROUGE sur `NokidoAutoCompact`,
    # reference morte assumee dont la correction serait une decision de charge.
    "tests/nr/test_symptom_index_auto_reference_nr.py",
    # 2026-09-20 : /admin/* ne reconnaissait que le master, si bien que le jeton
    # PROPRE du superviseur (seme le 02/09) rendait 401 la ou le master rendait
    # 200 -- et `_hubAuthHeaders()` prefere le propre des qu'il existe. Deux des
    # trois lancements NREM1 en sont morts, snapshot memoire perime de 14,25 j.
    # Ce NR garde l'elargissement ET ses bornes : liste blanche NOMMEE (jamais un
    # seuil de ring, qui ouvrirait /admin a CLAUDE et GEMINI), porteur exige,
    # comparaison en temps constant, master toujours accepte, et 401 conforme
    # RFC 7235 section 4.1 REELLEMENT appele.
    "tests/nr/test_admin_jeton_propre_organe_nr.py",
    # 2026-09-20 — CINQ NR ecrits ce soir etaient sur le disque et INVISIBLES aux
    # deux CI. « Un test commite mais NON declare ne tourne nulle part » (lecon du
    # 2026-09-19) : la faute etait deja consignee, et elle a ete recidivee cinq
    # fois dans la meme session. Le verdict ci-dessous vient d'une EXECUTION, pas
    # d'une lecture du fichier -- une sonde textuelle avait classe « vert » un NR
    # rouge parce que sa justification vivait dans le message de commit.
    "tests/nr/test_generation_differee_reinjecte_nr.py",
    "tests/nr/test_generation_promotion_nr.py",
    "tests/nr/test_declare_wanted_declare_son_emission_nr.py",
    "tests/nr/test_backlog_serie_temporelle_nr.py",
    "tests/nr/test_intention_ecriture_verifiee_nr.py",
    "tests/nr/test_deps_on_demand_ont_un_rallumeur_vivant_nr.py",
    "tests/nr/test_keeper_piliers_only_nr.py",
    "tests/nr/test_piliers_constatent_leur_transduction_nr.py",
    "tests/nr/test_drapeau_corrompu_est_reparable_nr.py",
    "tests/nr/test_differenciation_declare_son_couplage_nr.py",
    "tests/nr/test_preflight_ne_repond_pas_avec_du_code_tiers_nr.py",
    "tests/nr/test_preflight_verbose_priorise_le_corps_nr.py",
    "tests/nr/test_inbox_dit_l_age_et_le_sha_nr.py",
    "tests/nr/test_ami_train_dit_sur_quoi_il_s_entraine_nr.py",
    "tests/nr/test_m2m_identite_et_incarnation_nr.py",
    "tests/nr/test_m2m_sceau_integrite_nr.py",
    "tests/nr/test_tile_state_trois_etats_nr.py",
    "tests/nr/test_tpm_cle_par_agent_nr.py",
    "tests/nr/test_registre_identite_unicite_nr.py",
    # Pur : lit `config/agent_identities.json` et appelle des fonctions de
    # resolution, aucun service, aucun reseau. Adversarial et non census — il
    # attaque la RESOLUTION la ou le voisin ci-dessus verifie la STRUCTURE.
    "tests/nr/test_identite_escalade_par_alias_nr.py",
    # Pur : `_HEALTH` substitue vers `tmp_path`, cache vide, aucune valeur de
    # secret lue ni ecrite — le ledger reel n'est jamais touche.
    "tests/nr/test_revocation_ne_s_efface_pas_nr.py",
    # Pur : ne cree, n'ouvre ni ne supprime AUCUNE cle TPM — il lit des
    # signatures de fonctions et des textes. Passe donc identiquement sur une
    # machine sans TPM et sur un compte sans droits.
    "tests/nr/test_tpm_isolation_nest_pas_non_exportabilite_nr.py",
    # Pur : analyse des chaines et des fichiers de `tmp_path`, aucun secret lu.
    # C'est le NR de l'INSTRUMENT — il prouve les deux bords, qu'il mord et
    # qu'il ne crie pas a faux (3 faux positifs reels verrouilles).
    "tests/nr/test_secret_egress_gate_nr.py",
    # Pur : faux depots sous `tmp_path`, attestation substituee, coffre JAMAIS
    # touche. Il eprouve les REFUS de l'outil, pas son import.
    "tests/nr/test_rotation_proof_garde_nr.py",
    # Pur : `_API_KEYS` et `_HEALTH` substitues, credentials SYNTHETIQUES,
    # `Nokido.env` fabrique dans `tmp_path`. Le cache d'un hub en service n'est
    # jamais touche, aucune vraie cle n'est lue. NR de MESURE : il etablit ce
    # que `_API_KEYS` EST, il ne le corrige pas.
    "tests/nr/test_api_keys_provenance_et_revocation_nr.py",
    # Pur : l'artefact sensible est FABRIQUE dans le test, avec des jetons
    # synthetiques. Aucun fichier d'environnement reel n'est lu ni nomme.
    "tests/nr/test_audit_sortie_bornee_nr.py",
    # Pur : la classification des codes NCrypt est une fonction SANS effet ;
    # la sonde ouvre et referme, ne cree jamais. Passe sur une machine sans TPM
    # (elle rend INDETERMINE) — le NR ne juge jamais la MACHINE.
    "tests/nr/test_tpm_etat_cle_trois_etats_nr.py",
    # Pur : lecture seule d'ACL, aucune cle creee ni modifiee. Sur une machine
    # sans la cle il rend ABSENTE/INDETERMINE et reste vert — il teste LA
    # MESURE, jamais un SDDL particulier, qui serait une sonde sur le POSTE.
    "tests/nr/test_tpm_descripteur_lecture_seule_nr.py",
    # Pur : AUCUNE ecriture d'ACL. Tous les cas passent par le dry-run ou par
    # un refus ; la cle reelle n'est jamais modifiee. Il teste les INVARIANTS
    # (droit borne, etat capture, conservation des ACE), jamais un SDDL.
    "tests/nr/test_tpm_acl_gouvernee_nr.py",
    # Pur : n'ecrit rien, ne cree rien. Si la cle n'est pas ouvrable depuis le
    # compte courant, il se declare skip en DISANT pourquoi — il verrouille le
    # cycle LA OU il est possible, il ne juge jamais la MACHINE.
    "tests/nr/test_tpm_cycle_hub_reel_nr.py",
    # Pur : cle HMAC locale au fichier, aucun secret du corps. N'arme aucun
    # enforcement — il verifie que l'echec de signature TPM est DIT, pas qu'il
    # refuse. Sur une machine ou la signature aboutit, le test de journal se
    # declare skip en le disant (c'est le cas nominal).
    "tests/nr/test_tpm_demande_non_obtenue_nr.py",
    # Pur : formes de jetons FABRIQUEES dans le test, aucun porteur reel,
    # aucune decision d'autorisation touchee. Il verrouille surtout un REFUS —
    # qu'un troisieme segment non verifie ne soit jamais compte comme preuve.
    "tests/nr/test_authz_shadow_axe_tpm_nr.py",
    # HORS CI, DELIBEREMENT, et dit ici pour que l'omission ne passe pas pour un
    # oubli : tests/nr/test_admin_run_job_observable_nr.py (3 failed) et
    # tests/nr/test_circadien_chemin_reel_nr.py (1 failed, NokidoAutoCompact) sont
    # des NR ROUGES en attente de leur correctif. Ils entreront avec lui.
    # Accelerateur de vectorisation (2026-08-25) : le niveau de TSH_VECTORIZATION doit
    # ATTEINDRE le seuil que `forge_rag_warmup` applique reellement (0.4). L'ancienne
    # courbe ne le franchissait qu'en dessous de 48 % de corpus vectorise, et n'emettait
    # RIEN entre 80 et 95 %. `release` est double : aucune ecriture endocrinienne.
    "tests/nr/test_endocrine_vectorisation_nr.py",
    # Cellule vivante / organe mort (2026-08-25) : un keeper qui BAT n'atteste pas que
    # son organe repond, et un organe eteint n'est une panne que si un `.wanted` frais
    # le reclame. Effets purs, SANDBOX redirige vers tmp_path.
    "tests/nr/test_keeper_organe_nr.py",
    # Memoire de travail a strates (2026-08-25) : salience INVERSEE des dettes (une
    # obligation s'aggrave avec l'age, contrairement a une observation), et les trois
    # regles que l'organe s'impose — dire ce qu'on n'a pas vu, compter ce qu'on ecarte,
    # porter sa provenance. Registre double : aucun acces au blackboard reel.
    "tests/nr/test_memoire_active_nr.py",
    # Contrat de donnees RAG -> prompt (2026-08-25) : le chemin principal lisait
    # `text` quand le moteur emet `content`, donc le contexte injecte n'avait QUE des
    # en-tetes depuis le 2026-05-29. Moteur double, aucun index charge.
    "tests/nr/test_rag_contrat_proxy_nr.py",
    # Promotion en memoire globale + date d'origine au rappel (2026-08-25) : une
    # reponse LLM non verifiee n'atteint plus le tier vectorisable, et `recall` cesse
    # d'ecraser `archived_at` par la date du rappel. Connexion doublee, base intacte.
    "tests/nr/test_memoire_promotion_nr.py",
    # Validite temporelle et supersession (2026-08-25) : `valid_from` / `valid_to` /
    # `superseded_by` dans le meta JSON aux cotes de `consensus_level`, predicat
    # as-of, et fermeture d'un fait remplace SANS l'effacer. Base en memoire.
    "tests/nr/test_verite_temporelle_nr.py",
    # Emetteurs de la couche epistemique (2026-08-26) : extraction locale a trois
    # etats, reevaluation qui ECRIT claim_reevaluations, supersession sur contradiction
    # reelle (autorite respectee, colonne + meta), porte draft->verified par
    # corroboration independante, filtre as-of sur le chemin vivant, retention
    # core_memory declaree. LLM double, base temporaire, aucun ecrivain reel.
    "tests/nr/test_epistemique_emetteurs_nr.py",
    # Recensement du cablage des interfaces (2026-08-26) : classifieur pur
    # element -> cible -> verdict (CABLE / CABLE_AUTH / MORT / JS_OPAQUE / VISUEL /
    # CONTROLE), invisibilite agent, rapport. Aucun navigateur.
    "tests/nr/test_ui_nervous_census_nr.py",
    # Liens du dashboard (2026-08-26) : le lien d'une tuile suit ce qui est MONTE puis
    # ce qui est DECLARE, jamais sa cle -- deux tuiles rendaient 404. Fonctions pures +
    # lecture du registre du portail, aucun service.
    "tests/nr/test_dashboard_liens_nr.py",
    # Gain collectif (2026-08-26) : ce que le fanout apporte ET ce qu'il retire,
    # mesure sur ses PROPRES baselines (oracle et moyen) sans appel supplementaire,
    # avec le cout enfin conserve. Tentatives construites en memoire, LLM double.
    "tests/nr/test_gain_collectif_nr.py",
    # UI generee par LLM (2026-08-26) : un widget produit par un modele ne sert plus
    # une route qu'il a INVENTEE (cas reel /alerts, 404 en prod). Fonctions pures.
    "tests/nr/test_ui_generee_cibles_nr.py",
    "tests/nr/test_ui_delier_cdn_nr.py",
    "tests/nr/test_search_replace_zero_bloc_nr.py",
    "tests/nr/test_collective_gain_agregat_nr.py",
    "tests/nr/test_docs_souverains_nr.py",
    "tests/nr/test_import_niveau_module_nr.py",
    "tests/nr/test_ci_verdict_junit_nr.py",
    # Cycle swarm 1 (2026-09-07) : le budget d'attente sur verrou doit tenir SOUS le
    # `--timeout=30` de cette suite. Volontairement ROUGE tant que l'interrupteur
    # `forge_db_path.busy_ms()` n'existe pas -- c'est le signal de completion remis a
    # l'executant, pas un oubli.
    "tests/nr/test_socle_attente_bornee_nr.py",
    # Certificateur du cycle collaboratif : le NR fait foi, pas le rapport de l'agent.
    "tests/nr/test_cycle_verdict_nr.py",
    # Premier test du juge canonique du manifesto. 3 cas en xfail(strict) : la
    # correction est un geste owner, forge_separation interdisant a un agent de
    # modifier son propre juge. La dette est donc portee par la CI, et le jour ou
    # elle est reparee les xpass feront echouer la suite -- ce qui est voulu.
    "tests/nr/test_scorecard_axe_non_mesure_nr.py",
    # Le garde de separation transporte le ring prouve au lieu de le recalculer.
    "tests/nr/test_separation_identite_transportee_nr.py",
    # Un palier de duree ne solde pas ce qui tourne, et un succes efface l'echec
    # precedent : « pas de palier de duree si pas fini » (owner 2026-09-07).
    "tests/nr/test_budget_chaine_ne_solde_pas_le_travail_nr.py",
    # SERVING AUDIT : une veille n'est ingeree que si Nokido sait la RETROUVER.
    # Hermetique -- base fabriquee au schema reel, aucun service externe.
    "tests/nr/test_veille_serving_audit_nr.py",
    # 2026-09-08 : inventaire, completude et moisson du patrimoine de veille.
    # Chaque test encode un defaut PAYE le jour meme (fichiers pris pour des
    # depots, pages web hors inventaire, verdict de troncature indefendable).
    "tests/nr/test_veille_inventaire_nr.py",
    "tests/nr/test_veille_completude_nr.py",
    "tests/nr/test_veille_moisson_nr.py",
    "tests/nr/test_route_async_bloquante_nr.py",
    "tests/nr/test_montage_prefixe_nr.py",
    "tests/nr/test_vitals_cache_nr.py",
    "tests/nr/test_ui_repli_donnees_reelles_nr.py",
    "tests/nr/test_sse_deconnexion_nr.py",
    "tests/nr/test_route_affichage_bornee_nr.py",
    "tests/nr/test_ancrage_sans_redite_nr.py",
    "tests/nr/test_tuile_reveil_ondemand_nr.py",
    "tests/nr/test_hub_journal_de_fin_nr.py",
    "tests/nr/test_debate_providers_reels_nr.py",
    "tests/nr/test_ui_pages_rendent_nr.py",
    "tests/nr/test_epistemic_schema_absent_nr.py",
    "tests/nr/test_ps1_parse_gate_nr.py",
    "tests/nr/test_rag_search_route_nr.py",
    "tests/nr/test_forge_hooks_install.py",
    "tests/nr/test_forge_release_gate_nr.py",
    "tests/nr/test_forge_history_secret_audit_nr.py",
    "tests/nr/test_forge_public_mirror_nr.py",
    "tests/nr/test_forge_secret_rotation_check_nr.py",
    "tests/nr/test_orphan_reaper_refractaire_nr.py",
    "tests/nr/test_forge_patch_lane_auto_nr.py",
    "tests/nr/test_forge_tui_textual_nr.py",
    "tests/nr/test_forge_patch_vitals_sse_nr.py",
    "tests/nr/test_forge_outils_dynamiques_nr.py",
    "tests/nr/test_forge_patch_socle_nr.py",
    "tests/nr/test_webhub_journal_de_vie_nr.py",
    "tests/nr/test_pty_widget_local_nr.py",
    # Semantique d'echec de la veille et du gate (2026-08-30). Tous hermetiques :
    # aucun service externe, aucun modele joint, aucun reseau -- les sources, le
    # crawl et la cascade sont remplaces par des faux, et les bases sont des
    # `tmp_path`. Ils sont declares ICI parce qu'un test hors PURE_TESTS ne tourne
    # PAS en CI et ne protege donc aucune surface : ecrits sans cette ligne, ils
    # donnaient l'illusion d'un filet qui n'existait pas.
    "tests/nr/test_wal_checkpoint_nr.py",
    "tests/nr/test_embed_regulation_campagne_nr.py",
    "tests/nr/test_veille_non_mesuree_nr.py",
    "tests/nr/test_veille_verdict_chaine_nr.py",
    "tests/nr/test_veille_digest_auto_nr.py",
    "tests/nr/test_veille_provider_contrat_nr.py",
    "tests/nr/test_vault_mint_agent_token_nr.py",
    "tests/nr/test_digest_prompt_et_pont_local_nr.py",
    "tests/nr/test_digest_matiere_rag_nr.py",
    "tests/nr/test_digest_parseur_json_nr.py",
    "tests/nr/test_digest_affectation_organe_nr.py",
    "tests/nr/test_veille_github_changement_nr.py",
    "tests/nr/test_veille_github_capteur_nr.py",
    "tests/nr/test_veille_rattachement_dumps_nr.py",
    "tests/nr/test_veille_detecteur_multivoies_nr.py",
    "tests/nr/test_heartbeat_amorce_syspath_nr.py",
    "tests/nr/test_docker_bail_usage_nr.py",
    "tests/nr/test_docker_surface_et_coupure_nr.py",
    "tests/nr/test_veille_e2e_check_nr.py",
    "tests/nr/test_log_surface_nr.py",
    "tests/nr/test_regulation_age_heartbeat_nr.py",
    "tests/nr/test_crawl_tier1_nr.py",
    "tests/nr/test_docker_antiboucle_nr.py",
    "tests/nr/test_coder_liveness_composite_nr.py",
    "tests/nr/test_arbitre_entrees_audit_nr.py",
    "tests/nr/test_backlog_innervation_nr.py",
    "tests/nr/test_disque_occupation_nr.py",
    "tests/nr/test_journal_decision_nr.py",
    "tests/nr/test_association_abstention_detresse_nr.py",
    "tests/nr/test_reflexes_recurrents_nr.py",
    "tests/nr/test_switches_db_isolee_nr.py",
    "tests/nr/test_veille_reflist_et_cap_nr.py",
    "tests/nr/test_loop_kill_seuil_nr.py",
    "tests/nr/test_fts_delete_conditionnel_nr.py",
    "tests/nr/test_veille_github_selection_nr.py",
    "tests/nr/test_veille_backfill_un_chunk_nr.py",
    "tests/nr/test_job_runner_garde_et_pdf_cap_nr.py",
    # Dette D (2026-10-02) : chaque fiche de job porte timed_out (VRAI/FAUX/INCONNU) et sa
    # cause de fin ; compteur des timeouts sur les N derniers jobs par script.
    "tests/nr/test_job_fin_capteur_timeout_nr.py",
    "tests/nr/test_m2m_hors_embeddings_nr.py",
    "tests/nr/test_organ_declare_nr.py",
    # Anatomie 06/09 : le lecteur (census) et l'ecrivain (declare) partagent fenetre et
    # regex ; l'audit de regulation instruit ses zones mortes et lit le systeme a 3
    # etats. tmp_path + monkeypatch (subprocess.run remplace), aucun service.
    "tests/nr/test_census_declaration_fenetre_nr.py",
    "tests/nr/test_body_regulation_instruction_nr.py",
    "tests/nr/test_census_check_gate_nr.py",
    # Balayeurs 06/09 : le drain Qdrant impose l'ordre de boucle (CROSS JOIN) et le NR
    # verifie le PLAN sur une base fabriquee au meme schema. Aucun service.
    "tests/nr/test_qdrant_sync_plan_nr.py",
    "tests/nr/test_balayeurs_lisent_le_producteur_nr.py",
    # Bascule M2M 06/09 : le curseur de l'inbox Claude est lie a sa base (rebase si
    # la base change). sqlite en tmp_path, hook importe sans effet de bord.
    "tests/nr/test_inbox_tick_curseur_par_base_nr.py",
    # Lanceur 06/09 : mode --action non interactif, refus dit des actions Bureau sous
    # un compte de service, repli NSSM retire. Import sans effet de bord, aucun reseau.
    "tests/nr/test_nokido_launcher_cli_nr.py",
    "tests/nr/test_stop_epargne_les_ponts_clients_nr.py",
    "tests/nr/test_effet_reel_audit_nr.py",
    "tests/nr/test_embed_batch_cascade_politique_nr.py",
    "tests/nr/test_embed_drain_garde_ram_nr.py",
    "tests/nr/test_embed_outils_mesure_nr.py",
    "tests/nr/test_raccourcis_cibles_existent_nr.py",
    "tests/nr/test_embed_campagne_suspend_nr.py",
    "tests/nr/test_homeostasis_rythmes_nr.py",
    "tests/nr/test_mcp_lab_amont_muet_nr.py",
    "tests/nr/test_embed_quota_sommeil_nr.py",
    "tests/nr/test_hf_providers_bge_nr.py",
    "tests/nr/test_espace_vectoriel_preuve_nr.py",
    "tests/nr/test_embed_onnx_gate_identite_nr.py",
    "tests/nr/test_webhub_auth_asgi_pur_nr.py",
    "tests/nr/test_env_neutralisation_coffre_nr.py",
    # Inscrits le 2026-09-14 : un NR non declare ici n'est JAMAIS joue, donc il ne
    # garde rien -- c'est le piege que ce fichier documente plus haut, et il a
    # failli me reprendre le jour meme. Le premier verrouille le garde
    # anti-regression du deployeur de bundle (83,6 jours d'ecart mesures, cible
    # maintenue a la main) ; le second verifie que la cle du relais MCP vient du
    # COFFRE et n'apparait jamais dans une ligne de commande.
    "tests/nr/test_deploy_hub_bundle_nr.py",
    "tests/nr/test_tunnel_client_launch_nr.py",
    "tests/nr/test_deps_reconciliation_nr.py",
    "tests/nr/test_job_watch_notify_generique_nr.py",
    "tests/nr/test_sous_agent_deporte_nokido_nr.py",
    "tests/nr/test_wasm_defaut_start_et_motif_nr.py",
    "tests/nr/test_deps_rapport_courant_nr.py",
    "tests/nr/test_litellm_tiktoken_hors_ligne_nr.py",
    "tests/nr/test_license_guard_bsl_homonyme_nr.py",
    "tests/nr/test_generation_capture_untracked_nr.py",
    # Dimension du routeur DT (2026-09-09). Le modele entraine attendait 36 traits
    # quand le source en declarait 35 : l'etage DT ne routait plus, en silence, et
    # l'assert du module ne pouvait pas le voir — il ne compare que le source a
    # lui-meme. Zero service externe : deux fichiers du depot, lecture AST, aucun
    # import du module teste (son extracteur joint des providers a l'instanciation).
    "tests/nr/test_router_dt_dimension_modele_nr.py",
    # Passeur de generations (2026-09-09). La CI mesurait sa generation, la jugeait
    # STABLE, et ne pouvait pas l'inscrire : docs/generations n'est pas inscriptible
    # par les comptes sandbox. Elle deposait donc en attente et le disait -- mais
    # aucun passeur ne venait chercher, la ou la vitalite avait le sien depuis le
    # 2026-09-07. Le garde prouve ici est l'append-only : une generation date un sha
    # et un verdict, elle ne se reecrit pas. Zero service externe : tout en tmp_path.
    "tests/nr/test_generation_inscrire_nr.py",
    # T0, isolation de la preuve (2026-09-09). La CI de reference tenait un ARBRE la
    # ou elle devait tenir un SHA : `git status` etait lu dans le working tree, donc
    # la validite du verdict dependait des trois autres surfaces actives pendant 20
    # minutes. Le NR verrouille les deux pieges du remede : la recursion (le drapeau
    # ne se repasse pas au worktree) et surtout le FAIL-OPEN (un worktree impossible
    # REFUSE en le nommant, au lieu de retomber sur l'arbre partage et de rendre un
    # verdict qui ressemble a un verdict). A SAVOIR : le worktree ne porte que les
    # fichiers TRACKES -- un socle calibre sur l'arbre de travail peut donc y voir un
    # site de moins, et c'est correct : le sha ne contient pas les non-suivis.
    "tests/nr/test_ci_reference_worktree_nr.py",
    # Lecteur JSON a trois etats, factorise le 2026-09-09. Ecrire un passeur « sur le
    # patron » d'un autre voulait dire RECOPIER `_lire` (52 noeuds) : le cliquet de
    # clones l'a vu au premier push et a casse la CI GitHub (run 34342552425, seul
    # gate rouge sur 16). Le remede n'etait pas de regeler son socle. Ce NR est plus
    # STRICT que le cliquet, et c'est voulu : le cliquet compte des PAIRES, donc il
    # se tait des qu'un seul des deux jumeaux disparait, en laissant la copie
    # orpheline prete a re-cloner au passeur suivant.
    "tests/nr/test_lecture_json_trois_etats_nr.py",
    # Suppleance versionnee (2026-09-09). Le verdict vert du matin s'appuyait sur un
    # rapport pip-audit qui n'etait dans AUCUN commit : invisible depuis le worktree
    # de reference, ou le gate a rendu « 1 gate CRITIQUE non mesure ». L'isolation
    # n'a pas casse la preuve, elle a montre qu'elle empruntait une bequille. Second
    # garde du meme NR : un checkout rajeunit tous les mtimes, donc la fraicheur se
    # lit dans le NOM du rapport, jamais sur le fichier.
    "tests/nr/test_mesure_deportee_versionnee_nr.py",
    # Ordre capture-puis-journal (2026-09-09). La CI ecrivait tests/nr/vitalite_
    # gardes.json -- un fichier SUIVI -- avant de tester la proprete de l'arbre :
    # elle se retirait a elle-meme le droit de capturer son sha. Une ACL masquait le
    # defaut dans l'arbre principal ; le worktree de reference, inscriptible, l'a
    # rendu systematique. Un instrument ne modifie pas ce qu'il mesure avant de
    # l'avoir mesure.
    "tests/nr/test_capture_avant_vitalite_nr.py",
    # Boite M2M canonique (2026-09-09). `agent_messages` portait trois espaces de
    # noms pour les memes acteurs (`CLAUDE` a cote de `agt_claude`, `agt_agt_gemini`
    # a double prefixe) : les tick lisent UNE forme exacte, donc ~37 messages non lus
    # dormaient sans lecteur -- pour Gemini et Antigravity autant que pour moi. Le
    # second test pose la FRONTIERE : la normalisation reste mecanique, car le
    # registre du videur fusionne GEMINI et ANTIGRAVITY que RULES_SHARED distingue.
    "tests/nr/test_boite_m2m_canonique_nr.py",
    # Correctifs annonces mais ININSTALLABLES (2026-09-09). Un avis nomme la version qui
    # corrige, pas celle qu'on peut poser. DEUX causes, toutes deux payees : l'interpreteur
    # (litellm 1.84 exige Python <3.14) et le RETRAIT UPSTREAM (transformers 5.10.0 est
    # YANKED par ses auteurs, et c'est pourtant ce que pip-audit ET Dependabot recommandent).
    # Sans borne, une campagne de montee installe une version desavouee par son editeur.
    "tests/nr/test_correctif_hors_de_portee_nr.py",
    # Interface web mesuree des qu'elle repond (2026-09-09). `ui-acceptance` est
    # declare CRITIQUE et etait garde derriere `--ui-gate`, un drapeau que la CI
    # standard ne passe jamais : le domaine le plus visible du systeme n'etait mesure
    # par personne. Un vert par absence ressemble a un verdict. La sonde distingue
    # TRANSPORT et APPLICATIF (un port en LISTEN ne prouve pas qu'une page charge --
    # paye le 2026-09-06), et l'auto-detection reste NON BLOQUANTE : on observe avant
    # d'enforcer, comme pour `anatomie`.
    "tests/nr/test_ui_gate_autodetecte_nr.py",
    # Selecteur `--only` (2026-09-09) — NR COMPORTEMENTAL seul. Il prouve que le
    # predicat est exclusif et ne retombe jamais sur « tout autoriser », y compris sur
    # un nom inconnu. Il ne prouve PAS le cablage : la mesure AST du meme jour dit que
    # 20 producteurs de resultat sur 30 passent par `_run`, et que pytest (suite pure),
    # mutation-ratchet, ast-bunker et pip-audit lui echappent encore. Le selecteur est
    # donc INCOMPLET et le workflow ne doit pas le consommer -- cf. le fait SSoT
    # roadmap_selecteur_only_incomplet_2026_09_09.
    "tests/nr/test_selecteur_only_nr.py",
    # CLIQUET : aucun producteur de resultat n'echappe au selecteur (2026-09-09).
    # Aucune syntaxe Python n'oblige un `results.append` a consulter `--only` : la
    # regle ne peut pas vivre dans le code, elle vit dans ce cliquet -- comme le
    # socle de secrets ou celui des clones. Ne pas l'avoir des le depart a coute un
    # NR vert (7/7 sur le predicat) au-dessus d'un correctif INOPERANT : 10 des 30
    # producteurs echappaient au lanceur commun, dont pytest (suite pure), 542 s.
    "tests/nr/test_tout_gate_est_selectable_nr.py",
    "tests/nr/test_cartouches_concordance_nr.py",
    "tests/nr/test_chemin_erreur_nom_non_lie_nr.py",
    "tests/nr/test_acl_observabilite_nr.py",
    "tests/nr/test_daemon_demarrage_diag_nr.py",
    "tests/nr/test_patterns_non_bloquants_nr.py",
    "tests/nr/test_crawl_profondeur_nr.py",
    "tests/nr/test_veille_capacite_nr.py",
    "tests/nr/test_veille_reprise_et_budget_nr.py",
    "tests/nr/test_ui_generate_panne_nommee_nr.py",
    "tests/nr/test_release_gate_arbre_nr.py",
    "tests/nr/test_cascade_route_gouvernee_nr.py",
    "tests/nr/test_forge_docs_relink_nr.py",
    "tests/nr/test_provider_catalogue_perime_nr.py",
    "tests/nr/test_forge_docs_port_annotate_nr.py",
    "tests/nr/test_py314t_readiness_parallelisme_nr.py",
    "tests/nr/test_ui_gate_interpreteur_nr.py",
    "tests/nr/test_release_pypi_garde_nr.py",
    "tests/nr/test_capture_sorties_de_preuve_nr.py",
    "tests/nr/test_ui_temoin_nr.py",
    "tests/nr/test_ui_observations_nr.py",
    "tests/nr/test_repro_temoin_nr.py",
    # P4.2a : le README ne promet plus une installation que pip refuse, et le
    # gate capacites lit une declaration STRUCTUREE au lieu d'un marqueur dans
    # une commande d'installation.
    "tests/nr/test_readme_install_vcs_nr.py",
    # Chantier migration `nokido.*` : la carte des `sys.path` par INTENTION.
    # Garde le faux positif mesure le 2026-09-10 (un import TIERS compte pour
    # un module frere migrable) et le vocabulaire de surete (jamais
    # « supprimable » : un rapport qui l'ecrit sera lu comme une autorisation).
    "tests/nr/test_syspath_cartography_nr.py",
    # Chantier PyPI. Le contrat dit ce qu'il faut PROUVER (trois niveaux separes,
    # `pip install` reussi n'etant PAS la preuve finale) ; l'outillage mesure sa
    # propre limite avant de servir ; la baseline fixe le denominateur du delta.
    "tests/nr/test_pypi_contrat_nr.py",
    "tests/nr/test_pypi_chantier_outils_nr.py",
    "tests/nr/test_pypi_baseline_nr.py",
    # Namespace `nokido_agent` : les deux modes (checkout / installe), et le garde
    # de COLLISION — `nokido` etait deja pris par `tools/nokido.py`, ce qui aurait
    # masque le paquet dans tout le corps.
    "tests/nr/test_namespace_nokido_nr.py",
    "tests/nr/test_pypi_codemod_nr.py",
    "tests/nr/test_pypi_wheel_nr.py",
    "tests/nr/test_pypi_amorce_nr.py",
    "tests/nr/test_pypi_patch_tests_nr.py",
    # Verses le 2026-09-10, apres que la CI de reference a signale trois NR hors
    # suite pure. Un NR qui ne tourne pas ici ne protege AUCUNE surface.
    "tests/nr/test_pypi_outils_chantier_nr.py",
    "tests/nr/test_release_pipeline_graphe_nr.py",
    # Manifeste de distribution (P0 installation complete, 2026-10-02) : schema versionne,
    # validateur fail-closed, somme manquante = refus, aucun chemin du checkout dans le lot.
    "tests/nr/test_manifeste_distribution_nr.py",
    "tests/nr/test_wheel_paquets_declares_nr.py",
    "tests/nr/test_version_unique_nr.py",
    "tests/nr/test_ci_dependabot_quarantaine_nr.py",
    # `_sha_courant` appelait un alias importe dans une AUTRE fonction :
    # NameError avale, temoin rendu avec `tested_sha: null`. La fonction ecrite
    # pour empecher les certificats anonymes en produisait un.
    "tests/nr/test_sha_courant_nr.py",
    "tests/nr/test_forge_handoff_worker_nr.py",
    "tests/nr/test_wheel_probe_chemins_nr.py",
    "tests/nr/test_swarm_bus_mirror_nr.py",
    # Famille swarm (2026-10-02) : NR ecrits par ANTIGRAVITY (branche agent/antigravity), relus et
    # corriges (coffre jamais lu, imports canoniques), reportes sur alpha. 12 modules sur 13 ont
    # desormais un NR joue par la CI ; forge_swarm (le module de base) reste sans.
    "tests/nr/test_forge_swarm_patch_comportement_nr.py",
    "tests/nr/test_forge_swarm_validator_comportement_nr.py",
    "tests/nr/test_forge_swarm_context_comportement_nr.py",
    "tests/nr/test_forge_swarm_telemetry_guard_comportement_nr.py",
    "tests/nr/test_forge_swarm_worker_comportement_nr.py",
    "tests/nr/test_forge_swarm_orchestrator_comportement_nr.py",
    "tests/nr/test_forge_swarm_agents_comportement_nr.py",
    "tests/nr/test_forge_swarm_debate_comportement_nr.py",
    "tests/test_forge_swarm_telemetry_guard.py",
    # Cartouches du dist (2026-10-02) : le CI du README pointe le workflow qui EXISTE sur le dist.
    "tests/nr/test_dist_cartouches_nr.py",
    # Bail de priorite (2026-10-06) : la tache prioritaire prend le dessus et rend ce qu'elle a pris.
    "tests/nr/test_bail_priorite_nr.py",
    # Wiki GitHub du depot public (2026-10-07) : construit au commit du dist, clone garde, pages mortes retirees.
    "tests/nr/test_wiki_github_nr.py",
    # Pack RAG (2026-10-07) : la release refuse l'export NON FILTRE (sessions, memoire, veilles).
    "tests/nr/test_pack_rag_non_filtre_refuse_nr.py",
    "tests/nr/test_pack_rag_essentiel_nr.py",
    # Installation complete sur runners vierges (2026-10-07) : etapes, manifeste epingle, runners heberges seuls.
    "tests/nr/test_install_acceptance_nr.py",
    # Amorcage sur machine vierge (2026-10-07) : schema de base, import du pack, index plein texte par triggers.
    "tests/nr/test_db_bootstrap_schema_nr.py",
    # Recherche lexicale du hub (2026-10-07) : jamais la question brute dans MATCH.
    "tests/nr/test_rag_stream_requete_sure_nr.py",
    # Embedder :8099 (2026-10-08) : lot physique = contexte, borne en jetons sur les 3 portes.
    "tests/nr/test_embedder_8099_textes_longs_nr.py",
    # Chemins machine du superviseur (2026-10-08) : 0/60 services sur VM neuve, [vars] generises jamais developpes.
    "tests/nr/test_vars_machine_superviseur_nr.py",
    # Comptes runAs crees par l'installeur (2026-10-09) : f-strings d'icacls cassees, interpreteur hors miniforge,
    # install.ps1 ASCII et delegue a forge_sandbox_setup, organisme installe depuis un clone.
    "tests/nr/test_comptes_installeur_nr.py",
    "tests/nr/test_capability_gate_sondes_nr.py",
    "tests/nr/test_gate_depense_tokens_nr.py",
    "tests/nr/test_tool_budget_gate_nr.py",
    "tests/nr/test_context_firewall_nr.py",
    "tests/nr/test_llm_usage_adapters_nr.py",
    "tests/nr/test_usage_claude_current_usage_imbrique_nr.py",
    "tests/nr/test_llm_usage_event_contrat_nr.py",
    "tests/nr/test_token_usage_unique_writer_nr.py",
    "tests/nr/test_llm_usage_cout_et_contexte_nr.py",
    "tests/nr/test_usage_schema_provenance_nr.py",
    "tests/nr/test_dup_adaptateur_entree_nr.py",
    # 2026-09-20 : RETIRE avec `forge_veille_github_direct`. Ce NR n'avait pas de
    # portee generale -- il verifiait la liste des onze depots de la campagne de ce
    # script precis -- et sa cible n'existe plus.
    "tests/nr/test_knowledge_overlap_nr.py",
    "tests/nr/test_auto_compact_age_inconnu_nr.py",
    "tests/nr/test_veille_clone_priorite_nr.py",
    "tests/nr/test_bash_guard_substitution_nr.py",
    # Registre de veille : fail-closed, identite stable, lots deterministes,
    # etats de dump. Purs (tmp_path uniquement, ni reseau ni base).
    "tests/nr/test_veille_registre_nr.py",
    "tests/nr/test_vector_structure_jaccard_nr.py",
    # Etape 1 du plan « index structurel » : l attribution des appelants
    # declare son incertitude (RESOLU / AMBIGU / ILLISIBLE). Banc hermetique.
    "tests/nr/test_callgraph_ambiguite_nr.py",
    # Etape 2 : verbe unique d introspection, borne et declarant ses angles morts.
    "tests/nr/test_introspect_verbe_unique_nr.py",
    "tests/nr/test_introspect_jugeable_nr.py",
    # Etape 3 : memoire des corrections (faits dates, jamais une preuve non mesuree).
    "tests/nr/test_success_oplog_nr.py",
    # Commit 1 du plan reflexes : le verbe doit franchir les DEUX barrieres
    # (allowlist du endpoint + visibilite hors scope declare).
    "tests/nr/test_introspect_atteignable_nr.py",
    # Campagne observabilite du 2026-09-05. Ces trois gardes tiennent dans la suite
    # PURE : ils ne demarrent aucun service et ne touchent pas la base RAG. Leurs
    # cas de logique sont fabriques donc deterministes, et leurs rares assertions
    # sur la flotte vivante sont soit des invariants qui tiennent quel que soit
    # l'etat (aucun organe VIVANT sans porteur, aucun chemin sain sans preuve),
    # soit protegees par un skip explicite quand la source est illisible.
    "tests/nr/test_pouls_canon_nr.py",
    "tests/nr/test_liveness_correlation_nr.py",
    "tests/nr/test_flux_etats_nr.py",
    # Ancrage des memoires (P1 Memory Validity, 2026-09-05). Hermetique : le
    # `dernier_commit` est injecte, donc ni depot git fabrique ni lecture du profil
    # owner — que le compte de la CI ne peut de toute facon pas voir.
    "tests/nr/test_memory_ancrage_nr.py",
    # Jonction debat -> etat rejouable (2026-09-05). Hermetique : aucun appel LLM,
    # la sequence d'appels de run_debate est rejouee a la main et sa source est lue
    # pour verifier que le raccord n'a pas disparu.
    "tests/nr/test_debat_replay_jonction_nr.py",
    # Preflight et quorum du debat (2026-09-05). Hermetique : `_turn` et `_rag_context`
    # sont neutralises ; seule la lecture de `provider_scores` touche du reel, et elle
    # skippe proprement si la table est illisible.
    "tests/nr/test_debat_preflight_quorum_nr.py",
    # Separation identite DECLAREE / AUTORITE (2026-09-07). Hermetique : monkeypatch
    # de `forge_videur.resolve_identity`, aucun service, aucun reseau ; la seule
    # ecriture va dans `sandbox/`, que tous les comptes peuvent ecrire.
    "tests/nr/test_autorite_vs_declare_nr.py",
    # Corpus de classification des signaux d'agent (2026-09-07). Hermetique : lit
    # `forge_swarm_evidence.classer_erreur` sur des chaines constantes, rien d'autre.
    "tests/nr/test_classification_signal_nr.py",
    # Contrat WIT du premier composant wasm (2026-09-07). Hermetique : lit le fichier
    # components/wit/nokido-signal.wit comme un texte, ne compile rien, aucun runtime.
    # Inscrit DANS LA MEME PASSE que sa creation : une heure plus tot, le cliquet de
    # suite pure a rougi parce que deux NR ecrits la nuit meme n'etaient declares nulle
    # part et ne protegeaient donc aucune surface.
    "tests/nr/test_wit_signal_contrat_nr.py",
    # Visibilite du gate de capacites sur les routes gouvernees (2026-09-07).
    # Hermetique : appelle _texte_commande et les regles compilees sur des dicts
    # construits a la main, aucun sous-processus, aucun service.
    "tests/nr/test_gate_voit_les_routes_gouvernees_nr.py",
    # Contrat de la vue federee du cablage (2026-09-07). Hermetique : les deux
    # sources sont rebranchees sur des artefacts fabriques en tmp_path, aucun
    # artefact reel n'est requis, aucun instrument n'est lance.
    "tests/nr/test_wiring_view_nr.py",
    # Lecture des imports qualifies par le capteur de cablage (2026-09-07).
    # Hermetique : appelle _cibles_import sur des chaines constantes, ne scanne rien.
    "tests/nr/test_module_wiring_imports_qualifies_nr.py",
    "tests/nr/test_wiring_identite_noeud_nr.py",
    "tests/nr/test_bump_superrepo_garde_distant_nr.py",
    "tests/nr/test_ci_gate_trois_etats_nr.py",
    "tests/nr/test_vitalite_inscription_nr.py",
    "tests/nr/test_regeneration_commissure_nr.py",
    # Troisieme etat de la confiance d'intuition GOAP (2026-09-08, veille A1).
    # Hermetique : fonction pure, plus deux passages par GOAPPlanner.plan avec
    # intuition_rank et les journaux remplaces par monkeypatch. Aucun reseau,
    # aucun service, aucune ecriture.
    "tests/nr/test_confiance_troisieme_etat_nr.py",
    # Fermeture d'un run vert par un commit (2026-09-08, demande owner).
    # Hermetique : decider_commit est pure, les fichiers vivent en tmp_path,
    # aucun git n'est lance par le test.
    "tests/nr/test_ci_fermeture_par_commit_nr.py",
    # Reprise du rattrapage U1 des depots de veille (2026-09-08).
    # Hermetique : fonctions pures, fichiers en tmp_path, aucun reseau.
    "tests/nr/test_veille_u1_reprise_nr.py",
    # Decidabilite du gain : une absence de mesure n'est pas un gain nul (2026-09-08).
    # Hermetique : verdicts purs + juger_module_avec_gain avec mesure, juge et
    # restauration remplaces par monkeypatch. Aucun test lance, aucun git.
    "tests/nr/test_gain_indecidable_nr.py",
    # Perimetre de mesure partage, extrait de forge_self_mutation (2026-09-08).
    # Hermetique : arborescence fabriquee en tmp_path, racine injectee.
    "tests/nr/test_tests_cibles_nr.py",
    # Perimetre elargi a la detection par IMPORT (2026-09-08) : le capteur par
    # conventions ratait 264 modules. Hermetique : arborescence en tmp_path.
    "tests/nr/test_perimetre_par_import_nr.py",
    # Les DEUX metriques de couverture, jamais fusionnees (2026-09-08).
    # Hermetique : arborescence en tmp_path, aucun scan du depot reel.
    "tests/nr/test_couverture_perimetre_nr.py",
    # Contrat de representation du seuil RAM (2026-09-13) : UNIT + INTEGRATION +
    # SIMULATION. Ne reveille pas le corps -- capteurs injectes, aucun service.
    "tests/nr/test_forge_promotion_queue_nr.py",
    # Generateur de tests d'appui : ne genere que pour ce qui s'importe, et NOMME
    # ce qu'il ne peut pas couvrir (2026-09-08). Hermetique : sonde remplacee.
    "tests/nr/test_generer_appui_nr.py",
    # Regeneration periodique de la couverture de mesure en NREM1 (2026-09-08) :
    # sans elle la mesure est une photo datee. Hermetique : handler appele
    # directement, mesure et generation remplacees par monkeypatch.
    "tests/nr/test_regeneration_perimetre_nr.py",
    # La boucle autonome emprunte le chemin FERME du juge (2026-09-08).
    # Hermetique : le juge est remplace par un double, aucune mutation reelle.
    "tests/nr/test_boucle_raccordee_gain_nr.py",
    # Organe REACTIF : un module neuf est instrumente au commit, pas au sommeil.
    # Hermetique : fonction pure sur des chemins fabriques.
    "tests/nr/test_post_commit_appui_nr.py",
    # Le circadien LIT ce que son ecrivain ECRIT (2026-09-08) : le fichier porte
    # `last_fired`, le lecteur cherchait `last_completed` — dette permanente sur un
    # corps sain. Hermetique : etats fabriques en tmp_path, chemin injecte.
    "tests/nr/test_circadian_etat_lu_nr.py",
    # Le capteur voit les tests d'appui (5e convention) et les imports DYNAMIQUES
    # (2026-09-08) : sans eux, 57 tests generes etaient invisibles a la metrique
    # qu'ils devaient faire monter. Hermetique : arborescence en tmp_path.
    "tests/nr/test_perimetre_appui_et_dynamique_nr.py",
    # La cellule WASM ne meurt plus en silence (2026-09-08) : racine derivee,
    # chemin decode, amorcage FATAL distinct de l'apoptose de cellule.
    # Hermetique : lit la source .ts, ne lance pas deno.
    "tests/nr/test_pyexec_amorcage_nr.py",
    # 2026-09-08. Deux gardes nes du meme incident : un patcheur avait rendu
    # app/forge_mcp_registry.py (CRITICAL_FILE, registre d'outils du hub)
    # NON PARSABLE, et le hub tournait encore sur son code en memoire -- la panne
    # n'aurait eclate qu'au restart suivant, ou la cause aurait ete cherchee dans
    # le restart. Le premier verrouille TOUT app/ et tools/ (~2400 fichiers, 13 s) ;
    # le second un module casse par un decoupage a moitie fait.
    # Purs : ils lisent des sources et parsent, ils n'executent aucun service.
    "tests/nr/test_modules_parsables_nr.py",
    "tests/nr/test_agent_hardware_imports_nr.py",
    # 2026-09-08. sandbox/tasks.db comptait 35 taches « done » dont QUATRE
    # portaient un resultat en echec : l'ecrivain posait le statut des qu'une
    # reponse revenait, sans regarder son contenu. TRANSPORT != APPLICATIF.
    # Pur : la fonction jugee est sans effet de bord et lit le catalogue M2M.
    "tests/nr/test_statut_tache_transport_vs_applicatif_nr.py",
    # 2026-09-08. Le chemin TEMP du sandbox etait calcule en dur sur DEUX sites,
    # et personne ne purgeait la zone (4112 fichiers, 0,55 Go dans le depot).
    # Pur : lecture de sources + AST, aucune ecriture, aucun service.
    "tests/nr/test_tmp_point_unique_nr.py",
    # 2026-09-08. Un refus d'admission annoncait « CPU 100 % » quand la machine
    # tenait 21-26 % : echantillon de 100 ms pris au demarrage d'une CI, et
    # sentinelle de fail-closed indiscernable d'une mesure. Zero trace dans
    # 8736 journaux. Pur : injection de la sante, aucun appel systeme.
    "tests/nr/test_admission_mesure_vs_sentinelle_nr.py",
    # E1 de la roadmap veille (2026-09-08), tire de litellm : un garde n'est
    # PROUVE que par deux assertions symetriques -- il mord sur ce qui doit etre
    # refuse, il laisse passer ce qui doit passer. Le depot porte deux gardes qui
    # n'avaient JAMAIS agi (frein INSULIN sans emetteur, intention du reclaimer :
    # 312,94 Go recharges en 7,6 j). Patron dans tests/nr/_patron_garde.py.
    "tests/nr/test_gardes_mordent_nr.py",
    # 2026-09-08, passe au VERT par l'executeur local WORKER_CODE : 41 symboles
    # metier utilises sans import, restes du decoupage de Nokido.py. Les 38
    # ambigus et 18 introuvables restent HORS contrat -- choisir entre deux
    # definitions ou enqueter sur un symbole absent n'est pas mecanique.
    "tests/nr/test_symboles_source_unique_nr.py",
    # 2026-09-08, defaut revele PAR la parallelisation : l'audit du corps a
    # produit son verdict complet puis l'a PERDU sur « database is locked »
    # pendant qu'une veille ingerait. Pur : base SQLite fabriquee, jamais la
    # vraie -- la premiere version de ce test visait la base de 22,8 Go.
    "tests/nr/test_audit_ingestion_reprise_nr.py",
    # M1 de la roadmap veille (2026-09-08), complement de E1 : E1 prouve qu'un
    # garde MORD, M1 prouve qu'un detecteur DETECTE, en lui injectant un defaut
    # connu. A trouve du premier coup que les gardes de securite tournent en
    # warn-only sous pytest (Nokido.env -> LAFORGE_ENV=dev via tests/conftest).
    "tests/nr/test_detecteurs_detectent_nr.py",
    "tests/nr/test_repli_interactif_meme_session_nr.py",
    # U1.1 (2026-09-11) : tout composant passe a React.createElement depuis `window`
    # doit etre FOURNI par un script que la page charge. Six orphelins cassaient le
    # rendu du Hub apres le HTML statique -- 58 839 caracteres de DOM, 47 ressources,
    # et AUCUN des six fetch /api/hub/* n'etait appele.
    # ⚠️ Ce NR avait ete commite (429a57f2c) SANS etre inscrit ici : il existait et
    # ne gardait rien. Un NR hors de cette liste ne protege aucune surface.
    "tests/nr/test_hub_bundle_window_bindings_nr.py",
    # U1.2 (2026-09-11) : un echec HTTP ne s'ecrit pas dans la valeur du VIDE.
    # Mesure au navigateur (tools/forge_ui_contrat_etats.py) : LOADING, DATA_VIDE et
    # ERROR rendaient UNE SEULE empreinte de DOM sur /api/hub/persona. Le NR juge la
    # source ET l'artefact servi -- le bundle n'est pas regenere depuis la source.
    "tests/nr/test_hub_erreur_distincte_du_vide_nr.py",
    # P0 worktree de preuve (2026-09-11) : un agent qui n'a rien pousse ne doit plus
    # pouvoir empecher de juger un sha deja publie. Mesure du jour : l'arbre partage
    # rendait CAPTURE=False avec 72 entrees bloquantes, le worktree de preuve bati
    # sur le MEME sha rend CAPTURE=True avec 0 entree. Le NR verrouille les DEUX
    # sens -- un arbre d'agent sale n'atteint pas la preuve, ET un intrus depose
    # dans la preuve la bloque -- car le premier sens seul ne distingue pas un
    # garde repare d'un garde desarme.
    "tests/nr/test_worktree_preuve_non_interference_nr.py",
    # Phase 3 (2026-09-11) : le captureur sait juger un worktree de preuve. Le test
    # anti-desarmement est le plus important du lot — il etait DEJA vert avant
    # l'implementation et doit le rester : sur un arbre de travail partage, un
    # fichier inattendu bloque toujours. Un juge devenu permissif n'est pas un juge
    # repare, c'est un garde supprime.
    "tests/nr/test_capture_sur_worktree_de_preuve_nr.py",
    # P0 (2026-09-11) : la destruction de l'environnement de preuve ne detruit pas
    # la preuve. Mesure de la CI de reference complete : GEN-00013.json avait ete
    # ecrit DANS le worktree jetable -- la preuve vivait a l'endroit exact qu'on
    # supprime apres l'avoir produite. Une preuve qui ne survit pas a son propre
    # contexte n'est pas une preuve, c'est une trace d'execution.
    "tests/nr/test_preuve_survit_au_worktree_nr.py",
    # Verse le 2026-09-21 EN MEME TEMPS que le test, apres un incident ou le hub
    # a ete tue DEUX fois par une sonde GET sans jeton : `rag_stats` faisait
    # trois balayages complets de la base de 25 Go en `async def`, donc dans la
    # boucle d'evenements. Le remede existait depuis le 2026-08-26 pour
    # `app/web_hub/app.py` ; `tools/nokido_hub.py` ne l'avait jamais recu.
    # PUR : lit l'AST du depot, n'ouvre aucun service et ne sonde aucun port --
    # sonder est precisement ce qui a couche le hub.
    "tests/nr/test_hub_pas_d_io_bloquante_dans_la_boucle_nr.py",
    # Verses le 2026-09-21, reclames par `test_suite_pure_ratchet_nr` -- qui a
    # mordu sur MON travail du jour : le premier avait ete commite (65ad62093)
    # sans etre declare ici, donc il ne tournait dans AUCUNE des deux CI. Meme
    # defaut que celui cite deux tours plus tot dans la meme session.
    #
    # Purs tous les deux : ils substituent `_CHEMIN` du ledger sur `tmp_path` et
    # n'ouvrent aucun service.
    #
    # Le second SORT du socle (`_exclusion_2026_09_21`), ou il etait inscrit
    # comme « ORPHELIN DE SON CODE » : son module `forge_agent_keys` n'existait
    # pas et il rendait 15 errors. La condition est LEVEE -- le module est livre
    # (4ea9c79ee) et le NR rend 24/24. Une exclusion dont la cause a disparu
    # n'est plus une exclusion, c'est un test qui ne protege rien.
    # test_verify_consulte_le_ledger_de_cles_nr.py RETIRE le 2026-09-21 : le
    # cablage qu'il verrouillait a ete DECABLE apres mesure. `decode` ne
    # consulte plus le ledger pour un `jkt` generique, parce qu'il ne recoit
    # aucune `credential_class` et ne peut donc pas distinguer une preuve de
    # possession EPHEMERE d'une cle d'identite DURABLE. Il passe au socle comme
    # SPECIFICATION PREPARATOIRE -- meme traitement que le contrat du ledger
    # avant que son module existe. 8 de ses 13 tests restent d'ailleurs VRAIS
    # (binding, ordre, bearer, AST) ; ils reviendront avec le rebranchement.
    "tests/nr/test_agent_keys_ledger_nr.py",
    # Verse le 2026-09-21 EN MEME TEMPS que le test. Trois routes faisaient
    # INSERT + commit() dans RAG/embeddings.db SANS authentification -- mesure
    # runtime, sonde non mutante : `POST /ingest/bulk {}` sans jeton rendait
    # 400 « expected array », donc le handler etait ATTEINT. C'etait le NEGATIF
    # de la directive du 19/09 : des ecrivains ANONYMES sur la base qui doit
    # CESSER DE RECEVOIR. Garde `_admin_tok_ok` REUTILISE, pas invente.
    # PUR : lit l'AST du depot, n'ouvre aucun service, ne sonde aucun port.
    "tests/nr/test_ingestion_exige_un_porteur_nr.py",
    # Verse le 2026-09-21 EN MEME TEMPS que le test. Garder /ingest/* ne
    # protege pas le RAG : `/api/watch/create` cree une chaine dont un noeud
    # (`IngestAgent`) y ecrit SANS passer par ces routes. Ce NR inventorie la
    # CAPACITE, pas les URL, et mord dans les deux sens.
    # PUR : lit l'AST du depot, n'ouvre aucun service, ne sonde aucun port.
    "tests/nr/test_ecriture_rag_chemins_connus_nr.py",
    "tests/nr/test_journal_porte_acteur_et_sujet_nr.py",
    "tests/nr/test_maitre_est_attribuable_nr.py",
    "tests/nr/test_trace_refus_admin_ecrit_vraiment_nr.py",
    "tests/nr/test_vue_audit_porte_la_provenance_nr.py",
    "tests/nr/test_gate_borne_dit_combien_nr.py",
    "tests/nr/test_maitre_porte_acteur_et_sujet_nr.py",
    "tests/nr/test_vue_compte_l_ecart_de_ring_nr.py",
    "tests/nr/test_network_history_lecture_bornee_nr.py",
    "tests/nr/test_mcp_servers_ne_relaie_pas_les_preferences_nr.py",
    # 2026-10-02 : importer le registre MCP ne charge plus torch (evaluate_intent -> forge_intent_risk).
    "tests/nr/test_registre_sans_torch_nr.py",
    "tests/nr/test_inbox_liaison_identite_nr.py",
    "tests/nr/test_inbox_ownership_cycle_nr.py",
    "tests/nr/test_contrat_credential_routes_forge_nr.py",
    "tests/nr/test_portee_demandee_et_accordee_nr.py",
    "tests/nr/test_docstring_adossee_a_son_code_nr.py",
    "tests/nr/test_frontmatter_okf_nr.py",
    # Ecrit par la delegation ANTIGRAVITY du 2026-09-22 et commite en 9634f18ba
    # SANS etre declare ici : il ne tournait donc NULLE PART — meme motif que
    # `test_inbox_ownership_route_nr` douze lignes plus bas, le meme jour.
    "tests/nr/test_wiki_openwiki_nr.py",
    # S19 du registre de securite, requalifie `A VERIFIER` -> `INSTRUIT` le
    # 2026-09-22 : la denylist AST n'est PAS la frontiere (4 formes d'aliasing
    # mesurees passantes) ; le confinement reel est le ring 2 + le fait que la
    # FORGE n'est exposee par aucune surface. Ce NR garde les trois portes.
    "tests/nr/test_forge_dynamique_confinement_nr.py",
    # C2.1 du registre : cliquet anti-aggravation sur les `with ThreadPoolExecutor`
    # dont le `.result(timeout=)` est une promesse que `__exit__` ne tient pas.
    "tests/nr/test_pool_timeout_promesse_non_tenue_nr.py",
    # Les artefacts de la campagne d'audit doivent rester conformes au contrat
    # machine du skill Cloudflare. Mesure du 2026-09-22 : aucun run ne l'etait,
    # et run-2 avait ete annonce a 0 erreur quatre jours plus tot.
    "tests/nr/test_audit_findings_conformes_au_skill_nr.py",
    # Un item de roadmap declare son ETAT, et l'absence de marqueur vaut OUVERT.
    # Liste BLANCHE : `[MESURE le ...]` ou `[DIRECTIVE OWNER]` qualifient sans clore.
    "tests/nr/test_roadmap_statut_declare_nr.py",
    # Finding E1 : la cle Gemini passe par le coffre, a chaque appel, et ne reste
    # pas dans l'environnement du processus apres l'appel.
    "tests/nr/test_cle_gemini_passe_par_le_coffre_nr.py",
    # N0.1 : `test_journaux_hors_verrou_rag_nr` est declare plus haut (bloc du
    # 2026-09-19) -- le redeclarer ici l'avait fait tourner deux fois et rougir
    # `test_PURE_TESTS_n_a_aucun_doublon` (CI 869f9de16).
    # Le GRAPHE entier lecteurs+ecrivains partage-t-il le meme point de bascule ?
    # Recense par ANALYSE du SQL, jamais par liste figee : une liste se perime en
    # silence et le garde se relit alors comme une couverture.
    "tests/nr/test_journaux_graphe_acces_nr.py",
    # L'attente de RAM ARRETE sur un refus d'authentification au lieu de boucler
    # (23 tentatives mesurees le 2026-09-22 sur un `unauthorized`).
    "tests/nr/test_ci_quand_ram_dispo_nr.py",
    # Le recenseur de modeles gratuits resout `nokido_agent` hors du depot (mort en
    # ModuleNotFoundError en job, 2026-09-23) ; le swarm ne compte plus une erreur 401
    # ni un vide comme une reponse, et dit INDETERMINE pour un binaire illisible.
    "tests/nr/test_free_tier_census_importe_ses_cles_nr.py",
    "tests/nr/test_cli_swarm_faux_succes_nr.py",
    # Pousser EXACTEMENT le sha certifie (ancetre de la branche), jamais la tete
    # avancee pendant la CI ni un sha etranger (2026-09-23).
    "tests/nr/test_push_sovereign_sha_certifie_nr.py",
    # Instrument AVANT/APRES du switch journaux : comptage sur fenetre, trois
    # etats (ABSENTE / ILLISIBLE jamais 0), lecture seule (2026-09-23).
    "tests/nr/test_mesure_journaux_nr.py",
    # La veille clone+ingest S'ARRETE (rc=5) sous 30 Go libres sur le volume reel
    # de la base (incident WAL 53 Go du 2026-09-01, decision owner 2026-09-23).
    "tests/nr/test_veille_clone_garde_disque_nr.py",
    # La retention ne purge QUE les veilles prouvees reussies ; une veille ratee
    # (failed, partial, stalled, degraded, empty) attend son rattrapage (2026-09-23).
    "tests/nr/test_purge_veille_epargne_les_ratees_nr.py",
    # conversation_log : surveille, jamais purge tant que rien n'est distille (owner 24/09).
    "tests/nr/test_conversation_log_jamais_purge_nr.py",
    # Worktrees de preuve de la CI : purge quotidienne PAR GIT (garde recents), owner 24/09.
    "tests/nr/test_purge_worktrees_de_preuve_nr.py",
    # Superviseur : jamais un second demarrage d'un service deja en cours (orphelins).
    "tests/nr/test_superviseur_pas_de_double_demarrage_nr.py",
    # Points d'entree des services : racine importable AVANT nokido_agent (6 services morts au boot).
    "tests/nr/test_points_d_entree_racine_avant_nokido_agent_nr.py",
    # Boucle de ressources du superviseur : aucun await non borne (vitalite figee 18 min, pool sature).
    "tests/nr/test_superviseur_boucle_ressources_non_bloquante_nr.py",
    # Service gele (disabled) jamais reveille par la regulation RAM ; QdrantSync gele (owner 24/09).
    "tests/nr/test_service_gele_jamais_reveille_par_la_ram_nr.py",
    # Chemins frequents sans balayage de la base RAG (veille lot_B_34, cause du P0 WAL).
    "tests/nr/test_chemin_chaud_sans_balayage_nr.py",
    # Detecteur de tests instables : N passes, verdict test par test sur JUnit (veille lot_C_01b).
    "tests/nr/test_nr_instables_nr.py",
    # Bail de mission : reprise unique avec checkpoint, abandon apres plafond (veille lot_B_25).
    "tests/nr/test_tache_bail_expire_reprise_nr.py",
    # Aucun outil ne passe --no-verify a git : le pre-commit porte le scan de secrets (veille lot_C_03).
    "tests/nr/test_aucun_outil_ne_contourne_les_hooks_git_nr.py",
    # Soupape anti-perte etroite : ts/ps1 derogeables nommement et traces, secrets jamais (owner 24/09).
    "tests/nr/test_git_gate_soupape_etroite_nr.py",
    # Phase health > 90 s : l'audit des journaux n'arpente plus les copies de depot (87 s mesurees).
    "tests/nr/test_health_journaux_sans_copies_de_depot_nr.py",
    # Alertes de version : identite canonique depuis la source, securite lue, lecture seule (veille lot_C_06).
    "tests/nr/test_watch_alerts_identite_canonique_nr.py",
    # Veille : une ingestion non prouvee ne marque plus « vu » ; refus HTTP sans ecriture directe (C_06b).
    "tests/nr/test_rss_watcher_ne_perd_plus_d_alerte_nr.py",
    # Health : ports de la fusion multi-capteurs sondes en parallele (18 s de serie), semantique inchangee.
    "tests/nr/test_fusion_ports_sondes_en_parallele_nr.py",
    # Usage fournisseurs : un compte fait par tokenizer local s'enregistre ESTIMATED, jamais REPORTED.
    "tests/nr/test_usage_provider_estime_n_est_pas_rapporte_nr.py",
    # Health : smoke HTTP des services en parallele (8 s de serie), issues up/auth/erreur inchangees.
    "tests/nr/test_health_services_http_en_parallele_nr.py",
    # UI : la campagne ui-acceptance ouvre chaque vue du menu de l'application hub (jamais visitee avant).
    "tests/nr/test_ui_campagne_couvre_les_vues_hub_nr.py",
    # UI : la page /epistemic rend les memes faits sans parcourir rag_chunks (index non selectif `active`).
    "tests/nr/test_epistemic_page_sans_balayage_nr.py",
    # TUI multi-CLI : l'aide F1 / /help n'est plus effacee en < 1 s par la boucle de statut.
    "tests/nr/test_tui_aide_reste_visible_nr.py",
    # UI :8766 : ids accedes presents (#sdot), polices servies (/static/fonts), refus MCP dit.
    "tests/nr/test_pages_ui_8766_saines_nr.py",
    # TUI : chaque raccourci ctrl+<lettre> est emis ET decode tel quel par un vrai terminal (Ctrl+M = Entree).
    "tests/nr/test_tui_raccourcis_atteignables_nr.py",
    # Vue persona : le bouton ne promet pas une revocation qu'il ne fait pas (« Masquer », bundle servi compris).
    "tests/nr/test_hub_persona_masquer_nr.py",
    # Sonde headless des TUI (instrument de preuve de la TUI v13 sous trusted_script) : trois etats.
    "tests/nr/test_forge_tui_sonde_nr.py",
    # TUI v13 : RAG via le hub (decision owner 1), plus de chargement de toute la base au montage.
    "tests/nr/test_tui_rag_via_hub_nr.py",
    # Page /rag : instantane de la phase health (age expose), plus 17 s de comptages par chargement.
    "tests/nr/test_rag_stats_instantane_nr.py",
    "tests/nr/test_opencode_web_ferme_nr.py",
    # 2026-09-25 : passerelle :7777, voie outils — le modele DEMANDE est servi s'il est mesure
    # APPELLE, sinon refus nomme (plus de qwen impose) ; pare-feu sur tout ce qui part et revient.
    "tests/nr/test_passerelle_voie_outils_nr.py",
    # 2026-09-25 : TUI 13.6 (tools/nokido_tui.py) -- au lancement REEL, app/tui_adapters etait
    # introuvable et avale : PTY SSH et slash v13.6 morts sans un mot. Charges, et absence dite.
    "tests/nr/test_tui_136_adaptateurs_nr.py",
    # 2026-09-25 : couche « squashed » du detecteur d'injection -- ecart BORNE entre les deux
    # mots (le prompt systeme d'opencode etait bloque pour un .gitignore suivi d'« instructions »).
    "tests/nr/test_squashed_ecart_borne_nr.py",
    # 2026-09-25 : forge_network ne charge plus scapy (Npcap) a l'import -- la TUI v13 restait
    # figee dans `load_winpcapy` avant tout affichage (bridge :7440).
    "tests/nr/test_network_scapy_paresseux_nr.py",
    # 2026-09-25 : TUI v13 servie par le bridge -- la purge du demarrage retirait `__main__`
    # (OSError « source code not available » dans Textual), puis un appel a un accesseur
    # disparu (forge_prefect.get_prefect_manager) ; et le journal du lanceur :7400 se refermait
    # a chaque rafraichissement (3 s).
    "tests/nr/test_purge_garde_main_nr.py",
    "tests/nr/test_prefect_manager_appel_vivant_nr.py",
    "tests/nr/test_launcher_journal_survit_refresh_nr.py",
    # 2026-09-25 : SovereignMembrane en mode REVERSIBLE (pseudonymisation de la passerelle,
    # decision owner) + NoiseGuardian (deanonymize inverse, alias en collision).
    "tests/nr/test_membrane_reversible_nr.py",
    # 2026-09-25 : /forge/feed -- mojibake FIGE dans la source (ðŸ§ ) et heure UTC affichee brute.
    "tests/nr/test_portail_sans_mojibake_nr.py",
    # 2026-09-25 : sonde tool-call -- modeles FORTS designes (--modeles, fusion au rapport) et
    # 429 = NON_MESURE (Groq gratuit plafonnait opencode a 8 000 jetons/min).
    "tests/nr/test_tool_call_probe_modeles_nr.py",
    # 2026-09-25 : ce qu'un agent EXECUTE par le hub (run, governed_edit...) est lisible apres
    # coup -- journal des actes, caviarde, borne ; l'audit MCP coupait tout a 80/120 caracteres.
    "tests/nr/test_journal_actes_agents_nr.py",
    "tests/nr/test_token_usage_appel_alertant_compte_nr.py",
    "tests/nr/test_acces_ssh_au_coffre_nr.py",
    "tests/nr/test_soif_bloquee_par_dependance_nr.py",
    "tests/nr/test_veille_modele_vivant_nr.py",
    "tests/nr/test_soif_choisit_son_traitement_nr.py",
    "tests/nr/test_soif_examen_a_la_demande_nr.py",
    # Soif lot B (2026-10-02) : AVEUGLE_PARTIEL, cycle de vie des lacunes (fermeture par remesure
    # du meme instrument, IRRESOLUE owner seulement), plafond algedonique par fenetre, etalonnage gele.
    "tests/nr/test_soif_lot_b_nr.py",
    "tests/nr/test_effecteurs_du_tri_nr.py",
    "tests/nr/test_docs_deportes_hors_audit_nr.py",
    "tests/nr/test_medecin_lit_les_examens_nr.py",
    "tests/nr/test_critique_exige_deux_sondes_nr.py",
    "tests/nr/test_capteur_ram_superviseur_nr.py",
    "tests/nr/test_tri_des_experiences_nr.py",
    # 2026-09-25 : une EMISSION (status=CALL) n'est pas une issue -- groq/mistral lus « 0 % » alors
    # que leur reponse (ligne IN du canal CLOUD) n'atteint jamais execution_traces.
    "tests/nr/test_trace_mining_emission_n_est_pas_une_issue_nr.py",
    # 2026-09-25 : l'ISSUE d'un appel fournisseur atteint execution_traces (ligne IN du canal CLOUD),
    # un statut illisible est INCONNU (jamais OK), et l'echec du fournisseur s'ecrit comme sa reussite.
    "tests/nr/test_trace_sidecar_issue_cloud_nr.py",
    "tests/nr/test_proxy_journalise_echec_fournisseur_nr.py",
    # 2026-09-25 : le capteur d'intentions non tenues lit une liste BLANCHE de docs d'intention
    # (105 « ecarts » de 53 sources -> 21 de 12 docs) ; une ancienne mention n'est jamais RESOLU.
    "tests/nr/test_unmet_intention_liste_blanche_nr.py",
    # 2026-09-25 : cascade epuisee par la CAPACITE -> repli AGY puis Claude Code (fournisseurs declares
    # du proxy) ; jamais apres un refus de garde (DLP, injection, SecretGuard).
    "tests/nr/test_router_repli_oauth_capacite_nr.py",
    # 2026-09-26 : un tour assistant VIDE n'entre plus dans le fil (il faisait rendre 400 a tous les
    # appels suivants du fil -- swarm P1 bis).
    "tests/nr/test_proxy_fil_sans_tour_vide_nr.py",
    # 2026-09-26 (veille RSI) : l'evaluateur est hors de portee d'une mutation, et le gain exige une
    # non-regression PAR test (reparer 2 tests et en casser 1 n'est pas une amelioration).
    "tests/nr/test_juge_evaluateur_hors_portee_nr.py",
    # 2026-09-26 : des moteurs SearXNG muets ne se lisent pas comme un web vide (4/4 veilles de la
    # soif « no results » sans erreur) -- erreur nommee, repli academique.
    "tests/nr/test_veille_moteurs_muets_nr.py",
    # 2026-09-26 (veille RSI) : le gain d'une generation est un verdict de PARETO -- ajouter des
    # modules sans couverture n'est plus une victoire.
    "tests/nr/test_generation_fitness_pareto_nr.py",
    # Frein AUTOMATIQUE sur recul de capacite hors bande (meme cle de dimension), abstention dite
    # sur mesure illisible ; forge_capability_benchmark lit les capacites mesurees (2026-10-02).
    "tests/nr/test_frein_auto_capacite_nr.py",
    # 2026-09-26 (veille RSI, P7) : le registre d'evolution est CHAINE ; une entree reecrite,
    # supprimee ou inseree se detecte.
    "tests/nr/test_registre_evolution_chaine_nr.py",
    # 2026-09-26 (fiche V3) : une page arXiv /abs/ est re-sourcee en /html/ (article, pas resume).
    "tests/nr/test_veille_arxiv_html_nr.py",
    # 2026-09-26 : la veille respecte le GEL (INSERT OR REPLACE le levait) et ecarte le hors sujet en le disant.
    "tests/nr/test_veille_gel_et_pertinence_nr.py",
    # 2026-09-26 : la suite pure passe sa liste par fichier @ (815 tests = 34 714 car. > 32 767, WinError 206).
    "tests/nr/test_ci_suite_pure_ligne_de_commande_nr.py",
    # 2026-09-26 : une duree (`_S`/`_MS`/`_SECONDS`) n'est pas un secret pour la regle secret-from-env.
    "tests/nr/test_golden_secret_env_duree_nr.py",
    # 2026-09-26 (owner) : les cliquets golden-rules + duplication sont joues au PRE-PUSH, sur le SHA pousse.
    "tests/nr/test_prepush_cliquets_nr.py",
    # 2026-09-26 (owner) : un changement de modele ou de CLI rappelle l'audit de prompts au demarrage, jusqu'a acquittement.
    "tests/nr/test_session_start_rappel_audit_nr.py",
    # 2026-09-26 : --sortie relatif de la mesure pip-audit resolu contre le depot (NREM1 lisait un echec).
    "tests/nr/test_pip_audit_sortie_relative_nr.py",
    # Sauvegarde : cle hors des arguments (py7zr en processus), cible fixe E:, meme volume ecarte.
    "tests/nr/test_sauvegarde_cible_fixe_nr.py",
    # Chaine proposer -> appliquer cablee : reflexe seul, cortical jamais, acte trace.
    "tests/nr/test_pattern_proposal_applier_nr.py",
    # Capacite OBSERVEE des fournisseurs (x-ratelimit-*) captee au point d'appel litellm du
    # routeur ; FRAICHE / PERIMEE / INCONNU, MAL_FORME dit, liste blanche (2026-10-02).
    "tests/nr/test_capacite_fournisseur_observee_nr.py",
    # Regeneration L1 (2026-10-01, rendu claude.ai relu par CLAUDE) : set_param sur liste blanche,
    # cortical tant que la porte n'est pas armee, valeur precedente memorisee, retour a l'empreinte.
    "tests/nr/test_applicateur_set_param_l1_nr.py",
    # Regeneration : mesure APRES application, revert reel (git revert -m 1) PROUVE par l'arbre et
    # la bande, frein a deux reverts -- sur un DEPOT TEMPORAIRE (git local seul).
    "tests/nr/test_controleur_mesure_apres_revert_nr.py",
    # Un depot portant un chemin invalide sous NTFS (searxng `...conf:socket`) se clone
    # quand meme : chemin NOMME et exclu, le reste extrait (2026-09-23).
    "tests/nr/test_veille_clone_chemins_windows_nr.py",
    # Le capteur suit les depots DUMPES (identite deduite comme le dumper) et
    # re-recupere les CRITIQUES sur une intention de 180 j (decision owner 2026-09-23).
    "tests/nr/test_veille_github_critiques_nr.py",
    # 2026-09-23 : dumps de veille hors depot (E:), resolveur unique des 4 lecteurs.
    "tests/nr/test_veille_dumps_hors_depot_nr.py",
    # 2026-09-23 : ver Shai-Hulud dans le registre de veille — refus d'auto-lancement,
    # controle securite (marqueurs + Defender) au point de passage vers le RAG.
    "tests/nr/test_veille_intake_autolance_nr.py",
    # 2026-09-23 : ingestion d'un dump EN FLUX (job tue a 7 138 Mo), equivalence prouvee.
    "tests/nr/test_gitingest_ingest_flux_nr.py",
    # 2026-09-23 : substance seulement (owner points 1-4) + resume de la moelle.
    "tests/nr/test_veille_substance_nr.py",
    # 2026-09-23 : journal_size_limit sur les deux portes d'ecriture + priorite memoire.
    "tests/nr/test_wal_journal_size_limit_nr.py",
    # 2026-09-23 : le moteur RAG ne charge plus les chunks active=0 (raffinage owner).
    "tests/nr/test_rag_respecte_active_nr.py",
    # 2026-09-23 : re-filtrage LOCAL v3 des dumps (sans re-cloner), tracable, source intacte.
    "tests/nr/test_veille_refiltrage_local_nr.py",
    # 2026-09-23 : l'ingestion regule le WAL (attend le checkpoint) au lieu de l'empiler.
    "tests/nr/test_veille_regulation_wal_nr.py",
    "tests/nr/test_drains_sont_gouvernes_nr.py",
    "tests/nr/test_watch_tache_m2m_nr.py",
    # `test_inbox_ownership_route_nr` n'est PAS ici : il importe `nokido_hub`,
    # dont l'import reinitialise le manager de jetons et casse 9 tests de
    # `test_cycle_de_vie_jetons_nr` PLUS LOIN dans la suite (mesure 2026-09-22 :
    # 15/15 en isolation, 9 echecs des que les deux tournent ensemble,
    # « Format token invalide »). Sa place est BLOCS_ISOLES, avec les autres
    # tests qui chargent le hub.
    # Commite mais declare NULLE PART jusqu'au 2026-09-22 : il ne tournait donc
    # ni en local ni sur GitHub. Mesure avant declaration : 1 test, VERT.
    "tests/nr/test_appui_forge_hub_token_rotation_nr.py",
    "tests/nr/test_revocation_chemins_connus_nr.py",
    "tests/nr/test_rag_stats_ne_lit_pas_le_texte_nr.py",
    "tests/nr/test_capacite_atteinte_sans_garde_nr.py",
    "tests/nr/test_matrice_loopback_credential_nr.py",
    # Audit « noms non definis » (2026-09-29, mesures/audits/noms_non_definis.md) :
    # un NR par bug corrige, statiques (symtable, helper tests/nr/_noms_lies.py),
    # purs -- aucun service, aucun reseau, aucun secret.
    "tests/nr/test_handler_ci_journal_loop_nr.py",
    "tests/nr/test_handler_ci_loop_orchestrateur_nr.py",
    "tests/nr/test_dispatch_ai_routeur_intelligent_nr.py",
    "tests/nr/test_skilltree_legacy_asyncio_nr.py",
    "tests/nr/test_at_dispatch_escape_nr.py",
    "tests/nr/test_at_dispatch_ssh_cle_nr.py",
    "tests/nr/test_at_dispatch_ssh_reconnexion_nr.py",
    "tests/nr/test_at_dispatch_ssh_version_nr.py",
    "tests/nr/test_at_dispatch_debug_log_nr.py",
    "tests/nr/test_at_dispatch_scan_rag_nr.py",
    "tests/nr/test_at_dispatch_ids_disponibilite_nr.py",
    "tests/nr/test_at_dispatch_ids_etat_nr.py",
    "tests/nr/test_at_dispatch_agentic_moteur_nr.py",
    "tests/nr/test_at_dispatch_evolve_contexte_nr.py",
    "tests/nr/test_at_dispatch_ollama_statut_nr.py",
    "tests/nr/test_at_dispatch_ragas_etat_ollama_nr.py",
    "tests/nr/test_at_dispatch_services_ajout_nr.py",
    "tests/nr/test_dispatch_ai_apprentissage_predictif_nr.py",
    "tests/nr/test_dispatch_ai_badges_agents_nr.py",
    "tests/nr/test_dispatch_ai_suggestions_terminal_nr.py",
    "tests/nr/test_dispatch_ai_commandes_alternatives_nr.py",
    "tests/nr/test_dispatch_network_ids_etat_nr.py",
    "tests/nr/test_handler_ci_workflow_prefect_nr.py",
    "tests/nr/test_handler_ci_loop_merge_checkpoint_nr.py",
    "tests/nr/test_handler_rag_chemins_nr.py",
    "tests/nr/test_handler_rag_validation_suggestion_nr.py",
    "tests/nr/test_nokido_validation_suggestion_nr.py",
    "tests/nr/test_hub_handlers_loop_self_nr.py",
    "tests/nr/test_hub_handlers_loop_contexte_nr.py",
    "tests/nr/test_hub_handlers_workflow_hub_nr.py",
    "tests/nr/test_hub_handlers_delegations_nr.py",
    "tests/nr/test_hub_handlers_prefect_nr.py",
    "tests/nr/test_loop_propagation_patch_nr.py",
    "tests/nr/test_loop_apply_suggestion_signature_nr.py",
    "tests/nr/test_loop_apply_suggestion_contexte_nr.py",
    "tests/nr/test_nokido_apply_suggestion_nr.py",
    "tests/nr/test_nokido_post_loop_safe_check_nr.py",
    "tests/nr/test_handler_patch_run_escape_nr.py",
    "tests/nr/test_handler_patch_classify_texte_nr.py",
    "tests/nr/test_handler_patch_debug_log_nr.py",
    "tests/nr/test_handler_patch_classify_agenttype_nr.py",
    "tests/nr/test_handlers_classify_wrapper_nr.py",
    "tests/nr/test_core_models_classify_texte_nr.py",
    "tests/nr/test_handlers_compose_nr.py",
    "tests/nr/test_handlers_handle_rag_non_masque_nr.py",
    "tests/nr/test_handlers_role_nr.py",
    "tests/nr/test_handlers_debug_log_nr.py",
    "tests/nr/test_core_models_prefect_ssh_nr.py",
    "tests/nr/test_handlers_contexte_distant_nr.py",
    "tests/nr/test_handlers_classifieur_intention_nr.py",
    "tests/nr/test_handlers_types_routage_nr.py",
    "tests/nr/test_core_models_session_unregister_nr.py",
    "tests/nr/test_core_models_classifieur_predictif_nr.py",
    "tests/nr/test_nokido_jauge_entropie_nr.py",
    "tests/nr/test_nokido_contexte_distant_nr.py",
    "tests/nr/test_agentic_evolve_contexte_nr.py",
    "tests/nr/test_disco_proxy_nr.py",
    "tests/nr/test_mixin_ai_noms_nr.py",
    "tests/nr/test_mixin_patch_audit_memoire_nr.py",
    "tests/nr/test_mixin_patch_focus_saisie_nr.py",
    "tests/nr/test_mixin_patch_checkpoints_nr.py",
    "tests/nr/test_runtime_embedder_local_nr.py",
    "tests/nr/test_runtime_generateur_local_nr.py",
    "tests/nr/test_ssh_assistant_conteneurs_nr.py",
    "tests/nr/test_ssh_handle_reconnexion_nr.py",
    "tests/nr/test_ui_widgets_ecrans_modaux_nr.py",
    # sys.stdout remplace a l'IMPORT (2026-09-29, mesures/audits/stabilite_ci.md 2.2) : un NR par
    # module deplace ; purs -- import sous une fausse sortie + AST, aucun service,
    # aucun reseau, aucun secret.
    "tests/nr/test_stdout_import_goap_hub_bridge_nr.py",
    "tests/nr/test_stdout_import_self_patcher_nr.py",
    "tests/nr/test_stdout_import_paste_clean_nr.py",
]

# ── tests d'APPUI generes ────────────────────────────────────────────────────
# NON inscrits dans la suite pure — MESURE du 2026-09-08, abstention DELIBEREE.
#
# Verses d'un bloc dans PURE_TESTS, ils font CRASHER pytest : rc 0xC0000005
# (ACCESS_VIOLATION) au 8717e test, sans resume, sans JUnit, sans stderr — trois runs
# de CI perdus a chercher un test rouge qui n'existait pas. Or chacun passe SEUL, et
# par lots de quatre : ce n'est donc aucun module en particulier, c'est le CUMUL de
# quelques milliers d'imports dans UN process. Meme motif que `_a_part` plus bas, ou
# des fichiers sont deja joues dans une invocation separee pour cette raison.
#
# Tant que leur integration n'est pas MESUREE (invocation dediee, ou lots bornes),
# les inscrire ferait rougir la CI de tout le monde pour un gain de metrique. On
# observe avant d'enforcer — et on l'ECRIT, plutot que de laisser une absence passer
# pour un oubli.
#
# Consequence assumee : ces tests ne protegent aucune surface tant qu'ils ne sont pas
# dans la suite, et `perimetre non vide` ne les compte pas non plus (ils echappent aux
# quatre conventions ET a la detection par import, qui ne voit pas `import_module`).
# Les deux points restent OUVERTS.

# ast-bunker (miroir eco-shield.yml job ast-bunker) : parse + feature-flags.
_BUNKER_TARGETS = [
    "app/forge_collab_modes.py",
    "app/forge_ollama_bridge.py",
    "app/forge_prompt_guard.py",
    "app/forge_conv_sanitizer.py",
    "app/forge_env_crypt.py",
    "app/forge_settings.py",
    "tools/nokido_mcp_server.py",
]


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# ── TROIS ETATS, PAS DEUX ────────────────────────────────────────────────────
# PASS   : le gate a tourne et n'a rien trouve.
# FAIL   : le gate a tourne et a trouve un defaut.
# UNKNOWN: le gate n'a PAS PU se prononcer (outil absent, service down, secret
#          manquant). Ce n'est pas un succes — c'est une ABSENCE DE MESURE.
#
# MESURE 2026-08-14 : `return name, (ok or not blocking)` rendait TRUE pour tout
# gate non bloquant, meme en echec. Au resume, pip-audit trouvant 18
# vulnerabilites, archi-lint violant les Golden Rules et gitleaks introuvable
# s'affichaient tous en vert. Et un rc!=0 « binaire absent » etait indistinguable
# d'un rc!=0 « defaut trouve ». Dix commits ont ete pousses ce jour-la sur la foi
# de ce vert.
#
# Un UNKNOWN sur un domaine CRITIQUE bloque la livraison — sauf si un SUPPLEANT
# est declare : un controle peut legitimement etre couvert ailleurs, mais cela
# doit etre ECRIT, pas suppose.
_INCONCLUS: list = []

# Duree de CHAQUE gate, remplie par `_run` (leur point de passage unique). Sert a
# repondre « quel gate coute quoi » par la mesure, et non par la reputation des
# outils. Ajoute le 2026-09-04 quand la suite pure a cesse d'etre le goulot.
_CHRONO: list = []


def _afficher_chrono() -> None:
    """Classement des gates par duree, du plus cher au moins cher.

    Sans ce classement, la prochaine optimisation viserait ce qu'on CROIT lent. Le
    total est rappele pour que chaque part se lise en proportion : gagner 80 % sur
    un gate qui pese 3 % du temps ne se voit pas (loi d'Amdahl, deja verifiee ici --
    diviser pytest par trois n'a fait baisser la CI complete que de 23 %).
    """
    if not _CHRONO:
        return
    total = sum(d for _n, d in _CHRONO)
    print("\n\033[1;36m═══ TEMPS PAR GATE ═══\033[0m")
    for nom, d in sorted(_CHRONO, key=lambda x: x[1], reverse=True):
        part = (d / total * 100) if total else 0
        barre = "█" * max(1, int(part / 2.5))
        print("  %6.1f s  %5.1f%%  %-38s %s" % (d, part, nom[:38], barre))
    print("  %6.1f s  100.0%%  TOTAL (gates seuls, hors orchestration)" % total)
# CAUSES D'ANERGIE MESUREES. Une anergie sans cause ni suppleant se relit comme
# une negligence ; nommee, elle devient soit reparable, soit assumee.
# ⚠️ N'inscrire ici qu'une cause MESUREE, jamais supposee : une explication
# inventee est pire qu'une case vide, elle clot l'enquete.
def _coffre_de_l_installation():
    """Le coffre DPAPI de l'INSTALLATION — pas celui de l'arbre juge.

    En mode `--reference`, `ROOT` designe un worktree detache ou `data/` est
    gitignore : le coffre n'y est pas. On remonte alors au depot principal par
    le `gitdir` du worktree (`.git` y est un FICHIER, pas un dossier).

    Rend `None` quand il ne trouve pas — et l'appelant le DIT. Ne devine jamais
    un chemin : un coffre absent et un coffre vide se lisent tous deux « secret
    absent », donc une fausse piste couterait une enquete.

    ⚠️ Cette fonction doit rester au NIVEAU MODULE. Posee une premiere fois
    juste avant le bloc `ui-acceptance`, dont le commentaire est INDENTE, elle
    a coupe en deux la fonction englobante : 23 `undefined name` sur `a` et
    `results`, et les tests restaient verts parce qu'aucun ne traverse cette
    zone. Une ancre indentee ne recoit jamais un `def` de premier niveau.
    """
    local = ROOT / "data" / "machine_vault.dat"
    if local.exists():
        return local
    g = ROOT / ".git"
    try:
        if g.is_file():
            brut = g.read_text(encoding="utf-8", errors="replace").strip()
            if brut.startswith("gitdir:"):
                p = Path(brut.split(":", 1)[1].strip())
                # .../<depot>/.git/worktrees/<nom>  ->  <depot>/data/...
                for parent in p.parents:
                    if parent.name == ".git":
                        cand = parent.parent / "data" / "machine_vault.dat"
                        if cand.exists():
                            return cand
                        break
    except OSError:  # muet-ok : on rend None, et l'appelant l'annonce
        pass
    return None


_ANERGIE_CAUSES = {
    "pip-audit": (
        "POLITIQUE DE COMPTE, pas une panne. La CI tourne sous "
        "`LaForgeSbxOffline`, dont l'egress est bloque : mesure du 2026-09-17, "
        "meme machine et meme instant, `pypi.org` rend HTTP 000 en 0,03 s "
        "sous ce compte (refus LOCAL immediat) et HTTP 200 en 0,33 s sous "
        "`LaForgeSbxOnline`. Seul le COMPTE change. "
        "`DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE` : installer pip-audit n'y "
        "changerait rien, l'outil tourne. Et l'herméticite de la CI est VOULUE "
        "-- lui donner l'egress ferait passer des tests capables de joindre le "
        "reseau sans qu'on le sache. La mesure part donc en `run_job "
        "online=true` (declaree en NREM1 du circadien depuis le 2026-09-17), et "
        "ce gate JUGE la fraicheur du rapport au lieu de refaire l'appel"
    ),
    "archi-lint": (
        "semgrep est INSTALLE mais meurt au demarrage sous les comptes de "
        "service (CertOpenSystemStore rend NULL : pas de magasin de certificats "
        "utilisateur). Verifie le 2026-09-16 sous LaForgeSbxOffline ET "
        "LaForgeSbxOnline ; le plantage precede les options, donc "
        "SEMGREP_SEND_METRICS=off n'y change rien"
    ),
}


def _anergie_detail(cle: str) -> str:
    """Le complement du message d'anergie : cause mesuree et suppleant declare.

    MESURE 2026-09-16 : `archi-lint` a ete signale ANERGIQUE (domaine CRITIQUE)
    quatre fois dans la meme journee, sans qu'aucune action soit possible et
    alors que son domaine EST couvert par un suppleant declare. Le message
    alarmait donc sur un trou qui n'existait pas, et taisait la seule chose
    utile : pourquoi le garde ne se prononce plus.

    Un garde qui crie a faux se fait desarmer -- on corrige le faux positif,
    on ne supprime pas le signal. Rien n'est invente : sans cause mesuree NI
    suppleant declare, le complement reste VIDE.
    """
    bouts = []
    cause = _ANERGIE_CAUSES.get(cle)
    if cause:
        bouts.append("cause : %s" % cause)
    supp = _SUPPLEANTS.get(cle)
    if not supp:
        # ⚠️ DEUX CHEMINS, UN SEUL LISAIT LA TABLE (mesure 2026-09-17).
        # Un suppleant peut etre DECLARE en dur (`_SUPPLEANTS`) ou CONSTATE a
        # l'execution, avec sa date -- c'est le cas de `pip-audit`, supplee par
        # un rapport deporte dont la fraicheur est calculee au moment du run.
        # `_anergie_detail` ne lisait que la table statique : le meme rapport
        # affichait donc « supplee par pip_audit_<date>, 0.9 j » trois lignes
        # au-dessus de « ANERGIQUE — aucun verdict reel depuis jamais », sans
        # suppleant. Le detail juste et l'agregat nu, dans le meme ecran.
        for _nom, _bloquant, _constate in (_INCONCLUS or []):
            if _constate and _nom.split()[0].lower() == cle:
                supp = _constate
                break
    if supp:
        bouts.append("domaine SUPPLEE par %s" % supp)
    return (" — " + " | ".join(bouts)) if bouts else ""


_DOMAINES_CRITIQUES = ("gitleaks", "pip-audit", "archi-lint", "golden-rules",
                       "duplication", "license", "capacites",
                       "ui-acceptance", "integration", "ast-bunker")
_SUPPLEANTS = {
    "gitleaks": "pre-commit secret-guard (hook Nokido, scanne chaque commit)",
    # `forge_golden_rules_ast` a ete ecrit POUR remplacer semgrep, devenu aveugle
    # (reseau ferme en sandbox, site-packages non inscriptible). Il tourne, lui,
    # et porte le cliquet ERROR : archi-lint non mesure n'est donc pas un trou
    # de couverture -- mais cela doit se DIRE, pas se deguiser en vert.
    "archi-lint": "golden-rules (moteur AST natif, cliquet ERROR)",
}
_RC_OUTIL_ABSENT = (9009, 127)   # cmd.exe / POSIX : commande introuvable

# Empreinte des fichiers que la fermeture commiterait, figee AU DEBUT du run.
# L'arbre est VIVANT pendant les douze minutes qui suivent : sans ce temoin, le
# `git add` final emporterait l'etat du disque a t2, pas celui mesure a t0.
_EMPREINTES_FERMETURE: dict = {}

# Au-dela, une mesure d'approvisionnement ne vaut plus verdict : les avis OSV
# bougent tous les jours, un rapport ancien dit l'etat d'un AUTRE depot.
_AUDIT_FRAICHEUR_J = 7


def _age_mesure(chemin) -> tuple:
    """(age_en_jours, source_de_la_date) — la date du NOM prime sur le mtime.

    Un checkout de worktree rajeunit tous les fichiers : `st_mtime` y ferait passer
    une mesure de 2020 pour celle du jour. La date vit donc dans le nom
    (`pip_audit_2026-09-07.json`), qui survit au checkout et au versionnement. Le
    repli sur mtime reste possible mais il se DIT, sinon on ne sait pas quelle
    horloge a servi. Un chemin absent leve : ABSENT n'est ni frais ni perime.
    """
    from nokido_agent.tools.forge_deps_reconcilier import date_du_nom  # noqa: PLC0415

    p = Path(chemin)
    stat = p.stat()  # leve si absent, volontairement
    depuis = date_du_nom(p)
    if depuis is not None:
        return (time.time() - depuis) / 86400.0, "date du nom"
    return (time.time() - stat.st_mtime) / 86400.0, "repli mtime (nom sans date)"


_MAGASINS_PLAYWRIGHT = (Path("C:/nokido/ms-playwright"),)


def _magasin_playwright(home=None, magasins=None) -> tuple:
    """(chemin, motif) — ou vivent les navigateurs, SANS le deduire du HOME.

    MESURE 2026-09-09, en lancant Playwright NU (sans profil persistant) :

        BrowserType.launch: Executable doesn't exist at
          C:/Users/Default/AppData/Local/ms-playwright/firefox-1532/firefox/firefox.exe

    `firefox-1532` -- la version EXACTE reclamee -- est present dans
    `C:/nokido/ms-playwright`. Rien ne manquait : Playwright derive son magasin de
    HOME, qui vaut `C:/Users/Default` pour les comptes de service. Meme famille que
    `_python_ui`, un etage plus bas.

    Ce qui l'a rendu invisible : la campagne passe par `launch_persistent_context`,
    qui PEND puis expire a 180 s (« harnais mort au lancement ») au lieu de nommer
    l'executable manquant. Un timeout ne dit rien ; c'est le lancement nu qui a rendu
    la cause en deux secondes. Reflexe : devant un timeout muet, RETIRER les options
    avant de changer de compte.

    Le HOME reste prioritaire s'il porte deja un magasin : on ne redirige que ce qui
    serait autrement introuvable.
    """
    home = Path.home() if home is None else Path(home)
    essais = []
    du_home = home / "AppData" / "Local" / "ms-playwright"
    for origine, cand in ([("HOME", du_home)]
                          + [("magasin declare", Path(m))
                             for m in (magasins or _MAGASINS_PLAYWRIGHT)]):
        if cand.is_dir():
            return str(cand), origine
        essais.append("%s=%s" % (origine, cand))
    return None, "aucun magasin de navigateurs — essayes : " + " ; ".join(essais)


def _emettre_temoin_ui(rc, t0, only, ui_demande) -> dict:
    """Ecrit UI_ACCEPTANCE_WITNESS a cote du rapport de campagne.

    Le temoin repond a quatre questions que ni le `rc` ni le log ne permettent de
    trancher apres coup : qu'a-t-on execute, qu'a-t-on PAS execute, l'application
    a-t-elle vraiment ete jugee, combien de temps cela a pris.

    `selection` vient d'ICI et de nulle part ailleurs : la campagne ignore ce que la
    CI lui a demande. C'est pourtant le champ qui prouve l'EXCLUSIVITE -- « le bon
    gate s'execute » ne dit pas « SEUL le bon gate s'execute », et le 2026-09-09 le
    garde d'exclusivite etait mort sans que rien ne le signale.

    Ne bloque JAMAIS la CI : un temoin qui fait rougir un run est un juge, pas un
    temoin.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools import forge_ui_temoin as _tem
        from nokido_agent.tools.forge_lecture_json import lire as _lire

        base = ROOT / "sandbox" / "ui_campaign"
        rapport, etat = _lire(base / "report.json")
        if etat != "LU":
            rapport = {"verdict": "UNKNOWN", "reason": "rapport de campagne %s" % etat}
        # Les gates NON demandes qui se seraient executes quand meme : sous `--only`,
        # `_run` les court-circuite, donc la liste est vide par construction. Elle
        # cesserait de l'etre si un producteur echappait au selecteur -- c'est
        # precisement ce que le cliquet structurel surveille.
        temoin = _tem.construire({
            "identity": {"tested_sha": _sha_courant(), "run_id": os.environ.get("GITHUB_RUN_ID")},
            "selection": {"requested": ", ".join(only) if only else None,
                          "selected": ["ui-acceptance"] if ui_demande else [],
                          "non_selected_gates_executed": []},
            "transport": rapport.get("transport") or {},
            "browser": rapport.get("browser") or {},
            "report": rapport,
            "timing": {"duration_s_mesure_ci": round(time.time() - t0, 1)},
        })
        temoin["exit_code"] = rc
        (base).mkdir(parents=True, exist_ok=True)
        (base / "witness.json").write_text(
            json.dumps(temoin, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  \033[90m[temoin] UI_ACCEPTANCE_WITNESS final=%s — %s\033[0m"
              % (temoin["final"], temoin["application"]["reason"] or "contrat tenu"))
        return temoin
    except Exception as _e:  # noqa: BLE001 - le temoin ne fait jamais rougir un run
        print("  \033[90m[temoin] non emis (%s: %s)\033[0m"
              % (type(_e).__name__, str(_e)[:80]))
        return {}


def _sha_courant(env=None) -> str:
    """Le sha de l'arbre JUGE — dans un run `--reference`, celui du worktree.

    MESURE 2026-09-09 (run GitHub 34390571371) : le temoin est sorti
    `tested_sha: null`. Cette fonction n'interrogeait que `git rev-parse` et avalait
    son echec ; or `GITHUB_SHA` etait pose par le runner et ignore. Un temoin qui
    certifie sans dire sur QUOI ne certifie rien.

    L'ordre n'est pas arbitraire : `GITHUB_SHA` designe le commit que le workflow a
    CHECKOUT, c'est-a-dire exactement l'objet de la mesure. `git rev-parse` reste le
    repli local, et l'echec des deux rend None -- un sha inconnu se DIT, il ne
    s'invente pas.
    """
    env = os.environ if env is None else env
    depuis_ci = (env.get("GITHUB_SHA") or "").strip()
    if depuis_ci:
        return depuis_ci
    try:
        # `subprocess` est importe AU NIVEAU MODULE. La premiere version appelait
        # `_sp.run` — un alias importe dans une AUTRE fonction (ligne ~3120) :
        # `NameError` a chaque appel, avale par l'`except`, et le temoin rendait
        # `tested_sha: None`. La fonction ecrite pour empecher les certificats
        # ANONYMES en produisait un, en silence (mesure 2026-09-10, defaut
        # introduit par d22fcc676 la veille).
        #
        # Meme motif que l'amorce `sys.path` : un symbole importe dans une
        # fonction n'existe pas dans les autres. Un import n'est pas un contrat
        # entre fonctions.
        # `errors="replace"` : sans lui, un octet non decodable dans la sortie
        # fait lever `_readerthread` DANS subprocess — l'exception ne vient pas
        # de git mais du lecteur, et elle remonte a un endroit ou personne ne
        # l'attend. Anti-regression de l'incident 47 Go.
        return subprocess.run(["git", "-c", "safe.directory=*", "rev-parse", "HEAD"],
                              cwd=str(ROOT), capture_output=True, text=True,
                              errors="replace", timeout=10).stdout.strip() or None
    except Exception as _e:  # noqa: BLE001
        print("  \033[90m[temoin] sha indetermine (%s) — le temoin le dira\033[0m"
              % type(_e).__name__)
        return None


def _gravite_inconclusion(nom, demande_explicite) -> bool:
    """Cette inconclusion compte-t-elle comme un gate CRITIQUE non mesure ?

    REQUESTED != ACHIEVED, applique dans le bon sens. Ne pas obtenir un verdict
    qu'on a DEMANDE (`--ui-gate`, `--only <gate>`) est un echec. Ne pas obtenir un
    verdict que PERSONNE n'a demande -- le gate s'est reveille seul par
    auto-detection -- est une information.

    MESURE 2026-09-09 (CI de reference job_1dffb1d9eb38) : rc=1 avec « Tous les gates
    bloquants passent » et ZERO test en echec. Le rouge venait d'ici. Or le gate UI ne
    PEUT PAS juger sous le compte des jobs (Playwright pilote le navigateur par le
    loopback, que ce compte bloque) : l'auto-detection fabriquait donc un rouge
    PERMANENT sur toute CI locale. Un garde qui crie a faux se fait desarmer, et
    c'est le garde ENTIER qu'on perd, pas seulement son bruit.

    Ce n'est PAS un vert par absence : l'inconclusion reste consignee dans
    `_INCONCLUS` et AFFICHEE au resume. Seule sa gravite change. Sous
    `--only <gate>`, `_verdict_sans_mesure` continue par ailleurs de refuser de
    conclure quand rien n'a mesure.
    """
    return bool(demande_explicite) and _critique(nom)


def _ui_doit_tourner(ui_gate, only, ui_demande, ui_auto, fast, auto_permis=True) -> tuple:
    """(faut_il_lancer, motif) — la campagne ui-acceptance doit-elle s'executer ?

    MESURE 2026-09-09, trouvee par la DUREE d'un NR. Le garde d'exclusivite etait
    ecrit en `elif` de l'auto-detection :

        if not ui_gate and not ui_demande and not fast:
            ui_auto = _webhub_repond()[0]
        elif ONLY and not ui_demande:
            ui_auto = False          # <-- BRANCHE MORTE

    Sous `--only "ruff critique"` les TROIS conditions du `if` sont vraies : la
    premiere branche est prise et le `elif` n'est jamais atteint. Des que :7400
    repondait, `--only X` lancait donc la campagne UI complete — precisement ce que
    `--only` existe pour empecher.

    Le defaut est reste invisible parce qu'un SECOND le masquait : `_python_ui`
    resolvait l'interpreteur par `Path.home()`, faux sous le compte de service, donc
    le gate se sautait avant de demarrer. Corriger le second a revele le premier, en
    faisant passer `test_le_point_d_entree_traverse_vraiment` de 5 s a plus de 100 s.

    Une decision qui gouverne un gate ne reste pas enfouie dans une chaine if/elif :
    la sortir ici la rend testable SANS demarrer Playwright.
    """
    if ui_gate:
        return True, "--ui-gate explicite"
    if only:
        # EXCLUSIVITE, en premier et hors de toute autre condition.
        return bool(ui_demande), ("demande par --only" if ui_demande
                                  else "non demande par --only (exclusivite)")
    if fast:
        return False, "--fast : campagne UI hors du run partiel"
    if not auto_permis:
        # Un job DEDIE porte deja le contrat UI : le rejouer ici tuerait ce job-ci.
        # Mesure : `gates` dure 857 s pour une borne a 900 s, et la campagne a un
        # budget INTERNE de 480 s (`forge_ui_campaign._BUDGET_S`). L'auto-detection
        # reste le bon defaut en CI locale, ou aucun job dedie n'existe.
        return False, ("auto-detection desarmee (LAFORGE_UI_AUTO=0) : le contrat UI "
                       "est porte par un job dedie")
    return bool(ui_auto), ("auto-detecte : interface joignable" if ui_auto
                           else "auto-detecte : interface injoignable")


def _python_ui(home=None, executable=None, env=None) -> tuple:
    """(chemin, origine|motif) — l'interpreteur du gate UI, SANS dependre du HOME.

    MESURE 2026-09-09. La resolution etait `Path.home() / "miniforge3" / "envs" /
    "laforge_py314" / "python.exe"`. Sous le compte de service, `HOME=C:/Users/Default` :
    le chemin teste devenait `C:/Users/Default/miniforge3/...`, qui n'existe pour
    personne. Le gate se sautait donc lui-meme en accusant une absence qui n'en etait
    pas une -- les DEUX fichiers reels sont presents et lisibles depuis ce compte.

    L'interpreteur QUI EXECUTE est present par construction : c'est la source de verite
    du corps (`forge_python_bin.LAFORGE_PYTHON` vaut `sys.executable`). On l'emprunte
    au lieu de reconstruire un chemin depuis un HOME qui n'est pas le notre.

    Chaque candidat ecarte est NOMME dans le motif : une absence dit ce qu'elle n'a pas
    pu voir, sinon elle est indiscernable de « je n'ai pas regarde ».
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    executable = sys.executable if executable is None else executable
    essais = []
    for origine, cand in (
            ("LAFORGE_UI_PYTHON", env.get("LAFORGE_UI_PYTHON")),
            ("interpreteur courant", executable),
            ("HOME/miniforge3", str(home / "miniforge3" / "envs"
                                    / "laforge_py314" / "python.exe"))):
        if not cand:
            continue
        if Path(cand).exists():
            return cand, origine
        essais.append("%s=%s" % (origine, cand))
    return None, ("aucun interpreteur trouve — essayes : "
                  + " ; ".join(essais or ["(aucun candidat)"]))


def _webhub_repond(port: int = 7400, timeout: float = 2.5) -> tuple:
    """(joignable, motif) — l'interface web repond-elle APPLICATIVEMENT ?

    ⚠️ TRANSPORT != APPLICATIF. Un port en LISTEN ne prouve pas qu'une page se charge :
    le 2026-09-06, :7400 ecoutait avec quatre CLOSE_WAIT accumules et tout GET expirait
    -- transport vivant, applicatif mort. On interroge donc `/health`, et un 401 sur `/`
    compte comme une REPONSE (l'AuthMiddleware fait son travail), pas comme une panne.

    Un refus NOMME sa cause : « injoignable » sans motif se re-instruit a chaque run.
    """
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    url = "http://127.0.0.1:%d/health" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status == 200:
                return True, "GET /health 200"
            return False, "GET /health rend %s" % r.status
    except urllib.error.HTTPError as e:
        # Une reponse HTTP, meme 4xx, prouve que l'applicatif tourne.
        return True, "GET /health rend %s (applicatif vivant)" % e.code
    except Exception as e:  # noqa: BLE001
        return False, "injoignable sur :%d (%s)" % (port, type(e).__name__)


def _mesure_pip_audit_deportee() -> tuple:
    """(frais, detail) — le gate JUGE ce qu'un autre compte a MESURE.

    Le compte de la CI n'a pas d'egress : `pypi.org` rend `WinError 10013` et l'audit
    meurt avant le premier paquet (2026-09-07). La mesure est donc produite par
    `tools/forge_pip_audit_mesure.py`, lance en `run_job online=true`, qui n'ecrit un
    rapport QUE s'il a reellement audite. Ici on ne fait que lire sa FRAICHEUR.

    On reutilise `forge_deps_reconcilier.rapport_courant()` — sa selection du plus
    recent a ete corrigee le 2026-09-07 apres qu'un nom code en dur eut fait annoncer
    135 CVE quand il en restait 45. Une seconde selection divergerait le jour ou l'une
    des deux serait corrigee.
    """
    try:
        from nokido_agent.tools.forge_deps_reconcilier import rapport_courant  # noqa: PLC0415

        src = rapport_courant()
    except Exception as e:  # noqa: BLE001
        return False, "selection du rapport indisponible (%s)" % type(e).__name__
    if not src or not Path(src).exists():
        return False, ("aucun rapport deporte dans sandbox/ — lancer "
                       "forge_pip_audit_mesure.py en run_job online=true")
    age_j, _source = _age_mesure(src)
    if age_j > _AUDIT_FRAICHEUR_J:
        return False, ("rapport %s vieux de %.1f j (> %d j, %s) : perime, pas absent"
                       % (Path(src).name, age_j, _AUDIT_FRAICHEUR_J, _source))
    return True, ("mesure deportee %s, %.1f j (< %d j, %s)"
                  % (Path(src).name, age_j, _AUDIT_FRAICHEUR_J, _source))

# ── VITALITE DES GARDES : depuis QUAND ce gate a-t-il rendu un verdict REEL ? ─
# _INCONCLUS ne voit qu'UN run. Un gate qui cesse d'etre lance — retire d'un
# workflow, binaire desinstalle, flag opt-in jamais repasse — ne produit plus
# AUCUNE ligne : il disparait du resume au lieu d'y crier. C'est l'ANERGIE, le
# vert par absence. Deja paye deux fois : semgrep a affiche `scanned_files=0`
# avec une coche verte pendant des semaines, et le cliquet de mutation est
# reste INDETERMINE muet sans que personne le voie.
# Le registre est un CLIQUET commite, au meme endroit que le socle de mutation :
# il ne mesure pas le code, il mesure LES GARDES.
VITALITE = ROOT / "tests" / "nr" / "vitalite_gardes.json"
_ANERGIE_JOURS = 14   # au-dela, un gate d'un domaine CRITIQUE bloque la livraison


def _cle_garde(name: str) -> str:
    """Nom stable d'un gate : sans suffixe d'etat ni parenthese de detail."""
    return name.split(" [")[0].split(" (")[0].strip().lower()


def marque_resume(nom, ok, cles_inconclues) -> str:
    """OK | ECHEC | INCONNU pour UN gate du resume. Decision PURE.

    L'INCONCLUSION PRIME SUR LE BOOLEEN, et ce n'est pas un detail : `_run` rend
    True sur un UNKNOWN (« pas un echec du CODE »), donc lire la marque sur `ok`
    seul affiche un succes la ou rien n'a ete mesure.

    L'appariement se fait sur la CLE, jamais sur le libelle. Mesure du 2026-09-14
    (certification de `3ecc8d5a3`) : `results` enregistre « ui-acceptance (contrat
    web_hub :7400) [NON JUGE] » et `_INCONCLUS` « ui-acceptance (contrat web_hub
    :7400) » -- l'egalite de chaines echouait, et un gate portant « NON JUGE »
    dans son propre libelle s'affichait VERT."""
    if _cle_garde(nom) in (cles_inconclues or set()):
        return "INCONNU"
    return "OK" if ok else "ECHEC"


def phrase_non_mesures(inconclus) -> str:
    """Ce que la ligne finale a le droit d'affirmer. Decision PURE.

    Elle disait « tous supplees » EN DUR, sans jamais le verifier. Le meme ecran
    portait alors, a trois lignes d'intervalle, « NON MESURE (aucun supplement
    declare) » et « tous supplees » -- le detail juste, l'agregat faux. Un agregat
    qui ne compte pas affirme ; celui-ci compte, et NOMME ceux qui manquent."""
    if not inconclus:
        return ""          # rien a signaler n'ecrit rien : une parenthese vide inquiete
    sans = [n for n, _b, s in inconclus if not s]
    total = len(inconclus)
    if not sans:
        return "%d non mesure(s), tous supplees" % total
    return ("%d non mesure(s), %d supplee(s), %d SANS suppleant : %s"
            % (total, total - len(sans), len(sans),
               ", ".join(_cle_garde(n) for n in sans)))


# Depot de repli : `tests/nr/` n'est PAS inscriptible par les comptes sandbox, sous
# lesquels tourne `run_job`. Meme patron que la capture de generation — la mesure
# est DEPOSEE ici, l'inscription dans l'arbre versionne est un geste gouverne
# (`tools/forge_vitalite_inscrire.py` en `trusted_script`).
VITALITE_ATTENTE = ROOT / "sandbox" / "vitalite_en_attente" / "vitalite_gardes.json"

# MODE PREUVE : les sorties de run QUITTENT l'arbre juge (2026-09-11).
# Mesure du premier run `--reference` reel : les gates avaient bien bascule dans le
# worktree, mais PROOF_DIR restait VIDE et `tests/nr/vitalite_gardes.json` — un
# fichier SUIVI — y etait ecrit. Il ne bloquait la capture que parce que la liste
# blanche le tolere, et une tolerance n'est pas une justification.
# Le registre de vitalite est un cliquet COMMITE : l'ecrire dans un worktree detache
# qui sera detruit n'a aucun sens. En mode preuve il rejoint donc les artefacts,
# hors de l'arbre que la capture s'apprete a juger. Sans PROOF_DIR, RIEN ne change :
# pour un run ordinaire le cliquet reste a sa place versionnee.
_PROOF_DIR = os.environ.get("NOKIDO_PROOF_DIR")
if _PROOF_DIR:
    VITALITE = Path(_PROOF_DIR) / "vitalite_gardes.json"
    VITALITE_ATTENTE = Path(_PROOF_DIR) / "vitalite_gardes.json"


def _racine_artefacts(compte: str) -> Path:
    """Ou vivent les artefacts d'un run : basetemp pytest, rapport JUnit, gitconfig.

    EN MODE PREUVE ils quittent l'arbre juge. Mesure du 2026-09-11 : apres avoir
    sorti le registre de vitalite, `git status` du worktree juge portait encore
    `?? sandbox/ci_<compte>/`. La capture l'acceptait -- `sandbox/` est une sortie
    de preuve declaree -- mais une TOLERANCE n'est pas une justification : le
    worktree de preuve doit rester exclusivement le CODE JUGE.

    Hors mode preuve, l'emplacement historique par compte est conserve tel quel, et
    il reste necessaire : deux comptes ne peuvent pas partager un basetemp (mesure
    2026-09-03, 7 731 « failed on setup »).
    """
    if _PROOF_DIR:
        return Path(_PROOF_DIR) / ("ci_%s" % compte)
    return ROOT / "sandbox" / ("ci_%s" % compte)


def _args_depuis_fichier(tests, fichier) -> list:
    """Ecrit la liste des tests (un par ligne) et rend l'argument pytest `@fichier` qui la designe.

    Plafond de CreateProcess : 32 767 car. MESURE 2026-09-26 (CI de reference f6b3613bb) : 815 tests
    declares = 34 714 car. de chemins relatifs ; Windows rend WinError 206, que Python leve en
    FileNotFoundError -- le gate a dit « outil introuvable » et la suite pure n'a PAS tourne. La liste
    avait franchi le plafond en grandissant. pytest (>= 8.2) lit ses arguments dans un fichier `@chemin` :
    la commande garde une longueur FIXE quel que soit le nombre de tests.
    """
    fichier = Path(fichier)
    fichier.write_text("".join("%s\n" % t for t in tests), encoding="utf-8")
    return ["@%s" % fichier]


def _args_suite_pure(tests, fichier, turbo: bool) -> tuple:
    """Arguments pytest de la suite pure et variables d'environnement a y ajouter : `(args, env)`.

    MESURE 2026-09-29 (audit stabilite CI, `mesures/audits/stabilite_ci.md`) : passer ~900 fichiers en
    ARGUMENTS rend la collecte QUADRATIQUE -- pytest re-parcourt le paquet `tests/nr` pour chacun :
    237 s contre 9,8 s avec un seul argument. Hors turbo on passe donc la seule racine `tests` et la
    liste dans NOKIDO_CI_LISTE ; `tests/conftest.py` ecarte sans les importer les fichiers absents de
    la liste et rejoue l'ordre declare.

    Repli sur `@fichier` (forme precedente, meme perimetre) quand le filtre ne peut pas s'appliquer :
    - turbo : le conftest RETIRE la variable a la configuration, avant que xdist lance ses workers ;
      ils collecteraient tout `tests/` ;
    - une entree hors `tests/`, qui n'est pas un fichier `.py`, ou qui vise un test (`::`) : le filtre
      ne sait retenir que des fichiers entiers sous `tests/`.
    """
    args = _args_depuis_fichier(tests, fichier)
    norm = [str(t).replace("\\", "/") for t in tests]
    if turbo or not norm or any("::" in t or not t.startswith("tests/") or not t.endswith(".py")
                                for t in norm):
        return args, {}
    return ["tests"], {"NOKIDO_CI_LISTE": str(Path(fichier))}

# DEUX AXES ORTHOGONAUX, et les confondre est le piege (2026-09-07).
#   etat de lecture : "LU" · "ABSENT" · "ILLISIBLE"
#   fraicheur       : "FRESH" · "STALE" · "INCONNUE"
#   perimetre       : "FULL" · "PARTIAL" · "UNKNOWN"
# `FRESH + PARTIAL` est un etat LEGITIME : un run `--fast` peut etre tout recent et
# ne couvrir qu'une fraction des gardes. **FRESH n'est pas COMPLETE.** Sans le
# perimetre, un registre partiel se relit comme l'etat complet du systeme, et les
# gardes qu'il ne couvre PAS passent pour « jamais mesures ».
_VITALITE_ETAT = "ABSENT"
_VITALITE_SOURCE = None
_VITALITE_FRAICHEUR = "INCONNUE"
_VITALITE_PERIMETRE = "UNKNOWN"

# TTL PROPRE a la vitalite. Ce n'est pas celui des capacites (72 h) : un domaine peut
# rester legitimement sans nouveau verdict plusieurs jours si la CI n'a pas tourne,
# sans que le registre soit pour autant douteux. Herite d'un autre domaine, ce seuil
# aurait crie a chaque week-end.
_VITALITE_TTL_J = 3


def _rel(p: Path) -> str:
    """Chemin DIT relatif au depot s'il y vit, absolu sinon -- ne leve JAMAIS.

    Mesure 2026-09-07 (run GitHub 34138167173, sha 22f7b1ef3, puis 34129668534) :
    `src.relative_to(ROOT)` levait ValueError sur le runner, dont le basetemp de
    pytest vit HORS du depot (_work/_temp), alors que le basetemp local vit DANS
    sandbox/ -- 3 CI locales vertes, 2 pushes rouges. Un chemin d'AFFICHAGE n'a
    pas le droit de faire tomber un gate ; NR test_vitalite_inscription_nr
    (fixtures au layout du runner).
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _charger_vitalite() -> dict:
    """Le registre le plus RECENT entre l'arbre versionne et le depot en attente.

    ⚠️ CE QUI A ETE PAYE (2026-09-07). L'ancienne version rendait `{}` sur OSError
    comme sur JSONDecodeError : un registre ILLISIBLE devenait indistinguable de
    « aucun garde n'a jamais rendu de verdict ». Or ce registre sert a detecter
    l'ANERGIE — un registre qu'on ne sait pas lire aurait donc declare TOUS les
    gardes morts d'un coup, a 14 jours, et rendu la CI rouge sur rien.
    `_ecrire_vitalite` l'annoncait deja dans son commentaire ; la lecture ne s'en
    protegeait pas.

    Le depot en attente peut etre PLUS FRAIS que l'arbre : les runs sous compte
    sandbox n'ecrivent que la. On prend le plus recent des deux, et on le DIT.
    """
    global _VITALITE_ETAT, _VITALITE_SOURCE, _VITALITE_FRAICHEUR, _VITALITE_PERIMETRE
    cands = [p for p in (VITALITE, VITALITE_ATTENTE) if p.exists()]
    if not cands:
        _VITALITE_ETAT, _VITALITE_SOURCE = "ABSENT", None
        _VITALITE_FRAICHEUR, _VITALITE_PERIMETRE = "INCONNUE", "UNKNOWN"
        return {}
    src = max(cands, key=lambda p: p.stat().st_mtime)
    try:
        with open(src, encoding="utf-8") as fh:
            brut = json.load(fh)
        gardes = brut.get("gardes", {})
    except (OSError, json.JSONDecodeError) as exc:
        _VITALITE_ETAT, _VITALITE_SOURCE = "ILLISIBLE", "%s (%s)" % (
            src.name, type(exc).__name__)
        _VITALITE_FRAICHEUR, _VITALITE_PERIMETRE = "INCONNUE", "UNKNOWN"
        return {}
    _VITALITE_ETAT, _VITALITE_SOURCE = "LU", _rel(src)
    # Un registre ANCIEN n'est pas un capteur vivant : sans cette distinction, un
    # fichier fige se relit comme « ces gardes ont ete vus a cette date ».
    _obs = brut.get("observe_le")
    if _obs:
        try:
            _age = (date.today() - date.fromisoformat(str(_obs)[:10])).days
            _VITALITE_FRAICHEUR = "FRESH" if _age <= _VITALITE_TTL_J else "STALE"
        except ValueError:
            _VITALITE_FRAICHEUR = "INCONNUE"   # date illisible : on ne devine pas
    else:
        _VITALITE_FRAICHEUR = "INCONNUE"       # champ absent (registre d'avant)
    _p = brut.get("perimetre")
    _VITALITE_PERIMETRE = _p if _p in ("FULL", "PARTIAL") else "UNKNOWN"
    return gardes


def _maj_vitalite(results: list[tuple[str, bool]], registre: dict, jour: str) -> dict:
    """Horodate au JOUR (pas a la seconde) : sinon le registre diffe a chaque run."""
    inconclus = {_cle_garde(n) for n, _b, _s in _INCONCLUS}
    for name, ok in results:
        cle = _cle_garde(name)
        fiche = registre.setdefault(cle, {})
        if cle in inconclus:
            if fiche.get("dernier_unknown") != jour:
                fiche["unknown_consecutifs"] = int(fiche.get("unknown_consecutifs", 0)) + 1
            fiche["dernier_unknown"] = jour
        else:
            fiche["dernier_reel"] = jour
            fiche["etat"] = "PASS" if ok else "FAIL"
            fiche["unknown_consecutifs"] = 0
    return registre


def _anergiques(registre: dict, jour: str) -> list[tuple[str, int, bool]]:
    """(cle, jours depuis le dernier verdict reel, domaine critique). -1 = jamais."""
    out: list[tuple[str, int, bool]] = []
    for cle, fiche in sorted(registre.items()):
        reel = fiche.get("dernier_reel")
        if not reel:
            out.append((cle, -1, _critique(cle)))
            continue
        try:
            ecart = (date.fromisoformat(jour) - date.fromisoformat(reel)).days
        except (TypeError, ValueError):  # muet-ok : date illisible = non datable
            # Donc non jugeable sur l'anergie : la compter en retard accuserait
            # a tort. INCONNU n'est pas NON.
            continue
        if ecart > _ANERGIE_JOURS:
            out.append((cle, ecart, _critique(cle)))
    return out


def _enveloppe_vitalite(registre: dict, partiel: bool) -> dict:
    """Le registre PORTE son propre contexte : sans lui, un consommateur ne peut ni
    juger sa fraicheur ni savoir ce qu'il couvre."""
    return {"genere_par": "tools/ci_local.py",
            "seuil_anergie_jours": _ANERGIE_JOURS,
            "observe_le": date.today().isoformat(),
            # Perimetre du FICHIER, pas du dernier run : apres fusion d'un depot
            # PARTIAL dans une cible FULL, le fichier reste aussi complet qu'avant.
            "perimetre": "PARTIAL" if partiel else "FULL",
            "gardes": registre}


def _ecrire_vitalite(registre: dict, partiel: bool = False) -> None:
    # Sur le runner, ecrire salirait l'arbre — et le cliquet de mutation exige un
    # arbre propre pour se prononcer. La fraicheur vient donc des runs locaux.
    if os.environ.get("CI"):
        return
    try:
        VITALITE.parent.mkdir(parents=True, exist_ok=True)
        with open(VITALITE, "w", encoding="utf-8") as fh:
            json.dump(_enveloppe_vitalite(registre, partiel),
                      fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        # Nommer le REMEDE, pas seulement le symptome. Mesure 2026-09-04 : le
        # registre n'etait plus ecrit depuis la veille parce que `run_job`
        # s'execute sous LaForgeSbxOffline, qui n'a que (R) sur tests/nr —
        # LaForgeTrusted y a (M) (`forge_compte_capabilites` : ecrire_tests_nr
        # = oui). Un avertissement qui ne dit pas quoi faire se relit comme du
        # bruit, et ce registre-ci detecte l'ANERGIE des gardes : gele, il finit
        # par les declarer tous morts a 14 jours, d'un coup et a tort.
        # DEPOT DE REPLI plutot qu'un avertissement seul : un registre qui n'avance
        # jamais n'est pas un cliquet. `run_job` tourne sous un compte sandbox qui
        # n'a que (R) sur tests/nr ; on ecrit donc ou l'on peut, et l'inscription
        # dans l'arbre versionne devient un geste gouverne — exactement le patron
        # deja employe pour la capture de generation.
        try:
            VITALITE_ATTENTE.parent.mkdir(parents=True, exist_ok=True)
            with open(VITALITE_ATTENTE, "w", encoding="utf-8") as fh:
                json.dump(_enveloppe_vitalite(registre, partiel),
                          fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            print(f"  ⚠ registre de vitalite non ecrit dans l'arbre ({exc})")
            print("     mesure DEPOSEE : %s" % _rel(VITALITE_ATTENTE))
            print("     inscription : `run action=trusted_script "
                  "path=tools/forge_vitalite_inscrire.py` (LaForgeTrusted ecrit "
                  "tests/nr ; les comptes sandbox ne le peuvent pas)")
        except OSError as exc2:
            print(f"  ⚠ registre de vitalite NI ecrit NI depose ({exc} / {exc2}) : "
                  "le cliquet n'avance pas, l'anergie sera sous-estimee")


def _critique(name: str) -> bool:
    n = name.lower()
    return any(d in n for d in _DOMAINES_CRITIQUES)


# ── SELECTEUR EXCLUSIF `--only` (2026-09-09) ───────────────────────────────────
# POURQUOI. Le workflow lance `ci_local.py --ui-gate` dans le job `ui-acceptance`.
# Or ce drapeau est ADDITIF -- son aide le dit : « + contrat d'acceptation UI ». Le
# job rejouait donc TOUTE la CI avant d'entamer la campagne, alors qu'il declare
# `needs: gates`, c'est-a-dire qu'il depend du job qui vient de faire ce travail.
# Mesure du run 34351716951 : gates 857 s (vert), ui-acceptance 929 s -> TUE a 15m00.
# Sept `cancelled` consecutifs viennent de la. Le timeout avait deja ete releve de 10
# a 15 min le 2026-08-30 pour ce meme symptome : on ne rallonge pas le tuyau avant
# d'avoir retire la boucle.
#
# Le selecteur se branche dans `_run`, PASSAGE UNIQUE des 21 gates : un seul site
# plutot que vingt et un, et aucun gate ne peut lui echapper par oubli.
_ONLY: list | None = None
_NON_DEMANDE = "\x00non-demande"   # sentinelle filtree avant le resume


def _poser_only(valeurs) -> None:
    """Arme (ou desarme avec None) la selection exclusive. Reversible."""
    global _ONLY
    _ONLY = [str(v).strip().lower() for v in (valeurs or []) if str(v).strip()] or None


def _demande(nom: str) -> bool:
    """Ce gate est-il demande ?

    Sans `--only`, TOUT est demande : le comportement par defaut ne bouge pas d'un
    iota. Avec `--only`, seul ce qui matche passe -- y compris un nom qui ne matche
    RIEN, auquel cas plus aucun gate ne tourne. C'est voulu : un filtre qui retombe
    sur « tout autoriser » quand il ne reconnait rien transformerait une faute de
    frappe en run complet, c'est-a-dire exactement le defaut qu'on corrige.
    """
    if not _ONLY:
        return True
    n = (nom or "").lower()
    return any(o in n for o in _ONLY)


def _run(name: str, cmd: list[str], blocking: bool, env: dict | None = None,
         rc_non_mesure: tuple = (), motifs_non_mesure: tuple = (),
         timeout_s: float | None = None) -> tuple[str, bool]:
    """`rc_non_mesure` : codes par lesquels CE gate dit « je n'ai pas pu lire ».

    `motifs_non_mesure` : marqueurs de SORTIE disant la meme chose, pour les outils
    dont le code de retour ne distingue pas « j'ai trouve un probleme » de « je n'ai
    pas pu regarder`. MESURE 2026-09-07 : `pip-audit` rend 1 dans les DEUX cas -- une
    CVE trouvee et pypi injoignable (`WinError 10013`, le compte de la CI n'a pas
    d'egress). Le gate etant `warn`, son rc non nul se lisait ✅ au resume : un
    domaine declare CRITIQUE affichait vert en n'ayant audite AUCUN paquet, en 1,3 s.
    Meme signature que la panne du 2026-09-06 (cache absent, 1,4 s), autre cause.
    Le rc ne pouvant pas discriminer, le signal est dans la SORTIE.

    MESURE 2026-08-19 : `forge_archi_lint` declare la convention dans son propre
    code -- `return 3` sur quatre chemins d'abandon, dont un commente « un gate
    qui ne lit rien ne vaut pas un vert ». Mais l'appelant ne connaissait que
    `_RC_OUTIL_ABSENT` : rc=3 retombait donc en « warn », et le resume affichait
    ✅ alors que semgrep n'avait pas demarre et que ZERO fichier avait ete lu.
    L'auteur du gate avait code l'intention ; l'appelant ne l'avait jamais lue.
    """
    if not _demande(name):
        # Non demande : on n'execute RIEN et on ne pollue pas le resume. La
        # sentinelle est filtree en tete de `_summary`.
        return (_NON_DEMANDE, True)
    print(f"\n\033[1;36m── {name} ──\033[0m  {'(bloquant)' if blocking else '(warn)'}", flush=True)
    # PROGRESSION LISIBLE DE L'EXTERIEUR. `read_job()` joint une cle `progress`
    # et `forge_vitals_tools` appelle `all_active()` : deux consommateurs qui
    # n'avaient AUCUN emetteur (le module lui-meme n'existait pas). Un run de CI
    # se suivait donc en pollant `log_tail`, a l'aveugle, alors que le contrat de
    # sortie prevoyait la barre. Emettre ici couvre TOUTES les etapes d'un coup :
    # `_run` est leur point de passage unique.
    _run.__dict__["n"] = _run.__dict__.get("n", 0) + 1
    try:
        from nokido_agent.tools.forge_job_progress import emit as _jp_emit  # noqa: PLC0415

        _jp_emit(name, index=_run.__dict__["n"], message="en cours")
    except Exception:  # noqa: BLE001 — muet-ok : l'observabilite ne casse pas le gate
        pass  # muet-ok : hors job (LAFORGE_JOB_ID absent) ou module indisponible
    e = dict(os.environ)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"  # sous-processus (bandit/pytest) -> pas de crash cp1252
    # GIT SOUS UN COMPTE DE SERVICE. Mesure 2026-09-03 : le compte du hub a
    # USERPROFILE=C:\Users\Default, et git meurt en « unable to read config file
    # 'C:/Users/Default/.gitconfig' » — pour git c'est FATAL, donc `git init` rend 1
    # et SEPT tests NR tombaient (5x lats, 2x archeologie) sans qu'aucun defaut de
    # code n'existe. On ne cree rien dans le profil Default, partage par tous les
    # comptes de service : GIT_CONFIG_GLOBAL est la variable prevue pour ca, pointee
    # sur un fichier vide dans les artefacts du compte courant.
    if not e.get("GIT_CONFIG_GLOBAL"):
        _compte = "".join(c for c in (os.environ.get("USERNAME") or "anon")
                          if c.isalnum() or c == "_") or "anon"
        _gc = _racine_artefacts(_compte) / "gitconfig"
        try:
            _gc.parent.mkdir(parents=True, exist_ok=True)
            # Pas un fichier VIDE : il manquait `safe.directory`. Mesure 2026-09-03 :
            # un fichier vide reglait bien le « unable to read config file », mais le
            # depot appartient a l'owner et un compte de service se voit alors refuser
            # « detected dubious ownership » — 4 tests tombaient sur ce seul motif.
            # Les deux defauts venaient du meme fichier absent ; n'en corriger qu'un
            # laissait croire le probleme traite.
            _voulu = "[safe]\n\tdirectory = *\n"
            try:
                _actuel = _gc.read_text(encoding="utf-8") if _gc.exists() else ""
            except OSError:
                _actuel = ""      # illisible : on reecrit plutot que de supposer
            if _actuel != _voulu:
                _gc.write_text(_voulu, encoding="utf-8")
            e["GIT_CONFIG_GLOBAL"] = str(_gc)
        except OSError as _eg:
            print("  ⚠ GIT_CONFIG_GLOBAL non pose (%s) : les gates qui appellent git "
                  "peuvent echouer sous ce compte, sans defaut de code."
                  % type(_eg).__name__, flush=True)
    if env:
        e.update(env)
    # TEE, et non plus un stdout herite. MESURE 2026-08-26 : le gate « pytest (suite
    # pure) » a echoue en CI en n'affichant QUE « → FAIL (rc=1) » -- ni le test fautif,
    # ni l'assertion, ni meme le compte de tests. Deux causes cumulees : le parent
    # bufferise ses `print` quand la sortie n'est pas un terminal (donc l'en-tete du
    # gate arrivait APRES la sortie du sous-processus, ailleurs dans le journal), et
    # rien ne rappelait cette sortie au moment du verdict. Un gate bloquant qui refuse
    # sans dire pourquoi oblige a deviner : c'est le defaut que ce depot combat
    # partout ailleurs, ici dans l'instrument qui juge tous les autres.
    # On relaie ligne par ligne (l'ordre redevient vrai, le direct est conserve) et on
    # garde la fin pour la redire au verdict.
    # CHRONO PAR GATE. Ajoute le 2026-09-04 : apres le passage de la suite pure en
    # parallele (300 s -> 100 s), pytest n'est PLUS le goulot -- mais personne ne
    # savait lequel l'etait devenu. Optimiser d'apres la reputation des outils
    # (« la mutation est lente », « semgrep est lourd ») serait exactement le defaut
    # que ce depot combat : agir sur une impression au lieu d'une mesure. `_run` est
    # le point de passage UNIQUE de tous les gates, donc le chrono s'y pose une fois
    # et les couvre tous.
    # BORNE DE DUREE PAR GATE. MESURE 2026-09-08 : les cinq derniers runs GitHub sont
    # `cancelled` -- pas `failure` -- et le job `gates` s'arrete a 20 min PILE, soit le
    # `timeout-minutes: 20` du workflow. Sans borne INTERNE, c'est une borne EXTERNE
    # qui coupe -- et une borne externe n'explique rien, elle annule. Ici la borne
    # NOMME ce qui s'est passe, et le depassement vaut NON MESURE, jamais ECHEC : un
    # gate coupe n'a pas trouve de probleme, il n'a pas fini de regarder.
    #
    # ⚠ CORRECTION DU 2026-09-09, et elle porte sur MA PROPRE MESURE. J'ai d'abord
    # attribue les 18 minutes a `pip-audit`. C'ETAIT FAUX : la ligne de verdict
    # `→ OK (rc=0, 1120.5 s)` est celle de `pytest (suite pure)`, et `pip-audit` finit
    # en UNKNOWN presque aussitot. Mon extraction par regex a lu des EN-TETES DE
    # FIXTURE comme des en-tetes de gate -- les blocs `── pip-audit ──` apparaissent
    # DANS la sortie de pytest, parce qu'un NR teste la classification de ce gate, et
    # le motif a rattache le verdict de pytest a l'en-tete le plus proche. Meme defaut
    # que « un instrument ne lit jamais son propre vocabulaire », applique cette fois
    # au JOURNAL. Consequence : cette borne est une vraie dette comblee, mais elle ne
    # corrige PAS le depassement du budget GitHub. Le budget est mange par la suite
    # pure (18,7 min), et c'est la qu'il faut agir -- pas ici.
    _t0 = time.time()
    queue: list[str] = []
    _borne_atteinte = {"v": False}
    _minuteur = None
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=e, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace",
                                bufsize=1)
        if timeout_s:
            import threading  # noqa: PLC0415

            def _couper() -> None:
                _borne_atteinte["v"] = True
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001 — muet-ok : le processus est deja mort
                    pass  # muet-ok
            _minuteur = threading.Timer(float(timeout_s), _couper)
            _minuteur.daemon = True
            _minuteur.start()
        for ligne in proc.stdout or ():
            print(ligne.rstrip("\n"), flush=True)
            queue.append(ligne.rstrip("\n"))
            if len(queue) > 80:
                del queue[0]
        rc = proc.wait()
    except (FileNotFoundError, OSError) as ex:
        # WinError 206 (ligne de commande > 32 767 car.) est levee en FileNotFoundError : ce n'est PAS un
        # outil introuvable. MESURE 2026-09-26 : la suite pure n'a pas tourne et le gate accusait l'outil.
        if getattr(ex, "winerror", None) == 206:
            print("  → UNKNOWN (ligne de commande trop longue : WinError 206, %d car. > 32 767)"
                  % len(subprocess.list2cmdline([str(c) for c in cmd])), flush=True)
        else:
            print(f"  → UNKNOWN (outil introuvable : {type(ex).__name__})", flush=True)
        rc = None
    finally:
        if _minuteur is not None:
            _minuteur.cancel()
    _dt = time.time() - _t0
    _CHRONO.append((name, _dt))
    _motif_nm = next((m for m in motifs_non_mesure if m in "\n".join(queue)), None)
    if _borne_atteinte["v"]:
        _motif_nm = ("borne de %g s atteinte -- gate NON MESURE, pas en echec"
                     % float(timeout_s))
    # CE QUE `_run` SAIT ET NE RENDAIT PAS. Le code de retour et la sortie existent
    # ici et disparaissaient au `return`, qui ne rend qu'un booleen. Or c'est
    # exactement ce qu'il faut pour distinguer un bloc TUE d'un bloc en echec.
    # On les depose plutot que d'elargir la signature : `_run` a des dizaines
    # d'appelants, et aucun d'eux n'a besoin de changer.
    _run.__dict__["dernier"] = {"rc": rc, "sortie": "\n".join(queue),
                                "motif_non_mesure": _motif_nm}
    if rc is None or rc in _RC_OUTIL_ABSENT or rc in rc_non_mesure or _motif_nm:
        suppleant = _SUPPLEANTS.get(name.split()[0].lower())
        _INCONCLUS.append((name, _critique(name) and not suppleant, suppleant))
        print("  → UNKNOWN — le gate n'a pas pu se prononcer"
              + (f" [{_motif_nm}]" if _motif_nm else "")
              + (f" ; supplee par {suppleant}" if suppleant else ""))
        return name, True   # pas un echec du CODE : une absence de mesure
    ok = rc == 0
    print(f"  → {'OK' if ok else ('FAIL' if blocking else 'WARN')} (rc={rc}, {_dt:.1f} s)",
          flush=True)
    if not ok and blocking and queue:
        # Le rappel : au moment ou on lit « FAIL », on lit AUSSI ce qui a echoue.
        interessantes = [ln for ln in queue
                         if ln.startswith(("FAILED", "ERROR", "E ", "assert"))
                         or " failed" in ln or "short test summary" in ln]
        extrait = interessantes[-15:] or queue[-15:]
        print("  ┌ derniere sortie du gate :", flush=True)
        for ln in extrait:
            print("  │ " + ln[:200], flush=True)
        print("  └", flush=True)
        # TROISIEME ETAT. Un outil peut refuser sans avoir conclu : ce n'est ni un
        # succes ni un echec du CODE, et le confondre avec un echec envoie chercher
        # un bug qui n'existe pas. MESURE 2026-08-26 (runs 32957444508 et
        # 32958735437) : le gate « pytest (suite pure) » a rendu rc=1 alors que le
        # journal montre TOUS les fichiers verts et AUCUNE ligne de verdict --
        # ni `N passed`, ni `FAILED`, ni `short test summary`. Le processus s'est
        # donc arrete APRES les tests sans imprimer sa conclusion, et la suite
        # rejouee a l'identique en local rend rc=0. On le NOMME au lieu de le lire
        # comme une regression du depot.
        if any(m in " ".join(queue) for m in ("passed", "failed", "error", "no tests ran")):
            pass  # l'outil a conclu : le verdict ci-dessus est le sien
        else:
            print("  ⚠ CE GATE N'A PAS CONCLU : rc non nul mais aucune ligne de "
                  "verdict dans sa sortie (arret du processus apres le travail, pas "
                  "un echec mesure). Causes connues sous Windows : flux ferme au "
                  "shutdown (« lost sys.stderr »), thread non-daemon qui survit, "
                  "process tue par une borne externe. A instruire comme tel.",
                  flush=True)
    return name, (ok or not blocking)


# ---------------------------------------------------------------------------
# LA PREUVE EST PAR BLOC, PAS PAR PROCESSUS
#
# Un seul processus pytest pour 9561 tests, donc un seul rapport JUnit, ecrit A
# LA FIN de la session : si le processus est TUE avant, la preuve des 9560 tests
# sains disparait avec le fautif. Mesure du 2026-09-13 (run GitHub 34784517659,
# sha b3ed1cc50) -- `pytest-timeout` a coupe pendant un seul fichier, et le gate
# n'a pas pu dire mieux que « rapport illisible ».
#
# On DECLARE donc les fichiers qui doivent tourner dans leur propre processus,
# avec leur propre rapport. Chacun porte son MOTIF : une isolation sans motif se
# relit comme une exemption, et se supprime au premier menage.
# ---------------------------------------------------------------------------

# L'INVARIANT des timeouts mesures, et non la victime du jour. Le 2026-09-18 la
# suite a ete coupee 3 fois sur 4 avec une victime DIFFERENTE a chaque run : la
# victime n'est donc pas la cause. Ce que les piles avaient en commun, c'est la
# creation d'une BOUCLE D'EVENEMENTS. Le 2026-09-19, la CI de reference l'a
# reconfirme : `test_hub_auth.py` coupe a 721 s, pile
# `run_blocking_portal -> run_eventloop`, JUnit emporte, SUITE_INCOMPLETE, et
# donc AUCUNE certification possible -- ce qui bloquait la publication du dist.
# On isole les 19 fichiers qui ouvrent un portail anyio (`TestClient`). Cout :
# 19 demarrages pytest supplementaires (~1 min) ; en face, la preuve des ~590
# autres fichiers cesse de dependre d'eux.
_MOTIF_PORTAIL = (
    "Cree une BOUCLE D'EVENEMENTS : `TestClient` ouvre un portail anyio "
    "(`start_blocking_portal` -> `run_eventloop`) dans un thread pendant que le "
    "MainThread attend sur `future.result()`. Invariant des timeouts mesures les "
    "2026-09-18 et 2026-09-19. Isole, un blocage ne coute plus que la preuve de "
    "son propre bloc."
)

BLOCS_ISOLES = (
    ("tests/nr/test_epistemic_schema_absent_nr.py", _MOTIF_PORTAIL),
    # Importe `nokido_hub` pour appeler `inbox_stream` et COMPTER les `pop()` :
    # la preuve de « DENY -> NO EFFECT » exige le vrai handler, pas une lecture
    # de source. Cet import a des effets de bord globaux (manager de jetons),
    # d'ou l'isolation -- le meme motif que les `test_hub_*` ci-dessous.
    ("tests/nr/test_inbox_ownership_route_nr.py", _MOTIF_PORTAIL),
    # Meme motif : monte l'app du hub (`_build_app`) pour appeler
    # `/api/recon/run` et COMPTER les publications sur le bus. L'import de
    # `nokido_hub` reinitialise le manager de jetons -- mesure du 2026-09-22,
    # 9 tests de `test_cycle_de_vie_jetons_nr` tombes en suite partagee.
    ("tests/nr/test_recon_run_consomme_le_scope_nr.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_auth.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_config.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_csp.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_jti_persistence.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_jti_revoke.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_l.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_launcher.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_login_ui.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_m.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_n.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_o.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_sse.py", _MOTIF_PORTAIL),
    ("tests/nr/test_hub_web.py", _MOTIF_PORTAIL),
    ("tests/nr/test_rag_search_route_nr.py", _MOTIF_PORTAIL),
    ("tests/nr/test_tuile_orpheline_nr.py", _MOTIF_PORTAIL),
    ("tests/nr/test_ui_pages_rendent_nr.py", _MOTIF_PORTAIL),
    ("tests/test_forge_openai_proxy_firewall.py", _MOTIF_PORTAIL),
    ("tests/test_rbac_views.py", _MOTIF_PORTAIL),
    ("tests/nr/test_proprietes_generatives_nr.py",
     "Hypothesis reparcourt sys.modules et parse l'AST de chaque module local a "
     "CHAQUE input (_get_local_constants, providers.py), et vide son cache des "
     "que la moisson grandit. Le cout ne depend donc pas du test mais de ce que "
     "le RESTE de la suite a importe : seul il tient en 2,07 s, dans la suite "
     "complete il a depasse --timeout=30 et emporte le rapport de tous les "
     "autres (run 34784517659). Isole, son cout redevient le sien."),
)

# Ce que `pytest-timeout` imprime avant de tuer le processus. C'est la SEULE
# trace qui distingue « on m'a coupe » de « je ne sais pas pourquoi il n'y a
# rien » -- sans elle les deux se confondent en UNKNOWN, ce qui est honnete mais
# moins utile : un TIMEOUT nomme la cause et designe le fichier a isoler.
_MARQUEURS_TIMEOUT = ("+++ Timeout +++", "Timeout ++++")

# L'etat de suite, porte jusqu'au juge comme `_INCONCLUS` l'est deja : le site
# d'appel de `_inscrire_generation` ne passe que (results, partiel), et un
# manifeste qui ignorerait SUITE_PARTIELLE certifierait une execution reduite.
_ETAT_SUITE = None

# Les REGLES qui transforment une execution en verdict. Hacher ces fichiers, c'est
# repondre a « selon quel contrat ce verdict a-t-il ete rendu ? » — question
# distincte de « qu'est-ce qui devait tourner ? » (le plan). Mesure 2026-09-19 :
# une seule entree de PURE_TESTS separe un sha certifie d'un sha publie.
_CONTRAT_CI = ("tools/ci_local.py", "tools/forge_ci_selection.py",
               "tools/forge_ci_proof.py")


# D — TELEMETRIE DE BLOC. Bornee : une preuve ne grossit pas sans fin.
_TELEMETRIE = []
_TELEMETRIE_MAX = 400


def _telemetrie(etiquette: str) -> dict:
    """Instantane pris aux FRONTIERES de bloc, pour CORRELER — jamais conclure.

    Mesure ouverte au 2026-09-19 : meme sha, meme runtime certifiant, meme
    suite, resultat VARIABLE — 3 timeouts sur 4 runs, victime DIFFERENTE a
    chaque fois. La victime n'est donc pas la cause, et il manque la seule
    chose qui permettrait d'attribuer : l'etat de la machine AUTOUR du bloc
    coupe. On instrumente ; on ne redecoupe rien tant que la correlation n'est
    pas mesuree.

    Ce que cette sonde N'EST PAS : un temoin. C'est un capteur NEUF, donc un
    SUSPECT — ses valeurs se croisent avec le journal de l'organe avant toute
    action, et deux echantillons ne font pas une tendance.

    Trois etats partout : une valeur, ou `ILLISIBLE(<motif>)` — jamais un zero
    qui se lirait comme « rien ». `cpu_percent(interval=None)` rend 0.0 au
    PREMIER appel PAR CONSTRUCTION : le publier ferait lire « charge nulle »
    la ou l'on n'a rien mesure (piege du snapshot a froid, RULES_SHARED).

    N'est JAMAIS une cause : toute defaillance est capturee et nommee, la sonde
    ne rougit aucun run et n'introduit aucune attente bloquante.
    """
    import time as _t
    snap = {"etiquette": etiquette, "ts": _t.strftime("%H:%M:%S"),
            "mono": round(_t.monotonic(), 3)}
    try:
        import psutil as _ps
    except Exception as e:  # noqa: BLE001
        snap["etat"] = "ILLISIBLE(%s)" % type(e).__name__
        _TELEMETRIE.append(snap) if len(_TELEMETRIE) < _TELEMETRIE_MAX else None
        return snap
    snap["etat"] = "LU"

    def _ou_illisible(nom, fn):
        try:
            snap[nom] = fn()
        except Exception as e:  # noqa: BLE001
            snap[nom] = "ILLISIBLE(%s)" % type(e).__name__

    # `_amorce` : le tout premier appel de cpu_percent sert de reference et ne
    # mesure rien. On le DIT au lieu de publier son 0.0.
    if not getattr(_telemetrie, "_amorce", False):
        try:
            _ps.cpu_percent(interval=None)
        except Exception:  # noqa: BLE001, muet-ok : signale par le champ ci-dessous
            pass
        _telemetrie._amorce = True
        snap["cpu_pct"] = "ILLISIBLE(amorce: le 1er appel est une reference)"
    else:
        _ou_illisible("cpu_pct", lambda: round(_ps.cpu_percent(interval=None), 1))
    _ou_illisible("ram_pct", lambda: _ps.virtual_memory().percent)
    _ou_illisible("ram_dispo_mo", lambda: _ps.virtual_memory().available // 1048576)
    _ou_illisible("pids_total", lambda: len(_ps.pids()))
    try:
        _moi = _ps.Process()
        _ou_illisible("moi_threads", _moi.num_threads)
        _ou_illisible("moi_rss_mo", lambda: _moi.memory_info().rss // 1048576)
        # `num_handles` n'existe que sous Windows : son absence est une PROPRIETE
        # de la plateforme, pas une panne — on la nomme au lieu de rendre 0.
        _ou_illisible("moi_handles",
                      _moi.num_handles if hasattr(_moi, "num_handles")
                      else (lambda: "ILLISIBLE(hors Windows)"))
        # Les ENFANTS sont ce qui compte pour un timeout de bloc : ce sont les
        # processus pytest. Leur RSS est lisible ; celui des services ne l'est
        # pas sous ce compte, et c'est dit plus bas plutot que compte a zero.
        def _enfants():
            tot, vus, illis = 0, 0, 0
            for _c in _moi.children(recursive=True):
                try:
                    tot += _c.memory_info().rss
                    vus += 1
                except Exception:  # noqa: BLE001
                    illis += 1
            return {"rss_mo": tot // 1048576, "vus": vus, "illisibles": illis}
        _ou_illisible("enfants", _enfants)
    except Exception as e:  # noqa: BLE001
        snap["moi"] = "ILLISIBLE(%s)" % type(e).__name__
    snap["NON_COUVERT"] = [
        "RSS des SERVICES : la cmdline est illisible sous ce compte (331/339 "
        "vides, mesure 2026-07-30) — on ne sait pas a qui appartient un pid",
        "deux echantillons encadrent un bloc, ils n'en decrivent pas l'interieur",
    ]
    if len(_TELEMETRIE) < _TELEMETRIE_MAX:
        _TELEMETRIE.append(snap)
    elif len(_TELEMETRIE) == _TELEMETRIE_MAX:
        _TELEMETRIE.append({"etiquette": "BORNE ATTEINTE",
                            "note": "%d instantanes gardes, les suivants sont "
                                    "ECARTES — ce n'est pas une absence"
                                    % _TELEMETRIE_MAX})
    return snap


def verdict_bloc(rc, sortie, bilan):
    """PASS | FAIL | ERROR | TIMEOUT | UNKNOWN pour UN bloc pytest.

    CINQ etats, et chacun a coute quelque chose :

      PASS     des tests ont tourne, le rapport est propre
      FAIL     des tests ont echoue -- une MESURE
      ERROR    des cas ont leve hors assertion (collecte, fixture) -- une mesure
               aussi, mais qui ne dit rien du comportement vise
      TIMEOUT  le bloc a ete TUE : on sait POURQUOI la preuve manque
      UNKNOWN  la preuve manque et on ne sait pas pourquoi -- on le DIT

    `TIMEOUT` n'est PAS un `FAIL`. Un bloc coupe n'a pas trouve de probleme, il
    n'a pas fini de regarder ; les confondre envoie chercher un bug qui n'existe
    pas. Symetriquement, un `rc` nul SANS rapport ne vaut pas `PASS` : un code de
    retour ne rachete jamais une absence de mesure (defaut corrige la veille dans
    la chaine de certification, cf. `verdicts_pour_generation`).

    La fonction est PURE : elle ne lit ni disque ni horloge. C'est ce qui la rend
    eprouvable, la ou la chaine d'entrees-sorties qui l'entoure ne l'est pas."""
    texte = sortie or ""
    if bilan is not None:
        if bilan.get("problemes"):
            # Une erreur prime sur un echec : tant qu'un cas n'a pas pu s'executer,
            # le verdict des autres ne dit pas ce qu'on croit.
            return "ERROR" if bilan.get("errors") else "FAIL"
        if (bilan.get("tests") or 0) > 0:
            return "PASS"
        # Rapport lisible mais VIDE de cas executes (tout ignore) : rien n'a ete
        # prouve. `_lire_junit` retire deja les `skipped` du compte.
        return "UNKNOWN"
    if any(m in texte for m in _MARQUEURS_TIMEOUT):
        return "TIMEOUT"
    return "UNKNOWN"


def verdict_suite(blocs):
    """Agrege les blocs SANS jamais faire disparaitre un verdict acquis.

    Deux proprietes distinctes, qu'on confondait en un seul booleen :

      `etat`     SUITE_COMPLETE / SUITE_INCOMPLETE -- a-t-on TOUT mesure ?
      `bloquant` doit-on refuser de publier ?

    Un `FAIL` rend la suite bloquante mais COMPLETE : c'est une mesure. Un
    `TIMEOUT` ou un `UNKNOWN` la rend INCOMPLETE -- et une suite incomplete n'est
    jamais verte, sinon on publierait en appelant « absence de probleme » ce qui
    n'est qu'une absence de regard."""
    blocs = dict(blocs or {})
    sans_preuve = [nom for nom, v in blocs.items() if v in ("TIMEOUT", "UNKNOWN")]
    rouges = [nom for nom, v in blocs.items() if v in ("FAIL", "ERROR")]
    return {
        "blocs": blocs,
        "etat": "SUITE_INCOMPLETE" if sans_preuve else "SUITE_COMPLETE",
        "sans_preuve": sans_preuve,
        "rouges": rouges,
        "bloquant": bool(sans_preuve or rouges),
    }


def bilan_preuve(blocs, bilans, absents, sha):
    """Ce que le verdict DOIT dire, chiffre par chiffre.

    « pytest OK » ne dit pas sur quel arbre, ni combien de cas ont tourne, ni
    combien ont ete ignores, ni ce qui n'a pas pu etre mesure. Le 2026-09-13, la
    CI a affiche un gate rouge sur 9561 tests dont 9560 etaient verts : le chiffre
    manquait, donc la conversation a porte sur « le depot est casse » au lieu de
    « un fichier a ete coupe ».

    DEUX PIEGES, tous deux payes ailleurs dans ce fichier :

      1. un bilan ABSENT (`None`) ne vaut pas zero probleme -- il n'entre pas dans
         les sommes, il entre dans `sans_preuve` ;
      2. un sha illisible se DIT `INCONNU` -- un champ vide se relit comme
         « il n'y a pas de sha », ce qui n'est pas la meme chose.

    Fonction PURE : aucun acces disque, aucun appel git. Ce qui la rend eprouvable
    est exactement ce qui manquait a la chaine qu'elle resume."""
    agg = verdict_suite(blocs)
    lisibles = [b for b in (bilans or {}).values() if b]

    def _somme(clef):
        return sum((b.get(clef) or 0) for b in lisibles)

    return {
        "sha": sha or "INCONNU",
        "executes": _somme("tests"),
        "skipped": _somme("skipped"),
        "echecs": _somme("failures"),
        "erreurs": _somme("errors"),
        "timeouts": [n for n, v in agg["blocs"].items() if v == "TIMEOUT"],
        "sans_preuve": agg["sans_preuve"],
        "declares_absents": list(absents or []),
        "etat": agg["etat"],
        "bloquant": agg["bloquant"],
        "blocs": agg["blocs"],
    }


# ---------------------------------------------------------------------------
# CE QUI N'EST PAS DANS LE COMMIT ET ENTRE POURTANT DANS LE VERDICT
#
# Mesure du 2026-09-14 : deux runs de reference sur le sha 714f2694a ont rendu
# 2 echecs puis 0, sans qu'une ligne de code change. La cause etait `MEMORY.md`,
# qui vit dans le profil du client, n'est dans AUCUN commit, et que l'agent
# reecrit entre deux runs. Il a fallu une heure pour la retrouver, a la main.
#
#     tested_sha = 714f2694a  -> VRAI, mais INSUFFISANT comme identifiant
#     VERDICT = f(commit, runner, env de mesure, artefacts, deps, profil)
#
# On ne CORRIGE pas cette dependance ici -- versionner le profil deplacerait la
# mutabilite au lieu de la caracteriser. On la REND VISIBLE : une empreinte posee
# a cote du sha, pour que deux verdicts du meme commit soient comparables.
# ---------------------------------------------------------------------------

def _empreinte_fichier(chemin):
    """DELEGUE a `forge_cycle_verdict.empreinte` -- ne pas en reecrire une.

    Le depot porte deja plusieurs empreintes (`forge_code_identity.snapshot`,
    `forge_cycle_verdict.empreinte`, `forge_provision_clients`), et celle-ci
    tient les trois etats qu'il nous faut : sha256, `ABSENT`, `ILLISIBLE:<type>`.
    Sa docstring dit le piege qu'on veut eviter -- « une empreinte vide comparee
    a une empreinte vide serait identique : le garde s'ouvrirait exactement quand
    il ne peut pas voir ». Une sixieme implementation divergerait au premier
    changement de convention, et personne ne le verrait."""
    import importlib  # noqa: PLC0415

    _d = str(Path(__file__).resolve().parent)
    if _d not in sys.path:
        sys.path.insert(0, _d)
    return importlib.import_module("forge_cycle_verdict").empreinte(chemin)


def _etat_empreinte(e) -> str:
    if e == "ABSENT":
        return "ABSENT"
    return "ILLISIBLE" if str(e).startswith("ILLISIBLE") else "LU"


def _contexte_defaut():
    """Les postes hors commit, empruntes au module qui les DECLARE deja."""
    try:
        import importlib  # noqa: PLC0415

        _cb = importlib.import_module("forge_context_budget")
        return [(nom, chemin, "resident du profil, hors Git, mutable entre deux runs")
                for nom, chemin in getattr(_cb, "RESIDENT_PROFIL", ())]
    except Exception:  # noqa: BLE001
        return []      # muet-ok : l'absence est DITE par NON_COUVERT ci-dessous


def empreinte_contexte(entrees=None) -> dict:
    """Empreinte de ce qui, HORS du commit juge, peut faire diverger un verdict.

    `entrees` : suite de (nom, chemin, motif). Chaque poste porte son MOTIF --
    sans lui, une entree du contexte se relit comme une verrue et se supprime au
    premier menage."""
    import hashlib as _hashlib
    entrees = _contexte_defaut() if entrees is None else list(entrees)
    postes = {}
    for nom, chemin, motif in entrees:
        emp = _empreinte_fichier(chemin)
        postes[nom] = {"empreinte": emp, "etat": _etat_empreinte(emp),
                       "motif": motif}
    return {
        "postes": postes,
        # Deux runs du meme sha sous des comptes differents ne voient pas les
        # memes fichiers : le compte EST une entree de l'experience.
        "compte": os.environ.get("USERNAME") or "INCONNU",
        # La VERSION ne suffit pas a identifier l'environnement : deux envs de
        # meme version portaient la meme empreinte. Mesure 2026-09-19 — les NR
        # d'A3 joues a la main sous miniforge3 3.12 rendaient DIVERGENT quand la
        # chaine certifiante tourne sous `laforge_py314` ; le lock est une
        # CONSTANTE du depot, `fermeture()` lit un environnement VARIABLE, donc
        # le runtime certifiant est celui qui lance ce fichier (`PY =
        # sys.executable`) et il doit etre NOMME dans la preuve.
        # Le NOM de l'env et une empreinte de son prefixe, jamais le chemin brut :
        # un manifeste est destine a etre publie, il ne porte pas de profil.
        "interpreteur": sys.version.split()[0],
        "env": os.path.basename(sys.prefix.rstrip("\\/")) or "INCONNU",
        "env_empreinte": _hashlib.sha256(
            sys.prefix.encode("utf-8", "replace")).hexdigest()[:16],
        # LE DENOMINATEUR. Une empreinte muette sur ses angles morts se lit comme
        # exhaustive, et c'est ainsi qu'on croit avoir tout capture.
        "NON_COUVERT": [
            "artefacts generes non versionnes lus par les gates "
            "(module_cards.json, vitalite_gardes.json, couverture_perimetre.json)",
            "mesures DEPORTEES jugees par un gate sans etre refaites (pip-audit)",
            "suppleances declarees (_SUPPLEANTS) : un gate non execute, couvert "
            "par un tiers hors run",
            "etat des services et du reseau (ui-acceptance, PyPI)",
            # Les versions installees NE SONT PLUS un angle mort : B2 les
            # reconcilie (`dependency_lock_hash` + `dependency_match`). Ce qui
            # reste non couvert est plus etroit, et le dire evite de croire la
            # couverture plus large qu'elle n'est.
            "dependances HORS de la fermeture du lock (RACINES + requires) : "
            "un paquet qu'aucune racine n'atteint n'est pas reconcilie",
        ],
    }


def comparer_contexte(a, b) -> dict:
    """Deux verdicts du meme sha sont-ils COMPARABLES, et sur quoi different-ils ?

    TROIS sorties, jamais deux :

      `divergences`  un poste a MESURABLEMENT change (ou n'existe que d'un cote)
      `indetermines` un poste illisible d'au moins un cote -- on ne conclut NI a
                     l'identite NI a la difference
      `comparable`   faux des qu'un poste est indetermine

    Le cas qui decide : deux `ILLISIBLE` ne sont PAS egaux. Les declarer
    identiques ouvrirait le garde exactement quand il est aveugle. Symetriquement
    -- et ce n'est pas moins important -- deux `ABSENT` sont une vraie mesure :
    une absence CONSTATEE est un fait, une lecture REFUSEE est un aveu. Ne pas
    remplacer une sur-deduction par une autre."""
    pa = (a or {}).get("postes") or {}
    pb = (b or {}).get("postes") or {}
    divergences, indetermines = [], []
    for nom in sorted(set(pa) | set(pb)):
        ea, eb = pa.get(nom), pb.get(nom)
        if ea is None or eb is None:
            divergences.append(nom)          # present d'un seul cote
            continue
        if "ILLISIBLE" in (ea["etat"], eb["etat"]):
            indetermines.append(nom)
            continue
        if ea["empreinte"] != eb["empreinte"]:
            divergences.append(nom)
    for champ in ("compte", "interpreteur"):
        if (a or {}).get(champ) != (b or {}).get(champ):
            divergences.append(champ)
    return {
        "divergences": divergences,
        "indetermines": indetermines,
        "comparable": not indetermines,
    }


# Un rapport JUnit MINIMAL et valide -- le cas nominal du controle. Sans lui, une
# chaine qui repondrait UNKNOWN a tout passerait le controle en ayant perdu toute
# capacite de distinguer : la contre-epreuve fait partie du controle.
_JUNIT_TEMOIN = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<testsuites><testsuite name="auto-preuve" tests="1" failures="0" '
    'errors="0" skipped="0"><testcase classname="auto" name="temoin"/>'
    "</testsuite></testsuites>\n"
)


def auto_preuve(racine) -> dict:
    """CONTROLE POSITIF du producteur : le chemin negatif, OBSERVE a chaque run.

    Les NR prouvent que `verdict_bloc` SAIT rendre UNKNOWN sur un rapport absent.
    Ils ne prouvent pas que la chaine reelle l'emprunte -- aucun run ne produit
    spontanement « rc nul et pas de rapport », donc ce chemin restait vrai par
    construction et par test, jamais par OBSERVATION :

        SOURCE_CORRECT    le code et ses NR purs
        RUNTIME_ACTIVE    charge par le gate
        RUNTIME_OBSERVED  <- ce qui manquait

    On fabrique donc la condition ICI, avec les fonctions de PRODUCTION
    (`_lire_junit`, `verdict_bloc`) et dans le basetemp reel du run, donc sous les
    memes droits que le reste.

    TROIS ETATS, et la distinction est le coeur du dispositif :

        OK              la chaine distingue encore preuve et absence de preuve
        DEFAUT          elle ne distingue plus -- l'instrument qui juge tout le
                        reste est casse, et c'est bloquant
        NON EXECUTABLE  on n'a pas pu fabriquer le cas (droits, disque). Ce n'est
                        PAS un instrument casse, et le confondre enverrait
                        reparer un organe sain -- le motif paye le 2026-09-03,
                        ou 30 929 refus d'acces se sont lus « 7 731 echecs ».

    Le repertoire n'est volontairement PAS cree : le controle s'execute la ou le
    run ecrit deja, ou pas du tout."""
    base = Path(racine)
    suffixe = os.getpid()
    absent = base / ("_auto_preuve_absent_%d.xml" % suffixe)
    corrompu = base / ("_auto_preuve_corrompu_%d.xml" % suffixe)
    temoin = base / ("_auto_preuve_valide_%d.xml" % suffixe)
    try:
        corrompu.write_text("ceci n'est pas un rapport", encoding="utf-8")
        temoin.write_text(_JUNIT_TEMOIN, encoding="utf-8")
        if absent.exists():
            absent.unlink()
    except OSError as exc:
        return {"etat": "NON EXECUTABLE",
                "motif": "%s: %s" % (type(exc).__name__, str(exc)[:120]),
                "cas": []}
    attendus = (
        ("rc nul + rapport absent", absent, "UNKNOWN"),
        ("rc nul + rapport corrompu", corrompu, "UNKNOWN"),
        ("rc nul + rapport valide (cas nominal)", temoin, "PASS"),
    )
    cas = []
    for nom, chemin, attendu in attendus:
        rendu = verdict_bloc(0, "1 passed", _lire_junit(chemin))
        cas.append({"cas": nom, "attendu": attendu, "rendu": rendu,
                    "conforme": rendu == attendu})
    for p in (corrompu, temoin):
        try:
            p.unlink()
        except OSError:   # muet-ok : menage, sans effet sur le verdict
            pass          # muet-ok
    ecarts = [c for c in cas if not c["conforme"]]
    return {
        "etat": "OK" if not ecarts else "DEFAUT",
        "cas": cas,
        "ecarts": ecarts,
        "motif": ("" if not ecarts else
                  "; ".join("%s -> %s (attendu %s)"
                            % (c["cas"], c["rendu"], c["attendu"])
                            for c in ecarts)),
    }


def _lire_junit(chemin) -> dict | None:
    """Bilan du rapport JUnit, ou None si on N'A PAS PU LIRE.

    TROIS etats, jamais deux : un rapport absent ou corrompu doit se distinguer d'un
    rapport vert, sinon « je n'ai pas pu voir » se lit comme « il n'y a rien a voir » et
    un gate rouge serait rachete par une absence de preuve. C'est pour cela que
    l'appelant garde l'ECHEC quand cette fonction rend None.

    `tests` compte les cas EXECUTES : les ignores (skipped) n'ont rien prouve, donc un
    rapport ou tout est ignore ne rachete rien."""
    try:
        import xml.etree.ElementTree as _ET
        racine = _ET.parse(chemin).getroot()
    except Exception as ex:
        print(f"  [junit] rapport illisible ({type(ex).__name__})", flush=True)
        return None
    suites = [racine] if racine.tag == "testsuite" else list(racine.iter("testsuite"))
    if not suites:
        print("  [junit] aucun <testsuite> dans le rapport", flush=True)
        return None
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for clef in total:
            try:
                total[clef] += int(s.get(clef, 0) or 0)
            except ValueError:
                return None          # attribut non numerique : rapport douteux
    total["tests"] -= total["skipped"]
    total["problemes"] = total["failures"] + total["errors"]
    # Un compte SANS nom n'est pas exploitable. Le rapport est ecrit dans le basetemp
    # du runner, detruit entre deux runs et jamais publie en artefact : « 2 test(s) en
    # echec » laissait la session suivante sans rien a instruire, et la seule preuve
    # disparaissait avec le run. On nomme les cas ici, dans le journal, qui lui reste.
    rates = []
    for s in suites:
        for cas in s.iter("testcase"):
            for genre in ("failure", "error"):
                for noeud in cas.findall(genre):
                    rates.append(("%s::%s" % (cas.get("classname", ""),
                                              cas.get("name", "")),
                                  genre,
                                  (noeud.get("message") or "").replace("\n", " ")[:200]))
    total["rates"] = rates
    return total


def _ast_bunker() -> tuple[str, bool]:
    """Miroir eco-shield ast-bunker (BLOQUANT) : AST des 7 modules + feature-flags."""
    name = "ast-bunker (AST + feature-flags)"
    print(f"\n\033[1;36m── {name} ──\033[0m  (bloquant)")
    fails = 0
    for f in _BUNKER_TARGETS:
        p = ROOT / f
        if not p.exists():
            print(f"  SKIP {f}")
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            print(f"  OK   {f}")
        except SyntaxError as ex:
            print(f"  FAIL {f} L{ex.lineno}: {ex.msg}")
            fails += 1
    checks: dict[str, bool] = {}
    pb = ROOT / "app/forge_ollama_bridge.py"
    if pb.exists():
        s = pb.read_text(encoding="utf-8", errors="ignore")
        checks.update({
            "Proxy-Trigger": "_NEED_PATTERN" in s,
            "Sentinel": "_sentinel_query" in s,
            "Output-Max": "_WEB_OUTPUT_MAX" in s,
            "Ring-Fencing": "ring-fence" in s.lower(),
        })
    pc = ROOT / "app/forge_collab_modes.py"
    if pc.exists():
        s = pc.read_text(encoding="utf-8", errors="ignore")
        checks.update({
            "TOKEN_BUDGET": "TOKEN_BUDGET" in s,
            "blind_instruction": "blind_instruction" in s,
        })
    for k, v in checks.items():
        print(f"  {'OK' if v else 'FAIL'}  {k}")
        if not v:
            fails += 1
    ok = fails == 0
    print(f"  → {'OK' if ok else 'FAIL'} ({fails} échec(s))")
    return name, ok


def empreintes_fermeture(fichiers, racine) -> dict:
    """Empreinte des fichiers a fermer, prise AU DEBUT du run.

    Delegue a `_empreinte_fichier` (donc a `forge_cycle_verdict.empreinte`, qui
    porte les trois etats) : on ne reecrit pas un sha256 de plus."""
    racine = Path(racine)
    return {f: _empreinte_fichier(racine / f) for f in (fichiers or [])}


def fermeture_encore_valide(avant, racine) -> tuple[list, list]:
    """(bouges, indetermines) — l'arbre a-t-il bouge depuis le debut du run ?

    LE TROU QUE CECI FERME (releve le 2026-09-14). `--commit-si-vert` fait son
    `git add` A LA FIN du run, sur les chemins nommes au depart. Entre la mesure
    et ce `add`, une douzaine de minutes s'ecoulent pendant lesquelles l'arbre est
    VIVANT -- l'agent continue d'editer, et d'autres surfaces le partagent :

        t0   les gates mesurent l'etat A
        t1   quelqu'un ecrit l'etat B dans un fichier nomme
        t2   git add <fichier>   ->  c'est B qui part au commit

    Le contrat « on ne commit QUE ce qui a ete mesure vert » ne tenait donc que
    par chance. C'est exactement la situation ou l'on se croit protege : le
    mecanisme existe, il est teste, et son hypothese silencieuse est fausse.

    DEUX LISTES, JAMAIS FONDUES. Un fichier `bouge` est une difference MESUREE ;
    un `indetermine` est une lecture qu'on n'a pas pu faire des deux cotes. Deux
    `ILLISIBLE` ne prouvent pas l'egalite -- les confondre ouvrirait le garde
    precisement quand il est aveugle."""
    racine = Path(racine)
    bouges, indetermines = [], []
    for f, emp_avant in (avant or {}).items():
        emp_apres = _empreinte_fichier(racine / f)
        if (_etat_empreinte(emp_avant) == "ILLISIBLE"
                or _etat_empreinte(emp_apres) == "ILLISIBLE"):
            indetermines.append(f)
        elif emp_apres != emp_avant:
            bouges.append(f)
    return sorted(bouges), sorted(indetermines)


def decider_commit(sujet, fichiers, partiel: bool, racine,
                   reference: bool = False,
                   bouges=(), indetermines=()) -> tuple[bool, str]:
    """Faut-il fermer ce run VERT par un commit ? Decision PURE, aucun git lance.

    N'est appelee que sur le chemin vert de `main` : les trois refus (gate en echec,
    bloquant non mesure, gate anergique) sortent en rc=1 bien avant. Cette fonction
    ne juge donc pas la CI, elle juge si la FERMETURE est legitime.

    Refuse, en NOMMANT le motif :
      - fermeture non demandee (defaut : on ne commit pas tout seul) ;
      - run PARTIEL (--fast) : il annonce lui-meme ne mesurer qu'une fraction, son
        vert ne couvre pas le depot ;
      - run de REFERENCE : il juge un sha COMMITE dans un worktree detache, donc
        ce qui n'est pas commite n'a PAS ete mesure (cf. infra) ;
      - aucun fichier nomme : jamais de `git add -A`, qui balaierait l'uncommitted
        des autres surfaces (arbre de travail PARTAGE) ;
      - un fichier absent du disque, cite par son nom ;
      - sujet vide : un commit sans sujet ne se relit pas.

    ⚠️ POURQUOI `--reference` NE FERME RIEN (ajoute le 2026-09-14). Ce mode annonce
    lui-meme « l'arbre partage n'entre plus dans le verdict » : il juge un sha, dans
    un worktree detache, precisement pour que les autres surfaces puissent continuer
    a editer pendant le run. Les fichiers modifies et NON COMMITES ne sont donc pas
    dans l'arbre mesure -- les committer au nom de ce vert ajouterait du NON-MESURE,
    c'est-a-dire l'inverse exact du contrat de cette fonction.

    L'enchainement juste est en DEUX temps :

        ci_local --commit-si-vert "<sujet>" --commit-fichiers a,b   (mode ordinaire :
                                                                    mesure l'arbre)
        ci_local --reference                                        (certifie le sha
                                                                    ainsi produit)

    Trouve en verifiant une recommandation avant de l'eriger en regle : `--reference
    --commit-si-vert` etait sur le point d'etre conseille, et aurait produit un
    defaut PIRE que le commit manuel qu'il corrigeait.
    """
    if not sujet:
        return False, "fermeture par commit non demandee (--commit-si-vert absent)"
    if not str(sujet).strip():
        return False, "sujet de commit vide"
    if bouges:
        return False, ("fichier(s) MODIFIE(S) pendant le run : %s — ce qui serait "
                       "commite n'est pas ce qui a ete mesure. Relancer la CI sur "
                       "l'arbre tel qu'il est maintenant."
                       % ", ".join(bouges))
    if indetermines:
        return False, ("fichier(s) NON VERIFIABLE(S) : %s — impossible de comparer "
                       "leur etat a celui du debut du run. On ne ferme pas sur ce "
                       "qu'on n'a pas pu verifier ; ce n'est PAS une modification "
                       "constatee." % ", ".join(indetermines))
    if reference:
        return False, ("run de REFERENCE : il juge un sha commite dans un worktree "
                       "detache, donc ce qui n'est pas commite n'a pas ete MESURE. "
                       "Fermer ici commiterait du non-mesure. Enchainer plutot : "
                       "fermeture en mode ordinaire, puis --reference pour certifier "
                       "le sha produit")
    if partiel:
        return False, ("run PARTIEL (--fast) : il ne mesure qu'une fraction des gates, "
                       "son vert ne ferme pas le depot")
    if not fichiers:
        return False, ("aucun fichier nomme : la fermeture exige --commit-fichiers "
                       "(jamais `git add -A` sur un arbre partage)")
    racine = Path(racine)
    manquants = [f for f in fichiers if not (racine / f).exists()]
    if manquants:
        return False, "fichier(s) introuvable(s) sous la racine : " + ", ".join(manquants)
    return True, "CI verte, %d fichier(s) nomme(s) et presents" % len(fichiers)


def _fermer_par_commit(sujet, fichiers, corps, racine) -> int:
    """Execute la fermeture. Best-effort DIT : un echec est nomme, jamais avale.

    `-c safe.directory=*` est obligatoire : le compte qui lance la CI n'est pas
    l'owner du depot, et sans lui git sort en « detected dubious ownership ».
    """
    base = ["git", "-c", "safe.directory=*", "-C", str(racine)]
    try:
        r = subprocess.run(base + ["add", "--"] + list(fichiers),
                           capture_output=True, text=True, errors="replace",
                           timeout=120)
        if r.returncode != 0:
            print("\033[1;31m[fermeture] `git add` refuse (rc=%d) : %s\033[0m"
                  % (r.returncode, (r.stderr or "").strip()[:300]))
            return r.returncode
        cmd = base + ["commit", "-m", str(sujet)]
        if corps:
            cmd += ["-m", str(corps)]
        # Un message de commit porte des accents ; un nom de fichier peut porter
        # n'importe quel octet. Le decodeur ne doit jamais etre le point de rupture.
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=300)
        sortie = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0:
            print("\033[1;31m[fermeture] commit REFUSE (rc=%d) — le gate pre-commit a "
                  "peut-etre parle :\033[0m\n%s" % (r.returncode, sortie[:1200]))
            return r.returncode
        print("\033[1;32m[fermeture] commit ecrit :\033[0m\n%s" % sortie[:800])
        return 0
    except Exception as e:  # noqa: BLE001 — la fermeture ne doit jamais rougir un run vert EN SILENCE
        print("\033[1;31m[fermeture] impossible (%s: %s) — le run reste VERT, "
              "le commit n'a PAS eu lieu\033[0m" % (type(e).__name__, str(e)[:200]))
        return 0


# ── T0 (2026-09-09) : ISOLATION DE LA PREUVE ────────────────────────────────────
# `_inscrire_generation` interroge `git status` du WORKING TREE : la validite de la
# preuve dependait donc de ce que faisaient les autres surfaces pendant les ~20 min
# du run. Avec quatre agents actifs (CLAUDE, ANTIGRAVITY, GEMINI, COWORK) ce n'est
# pas un accident de calendrier mais une propriete du montage -- meme avec des tests
# parfaitement deterministes, la CERTIFICATION de ce qu'ils ont teste ne l'etait pas.
# Quatre CI vertes de suite n'ont ainsi capture aucun sha.
#
# La CI de reference cree donc un worktree DETACHE sur le sha d'entree et s'y
# re-execute. `ROOT` etant derive de `__file__` (L61), TOUT le verdict -- tests,
# gates, git status, generation -- bascule sur le worktree sans une ligne de plus.
# L'arbre partage peut etre modifie, commite ou reset pendant ce temps : la preuve
# n'en depend plus. La CI tient un SHA, elle ne tient plus un ARBRE.
#
# L'EMPLACEMENT n'est plus decide ici (convergence du 2026-09-11) : la creation vit
# dans `forge_worktree`, et la racine se declare par NOKIDO_PROOF_ROOT. L'ancienne
# constante `WT_REFERENCE = ROOT/sandbox/ci_reference_wt` a ete RETIREE plutot que
# laissee en place : un chemin qui ne sert plus laisse croire qu'il sert encore, et
# c'est exactement ce qui m'a fait perdre du temps le matin meme sur un commentaire
# decrivant un `--untracked-files=no` retire deux jours plus tot.


def _argv_sans_reference(argv: list) -> list:
    """Retire `--reference` et sa valeur. SANS ca, le worktree en creerait un autre,
    indefiniment : c'est le drapeau retire qui borne la recursion, pas une sentinelle
    d'environnement (qu'un sous-processus peut perdre)."""
    reste, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--reference":
            # La valeur SUIT le drapeau, sauf si c'en est un autre ou la fin.
            i += 2 if (i + 1 < len(argv) and not argv[i + 1].startswith("-")) else 1
            continue
        if a.startswith("--reference="):
            i += 1
            continue
        reste.append(a)
        i += 1
    return reste


def _git_reference(args: list):
    """(rc, stdout, stderr) — injecte dans `preparer_reference` pour le rendre testable
    sans depot reel."""
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                       capture_output=True, text=True, errors="replace", timeout=120)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def preparer_reference(sha: str = None, git=None, wt=None, execution_id=None) -> dict:
    """ADAPTATEUR MINCE vers `forge_worktree.create_proof`. {ok, worktree, sha, motif}.

    CONVERGENCE DU 2026-09-11. Deux implementations d'un worktree detache
    coexistaient : celle-ci (2026-09-09) et `forge_worktree.create_proof`
    (2026-09-11). Deux createurs, c'est deux endroits ou corriger un piege et la
    garantie qu'ils divergeront -- ils avaient DEJA diverge, l'un rafraichissant un
    worktree sur le mauvais sha quand l'autre refusait l'incoherence.

    La logique reelle vit desormais dans `forge_worktree`, parce que le besoin
    depasse la CI : un juge local, AGY, Codex ou un autre validateur doivent pouvoir
    demander un worktree de preuve sans importer toute la logique de ci_local. Le
    rafraichissement, meilleure propriete de cette fonction, y a ete PORTE.

    ⚠️ FAIL-CLOSED, inchange. Si le worktree ne peut pas etre prepare, on REFUSE en
    NOMMANT la panne. Retomber sur l'arbre partage rendrait un verdict d'apparence
    normale dont plus personne ne saurait qu'il ne certifie rien -- le motif
    « UNKNOWN range du cote sain » que la constitution semantique interdit.
    """
    git = git or _git_reference
    if wt is not None:
        # Ignorer en SILENCE serait pire que refuser : l'appelant croirait avoir
        # choisi l'emplacement. L'emplacement se declare par NOKIDO_PROOF_ROOT.
        print("\033[33m[reference] parametre `wt` ignore (%s) — l'emplacement du "
              "worktree de preuve se declare par NOKIDO_PROOF_ROOT\033[0m" % wt)
    if not sha:
        rc, out, err = git(["rev-parse", "HEAD"])
        if rc != 0 or not out:
            return {"ok": False, "worktree": None, "sha": None,
                    "motif": "git rev-parse HEAD rc=%s : %s"
                             % (rc, err[:140] or "sortie vide")}
        sha = out.split()[0]

    # Import PARESSEUX : `tools/` n'est pas toujours sur sys.path quand ci_local est
    # charge comme module, et un test doit pouvoir substituer le createur.
    _tools = str(Path(__file__).resolve().parent)
    if _tools not in sys.path:
        sys.path.insert(0, _tools)
    import forge_worktree as _fw

    res = _fw.create_proof(sha, execution_id=execution_id)
    if res.get("error"):
        return {"ok": False, "worktree": res.get("path"), "sha": sha,
                "motif": res["error"]}
    return {"ok": True, "worktree": res["path"], "sha": sha, "motif": "",
            "statut_worktree": res.get("status")}


def main() -> int:
    ap = argparse.ArgumentParser(prog="ci_local", description="Miroir local complet des GitHub Actions")
    ap.add_argument("--only", action="append", metavar="GATE", default=None,
                    help="EXCLUSIF : n'execute QUE le(s) gate(s) nomme(s) (sous-chaine "
                         "du nom suffit). Repetable. Sans lui, rien ne change.")
    ap.add_argument("--reference", nargs="?", const="", metavar="SHA", default=None,
                    help="CI de REFERENCE : s'execute dans un worktree detache sur "
                         "SHA (defaut HEAD), donc insensible a l'arbre partage")
    ap.add_argument("--fast", action="store_true", help="flake8+ruff critique seuls")
    ap.add_argument("--no-tests", action="store_true", help="saute pytest")
    ap.add_argument("--no-mutation", action="store_true",
                    help="saute le cliquet de mutation (lourd ; utile en iteration rapide)")
    ap.add_argument("--integration", action="store_true", help="+ tests intégration (services locaux)")
    ap.add_argument("--build-dist", action="store_true", help="+ build dist obfusquée (pyarmor)")
    ap.add_argument("--docker", action="store_true", help="+ docker build (validation Dockerfile)")
    ap.add_argument("--release-build", action="store_true", help="+ uv build + twine check")
    ap.add_argument("--ui-gate", action="store_true", help="+ contrat d'acceptation UI web_hub (Playwright, :7400 requis)")
    ap.add_argument("--turbo", action="store_true",
                    help="suite pure en parallele (xdist, --dist=loadfile). "
                         "Mesure 2026-09-04 : 300 s -> ~100 s. OPT-IN : le gate par "
                         "defaut reste sequentiel tant que le mode parallele n'a pas "
                         "garde une publication reelle.")
    ap.add_argument("--impacte", action="store_true",
                    help="ne rejouer que les tests que le diff peut avoir casses. "
                         "OPT-IN, et NON CERTIFIANT : publie SUITE_PARTIELLE, ne "
                         "capture aucun sha. La CI d'avant push et d'avant "
                         "publication dist reste COMPLETE.")
    ap.add_argument("--impacte-fichiers", metavar="FICHIER", default=None,
                    dest="impacte_fichiers",
                    help="liste des fichiers modifies (une par ligne), FOURNIE par "
                         "un appelant qui a acces a git. Sous le compte du hub, git "
                         "est refuse : sans cette liste, --impacte joue TOUT.")
    ap.add_argument("--all", action="store_true", help="active tous les gates opt-in")
    ap.add_argument("--commit-si-vert", metavar="SUJET", default=None,
                    help="ferme un run VERT par un commit portant ce sujet "
                         "(exige --commit-fichiers ; sans effet sur un run --fast)")
    ap.add_argument("--commit-fichiers", metavar="a,b,c", default="",
                    help="liste EXPLICITE des chemins a committer, separes par des "
                         "virgules. Jamais de `git add -A` : l'arbre est partage")
    ap.add_argument("--commit-corps", metavar="TEXTE", default=None,
                    help="corps optionnel du message de commit")
    a = ap.parse_args()
    # ON FIGE ICI, AVANT TOUTE MESURE. Plus tard serait deja trop tard : c'est
    # precisement l'intervalle entre le debut des gates et le `git add` qu'il faut
    # couvrir, et d'autres surfaces partagent cet arbre.
    global _EMPREINTES_FERMETURE
    _EMPREINTES_FERMETURE = empreintes_fermeture(
        [f.strip() for f in (getattr(a, "commit_fichiers", "") or "").split(",")
         if f.strip()], ROOT)
    _poser_only(getattr(a, "only", None))
    if _ONLY:
        print("\033[1;36m[only] selection EXCLUSIVE : %s — les autres gates ne sont "
              "pas executes\033[0m" % ", ".join(_ONLY))

    # T0 : bascule vers le worktree de reference AVANT tout gate, pour qu'aucun
    # element du verdict ne lise l'arbre partage (sinon la course est deplacee,
    # pas supprimee). Le drapeau n'est pas repasse : c'est ce qui borne la recursion.
    if getattr(a, "reference", None) is not None:
        import os as _os
        import uuid as _uuid
        # Une execution = un contexte. Deux juges peuvent mesurer le MEME sha en
        # meme temps : sans identifiant, ils partageraient l'arbre et le second
        # `checkout --force` deplacerait celui que le premier est en train de lire.
        _exec_id = (_os.environ.get("NOKIDO_EXECUTION_ID")
                    or "ci-reference-%s" % _uuid.uuid4().hex[:12])
        _ref = preparer_reference(a.reference or None, execution_id=_exec_id)
        if not _ref["ok"]:
            print("\033[1;31m[reference] REFUS — %s\033[0m" % _ref["motif"])
            print("\033[90m  la CI de reference ne retombe PAS sur l'arbre partage : "
                  "un verdict qui ne certifie rien ne doit pas ressembler a un verdict "
                  "normal\033[0m")
            return 2
        _cible = Path(_ref["worktree"]) / "tools" / "ci_local.py"
        if not _cible.is_file():
            print("\033[1;31m[reference] REFUS — %s absent du worktree\033[0m" % _cible)
            return 2
        # PROOF_DIR A COTE de l'arbre juge, jamais DEDANS. Les JUnit, logs, rapports
        # et captures saliraient l'arbre que la capture s'apprete a juger -- c'est
        # exactement le defaut paye le 2026-09-09, ou la CI se retirait a elle-meme
        # le droit de capturer son propre sha en y ecrivant son registre.
        _proof_dir = Path(_ref["worktree"]).parent / "artefacts"
        try:
            _proof_dir.mkdir(parents=True, exist_ok=True)
        except OSError as _exc:
            print("\033[33m[reference] PROOF_DIR non creable (%s) — les sorties "
                  "resteront la ou les gates les ecrivent\033[0m" % type(_exc).__name__)

        # Le contexte voyage par l'ENVIRONNEMENT : le sous-processus recalcule son
        # ROOT depuis `__file__` (donc le worktree), mais il ne peut pas DEVINER
        # quel sha il est cense juger ni ou deposer ses preuves. Sans ces variables
        # son juge rendrait `PROOF_ROOT_MISSING` et la chaine s'arreterait sans
        # certifier -- ce qui est honnete, mais inutile.
        _env = dict(_os.environ)
        _env["NOKIDO_PROOF_WORKTREE"] = str(_ref["worktree"])
        _env["NOKIDO_TARGET_SHA"] = str(_ref["sha"])
        _env["NOKIDO_EXECUTION_ID"] = _exec_id
        _env["NOKIDO_PROOF_DIR"] = str(_proof_dir)

        print("\033[1;36m[reference] worktree detache %s @ %s (%s) — l'arbre partage "
              "n'entre plus dans le verdict\033[0m"
              % (_ref["worktree"], _ref["sha"][:9], _exec_id))
        print("\033[90m  [reference] artefacts hors de l'arbre juge : %s\033[0m" % _proof_dir)
        return subprocess.run([sys.executable, str(_cible),
                               *_argv_sans_reference(sys.argv[1:])],
                              cwd=_ref["worktree"], env=_env).returncode
    if a.all:
        a.integration = a.build_dist = a.docker = a.release_build = a.ui_gate = True

    results: list[tuple[str, bool]] = []

    # ── secrets hors coffre (cliquet) : BLOQUANT sur toute lecture NOUVELLE.
    # L'environnement est la seule couche qu'aucune rotation ne met a jour ; 45
    # sites y lisent encore un secret, geles au socle. Le gate n'exige PAS de les
    # resorber — il empeche le 46e. Sans lui, corriger les 45 ne servirait qu'un
    # temps : mesure 2026-09-03, un jeton revoque dans une variable persistante a
    # tenu le pont stdio en 401 pendant des heures, coffre et config pourtant bons.
    results.append(_run("secrets hors coffre (cliquet)",
                        [PY, "tools/forge_secret_source_audit.py"], blocking=True))

    # ── flake8 + ruff critique E9/F63/F7 (BLOQUANT) : ci.yml lint + eco-shield fast-audit
    if _has("flake8"):
        results.append(_run(
            "flake8 critique (E9,F63,F7)",
            # `--isolated` : flake8 REMONTE l'arborescence pour chercher sa config et
            # fait `os.stat()` sur chaque parent. Mesure 2026-09-03 : sous le compte
            # LaForgeSbxOnline il meurt en « Acces refuse » sur la racine du SUPERREPO,
            # un cran au-dessus du depot — gate BLOQUANT rouge, sans un seul defaut de
            # code, et vert sous un autre compte. Le depot n'a ni .flake8 ni tox.ini ni
            # setup.cfg : il n'y a donc RIEN a perdre a l'isoler, et tous les reglages
            # sont deja passes en ligne de commande.
            [PY, "-m", "flake8", "--isolated", "app", "tools", "--count", "--select=E9,F63,F7",
             f"--exclude={EXCLUDE}", "--show-source", "--statistics"],
            blocking=True))
    else:
        print("\n\033[90m[skip] flake8 absent — pip install flake8\033[0m")
    if _has("ruff"):
        results.append(_run(
            "ruff critique (E9,F63,F7)",
            # --no-cache : le depot est partage entre plusieurs comptes (le mien, le
            # runner self-hosted, les comptes de service). Le premier qui cree
            # .ruff_cache le rend inecrivable aux autres -> ruff sort rc=2
            # "Failed to create temporary file: Acces refuse" et le gate BLOQUANT
            # tombe. Mesure 2026-07-24 : c'etait, avec PYBIN, la 2e cause des
            # 2 semaines de CI rouge. Le cache ne vaut pas un gate qui ment.
            [PY, "-m", "ruff", "check", "app", "tools", "--select=E9,F63,F7", "--no-cache"],
            blocking=True))
    else:
        print("\n\033[90m[skip] ruff absent — pip install ruff\033[0m")

    if a.fast:
        return _summary(results, partiel=True, args=a)

    # ── flake8 style (WARN) : ci.yml lint step 2
    if _has("flake8"):
        results.append(_run(
            "flake8 style (complexity/line-length)",
            [PY, "-m", "flake8", "--isolated", "app", "tools", "--count", "--exit-zero",
             "--max-complexity=15", f"--exclude={EXCLUDE}", "--max-line-length=120", "--statistics"],
            blocking=False))

    # ── couverture de mesure (OBSERVATION, non bloquant) ──────────────────────
    # Publie les DEUX metriques et NOMME les modules sans perimetre. Non bloquant a
    # dessein : « observer avant d'enforcer », le temps de mesurer son bruit — c'est la
    # lecon du gate `anatomie`, promu bloquant puis rouge au premier passage sur le
    # runner. Ce gate repond aussi a la question owner « un module repare sera-t-il
    # couvert dynamiquement ? » : il RE-MESURE a chaque run, la ou la generation seule
    # ne serait qu'une photo datee. La generation, elle, vit en NREM1 (forge_circadian).
    _cp = ROOT / "tools" / "forge_couverture_perimetre.py"
    if _cp.is_file():
        results.append(_run("couverture de mesure (2 metriques, observation)",
                            [PY, str(_cp)], blocking=False))

    # ── ruff style + bandit (WARN) : eco-shield fast-audit
    if _has("ruff"):
        results.append(_run("ruff style", [PY, "-m", "ruff", "check", ".", "--config",
                                           "pyproject.toml", "--no-cache"], blocking=False))
    if _has("bandit"):
        results.append(_run(
            "bandit",
            [PY, "-m", "bandit", "-r", "app", "-x", "app/backups,app/legacy", "-ll",
             "--skip", "B101,B404,B603,B607", "-q"],
            blocking=False))

    # ── ast-bunker (BLOQUANT) : eco-shield
    if _demande("ast-bunker"):
        results.append(_ast_bunker())

    # ── license guard AGPLv3 (BLOQUANT) : ci.yml license-scan
    if (ROOT / "tools" / "forge_license_guard.py").exists():
        results.append(_run("license guard (AGPLv3)", [PY, "tools/forge_license_guard.py"], blocking=True))
        # L'autre moitie de la distribution : les 22 fichiers tiers servis par le portail
        # (JS, CSS, polices), que importlib.metadata ne voit pas. NON BLOQUANT a sa
        # creation (2026-09-29), comme tout gate neuf : on mesure son bruit d'abord.
        results.append(_run("licences embarquees (vendor.lock)",
                            [PY, "tools/forge_license_guard.py", "--embarques"], blocking=False))
        # Les dependances DECLAREES (pyproject + requirements*.txt), pas l'environnement
        # entier : le mode par defaut rendait 0 incompatible sur l'env de CI le 2026-09-29.
        # NON BLOQUANT a sa creation : une declaree absente de l'env sort NON MESUREE.
        results.append(_run("licences declarees (manifestes)",
                            [PY, "tools/forge_license_guard.py", "--declarees"], blocking=False))
    else:
        print("\n\033[90m[skip] forge_license_guard.py absent\033[0m")

    # ── archi-lint Golden Rules (WARN) : ci.yml archi-lint
    if (ROOT / "tools" / "forge_archi_lint.py").exists():
        # SONDE DE DEMARRAGE (mesure 2026-08-20). Sous un compte de service sans
        # profil charge, le binaire semgrep meurt AVANT de lire ses arguments :
        #   Failed to create system store X509 authenticator:
        #   ca_certs_iter_on_anchors: CertOpenSystemStore returned NULL
        # L'echec vient de sa TELEMETRIE (opentelemetry_client_cohttp_eio), pas
        # de l'analyse -- et `--metrics=off` n'y change rien, l'authenticator
        # etant construit a l'initialisation. Le gate figurait donc « ❔ NON
        # MESURE » a CHAQUE run depuis le 2026-08-19, sur un domaine declare
        # critique. Un ❔ perpetuel use l'attention et finit par se lire comme
        # du bruit : on distingue desormais « l'outil ne demarre pas ici »
        # (skip explicite, motif nomme) de « le gate n'a pas su se prononcer »
        # (non mesure, qui doit rester rare et regarde). Si semgrep redevient
        # lancable, le gate reprend seul : rien a rearmer.
        _sg = which("semgrep")
        _sg_ok = False
        if _sg:
            try:
                # `errors="replace"` : en mode texte sans lui, une sortie non
                # decodable fait crasher le thread lecteur de subprocess --
                # anti-regression de l'incident 47 Go, et le garde pre-commit
                # l'a rattrape ici meme.
                _sg_ok = subprocess.run([_sg, "--version"], capture_output=True,
                                        text=True, errors="replace",
                                        timeout=60).returncode == 0
            except Exception as _sg_e:  # noqa: BLE001
                print(f"\n\033[90m[skip] sonde semgrep KO ({type(_sg_e).__name__})\033[0m")
        if _sg_ok:
            # rc 2 = semgrep introuvable, rc 3 = abandon (run KO, JSON illisible,
            # ou 0 fichier scanne). Dans les deux cas le gate n'a RIEN mesure :
            # il doit etre compte NON MESURE, jamais vert.
            results.append(_run("archi-lint (Golden Rules)",
                                [PY, "tools/forge_archi_lint.py", "app", "tools"],
                                blocking=False, rc_non_mesure=(2, 3)))
        elif _sg:
            # CAUSE COMPLETE, creusee le 2026-08-20 jusqu'au bout pour que
            # personne ne la recherche une troisieme fois :
            #   - `semgrep.exe` (coeur natif) meurt AVANT de lire ses arguments :
            #     « Failed to create system store X509 authenticator :
            #     CertOpenSystemStore returned NULL ». C'est sa TELEMETRIE, et
            #     `--metrics=off` n'y peut rien, l'authenticator etant construit
            #     a l'initialisation.
            #   - `pysemgrep` (front Python) demarre, LUI -- une fois `HOME`
            #     redirige hors de `C:\Users\Default`, que le compte de service
            #     ne peut pas ecrire. `forge_archi_lint` fait deja cette bascule.
            #   - mais il delegue l'analyse a `semgrep-core`, le MEME binaire
            #     natif, qui meurt a son tour : « RPC subprocess exited with
            #     code 2 / Expected a number, got '' ».
            # Autrement dit : ce n'est pas un probleme de PATH, de HOME ni de
            # flag. Semgrep exige un profil utilisateur charge ; un service n'en
            # a pas. Le faire tourner demanderait de le lancer sous le compte
            # owner -- ce qu'un gate de CI ne fait pas.
            print("\n\033[90m[skip] archi-lint : semgrep INUTILISABLE sous un compte "
                  "de service (le coeur natif semgrep-core meurt, front Python "
                  "compris). Domaine couvert par golden-rules, moteur AST natif "
                  "sans dependance externe.\033[0m")
        else:
            print("\n\033[90m[skip] archi-lint : semgrep absent — "
                  "golden-rules couvre le domaine\033[0m")
    else:
        print("\n\033[90m[skip] forge_archi_lint.py absent\033[0m")

    # ── golden-rules cliquet (BLOQUANT) : moteur AST natif ────────────────────
    # Le gate semgrep ci-dessus depend d'un binaire qui ne demarre pas sous un
    # compte de service : il a affiche scanned_files=0 + coche verte pendant des
    # semaines (run 31873587600). Celui-ci n'a aucune dependance, et il BLOQUE --
    # sur la nouveaute seulement : les 11 violations ERROR du 2026-08-15 sont
    # gelees dans tests/nr/golden_rules_socle.json.
    if (ROOT / "tools" / "forge_golden_rules_ast.py").exists():
        results.append(_run("golden-rules (cliquet ERROR)",
                            [PY, "tools/forge_golden_rules_ast.py", "app", "tools", "--socle"],
                            blocking=True))
    else:
        print("\n\033[90m[skip] forge_golden_rules_ast.py absent\033[0m")

    # ── duplication (BLOQUANT) : cliquet sur les groupes de clones ────────────
    # Le taux de bruit a ete MESURE avant l'armement, par backtest git : rejoue
    # sur un worktree a HEAD~150, le detecteur trouve 397 groupes contre 402
    # aujourd'hui, avec 2 groupes d'ecart. Environ un groupe nouveau tous les
    # trente commits : assez rare pour bloquer sans paralyser. Quand un nouveau
    # clone est assume, on regenere le socle (--ecrire-socle) et on le commite,
    # comme pour les Golden Rules.
    if (ROOT / "tools" / "forge_dup_detector.py").exists():
        results.append(_run("duplication (cliquet clones)",
                            [PY, "tools/forge_dup_detector.py", "app", "tools", "--socle"],
                            blocking=True))
    else:
        print("\n\033[90m[skip] forge_dup_detector.py absent\033[0m")

    # ── capacites : le README declare, le CODE decide (BLOQUANT) ──────────────
    # Une documentation qui survend une capacite est pire qu'une documentation
    # absente : l'agent suivant la CROIT et construit sur une garantie qui
    # n'existe pas. Le gate confronte chaque declaration verifiable a une mesure
    # prise sur le depot. rc=2 = README illisible, donc NON MESURE et jamais vert.
    if (ROOT / "tools" / "forge_capability_audit.py").exists():
        results.append(_run("capacites (README vs code)",
                            [PY, "tools/forge_capability_audit.py"],
                            blocking=True, rc_non_mesure=(2,)))
    else:
        print("\n\033[90m[skip] forge_capability_audit.py absent\033[0m")

    # ── effet reel (OBSERVATION) : un mecanisme present n'est pas un effet ─────
    # Mandat owner 2026-09-16. Six familles de « present mais sans effet » sont
    # deja instrumentees ailleurs (reachability_ledger, capability_contracts,
    # capability_execution_trace, body_regulation_audit, regulation_efficacy,
    # vitalite_gardes) ; ce gate porte les QUATRE qui ne l'etaient pas, et qui
    # sont precisement celles qui ont RECIDIVE : garde sans emetteur, interrupteur
    # oublie, artefact devant preexister non versionne, politique lue par un seul
    # de ses N chemins.
    # NON BLOQUANT d'emblee, comme `anatomie` : un gate promu bloquant avant
    # d'avoir mesure son bruit se fait desarmer sur son premier faux positif, et
    # c'est le garde ENTIER qu'on perd. Il OBSERVE ; la promotion se decidera sur
    # la mesure, pas d'avance.
    # Et il est cable ICI parce que l'audit qui l'a motive a d'abord etabli que
    # les instruments existants ne sont eux-memes lances par personne -- un
    # auditeur non appele est exactement le defaut qu'il traque.
    if (ROOT / "tools" / "forge_effet_reel_audit.py").exists():
        results.append(_run("effet-reel (mecanisme vs effet) [OBSERVATION]",
                            [PY, "tools/forge_effet_reel_audit.py"],
                            blocking=False))
    else:
        print("\n\033[90m[skip] forge_effet_reel_audit.py absent\033[0m")

    # ── cliquet de CAPACITES (OBSERVATION) : le contrat etait ecrit, jamais relu ─
    # `forge_capability_ratchet` existe depuis le 2026-08-16, compare 166 capacites
    # observees a un socle VERSIONNE (tests/nr/capability_socle.json), distingue
    # GARANTI et OPPORTUNISTE, et rend 3 pour INDETERMINE plutot que de le confondre
    # avec CONFORME. Il avait un NR... et AUCUN gate ne le lancait.
    # C'est le constat de l'audit du 2026-09-16 applique a lui-meme : le registre
    # d'atteignabilite mesure 165 noms de surface MCP pour 58 prouves par usage, et
    # l'instrument capable de surveiller la derive des 166 contrats n'etait appele
    # par personne. Un cliquet que rien ne declenche ne cliquette pas.
    # rc=3 = INDETERMINE -> NON MESURE, jamais un vert.
    # SA MATRICE EST UN ARTEFACT NON VERSIONNE, et c'est decisif ici : en mode
    # `--reference` le worktree est materialise depuis un sha, or `.gitignore`
    # ecarte `sandbox/*.json`. La matrice y est donc TOUJOURS absente, le cliquet
    # rend INDETERMINE, et comme son domaine est critique la CI rougit -- pour une
    # absence de mesure, pas pour une regression. Mesure du 2026-09-16 : deux runs
    # rouges de suite pour ce seul motif, sur un arbre par ailleurs sain.
    # C'est la famille C que ce meme commit instrumente : un artefact devant
    # PREEXISTER que le depot ne porte pas. Le gate le DIT au lieu de le compter
    # en echec -- et il tourne pour de vrai sur l'arbre partage, ou la matrice
    # existe. Un `[skip]` qui se tait serait un vert ; celui-ci nomme ce qui
    # manque et comment le produire.
    _matrice_cap = ROOT / "sandbox" / "regression_matrix.json"
    if (ROOT / "tools" / "forge_capability_ratchet.py").exists() and _matrice_cap.exists():
        results.append(_run("capacites-cliquet (formes de reponse) [OBSERVATION]",
                            [PY, "tools/forge_capability_ratchet.py", "--check"],
                            blocking=False, rc_non_mesure=(3,)))
    elif not (ROOT / "tools" / "forge_capability_ratchet.py").exists():
        print("\n\033[90m[skip] forge_capability_ratchet.py absent\033[0m")
    else:
        print("\n\033[90m[skip] capacites-cliquet : matrice absente de CET arbre "
              "(%s) — artefact non versionne, invisible d'un worktree detache. "
              "NON MESURE, ce n'est pas un succes. La produire : "
              "forge_regression_matrix.py --extract\033[0m" % _matrice_cap.name)

    # ── anatomie (0 module non classe) : OBSERVATION d'abord, blocage plus tard ──
    # Mesure 2026-09-06 : 301 -> 0 non classes en une journee (lecteur et ecrivain de
    # declaration accordes sur la meme fenetre). Sans garde, le prochain forge_*.py
    # sans declaration ni mot-cle rouvre la breche en silence, et un module non
    # classe est un module que rien ne regule. `--check` est en LECTURE SEULE (aucun
    # artefact). Promu BLOQUANT le 2026-09-06 apres 3 CI consecutives a 0 non classe
    # (critere pose a la creation du gate, le meme jour) : un forge_*.py sans
    # declaration ni mot-cle ne passe plus.
    if (ROOT / "tools" / "forge_module_census.py").exists():
        results.append(_run("anatomie (0 module non classe)",
                            [PY, "tools/forge_module_census.py", "--check"],
                            blocking=True))

    # ── wiki date : la page GENEREE decrit-elle le corps COURANT ? ──────────
    # NON BLOQUANT d'emblee, comme `anatomie` a sa creation : on observe son
    # bruit avant d'enforcer, un gate promu trop tot se fait desarmer.
    #
    # MESURE QUI L'IMPOSE (2026-09-16) : `docs/wiki/20-Modules-Reference.md`
    # datait du 2026-08-30 et 1204 des 1765 modules `tools+app` avaient change
    # depuis — les deux tiers du corps — sans que RIEN ne le signale. La page
    # nommait son outil mais pas l'ETAT du code qu'elle decrivait. Faute de
    # mesure, quelqu'un a colle une rustine MANUELLE en tete ce jour-la (« le
    # corps ci-dessous n'a pas ete reecrit ») : un artefact dont la fraicheur
    # demande une annotation humaine n'a pas de fraicheur mesurable.
    #
    # Le verdict porte sur l'EMPREINTE DU CONTENU publie, jamais sur HEAD : un
    # gate fonde sur « sha inscrit == HEAD » rendrait PERIME des le commit
    # suivant, meme s'il ne touche aucun module.
    #
    # `--check` est en LECTURE SEULE et la page est VERSIONNEE : c'est la
    # lecon du gate `anatomie`, vert 3x en local puis rouge au premier passage
    # sur le runner parce qu'il lisait un artefact non versionne.
    if (ROOT / "docs" / "wiki" / "20-Modules-Reference.md").exists():
        results.append(_run("wiki date (page generee a jour)",
                            [PY, "tools/forge_wiki_modules.py", "--check"],
                            blocking=False))

    # ── cliquet docstring : le vide documentaire ne GRANDIT plus ────────────
    # MESURE DU GEL (2026-09-16) : 879 modules sans docstring sur 2394, apres
    # avoir ecarte le jetable (backups, archives, tmp_, vendored — 130 fichiers
    # comptes et dits). `app/backups/` portait a lui seul CINQ copies du meme
    # fichier de 4902 lignes, comptees comme cinq modules.
    #
    # Le cliquet n'exige PAS de combler les 879 : exiger cela produirait soit
    # un gate rouge en permanence, soit des docstrings inventees depuis le nom
    # du fichier — filet essaye le 2026-07-25 puis RETIRE, parce qu'une
    # etiquette inventee se propage en RAG et dans l'atlas ou plus rien ne la
    # distingue d'une mesure. Il interdit seulement d'AGGRAVER.
    #
    # NON BLOQUANT d'emblee, comme `anatomie` : on mesure son bruit d'abord.
    # CRITERE DE PROMOTION, pose ici a la creation pour qu'il ne se negocie
    # pas plus tard : bloquant apres 3 CI consecutives sans REGRESSION.
    if (ROOT / "tests" / "nr" / "docstring_ratchet.json").exists():
        results.append(_run("cliquet docstring (le vide ne grandit pas)",
                            [PY, "tools/forge_wiki_modules.py", "--ratchet"],
                            blocking=False))

    # ── chemins morts dans la doc : une page ne renvoie pas vers du vide ────
    # MESURE 2026-09-17 (owner : « le wiki porte des informations fausses ou des
    # chemins absents desormais ») : sur `docs/wiki/`, 2465 references de chemin
    # distinctes et 24 qui ne resolvent pas, sur 14 pages.
    #
    # Le gate CLASSE au lieu de detecter -- MORT / COQUILLE / DEPLACE / EXEMPLE.
    # Un detecteur binaire crierait sur `tools/your_tool.py`, placeholder
    # pedagogique legitime de la doc des lanceurs, et se ferait desarmer.
    # Le tri a paye immediatement : 3 « morts » etaient des DEPLACES (dont un
    # effet de la migration de namespace `2fd348209`), 1 une coquille a un
    # caractere (`snn.wante`), et l'un d'eux a mene a une docstring fautive dans
    # le CODE -- `forge_test_resource_calibrator` portait en tete le nom d'un
    # autre module. Sans le tri, on « corrige » la doc en supprimant une mention
    # utile, dans le mauvais sens.
    #
    # NON BLOQUANT : 14 chemins MORTS subsistent, et ce sont de vraies
    # disparitions a instruire, pas des fautes de frappe. Le poser bloquant
    # d'emblee rendrait la CI rouge en permanence -- un gate qu'on ne peut pas
    # satisfaire se fait desarmer. A promouvoir quand les 14 seront instruits.
    if (ROOT / "tools" / "forge_docs_chemins_morts.py").exists():
        results.append(_run("doc: chemins morts (une page ne renvoie pas vers du vide)",
                            [PY, "tools/forge_docs_chemins_morts.py",
                             "--dossier", "docs/wiki", "--check"],
                            blocking=False))

    # ── doc: fraicheur — une page perimee qui ne le DIT pas se lit comme a jour ──
    # MESURE 2026-09-17 : 49 pages sur 50 au-dela de 7 j. Et la date GIT donne
    # bien pire que le `mtime` -- jusqu'a 91 j (`21-SSoT-Cross-CLI`), 70 j pour
    # `01-Installation`, `02-Quick-Start`, `09-TUI-Reference`. Le `mtime`
    # annoncait 25 j : c'etait la date d'un CHECKOUT, pas d'une revue. Sur le
    # runner, ou tout est clone le jour meme, il aurait declare TOUTES les pages
    # fraiches -- meme famille que `job_status` apres un kill externe.
    # Seuil 60 j, NON BLOQUANT : 21 pages le depassent aujourd'hui, et les
    # relire est un travail de fond, pas une rustine. Le gate DIT, il ne
    # pretend pas juger le contenu -- ca demande un humain.
    if (ROOT / "tools" / "forge_docs_datation.py").exists():
        results.append(_run("doc: fraicheur (une page dit quand elle a ete revue)",
                            [PY, "tools/forge_docs_datation.py",
                             "--dossier", "docs/wiki", "--check", "--seuil-j", "60"],
                            blocking=False))

    # ── mutation ratchet (BLOQUANT sur REGRESSION) : cliquet de mutation ──────
    # forge_mutation_test MESURE, ce cliquet BLOQUE : il gele le nombre de mutants
    # survivants par (module, genre) sur les surfaces critiques (les outils
    # anti-regression eux-memes) et echoue des qu'une NOUVELLE faiblesse apparait.
    # Tri-etat : rc 1 = regression (FAIL), rc 3 = surface non mesurable (arbre non
    # propre en local) = UNKNOWN, jamais un faux vert. LOURD (mute + relance la
    # suite du surface) -> --no-mutation en iteration rapide, exclu de --fast.
    # `_demande` est teste ICI et non sur les `results.append` de ce bloc : le
    # cliquet mute puis relance la suite du surface. Garder la sortie laisserait le
    # travail se faire quand meme -- un cliquet vert pour un gain nul.
    if (not a.no_mutation and _demande("mutation")
            and (ROOT / "tools" / "forge_mutation_ratchet.py").exists()):
        name = "mutation-ratchet (surfaces critiques)"
        print(f"\n\033[1;36m── {name} ──\033[0m  (bloquant sur regression)")
        e = dict(os.environ)
        e["PYTHONDONTWRITEBYTECODE"] = "1"
        e["PYTHONIOENCODING"] = "utf-8"
        # Muter, c'est ECRIRE dans tools/. Or un compte qui n'y a que (R) -- tout
        # job detache tourne sous LaForgeSbxOffline -- leve PermissionError des le
        # premier mutant, et le cliquet rend INDETERMINE. C'est ainsi qu'il a
        # figure « vert » sans avoir JAMAIS mordu : le gate ne mesurait rien et
        # personne ne le voyait (mesure 2026-08-18, reconfirmee le 19).
        # `sandbox/` porte, lui, une ACE explicite en ecriture. On y mute une
        # COPIE via un arbre de travail git : le `tools/` reel n'est jamais
        # touche -- plus sur que d'accorder l'ecriture du code a un compte de
        # service pour faire taire un INDETERMINE.
        cwd_mut = ROOT
        try:
            with open(ROOT / "tools" / "forge_mutation_ratchet.py", "r+", encoding="utf-8"):
                pass
        except OSError:
            # CONVERGENCE 2026-09-11 : la creation passe par le createur canonique
            # `forge_worktree`. Cet arbre-ci est un SCRATCH, pas une preuve — le
            # cliquet y ECRIT, c'est tout son objet (il mute le code pour verifier
            # que les tests mordent). D'ou `create_scratch` et non `create_proof` :
            # un seul createur, deux contrats d'usage qui se nomment.
            # L'EMPLACEMENT ne bouge pas : `sandbox/` porte une ACE explicite en
            # ecriture, et deplacer un gate bloquant pendant une convergence
            # ajouterait un risque que rien n'exige.
            wt = ROOT / "sandbox" / "mutation_wt"
            sha = subprocess.run(
                ["git", "-c", "safe.directory=*", "-C", str(ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True, errors="replace").stdout.strip()
            _tools = str(Path(__file__).resolve().parent)
            if _tools not in sys.path:
                sys.path.insert(0, _tools)
            import forge_worktree as _fw
            _res_wt = _fw.create_scratch(sha, wt) if sha else {"error": "HEAD illisible"}
            if not _res_wt.get("error") and (wt / "tools" / "forge_mutation_ratchet.py").exists():
                cwd_mut = wt
                print(f"  [worktree] tools/ non inscriptible ici -> mutation sur "
                      f"sandbox/{wt.name} @ {sha[:8]} ({_res_wt.get('status')})")
            else:
                motif = _res_wt.get("error") or "arbre incomplet"
                print(f"  [worktree] indisponible ({motif}) -> le cliquet restera "
                      "INDETERMINE, et il le DIRA")
        rc = subprocess.run([PY, "tools/forge_mutation_ratchet.py", "--check"],
                            cwd=str(cwd_mut), env=e).returncode
        if rc == 0:
            print("  → OK (aucune nouvelle faiblesse de mutation) (rc=0)")
            results.append((name, True))
        elif rc == 1:
            print("  → FAIL (nouvelle faiblesse : un comportement teste ne l'est plus) (rc=1)")
            results.append((name, False))
        else:
            # Un INDETERMINE muet est un vert deguise : le resume l'affichait
            # « ✅ [INDETERMINE] » sans jamais le nommer parmi les non-mesures.
            # Mesure 2026-08-18 : ce gate n'a JAMAIS mesure — refus d'ACL en
            # sandbox, arbre juge non propre en CI — et personne ne l'a vu.
            _INCONCLUS.append((name, _critique(name), None))
            print(f"  → UNKNOWN — le cliquet n'a pas pu mesurer (rc={rc}) ; motif "
                  "ci-dessus (droit d'ecriture, arbre non propre, ou suite deja rouge)")
            results.append((f"{name} [INDETERMINE]", True))
    elif a.no_mutation:
        print("\n\033[90m[skip] mutation-ratchet (--no-mutation)\033[0m")
    else:
        print("\n\033[90m[skip] forge_mutation_ratchet.py absent\033[0m")

    # ── pytest suite "pure" (BLOQUANT) : ci.yml unit-tests
    if not a.no_tests and _has("pytest"):
        present = [t for t in PURE_TESTS if (ROOT / t).exists()]
        _absents = [t for t in PURE_TESTS if not (ROOT / t).exists()]
        # ── SELECTION (--impacte) : ne rejouer que ce que le diff peut casser ──
        # Une iteration touche une poignee de modules ; rejouer la suite entiere a
        # chaque coup coute le temps de l'owner. Le selecteur s'abstient TOUJOURS
        # du cote de la prudence (diff illisible, aucun changement, fichier global
        # -> TOUT), et ce mode ne CERTIFIE rien.
        _selection = None
        if getattr(a, "impacte", False):
            try:
                from forge_ci_selection import (TOUT, fichiers_modifies, resume,
                                                selectionner)
            except ImportError as _esel:
                print("  [selection] INDISPONIBLE (%s) — suite COMPLETE jouee. "
                      "Un selecteur absent ne doit jamais REDUIRE le perimetre."
                      % type(_esel).__name__, flush=True)
            else:
                _liste = getattr(a, "impacte_fichiers", None)
                if _liste:
                    from forge_ci_selection import liste_depuis_fichier
                    _mods, _etat_diff = liste_depuis_fichier(_liste)
                else:
                    # Auto-detection : correcte, mais ILLISIBLE sous le compte du
                    # hub (git refuse) — elle joue donc TOUT, ce qui est sur.
                    _mods, _etat_diff = fichiers_modifies(ROOT)
                _selection = selectionner(present, _mods, etat_diff=_etat_diff)
                print("  " + resume(_selection), flush=True)
                if _selection["mode"] != TOUT:
                    present = _selection["retenus"]
        if _absents:
            # Un filtre qui ecarte des donnees le DIT. Sans cette ligne un test
            # DECLARE mais disparu n'est jamais execute et RIEN ne le signale : la
            # suite parait complete, et « je n'ai pas pu le voir » se lit comme
            # « il n'y a rien a voir ». Mesure 2026-08-25 :
            # `tests/nr/test_redteam_link_nr.py` etait ecarte en silence depuis la
            # separation du lab du 22/08, soit trois jours de suite amputee sans le
            # moindre signe. Le cliquet `test_suite_pure_ratchet_nr` attrape les
            # tests AJOUTES hors liste, pas les SUPPRIMES restes dedans.
            print("\n\033[33m[pytest] %d test(s) DECLARE(S) mais ABSENT(S) du disque "
                  "— NON executes : %s\033[0m" % (len(_absents), _absents))
        if present:
            plug = []
            # `-p <module>` doit nommer le module qui PORTE LES HOOKS, pas le paquet.
            # pytest-asyncio 1.3.0 declare son entry-point `[pytest11]` comme
            # `asyncio = pytest_asyncio.plugin` ; `pytest_asyncio/__init__.py`
            # n'exporte que fixture/is_async_test, donc AUCUN hook. Avec
            # PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, `-p pytest_asyncio` enregistrait un
            # plugin VIDE et pytest ne proteste pas (un module importable est accepte
            # en silence) : tout test @pytest.mark.asyncio tombait en "async def
            # functions are not natively supported". Mesure 2026-09-13 : 23 echecs lus
            # une journee entiere comme un defaut du depot. pytest_mock et
            # pytest_timeout portent bien leurs hooks dans le module de tete.
            # Avant tout ajout ici : lire `[pytest11]` dans entry_points.txt du paquet,
            # une montee de version deplace les hooks et desarme un `-p` qui marchait.
            for _m in ("pytest_asyncio.plugin", "pytest_mock", "pytest_timeout"):
                if _has(_m):
                    plug += ["-p", _m]
            # TEMP est PARTAGE entre comptes (owner, runner self-hosted, services).
            # pytest derive son basetemp de tempfile.gettempdir() et balaie les anciens
            # `pytest-of-<user>` : si le dossier appartient a un AUTRE compte, il meurt
            # en PermissionError AVANT le premier test. Mesure 2026-07-28 : CI rouge sur
            # "[WinError 5] Acces refuse: D:\\Temp\\pytest-of-user" quand la meme suite
            # passait 100/100 en local.
            #
            # 2026-08-10 : ancrer DANS le checkout a bien tue le TEMP partage, mais a
            # produit l'inverse — actions/checkout ne peut plus nettoyer le workspace au
            # run SUIVANT : `git clean -ffdx` sort "Permission denied" puis
            # "EPERM: operation not permitted, scandir ...\\sandbox\\pytest_basetemp",
            # le dossier ayant ete cree par le job precedent sous un AUTRE compte.
            # Mesure du jour : 4 runs rouges sur 8, checkout en echec sur ui-acceptance
            # et notify-failure pendant que `gates` PASSAIT — donc un rouge d'INFRA lu
            # comme un rouge de CODE. RUNNER_TEMP est la variable prevue pour ce cas :
            # propre au JOB, HORS du checkout, purgee par le runner lui-meme. Repli sur
            # le checkout en local, ou RUNNER_TEMP n'existe pas et ou le compte est un.
            _rt = os.environ.get("RUNNER_TEMP")
            # 2026-09-03 : un basetemp PARTAGE entre comptes ne peut pas marcher, et le
            # hub lance ses jobs sous un compte de SERVICE (LaForgeSbxOffline, ou Online
            # avec network, ou LaForgeTrusted via trusted_script). Mesure : 7 731
            # « failed on setup » et 30 929 refus d'acces — la suite n'a RIEN execute,
            # parce que sandbox/pytest_basetemp appartenait a l'owner. La meme suite
            # passe 66/66 sous le compte de service des qu'on lui donne un basetemp
            # inscriptible : ce n'etait donc pas une affaire de droits a obtenir, mais
            # de repertoire a ne pas partager. RUNNER_TEMP reglait le cas GitHub ; le
            # SUFFIXE PAR COMPTE regle tous les autres — sans avoir a choisir le bon
            # compte a l'appel, ce qui serait un savoir a retenir plutot qu'un defaut
            # corrige.
            _qui = "".join(c for c in (os.environ.get("USERNAME") or "anon")
                           if c.isalnum() or c == "_") or "anon"
            # Tous les artefacts du gate vivent dans le MEME dossier par compte : le
            # rapport JUnit se calcule en `_btmp.parent`, donc l'ancrer ici suffit.
            # Mesure 2026-09-03 : le basetemp par compte avait supprime les 7 731
            # « failed on setup », mais le JUnit partait toujours dans `sandbox/`, que
            # le compte ne peut pas ecrire -> « rapport illisible », et le gate refusait
            # (a juste titre) de racheter sans preuve. Corriger la moitie d'un chemin
            # d'ecriture ne corrige rien : c'est la preuve elle-meme qui manquait.
            _art = _racine_artefacts(_qui)
            _btmp = (Path(_rt) / "pytest_basetemp") if _rt else (_art / "pytest_basetemp")
            # Le verdict ne doit pas dependre d'un FLUX. Mesure 2026-08-26 (runs
            # 32957444508, 32958735437, 32972075477) : le processus meurt APRES avoir
            # tout execute, sans imprimer « N passed » -- tous les fichiers verts dans
            # le journal, rc=1, et la CI rouge trois fois de suite pour un travail
            # entierement fait. Le rapport JUnit, lui, est ECRIT PAR pytest a la fin de
            # la session, donc AVANT le shutdown de l'interpreteur : il survit a la
            # fermeture des flux. On tranche dessus, et le rc ne sert plus que de
            # signal secondaire.
            _xml = _btmp.parent / "pytest_pur_junit.xml"

            # MODE TURBO (opt-in) — mesures du 2026-09-04, selection reelle de la CI :
            #   sequentiel                 299,8 s   0 echec
            #   xdist --dist=loadscope      96 s     16 a 19 echecs, INSTABLE a arbre
            #                                        constant (38 puis 32) : inutilisable
            #                                        comme gate, un verdict ne peut pas
            #                                        bouger sans que le code bouge
            #   xdist --dist=loadfile       98,5 s   4 echecs, REPRODUCTIBLE (deux runs
            #                                        a la seconde et au test pres)
            # `loadfile` garde un fichier entier dans un worker : la pollution etant
            # intra-fichier, elle devient deterministe au lieu de suivre le voisinage.
            #
            # Les 4 echecs restants tiennent a un ARTEFACT WINDOWS connu depuis le
            # 2026-08-27 (indexe par forge_symptom_index) : sous capture, pytest rend
            # des « ValueError: I/O operation on closed file » sans rapport avec le code
            # teste — 2700 faux positifs mesures le 01/09. Son seul remede est `-s`, que
            # xdist REFUSE. Ces fichiers sont donc joues A PART, en sequentiel et sans
            # capture. Ils ne sont PAS exemptes : ils sont joues integralement, dans un
            # second processus, et leur verdict compte autant que l'autre.
            _ARTEFACT_CAPTURE = (
                "tests/test_self_patcher_thymus.py",
                "tests/test_predict_impact_sr.py",
            )
            _turbo = bool(getattr(a, "turbo", False)) and _has("xdist")
            # Les BLOCS ISOLES sortent du processus principal QUEL QUE SOIT le mode.
            # `_a_part` ne les couvrait pas : il n'existe qu'en turbo, et son motif est
            # tout autre (artefact de capture sous xdist). Deux raisons distinctes
            # d'isoler, deux listes -- les fondre ferait disparaitre un motif.
            _ISOLES = tuple(chemin for chemin, _motif in BLOCS_ISOLES)
            _isoles_presents = [t for t in present if t in _ISOLES]
            _reste = [t for t in present if t not in _ISOLES]
            _a_part = [t for t in _reste if t in _ARTEFACT_CAPTURE] if _turbo else []
            _paralleles = ([t for t in _reste if t not in _ARTEFACT_CAPTURE]
                           if _turbo else _reste)

            # Liste des tests passee par FICHIER (`@`) : voir `_args_depuis_fichier`. Hors du basetemp, que
            # pytest vide au demarrage ; a cote du JUnit, dans le dossier d'artefacts du compte.
            _liste_pur = _btmp.parent / "pytest_pur_tests.txt"
            _env_liste = {}
            try:
                _liste_pur.parent.mkdir(parents=True, exist_ok=True)
                _args_tests, _env_liste = _args_suite_pure(_paralleles, _liste_pur, _turbo)
            except OSError as _eliste:
                # Non inscriptible : l'aptitude ci-dessous le dira (meme dossier que le JUnit). Repli sur la
                # forme en ligne, que le lanceur NOMME (WinError 206) si elle depasse le plafond.
                print("  [pytest] liste @ non inscriptible (%s) -- arguments en ligne"
                      % type(_eliste).__name__, flush=True)
                _args_tests = list(_paralleles)
            _cmd = [PY, "-m", "pytest", *_args_tests, "-q", "--tb=short",
                    "-p", "no:cacheprovider", "--basetemp=%s" % _btmp,
                    "--junitxml=%s" % _xml, *plug]
            if _turbo:
                # `--capture=no` est INCOMPATIBLE avec xdist : ne pas le passer ici. Le
                # verdict continue de se lire sur le JUnit, ecrit par pytest AVANT la
                # fermeture des flux — c'est deja la parade retenue le 2026-08-26, elle
                # couvre donc le besoin que `--capture=no` couvrait.
                _cmd += ["-p", "xdist", "-n", str(max(1, (os.cpu_count() or 2) // 2)),
                         "--dist=loadfile"]
            else:
                _cmd += ["--capture=no"]
            if _has("pytest_timeout"):
                _cmd += ["--timeout=30"]
            try:
                _xml.unlink()        # jamais juger sur le rapport du run precedent
            except OSError:  # muet-ok : absent = l'etat voulu est deja atteint
                pass
            # APTITUDE AVANT VERDICT. Mesure 2026-09-03 : lance par le hub (compte
            # de service), pytest a rendu 7 731 « failed on setup » et 30 929 refus
            # d'acces — la suite n'a RIEN execute, et le resume affichait pourtant
            # « pytest ❌ / NE PAS pousser ». Deux torts en un : on juge ce qu'on n'a
            # pas pu lancer, et on impute au depot un defaut d'environnement. Un gate
            # qui crie a faux finit desarme. Le verdict reste BLOQUANT — on ne publie
            # pas sans avoir teste — mais il dit « non execute », pas « en echec ».
            _bt = _btmp
            _inapte = ""
            try:
                _bt.mkdir(parents=True, exist_ok=True)
                _sonde = _bt / (".aptitude_%d" % os.getpid())
                _sonde.write_text("x", encoding="utf-8")
                _sonde.unlink()
            except OSError as _e:
                _inapte = "%s: %s" % (type(_e).__name__, str(_e)[:120])
            if _inapte:
                print("  ⚠ NON EXECUTE : %s n'est pas inscriptible sous ce compte "
                      "(%s). La suite ne peut pas demarrer : ce resultat n'est ni "
                      "vert ni rouge. Relancer ci_local depuis une console OWNER."
                      % (_bt.name, _inapte), flush=True)
                if _demande("pytest"):
                    results.append(("pytest (suite pure) [NON EXECUTE — compte inapte]", False))
                _verdict, _nom = True, ""
            else:
                _telemetrie("avant: suite pure")
                _nom, _verdict = _run(
                    "pytest (suite pure)%s" % (" [turbo]" if _turbo else ""),
                    _cmd, blocking=True,
                    env={"PYTHONPATH": str(ROOT / "app"),
                         "LAFORGE_SQLITE_BUSY_MS": "9000",
                         "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", **_env_liste})
                _telemetrie("apres: suite pure")
                _dernier_principal = dict(_run.__dict__.get("dernier") or {})
                if _turbo and _a_part:
                    # Second processus, sequentiel et SANS capture : les fichiers que
                    # l'artefact Windows rend illisibles en parallele. Le gate n'est
                    # vert que si les DEUX passent — sauter ce run rendrait le mode
                    # turbo plus rapide en ne testant simplement pas tout.
                    _xml2 = _btmp.parent / "pytest_pur_junit_apart.xml"
                    _cmd2 = [PY, "-m", "pytest", *_a_part, "-q", "--tb=short",
                             "-p", "no:cacheprovider", "--basetemp=%s" % _btmp,
                             "--junitxml=%s" % _xml2, *plug, "--capture=no"]
                    if _has("pytest_timeout"):
                        _cmd2 += ["--timeout=30"]
                    # Trouve NU par le NR d'atteignabilite : ce bloc turbo
                    # n'etait pas encadre. Je n'avais cable que les deux
                    # frontieres que je croyais exister.
                    _telemetrie("avant: fichiers hors parallele")
                    _n2, _v2 = _run("pytest (fichiers hors parallele)", _cmd2,
                                    blocking=True,
                                    env={"PYTHONPATH": str(ROOT / "app"),
                                         "LAFORGE_SQLITE_BUSY_MS": "9000",
                                         "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
                    _telemetrie("apres: fichiers hors parallele")
                    _verdict = _verdict and _v2
            if _nom and not _verdict:
                _bilan = _lire_junit(_xml)
                if _bilan is None:
                    print("  ⚠ aucun rapport JUnit lisible : le gate reste en ECHEC "
                          "(on ne rachete pas un rc non nul sans preuve ecrite).",
                          flush=True)
                elif _bilan["problemes"] == 0 and _bilan["tests"] > 0:
                    print("  ✅ RACHAT SUR PREUVE ECRITE : %d tests, 0 echec, 0 erreur "
                          "dans %s. Le processus est mort APRES la session (flux ferme "
                          "au shutdown) — le travail est fait et mesure, le rc non nul "
                          "ne dit rien du depot." % (_bilan["tests"], _xml.name),
                          flush=True)
                    _verdict = True
                else:
                    print("  ❌ le rapport JUnit CONFIRME l'echec : %d test(s) en echec, "
                          "%d erreur(s) sur %d." % (_bilan["failures"], _bilan["errors"],
                                                    _bilan["tests"]), flush=True)
                    for _cas, _genre, _msg in _bilan.get("rates") or []:
                        print("     [%s] %s" % (_genre.upper(), _cas), flush=True)
                        if _msg:
                            print("        %s" % _msg, flush=True)
                    if not _bilan.get("rates"):
                        print("     (rapport sans <testcase> nomme : compte sans nom, "
                              "a instruire — pas un rachat)", flush=True)
            # ---- LA PREUVE EST PAR BLOC ---------------------------------------
            # Chaque bloc isole tourne dans SON processus avec SON rapport. Le gate
            # reste aussi exigeant : ces fichiers sont joues INTEGRALEMENT et leur
            # verdict compte autant que celui de la suite. Ce qui change, c'est
            # qu'un fichier coupe n'emporte plus que le sien.
            _blocs = {}
            _bilans = {}
            if _nom and _nom != _NON_DEMANDE:
                _bilans["suite pure"] = _lire_junit(_xml)
                _blocs["suite pure"] = verdict_bloc(
                    _dernier_principal.get("rc"), _dernier_principal.get("sortie"),
                    _bilans["suite pure"])
                for _i, _chemin in enumerate(_isoles_presents, 1):
                    _xmli = _btmp.parent / ("pytest_isole_%d_junit.xml" % _i)
                    try:
                        _xmli.unlink()   # jamais juger sur le rapport du run precedent
                    except OSError:  # muet-ok : absent = l'etat voulu est atteint
                        pass
                    _cmdi = [PY, "-m", "pytest", _chemin, "-q", "--tb=short",
                             "-p", "no:cacheprovider", "--basetemp=%s" % _btmp,
                             "--junitxml=%s" % _xmli, *plug, "--capture=no"]
                    if _has("pytest_timeout"):
                        _cmdi += ["--timeout=30"]
                    _telemetrie("avant: %s" % _chemin)
                    _ni, _vi = _run("pytest [isole] %s" % os.path.basename(_chemin),
                                    _cmdi, blocking=True,
                                    env={"PYTHONPATH": str(ROOT / "app"),
                                         "LAFORGE_SQLITE_BUSY_MS": "9000",
                                         "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
                    # Pris AVANT le `continue` : un bloc non demande encadre quand
                    # meme le suivant, et un trou dans la serie se lirait comme une
                    # panne de la sonde.
                    _telemetrie("apres: %s" % _chemin)
                    if _ni == _NON_DEMANDE:
                        continue
                    _di = _run.__dict__.get("dernier") or {}
                    _bilans[_chemin] = _lire_junit(_xmli)
                    _blocs[_chemin] = verdict_bloc(_di.get("rc"), _di.get("sortie"),
                                                   _bilans[_chemin])
                    _verdict = _verdict and _vi
            if _blocs:
                _agg = verdict_suite(_blocs)
                for _b, _v in _agg["blocs"].items():
                    print("  [bloc] %-52s %s" % (_b[:52], _v), flush=True)
                if _agg["etat"] == "SUITE_INCOMPLETE":
                    print("  SUITE_INCOMPLETE : %d bloc(s) sans preuve (%s). Une suite "
                          "incomplete n'est JAMAIS verte -- on ne publie pas ce qu'on "
                          "n'a pas mesure, et un bloc coupe n'est pas un bloc en echec."
                          % (len(_agg["sans_preuve"]), ", ".join(
                              os.path.basename(_s) for _s in _agg["sans_preuve"])),
                          flush=True)
                # LE VERDICT SE CHIFFRE. Sans ces nombres, « pytest OK » ne dit ni
                # sur quel arbre, ni combien de cas ont reellement tourne.
                _bp = bilan_preuve(_blocs, _bilans, _absents, _sha_courant())
                if _selection is not None and _selection["mode"] != "TOUT":
                    # Une partielle ne peut pas rendre SUITE_COMPLETE : ce serait le
                    # faux vert parfait — vert sur ce qu'on a choisi de jouer. Elle
                    # porte son denominateur, comme toute borne de ce depot.
                    _bp["etat"] = "SUITE_PARTIELLE"
                    _bp["selection"] = {k: _selection[k] for k in
                                        ("total", "ecartes", "raison", "modules_touches")}
                global _ETAT_SUITE
                _ETAT_SUITE = _bp["etat"]
                print("  [preuve] sha=%s  executes=%d  skipped=%d  echecs=%d  "
                      "erreurs=%d  timeouts=%d  blocs_sans_preuve=%d  "
                      "declares_absents=%d  etat=%s"
                      % (_bp["sha"][:12], _bp["executes"], _bp["skipped"],
                         _bp["echecs"], _bp["erreurs"], len(_bp["timeouts"]),
                         len(_bp["sans_preuve"]), len(_bp["declares_absents"]),
                         _bp["etat"]), flush=True)
                # CE QUI N'EST PAS DANS LE SHA ET ENTRE POURTANT DANS LE VERDICT.
                # Sans cette ligne, deux runs du meme commit qui divergent ne se
                # comparent qu'a la main : c'est ce qui a coute une heure le
                # 2026-09-14, pour un `MEMORY.md` reecrit entre les deux.
                try:
                    _ctx = empreinte_contexte()
                    print("  [contexte] compte=%s  python=%s  angles_morts=%d"
                          % (_ctx["compte"], _ctx["interpreteur"],
                             len(_ctx["NON_COUVERT"])), flush=True)
                    for _n, _d in _ctx["postes"].items():
                        print("    %-26s %-10s %s"
                              % (_n[:26], _d["etat"],
                                 str(_d["empreinte"])[:16]), flush=True)
                except Exception as _ec:  # noqa: BLE001
                    # L'observabilite ne casse jamais le gate -- mais elle ne se
                    # tait pas non plus : un contexte absent se lirait « rien a
                    # signaler », ce qui est precisement le defaut combattu ici.
                    print("  [contexte] NON MESURE (%s) — deux verdicts de ce "
                          "sha ne seront pas comparables" % type(_ec).__name__,
                          flush=True)
                # CONTROLE POSITIF DU PRODUCTEUR, execute en production. Le chemin
                # « rc nul + rapport absent -> UNKNOWN » n'est emprunte par aucun
                # run spontanement : on le fabrique, avec les fonctions reelles.
                _ap = auto_preuve(_btmp)
                print("  [auto-preuve] %s%s"
                      % (_ap["etat"],
                         (" — " + _ap["motif"]) if _ap.get("motif") else ""),
                      flush=True)
                if _ap["etat"] == "DEFAUT":
                    # L'instrument qui juge tous les autres gates ne distingue
                    # plus une preuve d'une absence de preuve. Aucun verdict de ce
                    # run ne peut etre tenu pour fiable -- y compris un vert.
                    print("  ⚠ L'INSTRUMENT DE PREUVE NE DISTINGUE PLUS : le "
                          "verdict de ce run ne vaut rien, quel qu'il soit.",
                          flush=True)
                    _verdict = False
                elif _ap["etat"] == "NON EXECUTABLE":
                    # Ni vert ni rouge : on n'a pas pu verifier l'instrument. On
                    # le DIT -- un controle muet se lit comme un controle passe.
                    print("  [auto-preuve] le chemin negatif n'a PAS ete observe "
                          "sur ce run ; ne pas lire son silence comme une preuve.",
                          flush=True)
                # L'agregat ne peut que DURCIR : il n'a aucun chemin qui rende vert
                # ce que le gate tenait pour rouge.
                _verdict = _verdict and not _agg["bloquant"]
            # `_nom` vient de `_run`, qui a deja consulte la selection : quand le gate
            # n'est pas demande il rend la sentinelle. Le test la nomme pour que la
            # couverture soit VISIBLE, et pas seulement vraie par effet de bord.
            if _nom and _nom != _NON_DEMANDE:
                results.append((_nom, _verdict))
        else:
            print("\n\033[90m[skip] aucun test whitelist présent\033[0m")

    # ── pip-audit (WARN) : supply-chain CVE sur deps installées
    if _has("pip_audit"):
        # CACHE EXPLICITE — sans lui, ce gate n'a JAMAIS rien mesure.
        # Mesure 2026-09-06 : sous le compte des jobs, HOME vaut C:\Users\Default, donc
        # pip-audit tente `C:\Users\Default\AppData\Local\pip-audit\Cache` et meurt en
        # FileNotFoundError AVANT le premier paquet. Duree observee : 1,4 s -- impossible
        # pour un audit OSV de plusieurs centaines de paquets, et c'est ce chiffre qui a
        # trahi la panne. Le gate etant `warn`, son rc non nul passait pour un simple
        # avertissement : un domaine pourtant declare CRITIQUE (_DOMAINES_CRITIQUES) n'a
        # jamais eu de verdict, et personne ne l'a vu.
        _cache_audit = ROOT / "sandbox" / "pip_audit_cache"
        try:
            _cache_audit.mkdir(parents=True, exist_ok=True)
        except OSError as _e_cache:
            print("[pip-audit] cache non creable (%s) : l'audit dira lui-meme s'il a pu "
                  "mesurer" % type(_e_cache).__name__)
        # TROIS ETATS, pas deux : MESURE+sain -> PASS · MESURE+CVE -> WARN/FAIL ·
        # PAS MESURE -> UNKNOWN. `pip-audit` rend 1 pour les deux derniers, donc on
        # lit sa SORTIE. Sans ca il affichait ✅ sans avoir audite un seul paquet.
        # BORNE : 300 s. Elle est PREVENTIVE et non curative -- contrairement a ce que
        # j'ai d'abord ecrit : mesure du 2026-09-09, ce gate finit en UNKNOWN presque
        # aussitot sous ce compte (pas d'egress), il ne consommait PAS les 18 minutes
        # qu'on lui a attribuees a tort. La borne reste juste : sur un compte AYANT du
        # reseau, un audit de 226 paquets peut durer, et le budget du job est de 20 min.
        # La mesure DEPORTEE le supplee juste apres, avec sa date -- c'est elle le
        # verdict, pas l'attente.
        results.append(_run("pip-audit",
                            [PY, "-m", "pip_audit", "--progress-spinner=off",
                             "--cache-dir", str(_cache_audit)],
                            blocking=False, timeout_s=300,
                            motifs_non_mesure=(
                                "NewConnectionError",
                                "Max retries exceeded",
                                "Failed to establish a new connection",
                                "requests.exceptions.ConnectionError",
                                "Failed to read from cache directory")))
        # La mesure DIRECTE a echoue (compte sans egress) : on juge alors la mesure
        # DEPORTEE. Ce n'est un suppleant que s'il est FRAIS -- et on le NOMME avec sa
        # date, au lieu de declarer un suppleant de principe. `.github/workflows/
        # ci-selfhosted.yml` n'en est pas un : il INSTALLE pip-audit sans jamais le
        # lancer (mesure 2026-09-07).
        if _INCONCLUS and _INCONCLUS[-1][0] == "pip-audit":
            _frais, _detail = _mesure_pip_audit_deportee()
            if _frais:
                _INCONCLUS[-1] = ("pip-audit", False, _detail)
                print("  ↳ mesure directe impossible sous ce compte ; %s" % _detail)
            else:
                print("  ↳ et AUCUNE mesure deportee exploitable : %s" % _detail)
    else:
        print("\n\033[90m[skip] pip-audit absent — pip install pip-audit\033[0m")

    # ── gitleaks (WARN) : gitleaks.yml
    if which("gitleaks"):
        results.append(_run("gitleaks", ["gitleaks", "detect", "--source", ".", "--no-banner", "--redact"], blocking=False))
    else:
        print("\n\033[90m[skip] gitleaks absent (pre-commit secret-guard couvre déjà)\033[0m")

    # ══ opt-in : jobs dispatch-only des workflows ══════════════════════════════
    # ── integration (WARN) : ci-selfhosted job integration
    if a.integration and _has("pytest"):
        results.append(_run(
            "intégration (hub/e2e)",
            [PY, "-m", "pytest", "tests/", "-q", "-k", "integration or hub or e2e", "--timeout=60"],
            blocking=False, env={"PYTHONPATH": str(ROOT / "app")}))

    # ── ui-acceptance : contrat forge_ui_campaign sur web_hub :7400.
    #    Playwright headless + login (LAFORGE_ADMIN_TOKEN via env runner ; vault si runner=owner).
    #    exit 1 du script = contrat rouge. Requiert :7400 up + python py314.
    #
    # AUTO-DETECTION (2026-09-09). Ce gate figure dans `_DOMAINES_CRITIQUES` et etait
    # pourtant garde derriere `--ui-gate`, un drapeau que la CI standard ne passe
    # jamais : il ne tournait DONC JAMAIS. Le domaine le plus visible du systeme
    # n'etait mesure par personne, et le registre de vitalite criait son anergie sans
    # bloquer. Un vert par absence est pire qu'un rouge : il ressemble a un verdict.
    # Mesure du jour : :7400 LISTENING, GET /health 200 en 18 ms, GET / 401 (middleware
    # actif). Le gate POUVAIT tourner ; rien ne le demandait.
    #
    # DEUX REGIMES, volontairement distincts :
    #   --ui-gate explicite -> BLOQUANT, comme avant : la demande engage.
    #   auto-detection      -> NON BLOQUANT, il OBSERVE. Ce gate a un historique
    #                          (« 4 runs rouges sur 8, checkout en echec ») et on
    #                          observe avant d'enforcer, comme pour `anatomie` --
    #                          un gate promu bloquant d'emblee se fait desarmer.
    # Ce gate n'emprunte pas `_run` (il pilote un sous-processus Playwright), donc le
    # selecteur ne l'atteint pas tout seul : il le consulte explicitement. C'est le
    # SEUL gate dans ce cas, et c'est precisement lui que `--only ui-acceptance` sert
    # a lancer depuis le workflow -- l'oublier ici viderait le correctif de son objet.
    _ui_demande = bool(_ONLY) and _demande("ui-acceptance")
    _ui_auto = False
    # `a.fast` et NON `partiel` : ce dernier est le parametre de `_summary`, pas une
    # variable de `main`. Pose ici le 2026-09-09, il levait un NameError qui tuait
    # `main()` dans son cas nominal -- invisible au parse, invisible aux NR qui ne
    # traversent pas le point d'entree, et masque par le fait que la CI de reference
    # qui l'a « valide » tournait sur un sha ANTERIEUR a son commit. Meme ambiguite
    # d'ancre que la greffe du 2026-09-08, posee dans `_summary` au lieu de `main` :
    # les deux fonctions se ressemblent, et l'ancre seule ne dit pas laquelle on vise.
    if not a.ui_gate and not _ui_demande and not a.fast:
        _ui_ok, _ui_motif = _webhub_repond()
        _ui_auto = _ui_ok
        if not _ui_ok:
            print("\n\033[90m[skip] ui-acceptance : interface injoignable (%s) — "
                  "NON MESURE, ce n'est pas un succes\033[0m" % _ui_motif)
    _ui_auto_permis = os.environ.get("LAFORGE_UI_AUTO", "1").strip() != "0"
    _lancer_ui, _ui_pourquoi = _ui_doit_tourner(
        bool(a.ui_gate), _ONLY, _ui_demande, _ui_auto, bool(a.fast), _ui_auto_permis)
    if not _lancer_ui and (_ui_auto or _ONLY):
        print("\n\033[90m[ui-acceptance] non lance — %s\033[0m" % _ui_pourquoi)
    if _lancer_ui:
        _laf_py, _laf_src = _python_ui()
        _campagne = ROOT / "tools" / "forge_ui_campaign.py"
        if _campagne.exists() and _laf_py:
            name = "ui-acceptance (contrat web_hub :7400)"
            print(f"\n\033[1;36m── {name} ──\033[0m  (bloquant si disponible)")
            cmd = [_laf_py, "tools/forge_ui_campaign.py"]
            e = dict(os.environ)
            e["PYTHONDONTWRITEBYTECODE"] = "1"
            e["PYTHONIOENCODING"] = "utf-8"
            e["LAFORGE_UI_HEADED"] = "0"
            # PASSE DE CLIC ACTIVEE. Mesure 2026-08-26 : la campagne la laisse ETEINTE
            # par defaut (`if LAFORGE_UI_CLICKS == "1" or "--clicks" in sys.argv`), et le
            # gate ne la demandait pas. Le contrat verifiait donc la PRESENCE de textes,
            # jamais qu'un bouton FASSE quelque chose — sur une interface dont l'owner
            # signalait justement qu'« on ne peut rien saisir ».
            # Sans risque : la campagne enumere les controles, ne clique que ceux qu'elle
            # classe SURS et saute les destructifs (mesure : 4 cliques, 6 sautes — Scan
            # ADB, Shell, Screenshot, « Lancer un swarm »... tous ecartes).
            e["LAFORGE_UI_CLICKS"] = "1"
            # ── COFFRE : ce qui manque au login n'est pas un secret, c'est un CHEMIN ──
            # MESURE 2026-09-17. En `--reference`, ROOT est un worktree DETACHE et
            # `data/` est gitignore : `data/machine_vault.dat` y est ABSENT.
            # `forge_secrets` descend alors sa cascade jusqu'a `os.environ`, ne
            # trouve rien, et la campagne rend AUTH_FAILURE — « on a vu le
            # formulaire de login, pas les pages ». Ca se lit comme un defaut de
            # l'INTERFACE alors que c'est un defaut de LOCALISATION du coffre.
            # Exactement le defaut corrige le 2026-09-16 cote runner GitHub, ou
            # `LAFORGE_VAULT_PATH` avait ete pose en variable de depot ; la CI
            # LOCALE, elle, ne le posait toujours pas.
            # On transmet un CHEMIN, jamais une valeur : le coffre est
            # CRYPTPROTECT_LOCAL_MACHINE, donc tout compte de la machine le
            # dechiffre, et l'override est LECTURE SEULE par construction.
            if not e.get("LAFORGE_VAULT_PATH"):
                _cof = _coffre_de_l_installation()
                if _cof:
                    e["LAFORGE_VAULT_PATH"] = str(_cof)
                    print("  \033[90m[ui] coffre : %s\033[0m" % _cof)
                else:
                    print("  \033[33m[ui] coffre INTROUVABLE — le login du gate "
                          "echouera (AUTH_FAILURE). Ce n'est pas un defaut de "
                          "l'interface, c'est un defaut de chemin.\033[0m")
            # Resoudre ne suffit pas : c'est le SOUS-PROCESSUS qui lance le
            # navigateur. On ne surcharge pas un reglage deja pose par l'appelant.
            if not e.get("PLAYWRIGHT_BROWSERS_PATH"):
                _magasin, _magasin_src = _magasin_playwright()
                if _magasin:
                    e["PLAYWRIGHT_BROWSERS_PATH"] = _magasin
                else:
                    print("  \033[90m[ui] magasin de navigateurs introuvable — %s\033[0m"
                          % _magasin_src)
            _t_ui0 = time.time()
            rc = subprocess.run(cmd, cwd=str(ROOT), env=e).returncode
            _emettre_temoin_ui(rc, _t_ui0, _ONLY, _ui_demande)
            if rc == 0:
                print("  → OK (CONFORME — contrats UI valides) (rc=0)")
                results.append((name, True))
            elif rc == 2:
                # TROISIEME ETAT, et il ne vaut PAS un vert. MESURE 2026-08-26 :
                # `results.append((..., True))` faisait passer « je n'ai pas pu regarder »
                # pour « le contrat est tenu » — sur un domaine pourtant declare CRITIQUE
                # (`_DOMAINES_CRITIQUES` contient "ui-acceptance"). L'owner signalait une
                # UI cassee pendant que ce gate affichait vert : il n'avait rien juge.
                # Le mecanisme d'inconclusion existait deja quelques lignes plus haut,
                # dans `_run` ; ce chemin-ci ne l'empruntait simplement pas.
                print("  → UNKNOWN — interface injoignable, contrat NON JUGE (rc=2). "
                      "Ce n'est pas un succes : aucune page n'a ete chargee.")
                _INCONCLUS.append(
                    (name, _gravite_inconclusion(name, a.ui_gate or _ui_demande), None))
                results.append((f"{name} [NON JUGE]", True))
            elif rc == 4:
                # DEGRADE : les routes ont bien ete SERVIES, et elles sont en
                # defaut sur un des quatre signaux que la campagne mesure depuis
                # le 2026-08-29 -- page vide, mot d'erreur rendu, exception JS non
                # benigne, API en 4xx/5xx. Elle les collectait, les imprimait en
                # drapeaux, et les jetait : une page rendant « Traceback » sortait
                # CONFORME, et dix routes sur vingt n'etaient jugees sur rien.
                # OBSERVER AVANT D'ENFORCER, meme discipline que le gate
                # `anatomie` : un gate promu bloquant d'emblee se fait desarmer
                # sur son premier faux positif, et c'est le garde ENTIER qu'on
                # perd, pas seulement son bruit.
                # Mais ce qu'on differe est l'ENFORCEMENT, PAS le signal : la
                # campagne rend un code distinct et un « NON livrable », et le
                # detail par route est imprime tel quel juste au-dessus. Promouvoir
                # ne reecrira rien -- il suffira de lever l'interrupteur, une fois
                # le bruit mesure sur quelques runs reels.
                _degr_bloque = os.environ.get(
                    "LAFORGE_UI_DEGRADE_BLOQUANT", "0").strip() == "1"
                print("  → DEGRADE (rc=4) — des routes ont ete servies "
                      "et sont en defaut : page vide, mot d'erreur rendu, "
                      "exception JS ou API>=400. Detail route par route au-dessus."
                      + ("" if _degr_bloque else
                         " OBSERVATION : ce gate ne fait pas encore rougir ce run "
                         "(LAFORGE_UI_DEGRADE_BLOQUANT=1 pour l'enforcer)."))
                results.append((name, False) if _degr_bloque
                               else (f"{name} [DEGRADE - OBSERVATION]", True))
            elif rc == 5:
                # CINQUIEME ETAT (cliquet du 2026-09-16, soir). Le defaut EXISTE
                # mais ne se reproduit pas a chaque passe : cinq passes de la
                # campagne ont rendu cinq compositions du verdict, et une route
                # est sortie du defaut sans que rien n'ait ete corrige.
                #
                # Il ne devient PAS vert pour autant -- « parfois casse » n'est
                # pas « conforme », et se servir des passes pour faire
                # disparaitre un defaut echangerait un faux rouge contre un faux
                # vert. Ce qui change, c'est ce qu'on DEMANDE ensuite : un
                # defaut stable se corrige sur le champ, un defaut intermittent
                # se documente d'abord (log, horodatage, charge) parce qu'un
                # fait TEMPOREL ne se diagnostique pas sur une lecture unique.
                _int_bloque = os.environ.get(
                    "LAFORGE_UI_INTERMITTENT_BLOQUANT", "0").strip() == "1"
                print("  → INTERMITTENT (rc=5) — des routes sont en defaut sur "
                      "CERTAINES passes seulement ; le taux (k/n) est imprime "
                      "au-dessus. NON livrable, mais a instruire par un LOG "
                      "avant toute correction."
                      + ("" if _int_bloque else
                         " OBSERVATION : ce gate ne fait pas encore rougir ce run "
                         "(LAFORGE_UI_INTERMITTENT_BLOQUANT=1 pour l'enforcer)."))
                results.append((name, False) if _int_bloque
                               else (f"{name} [INTERMITTENT - OBSERVATION]", True))
            elif rc == 3:
                # QUATRIEME ETAT, et c'est le cliquet du 2026-09-16. Distinct du
                # rc=2 : la, le service ne repondait pas ; ici il repond tres bien
                # et c'est le GATE qui n'a pas pu s'authentifier. Les routes ont
                # donc affiche le formulaire de login, pas les pages demandees --
                # ni contrat tenu, ni contrat viole : RIEN n'a ete juge.
                # MESURE qui l'a impose (CI de reference du jour, jobs
                # job_f34603d549ba et job_b334189da2bc) : 17 routes sur 20 dans ce
                # cas, et ce gate a rendu VERT « CONFORME ». La campagne ecrivait
                # pourtant INDISPONIBLE dans son rapport -- mais elle sortait en
                # rc=0, et c'est le rc que ce chemin-ci lit. Un vert avec 17 trous
                # ressemble a un verdict, c'est pire qu'un rouge.
                # Le remede se nomme, parce qu'il n'est PAS celui du rc=2 :
                # reparer le login du gate, pas le service.
                print("  → UNKNOWN — login du gate NON etabli, contrat "
                      "NON JUGE (rc=3). Ce n'est pas un succes : on a vu le "
                      "formulaire de login, pas les pages. Verifier "
                      "LAFORGE_ADMIN_TOKEN et le profil de navigateur.")
                _INCONCLUS.append(
                    (name, _gravite_inconclusion(name, a.ui_gate or _ui_demande), None))
                results.append((f"{name} [NON JUGE]", True))
            elif _ui_auto and not a.ui_gate:
                # OBSERVATION : le contrat est viole, on le DIT en toutes lettres, mais
                # on ne fait pas rougir un run qui ne l'avait pas demande. La promotion
                # en bloquant se decidera sur la mesure du bruit, pas d'avance.
                print("  → VIOLÉ (rc=1) — contrat UI non tenu. OBSERVATION : ce gate "
                      "s'est declenche par auto-detection, il ne bloque pas encore ce "
                      "run. Relancer avec --ui-gate pour un verdict engageant.")
                results.append((f"{name} [OBSERVATION]", True))
            else:
                print("  → FAIL (VIOLÉ — contrat UI non tenu sur interface disponible) (rc=1)")
                results.append((name, False))
        else:
            # TROIS ETATS, PAS DEUX. « A ou B absent » confondait trois causes
            # (script absent · interpreteur absent · HOME etranger) sous un seul mot,
            # et ne nommait AUCUN chemin : indiagnosticable depuis un log de CI.
            if not _campagne.exists():
                _quoi = "tools/forge_ui_campaign.py introuvable (%s)" % _campagne
            else:
                _quoi = "interpreteur du gate UI introuvable — %s" % _laf_src
            print("\n\033[90m[skip] ui-acceptance NON MESURE : %s "
                  "(declenchement : %s)\033[0m" % (_quoi, _ui_pourquoi))

    # ── docker build (WARN) : docker-publish.yml (validation Dockerfile, sans push)
    if a.docker:
        if which("docker") and (ROOT / "docker" / "laforge" / "Dockerfile").exists():
            results.append(_run(
                "docker build",
                ["docker", "build", "-f", "docker/nokido/Dockerfile", "-t", "nokido:ci-local", "."],
                blocking=False))
        else:
            print("\n\033[90m[skip] docker ou docker/nokido/Dockerfile absent\033[0m")

    # ── uv build + twine check (WARN) : release.yml job build
    if a.release_build:
        if which("uv"):
            results.append(_run("uv build", ["uv", "build"], blocking=False))
            dist_files = [str(p) for p in (ROOT / "dist").glob("*")] if (ROOT / "dist").exists() else []
            if which("uvx") and dist_files:
                results.append(_run("twine check", ["uvx", "twine", "check", *dist_files], blocking=False))
        else:
            print("\n\033[90m[skip] uv absent — pip install uv\033[0m")

    # ── build-dist pyarmor (WARN) : ci-selfhosted job build-dist
    if a.build_dist:
        if (ROOT / "tools" / "build_dist.py").exists():
            results.append(_run(
                "build-dist (pyarmor)",
                [PY, "tools/build_dist.py", "--backend", "pyarmor", "--mode", "groups"],
                blocking=False))
        else:
            print("\n\033[90m[skip] tools/build_dist.py absent\033[0m")

    return _summary(results, args=a)


def _verdict_sans_mesure(n_resultats: int, only) -> tuple:
    """(rc, motif) — NE RIEN AVOIR MESURE N'EST PAS UN SUCCES.

    MESURE 2026-09-09 (job_9b956666182d) : `ci_local.py --only ui-acceptance` a rendu
    rc=0 avec un resume VIDE et « Tous les gates bloquants passent ». Zero gate
    execute, zero mesure, verdict de succes -- le gate UI n'avait pas pu demarrer
    (`forge_ui_campaign.py ou python py314 absent`, le compte du job ayant
    HOME=C:/Users/Default). Une generation STABLE a meme ete produite sur ce vide.

    C'est le « vert par absence » que le corps combat partout, fabrique par le
    selecteur lui-meme : branche dans le workflow, le job ui-acceptance serait passe
    au vert SANS JAMAIS tester l'interface.

    On ne se mele PAS du cas sans `--only` : un resume vide y releve d'un autre
    probleme, et ce garde ne doit pas changer le comportement par defaut.
    """
    if only and n_resultats == 0:
        return 2, ("aucun gate n'a produit de mesure sous `--only %s` — nom inconnu, "
                   "ou gate incapable de demarrer dans ce contexte. Un run qui ne "
                   "mesure RIEN ne conclut pas." % ", ".join(only))
    return 0, ""


def _summary(results: list[tuple[str, bool]], partiel: bool = False, args=None) -> int:
    # Les gates ecartes par `--only` ne figurent pas au resume : ils n'ont RIEN
    # mesure, et les afficher en vert dirait le contraire. Ils ne sont pas non plus
    # comptes en echec -- on ne leur a simplement rien demande.
    results = [r for r in results if r and r[0] != _NON_DEMANDE]
    _rc_vide, _motif_vide = _verdict_sans_mesure(len(results), _ONLY)
    if _rc_vide:
        print("\n\033[1;31m═══ AUCUNE MESURE ═══\033[0m")
        print("\033[1;31m  %s\033[0m" % _motif_vide)
        print("\033[90m  Aucune generation n'est capturee sur un run qui n'a rien "
              "mesure.\033[0m")
        return _rc_vide
    print("\n\033[1;36m═══ RÉSUMÉ ═══\033[0m")
    failed = [n for n, ok in results if not ok]
    inconclus = {n for n, _b, _s in _INCONCLUS}
    # LE LIBELLE SERT DE CLE, et c'est ce qui a fait afficher VERT un gate NON JUGE
    # le 2026-09-14. `results` porte des suffixes d'etat que `_INCONCLUS` n'a pas :
    # on apparie donc par CLE normalisee, puis on rajoute les libelles complets
    # correspondants. `_cle_garde` existait deja et n'etait employee qu'a un seul
    # des deux sites -- une primitive juste, appliquee a moitie.
    _cles_inconclues = {_cle_garde(n) for n in inconclus}
    inconclus = inconclus | {n for n, _ok in results
                             if _cle_garde(n) in _cles_inconclues}
    for n, ok in results:
        marque = "❔" if n in inconclus else ("✅" if ok else "❌")
        print(f"  {marque} {n}")
    # Un UNKNOWN n'est JAMAIS un succes : on le nomme, toujours.
    for n, bloquant, suppleant in _INCONCLUS:
        if suppleant:
            print(f"\n\033[1;33m  ❔ {n} : non mesure — supplee par {suppleant}\033[0m")
        else:
            print(f"\n\033[1;33m  ❔ {n} : NON MESURE (aucun supplement declare)\033[0m")
    bloquants_inconclus = [n for n, b, _s in _INCONCLUS if b]

    # Vitalite : ce que ce run vient de mesurer met a jour le cliquet ; ce que
    # PERSONNE ne mesure plus depuis _ANERGIE_JOURS se met a crier.
    jour = date.today().isoformat()
    registre = _maj_vitalite(results, _charger_vitalite(), jour)
    # L'ECRITURE du registre est DIFFEREE apres la capture (2026-09-09) : voir plus
    # bas. Le calcul reste ici, l'affichage d'anergie qui suit en depend.
    anergie = _anergiques(registre, jour)
    if _VITALITE_ETAT != "LU":
        # ABSTENTION. Un registre qu'on n'a pas pu lire ne prouve PAS que les gardes
        # se taisent : il prouve qu'on ne sait pas. Declarer l'anergie ici rendrait
        # la CI rouge sur une absence de mesure DE LA MESURE.
        print("\n\033[1;33m  ⚠ vitalite %s (%s) : anergie NON EVALUEE — un registre "
              "illisible n'est pas un corps sans verdict\033[0m"
              % (_VITALITE_ETAT, _VITALITE_SOURCE or "aucun fichier"))
        anergie = []
    elif _VITALITE_FRAICHEUR != "FRESH" or _VITALITE_PERIMETRE != "FULL":
        # SIGNALER sans bloquer. Un registre STALE ne distingue pas « le garde se
        # tait » de « le registre n'a pas ete rejoue » ; un registre PARTIAL ne
        # couvre pas tous les gardes, donc une absence n'y prouve rien.
        print("\n\033[1;33m  ⚠ vitalite fraicheur=%s perimetre=%s (%s) : anergie "
              "SIGNALEE mais NON BLOQUANTE — FRESH n'est pas COMPLETE\033[0m"
              % (_VITALITE_FRAICHEUR, _VITALITE_PERIMETRE,
                 _VITALITE_SOURCE or "?"))
    for cle, ecart, crit in anergie:
        age = "jamais" if ecart < 0 else f"{ecart} j"
        print(f"\n\033[1;33m  💤 {cle} : ANERGIQUE — aucun verdict réel depuis {age}"
              f"{' (domaine CRITIQUE)' if crit else ''}{_anergie_detail(cle)}\033[0m")
    # Un run partiel (--fast) annonce deja qu'il ne mesure qu'une fraction :
    # il NOMME l'anergie mais ne bloque pas dessus.
    _vit_sur = (_VITALITE_ETAT == "LU" and _VITALITE_FRAICHEUR == "FRESH"
                and _VITALITE_PERIMETRE == "FULL")
    anergie_bloquante = ([c for c, _e, crit in anergie if crit]
                         if (not partiel and _vit_sur) else [])

    if failed:
        print(f"\n\033[1;31m{len(failed)} gate(s) bloquant(s) en échec — NE PAS pousser.\033[0m")
        # A3 : la preuve NEGATIVE existe aussi. Ecrite AVANT le return, elle ne
        # masque pas l'echec originel — elle le NOMME dans un artefact portable.
        _ecrire_ci_proof("NO_CAPTURE",
                         failure_stage="GATE_FAILURE: %d gate(s) bloquant(s)"
                                       % len(failed))
        return 1
    if bloquants_inconclus:
        print(f"\n\033[1;31m{len(bloquants_inconclus)} gate(s) CRITIQUE(S) non mesure(s) : "
              f"{', '.join(bloquants_inconclus)}\n  Une absence de mesure sur un domaine "
              f"critique n'est pas un succes. Installer l'outil, ou declarer son "
              f"suppleant dans _SUPPLEANTS.\033[0m")
        _ecrire_ci_proof("NO_CAPTURE",
                         failure_stage="GATE_NON_MESURE: %s"
                                       % ", ".join(bloquants_inconclus)[:100])
        return 1
    if anergie_bloquante:
        print(f"\n\033[1;31m{len(anergie_bloquante)} gate(s) CRITIQUE(S) ANERGIQUE(S) — "
              f"aucun verdict réel depuis plus de {_ANERGIE_JOURS} j : "
              f"{', '.join(anergie_bloquante)}\n  Un garde qui ne se prononce plus "
              f"n'est pas un garde vert : le relancer, ou le retirer du registre "
              f"({VITALITE.name}) s'il est mort pour de bon.\033[0m")
        _ecrire_ci_proof("NO_CAPTURE",
                         failure_stage="GATE_ANERGIQUE: %s"
                                       % ", ".join(anergie_bloquante)[:100])
        return 1
    # VERDICT VERT -> point de retour restaurable. Un etat qui passe la CI merite
    # de redevenir atteignable sans qu'on ait a re-deduire « quel commit marchait ».
    # Deux precautions : idempotence par sha (relancer la CI sur le meme etat ne
    # cree pas de doublon), et working tree PROPRE (sinon le sha ne represente pas
    # ce qui vient d'etre teste -- capturer la serait mentir sur l'etat mesure).
    _inscrire_generation(results, partiel)

    # ── LE JOURNAL DU RUN VIENT APRES LA MESURE DU CODE (2026-09-09) ────────────
    # `tests/nr/vitalite_gardes.json` est un fichier SUIVI. L'ecrire AVANT
    # `_inscrire_generation` salissait l'arbre que la capture s'apprete a juger : la
    # CI se retirait a elle-meme le droit de capturer son propre sha.
    #
    # Le defaut est reste invisible parce qu'une ACL le masquait : dans l'arbre
    # principal `tests/nr/` n'est pas inscriptible par les comptes sandbox, donc
    # l'ecriture echouait et la mesure partait dans `sandbox/vitalite_en_attente/`
    # (non suivi). L'arbre restait propre PAR ACCIDENT. T0 l'a rendu systematique --
    # le worktree de reference vit sous `sandbox/`, ou `tests/nr/` EST inscriptible :
    # 16 gates verts, 8599 tests sans echec, et « 1 fichier(s) SUIVI(s) modifie(s) —
    # pas de capture » (mesure du 2026-09-09 sur e20ab0182).
    #
    # L'ordre juste decoule du SENS : la generation date le CODE teste, le registre
    # date le RUN. Un instrument ne modifie pas ce qu'il mesure avant de l'avoir
    # mesure. Garde : tests/nr/test_capture_avant_vitalite_nr.py
    _ecrire_vitalite(registre, partiel)

    if inconclus:
        print(f"\n\033[1;32mTous les gates bloquants passent\033[0m "
              f"\033[1;33m({phrase_non_mesures(_INCONCLUS)})\033[0m")
        _fermeture_si_demandee(args, partiel)
        return 0
    _afficher_chrono()
    print("\n\033[1;32mTous les gates bloquants passent.\033[0m")
    _fermeture_si_demandee(args, partiel)
    return 0


def _fermeture_si_demandee(args, partiel: bool) -> None:
    """Enchaine CI verte -> commit. Le refus est TOUJOURS dit, jamais silencieux.

    Ne change PAS le code de retour de la CI : un commit qui echoue ne rend pas rouge
    un run qui etait vert — il le DIT, et l'etat mesure reste l'etat mesure.
    """
    fichiers = [f.strip() for f in (getattr(args, "commit_fichiers", "") or "").split(",")
                if f.strip()]
    sujet = getattr(args, "commit_si_vert", None)
    # `--reference` a `nargs="?"` : sa presence se lit sur `is not None`, jamais sur
    # la verite de la valeur -- `--reference` seul vaut la chaine vide.
    _ref = getattr(args, "reference", None) is not None
    # Relecture du temoin fige au depart : ce qu'on s'apprete a committer est-il
    # encore ce qui a ete mesure ?
    _bouges, _indetermines = fermeture_encore_valide(_EMPREINTES_FERMETURE, ROOT)
    ok, motif = decider_commit(sujet, fichiers, partiel, ROOT, reference=_ref,
                               bouges=_bouges, indetermines=_indetermines)
    if not ok:
        if sujet:  # demandee mais refusee : le motif doit ETRE LU
            print("\033[1;33m[fermeture] pas de commit — %s\033[0m" % motif)
        return
    print("\033[1;36m[fermeture] %s\033[0m" % motif)
    _fermer_par_commit(sujet, fichiers, getattr(args, "commit_corps", None), ROOT)


# Sorties DECLAREES du protocole de preuve. Liste BLANCHE : tout ce qui n'y figure
# pas fait refuser la capture. On ne « ignore » donc rien -- on declare ce que la
# mesure a le droit de produire, et le defaut reste le refus.
SORTIES_DE_PREUVE = (
    "tests/nr/vitalite_gardes.json",   # registre ecrit par _ecrire_vitalite
    "docs/generations/",               # captures ecrites par _inscrire_generation
    "sandbox/",                        # zone de travail : rapports, junit, basetemp
)


def _lire_porcelain(texte: str) -> list:
    """[(statut, chemin)] depuis `git status --porcelain`, renommages resolus."""
    entrees = []
    for ligne in (texte or "").splitlines():
        if len(ligne) < 4:
            continue
        statut, chemin = ligne[:2], ligne[3:].strip().strip('"')
        if " -> " in chemin:            # R  ancien -> nouveau
            chemin = chemin.split(" -> ", 1)[1]
        entrees.append((statut, chemin))
    return entrees


def classer_modification(statut, chemin) -> str:
    """PRODUIT | PREUVE | INATTENDU — la nature d'une entree de `git status`.

    PRODUIT    fichier suivi hors sortie declaree : c'est l'objet mesure, il ne
               bouge pas, sinon le sha ne represente plus ce qui a ete teste.
    PREUVE     sortie declaree du protocole : la mesure a le DROIT de l'ecrire.
    INATTENDU  fichier non suivi hors sortie declaree : on ne sait pas ce que
               c'est, donc on ne capture pas. Ce troisieme etat est ce qui empeche
               de passer de « tout auto-output est rejete » a « tout ce qui
               RESSEMBLE a un output est accepte ».
    """
    c = (chemin or "").replace("\\", "/").lstrip("./")
    for decl in SORTIES_DE_PREUVE:
        if c == decl or (decl.endswith("/") and c.startswith(decl)):
            return "PREUVE"
    return "INATTENDU" if (statut or "").strip() == "??" else "PRODUIT"


def capture_autorisee(entrees) -> tuple:
    """(autorisee, motif) — l'arbre ne porte-t-il QUE des sorties de la mesure ?

    MESURE 2026-09-09 : quatre CI vertes d'affilee n'ont capture aucun sha. Le
    fichier qui salissait l'arbre de reference etait `tests/nr/vitalite_gardes.json`
    -- LE REGISTRE QUE LA CI VENAIT D'ECRIRE. La procedure de preuve prenait ses
    propres sorties pour une alteration adverse :

        elle mesure un SHA dans un worktree detache
          -> elle y ecrit son registre
            -> `git status` n'est plus vide
              -> elle refuse de capturer ce qu'elle vient de mesurer

    Le critere de sortie de la phase 0 -- un statut FERME PAR COMMIT -- etait donc
    INATTEIGNABLE PAR CONSTRUCTION, quel que soit le code teste. Ce n'etait pas un
    arbre mal prepare : c'etait une erreur de definition de l'objet mesure.
    `git status == clean` est incompatible avec une procedure qui produit ses
    preuves dans son propre worktree.

    Le refus NOMME chaque fichier : une borne doit dire COMBIEN et LESQUELS, pas
    seulement TROP.
    """
    classees = [(classer_modification(s, c), c) for s, c in (entrees or [])]
    bloquants = [(nature, c) for nature, c in classees if nature != "PREUVE"]
    if not bloquants:
        return True, ("%d sortie(s) de preuve, aucune modification du produit"
                      % len(classees))
    return False, ("%d modification(s) hors sortie de preuve declaree : %s"
                   % (len(bloquants),
                      ", ".join("%s [%s]" % (c, n) for n, c in bloquants)))


def capture_depuis_worktree(proof_root, target_sha=None, execution_id=None) -> tuple:
    """(autorisee, motif, contexte) — juge un WORKTREE DE PREUVE, pas l'arbre partage.

    POURQUOI (mesure du 2026-09-11) : `capture_autorisee` lit la racine du POSTE.
    Or cette racine est partagee par Claude, AGY, Codex et la veille, et elle porte
    en permanence des dizaines de fichiers non suivis qui n'ont aucun rapport avec
    le code juge — 119 entrees ce jour-la, dont 72 bloquantes. Un agent qui n'avait
    RIEN pousse empechait donc de capturer le sha d'un commit deja publie et vert.

    Le remede n'est pas d'excuser ces fichiers (liste blanche sans fin, et fausse :
    `tests/nr/_socle_capabilites_comptes.json` est un NON SUIVI qui est LU par un
    test, donc un non-suivi PEUT changer un resultat). Le remede est de changer de
    PERIMETRE : ici, ces fichiers n'existent pas.

    LE GARDE N'EST PAS ASSOUPLI, il est deplace. `capture_autorisee` reste le juge,
    a l'identique — seul l'arbre qu'on lui donne change. Un intrus dans le worktree
    de preuve bloque donc toujours, et c'est ce qui distingue un garde repare d'un
    garde desarme.

    TROIS REFUS DISTINCTS, parce qu'ils n'ont pas le meme sens :
      - arbre absent          : on n'a rien a juger ;
      - HEAD != target_sha    : le juge se trompe de SUJET, pire que pas de juge —
                                un verdict serait attribue a un sha jamais mesure ;
      - HEAD attachee         : une branche BOUGE, donc ce n'est pas un etat
                                immuable et la capture promettrait plus qu'elle ne
                                peut tenir.

    `execution_id` n'est pas utilise pour decider : il est porte dans le contexte
    pour que la preuve reste rattachable a QUI l'a produite (l'identite d'execution
    composite est le P1 suivant, pas celui-ci).
    """
    import subprocess as _sp
    racine = Path(proof_root)
    ctx = {"proof_root": str(racine), "target_sha": target_sha,
           "execution_id": execution_id, "head": None, "detached": None}

    if not racine.is_dir():
        return False, "worktree de preuve absent : %s" % racine, ctx

    def _g(args):
        return _sp.run(["git", "-c", "safe.directory=*", *args], cwd=str(racine),
                       capture_output=True, text=True, errors="replace", timeout=60)

    tete = _g(["rev-parse", "HEAD"])
    if tete.returncode != 0:
        return False, ("worktree de preuve illisible par git : %s"
                       % (tete.stderr or "").strip()[:160]), ctx
    ctx["head"] = tete.stdout.strip()
    ctx["detached"] = _g(["symbolic-ref", "-q", "HEAD"]).returncode != 0

    if target_sha and not ctx["head"].startswith(str(target_sha).strip()):
        return False, ("sha juge different du sha demande : worktree sur %s, demande %s"
                       % (ctx["head"][:12], str(target_sha)[:12])), ctx

    if not ctx["detached"]:
        return False, ("HEAD attachee a une branche : une preuve doit porter un etat "
                       "immuable, or une branche bouge (utiliser --detach)"), ctx

    porcelain = _g(["status", "--porcelain"])
    if porcelain.returncode != 0:
        return False, ("git status illisible dans le worktree de preuve : %s"
                       % (porcelain.stderr or "").strip()[:160]), ctx
    entrees = _lire_porcelain(porcelain.stdout)
    ctx["entrees"] = len(entrees)
    ok, motif = capture_autorisee(entrees)
    return ok, motif, ctx


def verdicts_pour_generation(results, inconclus) -> dict:
    """Traduit les verdicts de gate pour la PREUVE. TROIS etats, jamais deux.

    `_run` rend `True` pour un gate qui n'a PAS PU se prononcer. C'est juste pour
    le code de retour -- une absence de mesure n'est pas un echec du CODE -- mais
    ce booleen ECRASE l'information. Sans relire `_INCONCLUS`, la generation
    inscrivait PASS pour un gate qui n'a rien mesure : le resume disait
    honnetement « non mesure, supplee par... » pendant que la PREUVE disait
    « PASS ». Deux representations du meme verdict, et la preuve retenait la plus
    flatteuse.

    `NON_MESURE` n'est pas invente pour l'occasion : `forge_generation` le
    documente depuis toujours ({suite: "PASS"|"FAIL"|"NON_MESURE"}). Le
    certificateur possedait le vocabulaire et ne s'en servait pas -- ce qui est
    pire qu'un format trop pauvre, parce que rien ne le signalait.

    UN SUPPLEANT NE CONVERTIT PAS EN PASS. Un gate supplee reste NON MESURE : le
    suppleant dit qu'on accepte de ne pas mesurer ici et maintenant, pas que la
    mesure a eu lieu. Confondre les deux, c'est exactement ce que cette fonction
    existe pour empecher.

    Fonction PURE, extraite pour etre eprouvable : la version precedente vivait au
    milieu d'une chaine d'entrees-sorties qu'aucun test ne pouvait traverser, et
    c'est pour cela que le defaut a vecu si longtemps. Releve par un audit externe
    le 2026-09-14 sur le sha b3ed1cc50d5c.
    """
    non_mesures = {n for n, _bloquant, _suppleant in (inconclus or [])}
    return {nom: ("NON_MESURE" if nom in non_mesures
                  else ("PASS" if ok else "FAIL"))
            for nom, ok in results}


def _ecrire_ci_proof(process_state, failure_stage=None, ctx=None,
                     target_sha=None, execution_id=None) -> None:
    """A3 — le verdict devient un ARTEFACT PORTABLE, sur TOUS les chemins de sortie.

    Mesure 2026-09-19 : cette fonction n'etait appelee qu'APRES une capture
    reussie, donc jamais sur un run rouge — `main` rend 1 bien avant. Ses NR
    passaient en l'appelant DIRECTEMENT : fausse couverture de production. Sur
    90 executions, ZERO `ci_proof.json` ecrit, y compris pour un run qui avait
    mesure 10 892 tests et nomme trois blocs coupes. Toute cette information ne
    vivait que dans un journal.

    `ctx` est OPTIONNEL et DECLARE PARTIEL : sans capture on ne connait ni
    `observed_head` ni le nombre d'entrees, et c'est precisement ce qu'il faut
    dire plutot que de laisser croire qu'on a mesure le sujet.

    Ne rougit JAMAIS un run et ne masque JAMAIS l'echec originel : si l'ecriture
    echoue, la cause principale reste l'echec de CI et l'on signale a part.
    """
    import os as _os
    ctx = ctx or {}
    target_sha = target_sha or _os.environ.get("NOKIDO_TARGET_SHA")
    execution_id = execution_id or _os.environ.get("NOKIDO_EXECUTION_ID")
    try:
        from forge_ci_proof import (certifie, ecrire, hash_canonique, hash_contrat,
                                    hash_plan, manifeste)
    except ImportError as e:  # muet-ok : dit juste en dessous
        print("\033[33m  [ci-proof] NON ECRIT (%s) — la preuve reste dans le "
              "journal, donc non portable\033[0m" % type(e).__name__)
        return
    # Resolu A L'APPEL, pas fige a l'import : une globale d'import ne voit pas la
    # configuration effective du run. Et AUCUN repli sur le worktree — `PROOF_DIR`
    # existe precisement pour dissocier la preuve de l'arbre juge (defaut 09/09).
    dossier = _os.environ.get("NOKIDO_PROOF_DIR") or _PROOF_DIR
    if not dossier:
        print("\033[33m  [ci-proof] NON ECRIT : aucun repertoire de preuve "
              "(NOKIDO_PROOF_DIR absent) — on ne replie PAS sur l'arbre juge\033[0m")
        return
    contrat, illisibles = hash_contrat([ROOT / c for c in _CONTRAT_CI])
    # B2 : le lock dit ce qui est REQUIS, la reconciliation dit si l'environnement
    # y correspond. Sans elle, `dependency_lock_hash` affirmerait quelque chose
    # sur un FICHIER. Avec un laforge_py314 PERMANENT partage avec le hub vivant,
    # c'est exactement l'ecart a mesurer.
    _lock_hash, _match = None, None
    try:
        from forge_ci_lock import fermeture, hash_lock, lire_lock, reconcilier
        _lock, _motif_lock = lire_lock(ROOT / "requirements-ci.lock")
        if _lock is None:
            _match = "ILLISIBLE"
            print("\033[33m  [ci-lock] %s — environnement NON reconcilie\033[0m"
                  % _motif_lock)
        else:
            _lock_hash = hash_lock(_lock)
            _match, _det = reconcilier(_lock, fermeture()["paquets"])
            print("\033[90m  [ci-lock] %s — %d attendu(s), %d ecart(s), %d "
                  "manquant(s), %d hors lock\033[0m"
                  % (_match, _det["attendus"], len(_det["ecarts"]),
                     len(_det["manquants"]), len(_det["hors_lock"])))
            for _n, _d in sorted(_det["ecarts"].items())[:8]:
                print("\033[33m     ECART %-26s lock=%-12s installe=%s\033[0m"
                      % (_n, _d["lock"], _d["installe"]))
    except ImportError as _el:  # muet-ok : dit juste au-dessus/au-dessous
        _match = "ILLISIBLE"
        print("\033[33m  [ci-lock] INDISPONIBLE (%s) — environnement NON "
              "reconcilie\033[0m" % type(_el).__name__)
    # Liste BLANCHE prise chez le producteur du vocabulaire, jamais recopiee :
    # une copie en dur ecrasait `SUITE_PARTIELLE` (produit par `--impacte`) en
    # `NON_CERTIFIANT`, confondant « on a choisi de ne jouer qu'un sous-ensemble »
    # avec « on n'a pas pu mesurer ». Une valeur inconnue tombe bien du cote non
    # certifiant : c'est la liste blanche qui le garantit, pas une enumeration.
    from forge_ci_proof import CERTIFICATION_STATES as _ETATS_CERT
    _cert_state = _ETAT_SUITE if _ETAT_SUITE in _ETATS_CERT else "NON_CERTIFIANT"
    if process_state != "CAPTURED":
        # Une suite « complete » sans capture ne certifie rien : l'etat de preuve
        # prime sur l'etat de test, et la contradiction serait declaree sinon.
        _cert_state = "NON_CERTIFIANT" if _cert_state == "SUITE_COMPLETE" else _cert_state
    m = manifeste(
        target_sha=target_sha,
        observed_head=ctx.get("head"),
        process_state=process_state,
        certification_state=_cert_state,
        failure_stage=failure_stage,
        test_plan_hash=hash_plan(PURE_TESTS, BLOCS_ISOLES),
        ci_contract_hash=contrat,
        # A2 : l'empreinte d'environnement REJOINT la preuve. Elle existait et
        # n'etait qu'imprimee — un contexte affiche puis perdu ne permet pas de
        # comparer deux verdicts du meme sha.
        environment_fingerprint=hash_canonique(empreinte_contexte()),
        proof_root=ctx.get("proof_root"), execution_id=execution_id,
        dependency_lock_hash=_lock_hash, dependency_match=_match,
        contrat_illisible=illisibles,
        # D : la telemetrie VOYAGE avec la preuve. Un journal affiche puis perdu
        # ne permet pas de comparer deux runs du meme sha — c'est exactement ce
        # qui manquait pour attribuer les 3 timeouts sur 4 runs.
        extra={"telemetrie": list(_TELEMETRIE)} if _TELEMETRIE else None)
    cible = Path(dossier) / "ci_proof.json"
    ok, motif = ecrire(cible, m)
    if not ok:
        print("\033[33m  [ci-proof] NON ECRIT (%s)\033[0m" % motif)
        return
    _cert, _pourquoi = certifie(m)
    print("\033[90m  [ci-proof] %s — %s/%s plan=%s contrat=%s env=%s%s\033[0m"
          % (cible.name, m["process_state"], m["certification_state"],
             m["test_plan_hash"][:12], m["ci_contract_hash"][:12],
             m["environment_fingerprint"][:12],
             "" if _cert else " — NON CERTIFIANT : %s" % _pourquoi))
    for _i in m.get("incoherences") or []:
        print("\033[33m     INCOHERENCE : %s\033[0m" % _i)
    if m["non_couvert"]:
        print("\033[90m     non couvert : %s\033[0m" % ", ".join(m["non_couvert"]))


def _inscrire_generation(results, partiel: bool, proof_root=None, target_sha=None,
                         tests_root=None) -> None:
    """Inscrit une generation depuis les verdicts de gate, best-effort.

    Ne bloque JAMAIS la CI : une capture qui echoue ne doit pas rougir un run vert.
    Un run partiel (--fast) ne mesure qu'une fraction : il ne pretend pas au STABLE,
    donc on ne capture pas -- une reference batie sur une mesure partielle est un
    faux point sûr.

    ETAPE 4 (2026-09-11) — LE JUGE REGARDE LE BON ARBRE. Jusqu'ici cette fonction
    lisait la racine du POSTE, partagee par Claude, AGY, Codex et la veille. Le
    worktree de preuve existait (P0, commit b8c2c9336) et la capacite de le juger
    aussi (phase 3, 241825864), mais rien ne les CONSOMMAIT : un mecanisme present
    et non cable est une dette de cablage, jamais une securite.

    AUCUN REPLI SUR LA RACINE PARTAGEE. Sans `proof_root`, on ne capture pas et on
    le DIT (`PROOF_ROOT_MISSING`). Un repli silencieux serait le vrai danger :
    il rendrait un verdict certifiant depuis l'arbre partage sans que personne ne
    le voie. Mesure du 2026-09-11 : avec le juge espionne et les 70 bloquants
    neutralises, l'ancien chemin allait jusqu'a inscrire GEN-00013 -- seule une ACL
    l'a arrete. Le faux vert etait donc ATTEIGNABLE, pas theorique.

    ET ON NE CERTIFIE PAS UN ARBRE OU RIEN N'A TOURNE. Tant que les tests
    s'executent ailleurs que dans le worktree juge (c'est le cas aujourd'hui :
    l'execution dans le proof est la phase 7), capturer un sha depuis un arbre
    propre serait PIRE que le blocage actuel -- la CI certifierait un etat qui n'a
    jamais vu passer un test. L'ecart est donc nomme (`TESTS_HORS_PROOF`) au lieu
    d'etre capture.
    """
    if partiel:
        # Un run partiel ne pretend pas au STABLE, mais il laisse une trace : sans
        # elle, « pas de fichier » signifierait a la fois « --fast » et « rien n'a
        # tourne ». La regle « tout chemin de sortie ecrit sa preuve » n'a ainsi
        # AUCUNE exception — et une regle sans exception est un garde plus fort.
        _ecrire_ci_proof("NO_CAPTURE", failure_stage="PARTIAL_RUN: --fast ne "
                         "mesure qu'une fraction, il ne pretend pas certifier")
        return
    try:
        import os as _os

        _proof = proof_root or _os.environ.get("NOKIDO_PROOF_WORKTREE")
        _sha = target_sha or _os.environ.get("NOKIDO_TARGET_SHA")
        _tests = Path(tests_root) if tests_root else ROOT

        if not _proof:
            print("\033[90m  [generation] pas de capture — PROOF_ROOT_MISSING : le juge "
                  "exige un worktree de preuve explicite (NOKIDO_PROOF_WORKTREE), il ne "
                  "retombe jamais sur l'arbre de travail partage\033[0m")
            _ecrire_ci_proof("NO_CAPTURE", failure_stage="PROOF_SETUP_FAILURE: "
                             "NOKIDO_PROOF_WORKTREE absent")
            return

        if Path(_proof).resolve() != _tests.resolve():
            print("\033[33m  [generation] pas de capture — TESTS_HORS_PROOF : les tests ont "
                  "tourne dans %s alors que l'arbre a juger est %s ; certifier un arbre ou "
                  "rien n'a ete execute serait un faux vert\033[0m" % (_tests, _proof))
            _ecrire_ci_proof("NO_CAPTURE", failure_stage="TESTS_HORS_PROOF",
                             target_sha=_sha)
            return

        _ok_capture, _motif_capture, _ctx = capture_depuis_worktree(
            _proof, target_sha=_sha, execution_id=_os.environ.get("NOKIDO_EXECUTION_ID"))
        if not _ok_capture:
            print("\033[90m  [generation] pas de capture — %s\033[0m" % _motif_capture)
            # La preuve NEGATIVE est ecrite : un refus d'identite n'est pas un
            # echec de test, et l'absence d'artefact ne doit plus servir a
            # representer l'echec quand le contrat est de le CONSERVER.
            _ecrire_ci_proof("CAPTURE_REFUSED", failure_stage=_motif_capture[:120],
                             ctx=_ctx, target_sha=_sha,
                             execution_id=_os.environ.get("NOKIDO_EXECUTION_ID"))
            return
        # Une borne doit dire COMBIEN, pas seulement TROP : ce que la trace n'inclut
        # pas est imprime avec la capture.
        _hors = int(_ctx.get("entrees") or 0)
        _ecrire_ci_proof("CAPTURED", ctx=_ctx, target_sha=_sha,
                         execution_id=_os.environ.get("NOKIDO_EXECUTION_ID"))
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_generation as _gen

        tests = verdicts_pour_generation(results, _INCONCLUS)
        # CAPACITES MESUREES (2026-10-01) : sans elles, une generation ne peut plus se dire
        # meilleure (fitness par capacite, d2ffaf64a). Mesure : forge_bench_beir --capacite.
        r = _gen.capturer_si_absent(tests=tests, capacites=_gen.capacites_mesurees(), agent="CI_LOCAL",
                                    note="capture auto au verdict vert de ci_local")
        if r.get("skip"):
            print(f"\033[90m  [generation] etat deja capture ({r['skip']})\033[0m")
        elif r.get("inscription_differee"):
            # MESUREE mais NON INSCRITE. Ne jamais afficher ce cas comme un succes :
            # l'ACL est une raison legitime de differer, pas de mentir.
            _d = r["inscription_differee"]
            print("\033[33m  [generation] %s MESUREE mais NON INSCRITE — %s\033[0m"
                  % (r["generation"], _d["motif"]))
            print("\033[90m     cible refusee  : %s\033[0m" % _d["cible"])
            print("\033[90m     mesure deposee : %s\033[0m" % _d["depot"])
            print("\033[90m     inscription = chemin gouverne, puis RELECTURE du "
                  "fichier cible pour conclure (jamais l'absence d'erreur)\033[0m")
        else:
            if _hors:
                # « non suivie(s) » n'est pas un detail de style : ces entrees sont
                # tolerees PARCE QUE ce sont des sorties declarees, mais elles ne
                # sont dans AUCUN commit. Une borne dit COMBIEN et de QUOI, sinon la
                # trace ne dit pas ce qu'elle n'inclut pas.
                print("\033[90m  [generation] %d entree(s) non suivie(s) toleree(s) dans "
                      "l'arbre juge (sorties declarees, dans aucun commit)\033[0m" % _hors)
            print(f"\033[1;32m  [generation] {r['generation']} inscrite "
                  f"({r['statut']})\033[0m")
    except Exception as _e:  # noqa: BLE001 - la capture ne rougit jamais un run vert
        # Le TYPE seul ne dit pas ce qui etait inaccessible : trois runs de suite ont
        # repete « PermissionError » sans jamais nommer le fichier refuse. Un echec
        # se NOMME -- type, chemin, errno -- sinon il faut le re-instruire a chaque
        # fois. Chemin d'erreur muet, paye le 2026-09-07.
        _det = [type(_e).__name__]
        for _champ in ("filename", "errno", "strerror"):
            _v = getattr(_e, _champ, None)
            if _v:
                _det.append("%s=%s" % (_champ, _v))
        if len(_det) == 1:
            _det.append(str(_e)[:160])
        print("\033[90m  [generation] capture ignoree (%s)\033[0m" % " ".join(_det))


if __name__ == "__main__":
    raise SystemExit(main())
