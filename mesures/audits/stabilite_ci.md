# Audit — stabilite de la CI (timeouts, collecte)

Brief « session cloud B », 2026-09-29. Branche `claude/ci-stabilite`, creee depuis `alpha` a
`ea3c441`. Environnement cloud **Linux** (pas Windows) : voir « Limites » en fin de document.

## Resume

- **158 fichiers de test a risque avere n'avaient aucune marque timeout > 30 s** -- 130 dans
  `PURE_TESTS`, 2 dans `BLOCS_ISOLES`, 26 hors suite. Tous portent desormais
  `pytestmark = pytest.mark.timeout(120)` et un commentaire qui nomme le risque et sa preuve.
  Des trois temoins du brief, deux etaient deja marques ; `test_prefect_manager_appel_vivant_nr`
  (rglob de `app/`) ne l'etait pas -- il l'est.
- **La collecte de la suite pure coute ~4 minutes a cause de la FORME de l'appel, pas des
  imports** : `ci_local` passe ~900 fichiers en arguments, et pytest re-parcourt le paquet
  `tests/nr` entier (~2 200 entrees) pour CHAQUE argument. Meme liste par un seul argument
  filtre : ~10 s au lieu de ~240 s (Linux ; Windows ajoute deux `stat` par comparaison).
  C'est tres probablement la plus grosse part des 6 a 9 minutes constatees sous Windows (non
  mesure la-bas). Proposition en 2.1, non appliquee.
- Les imports ne pesent que ~5,4 s ; le premier poste est **torch** (1,9 s), tire au niveau
  module par `forge_mcp_registry` -> `forge_spike_router`.

## Methode

**Recensement.** Balayage AST des 2 397 fichiers `tests/**/test_*.py` (et `*_test.py`) pour
quatre familles de risque : (a) vrai sous-processus, (b) parcours du depot, (c) SQLite avec un
timeout de connexion >= 30 s, (d) reseau reel -- dans le test, une fixture, ou le code appele
quand c'est direct. 344 candidats, puis **lecture de chacun** : 167 risques averes, 177 ecartes
(mock ou faux `Popen`, `subprocess` dans une docstring, parcours de `tmp_path`...). 9 averes
etaient deja marques (> 30 s) ; les 158 autres ont recu la marque.

**Controles avant commit** (au-dela de la lecture) :

- pour chacun des 158, la ligne citee en preuve a ete relue : c'est bien l'appel risque, ou
  l'appel au code qui le fait ; les 15 fichiers qui contiennent un mock ont ete relus un a un
  (le mock ne couvre qu'une partie des tests, un autre test fait le vrai appel) ; des risques
  « code appele » verifies dans le code (`anchor_solution` -> `sqlite3.connect(timeout=30)`,
  `ci_local._sha_courant` -> `git rev-parse`, `forge_postal._conn` -> `timeout=30`...) ;
- **par pytest lui-meme** : un greffon releve la marque timeout effective de chaque test
  collecte, avant (`alpha`) et apres. Collecte identique (1 469 tests, memes 4 erreurs
  d'environnement cloud) ; dans les 153 fichiers collectables ici, **chaque test porte
  timeout=120** (aucune marque avant). Les 5 autres (dependances absentes du cloud) sont
  verifies par AST : `import pytest` lie avant le dernier `pytestmark`, qui contient
  `timeout(120)` ;
- les 9 tests qui lisent d'autres fichiers de test (cliquet de la suite pure, cliquet des
  docstrings, detecteurs...) rendent le meme resultat avant/apres (90 passes).

**Forme de la marque** (ajouts seulement, 758 lignes, aucune suppression) :

    # Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.34)
    # Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
    pytestmark = pytest.mark.timeout(120)

`import pytest` a ete ajoute la ou il manquait au niveau module (63 fichiers, dont 3 qui ne
l'importaient que dans une fonction). Un fichier portait deja un `pytestmark` (un `skipif`) :
la marque s'y ajoute par `pytestmark = [pytestmark, pytest.mark.timeout(120)]`, sans modifier
la ligne existante. Les marques par fonction plus basses, s'il en existe, restent prioritaires
(pytest-timeout lit la marque la plus proche).


## 1. Tests a risque (167 averes, dont 9 deja marques)

Colonnes : `a` sous-processus reel, `b` parcours du depot, `c` SQLite a timeout de connexion >= 30 s, `d` reseau reel. « code appele » : l'action risquee est dans le code que le test appelle. Preuve : ligne relevee a la lecture.

| fichier | suite | nature du risque | preuve | marque ajoutee |
|---|---|---|---|---|
| `tests/nr/test_AB4_garde_injection_mord_nr.py` | PURE | b : rglob app+tools + lecture | test_AB4_garde_injection_mord_nr.py:164 (RACINE / d).rglob('*.py') pour d in ('app','tools') + read_text (~2300) | oui (+ `import pytest`) |
| `tests/nr/test_a2a_tier1_nr.py` | PURE | b : parcours tests/nr (code appele); a : subprocess git (code appele) | test_a2a_tier1_nr.py:133 card.etats() -> tools/forge_a2a_card.py:66 nr.glob('*.py') + read_text de ~2200 NR par capacite ; :174 git rev-parse | oui |
| `tests/nr/test_acces_ssh_au_coffre_nr.py` | PURE | b : rglob app + lecture | test_acces_ssh_au_coffre_nr.py:147 (RACINE / 'app').rglob('*.py') puis read_text de chaque fichier (1224) | oui (+ `import pytest`) |
| `tests/nr/test_acp_authenticate_sans_ceremonie_nr.py` | PURE | a : subprocess python | test_acp_authenticate_sans_ceremonie_nr.py:54 subprocess.run([sys.executable, SERVEUR, '--echo'], timeout=25) | oui |
| `tests/nr/test_acp_session_e2e_nr.py` | PURE | d : reseau localhost reel | test_acp_session_e2e_nr.py:48 socket.create_connection(('127.0.0.1', 7782), timeout=8) ; :35 connect timeout 1.5 | oui |
| `tests/nr/test_acp_toolcallid_canonique_nr.py` | PURE | a : subprocess python | test_acp_toolcallid_canonique_nr.py:60 subprocess.Popen([sys.executable, SERVEUR, '--echo']) | oui |
| `tests/nr/test_ancrage_sans_redite_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_ancrage_sans_redite_nr.py:127 35x SC.anchor_solution -> app/forge_self_correction.py:629 sqlite3.connect(timeout=30.0) | oui |
| `tests/nr/test_archeologie_outils_nr.py` | PURE | a : subprocess git | test_archeologie_outils_nr.py:67 subprocess.run(['git', '-C', d, ...], timeout=60) (depot tmp) | oui |
| `tests/nr/test_aucun_executable_hors_depot_nr.py` | PURE | b : rglob app+tools + lecture + ast | test_aucun_executable_hors_depot_nr.py:66 (ROOT / dossier).rglob('*.py') + read_text + ast.parse (~2300) | oui (+ `import pytest`) |
| `tests/nr/test_aucun_outil_ne_contourne_les_hooks_git_nr.py` | PURE | b : subprocess git ls-files; b : rglob app+tools (repli) | test_aucun_outil_ne_contourne_les_hooks_git_nr.py:34 subprocess.run(['git','ls-files','--','app','tools']) puis lecture des ~2300 .py ; :40 repli rglob | oui (+ `import pytest`) |
| `tests/nr/test_audit_copies_hors_depot_nr.py` | PURE | b : os.walk racine (code appele) | test_audit_copies_hors_depot_nr.py:147 A._index_depot() -> tools/forge_audit_copies_hors_depot.py:122 os.walk(ROOT) | oui (+ `import pytest`) |
| `tests/nr/test_audit_findings_conformes_au_skill_nr.py` | PURE | a : subprocess node (code appele) | test_audit_findings_conformes_au_skill_nr.py:99 V.recenser() -> tools/forge_audit_findings_validate.py:111 subprocess node par run d'audit | oui |
| `tests/nr/test_audit_ingestion_reprise_nr.py` | PURE | c : sqlite timeout=30 (verrou reel) | test_audit_ingestion_reprise_nr.py:109 sqlite3.connect(base, timeout=30) + BEGIN IMMEDIATE tenu par un thread voisin | oui |
| `tests/nr/test_await_async_nr.py` | PURE | b : lecture de tous les app/*.py | test_await_async_nr.py:51 APP_DIR.glob('*.py') (626 fichiers) lus et parses | oui |
| `tests/nr/test_balayeurs_lisent_le_producteur_nr.py` | PURE | b : os.walk racine (code appele) | test_balayeurs_lisent_le_producteur_nr.py:93 P.measure_storage() -> app/forge_proprioception.py:273 os.walk(ROOT) (elague) | oui |
| `tests/nr/test_bash_guard_substitution_nr.py` | PURE | a : subprocess python | test_bash_guard_substitution_nr.py:39 subprocess.run([sys.executable, _HOOK], timeout=60) | oui (fusion avec le `pytestmark` existant) |
| `tests/nr/test_bisect_nr.py` | PURE | a : subprocess python | test_bisect_nr.py:274 subprocess.run([sys.executable, '-c', programme], timeout=180) | oui |
| `tests/nr/test_budget_chaine_ne_solde_pas_le_travail_nr.py` | PURE | c : sqlite timeout=30 + busy_timeout=30000 sur la VRAIE base (code appele) | test_budget_chaine_ne_solde_pas_le_travail_nr.py:86 ChainExecutor() -> app/forge_chain_executor.py:73 sqlite3.connect(DB reel, timeout=30) + PRAGMA busy_timeout=30000 | oui (+ `import pytest`) |
| `tests/nr/test_callgraph_ambiguite_nr.py` | PURE | a : subprocess rg (code appele) | test_callgraph_ambiguite_nr.py:109 jit.callers('speak') -> app/forge_callgraph_jit.py:71 subprocess.run(['rg', ...], timeout=20) | oui |
| `tests/nr/test_capability_lineage_nr.py` | PURE | a : subprocess git (code appele) | test_capability_lineage_nr.py:57 L.analyser({'faux': tmp}) -> tools/forge_capability_lineage.py:76 subprocess.Popen(['git', ..., 'log', '--all']) | oui (+ `import pytest`) |
| `tests/nr/test_capture_sur_worktree_de_preuve_nr.py` | PURE | a : subprocess git | test_capture_sur_worktree_de_preuve_nr.py:44 subprocess.run(['git', ...], timeout=180) (fixture atelier, 7 tests) | oui |
| `tests/nr/test_changelog_nr.py` | PURE | a : subprocess git | test_changelog_nr.py:45 subprocess.run(['git', '-C', d, ...]) sans timeout | oui (+ `import pytest`) |
| `tests/nr/test_ci_bloc_isole_chemin_reel_nr.py` | PURE | a : subprocess pytest (python) | test_ci_bloc_isole_chemin_reel_nr.py:102 subprocess.run([sys.executable,'-m','pytest',...], timeout=240) | oui |
| `tests/nr/test_ci_debug_tools_nr.py` | PURE | a : subprocess git | test_ci_debug_tools_nr.py:56 subprocess.run(['git', ...]) sans timeout (depot tmp) | oui (+ `import pytest`) |
| `tests/nr/test_ci_gate_borne_duree_nr.py` | PURE | a : subprocess python (via ci_local._run) | test_ci_gate_borne_duree_nr.py:54 ci._run('gate_qui_pend', [sys.executable, '-c', 'time.sleep(30)'], timeout_s=1.5) | oui (+ `import pytest`) |
| `tests/nr/test_ci_selection_partielle_nr.py` | PURE | a : subprocess python | test_ci_selection_partielle_nr.py:164 subprocess.run([sys.executable, 'tools/ci_local.py', '--help'], timeout=180) | oui (+ `import pytest`) |
| `tests/nr/test_constituent_archaeology_nr.py` | PURE | a : subprocess git (code appele) | test_constituent_archaeology_nr.py:136 A.analyser({'faux': tmp_path}) -> tools/forge_constituent_archaeology.py:205 subprocess.Popen(['git', ..., 'log', '--all', '-U0']) | oui (+ `import pytest`) |
| `tests/nr/test_contrat_credential_routes_forge_nr.py` | PURE | b : rglob tests + lecture | test_contrat_credential_routes_forge_nr.py:241 (_RACINE / 'tests').rglob('test_*.py') + read_text (2397 fichiers) | oui |
| `tests/nr/test_conversation_log_jamais_purge_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_conversation_log_jamais_purge_nr.py:59 lr._surveiller_conversation_log() -> tools/forge_log_retention.py:1770 sqlite3.connect(DB, timeout=30) | non (deja : `l.29 pytestmark = pytest.mark.timeout(120)`) |
| `tests/nr/test_crawl_profondeur_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_crawl_profondeur_nr.py:74 ce.ChainExecutor(db_path=tmp) -> app/forge_chain_executor.py:73 sqlite3.connect(timeout=30) + busy_timeout=30000 | oui (+ `import pytest`) |
| `tests/nr/test_cve_ingest_nvd11_gele_nr.py` | PURE | a : subprocess python | test_cve_ingest_nvd11_gele_nr.py:59 subprocess.run([sys.executable, '-c', code], timeout=60) | oui |
| `tests/nr/test_cycle_verdict_nr.py` | PURE | a : subprocess python -m pylint (code appele) | test_cycle_verdict_nr.py:201 fcv.scorecard([...]) -> app/forge_scorecard.py:409 subprocess.run([sys.executable, '-m', 'pylint', ...], timeout=20) | oui (+ `import pytest`) |
| `tests/nr/test_decisions_de_chemin_sur_scope_nr.py` | PURE | b : lecture de tous les .py de app/, app/web_hub, tools/ | test_decisions_de_chemin_sur_scope_nr.py:32 (RACINE / d).glob('*.py') + read_text pour app, app/web_hub, tools (~1750) | oui (+ `import pytest`) |
| `tests/nr/test_deserialisation_gouvernee_nr.py` | PURE | b : lecture + ast de app/, tools/, web_hub | test_deserialisation_gouvernee_nr.py:53 glob.glob(RACINE/sub/'*.py') + ast.parse (~1750 fichiers, 3 tests) | oui |
| `tests/nr/test_detecteurs_detectent_nr.py` | PURE | b : glob tests/nr + lecture | test_detecteurs_detectent_nr.py:155 dossier.glob('test_*_nr.py') + read_text (~2190 fichiers) | oui |
| `tests/nr/test_edge_node_durci_nr.py` | PURE | a : subprocess python (serveur); d : reseau localhost | test_edge_node_durci_nr.py:62 subprocess.Popen([sys.executable, script, '--serve', ...]) puis attente jusqu'a 15 s ; :83 HTTPConnection timeout=10 | oui |
| `tests/nr/test_epistemic_schema_absent_nr.py` | PURE (isole) | c : sqlite timeout=30 (code appele) | test_epistemic_schema_absent_nr.py:49 ep._conflicts_top() -> app/web_hub/epistemic.py:56 sqlite3.connect(timeout=30) | oui |
| `tests/nr/test_epistemique_emetteurs_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_epistemique_emetteurs_nr.py:197 consol.consolider(db_path=base) -> tools/forge_epistemic_extract_claims.py:267 sqlite3.connect(timeout=30) | oui |
| `tests/nr/test_esoleau_empreintes_nr.py` | PURE | a : subprocess git | test_esoleau_empreintes_nr.py:34 subprocess.run(['git', ...], check=True) sans timeout | oui (+ `import pytest`) |
| `tests/nr/test_exec_dynamique_orphelins_nr.py` | PURE | b : lecture de app/, tools/, web_hub | test_exec_dynamique_orphelins_nr.py:49 glob.glob(RACINE/sub/'*.py') puis lecture/parse (~1750) | oui |
| `tests/nr/test_facade_web_service_gelee_nr.py` | PURE | b : lecture + ast de app/, tools/, web_hub | test_facade_web_service_gelee_nr.py:43 glob.glob(RACINE/sub/'*.py') + ast.parse (~1750) | oui |
| `tests/nr/test_forge_dynamique_confinement_nr.py` | PURE | b : subprocess git ls-files | test_forge_dynamique_confinement_nr.py:157 subprocess.run(['git','-C',ROOT,'ls-files','app/forge_tools_dynamic/'], timeout=60) | oui (+ `import pytest`) |
| `tests/nr/test_forge_hooks_install.py` | PURE | a : subprocess git (code appele) | test_forge_hooks_install.py:46 fhi.etat(tmp, sys.executable) -> tools/forge_hooks_install.py:47 subprocess.run(['git','-C',ROOT,'config','--get','core.hooksPath'], timeout=30) | oui |
| `tests/nr/test_forge_public_mirror_nr.py` | PURE | a : subprocess git (code appele) | test_forge_public_mirror_nr.py:53 fpm.construire('branche-qui-n-existe-pas') -> tools/forge_public_mirror.py:414 _git('rev-parse', ...) -> l.197 subprocess.run(['git', '-C', ROOT, ...], timeout=600) | oui (+ `import pytest`) |
| `tests/nr/test_free_tier_census_importe_ses_cles_nr.py` | PURE | a : subprocess python | test_free_tier_census_importe_ses_cles_nr.py:30 subprocess.run([sys.executable, '-c', code], timeout=60) | oui (+ `import pytest`) |
| `tests/nr/test_fts_jamais_purge_par_colonne_unindexed_nr.py` | PURE | b : rglob app+tools + ast | test_fts_jamais_purge_par_colonne_unindexed_nr.py:47 (RACINE / zone).rglob('*.py') + ast.parse (ZONES = app, tools) | oui (+ `import pytest`) |
| `tests/nr/test_fts_rattrapage_incremental_nr.py` | PURE | c : sqlite timeout=30 (doublure) | test_fts_rattrapage_incremental_nr.py:71 open_writer -> sqlite3.connect(chemin, timeout=30.0 par defaut) | oui |
| `tests/nr/test_fts_triggers_source_unique_nr.py` | PURE | c : sqlite timeout=30 (doublure) | test_fts_triggers_source_unique_nr.py:54 open_writer -> sqlite3.connect(chemin, timeout=30.0 par defaut) | oui |
| `tests/nr/test_functional_coverage_nr.py` | hors suite | c : sqlite timeout=30 sur la VRAIE base (code appele); b : glob app (code appele) | test_functional_coverage_nr.py:260 anchor_error(...) -> app/forge_self_correction.py:487 sqlite3.connect(timeout=30.0) sans isolation de la base | oui |
| `tests/nr/test_gabarits_prompt_format_nr.py` | PURE | b : lecture de tous les app/*.py et tools/*.py | test_gabarits_prompt_format_nr.py:51 (RACINE / d).glob('*.py') + read_text (~1700) | oui (+ `import pytest`) |
| `tests/nr/test_gain_indecidable_nr.py` | PURE | a : subprocess git (code appele) | test_gain_indecidable_nr.py:106 MJ.juger_module_avec_gain(...) -> patron_sain -> app/forge_mutation_judge.py:172 git show HEAD:... (timeout=30) | oui (+ `import pytest`) |
| `tests/nr/test_garde_python_parite_shell_nr.py` | PURE | a : subprocess python | test_garde_python_parite_shell_nr.py:37 subprocess.run([sys.executable, script], timeout=120) | oui (+ `import pytest`) |
| `tests/nr/test_gardes_mordent_nr.py` | PURE | b : glob tests/nr + lecture | test_gardes_mordent_nr.py:159 dossier.glob('test_*_nr.py') + read_text (~2190 fichiers) | oui |
| `tests/nr/test_generation_differee_reinjecte_nr.py` | PURE | a : subprocess git (code appele) | test_generation_differee_reinjecte_nr.py:71 fg.capturer() -> app/forge_generation.py:102 subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30) + importlib.metadata de toutes les distribu… | oui |
| `tests/nr/test_heartbeat_amorce_syspath_nr.py` | PURE | b : lecture de tous les tools/*.py | test_heartbeat_amorce_syspath_nr.py:62 (ROOT / 'tools').glob('*.py') + read_text + ast.parse (1090 fichiers) | oui (+ `import pytest`) |
| `tests/nr/test_hook_instructions_loaded_nr.py` | PURE | a : subprocess python | test_hook_instructions_loaded_nr.py:26 subprocess.run([sys.executable, SCRIPT], timeout=60) | oui (+ `import pytest`) |
| `tests/nr/test_hub_erreur_distincte_du_vide_nr.py` | PURE | a : subprocess node | test_hub_erreur_distincte_du_vide_nr.py:162 subprocess.run([node, '--check', BUNDLE], timeout=60) | oui |
| `tests/nr/test_hub_l.py` | BLOCS_ISOLES | a : subprocess python | test_hub_l.py:110 subprocess.run([sys.executable, 'tools/nokido.py', ...], timeout=15) | oui |
| `tests/nr/test_hub_launcher.py` | PURE (isole) | a : subprocess python (code appele) | test_hub_launcher.py:126 asyncio.run(lm.start(mod)) -> app/web_hub/launcher.py:392 subprocess.Popen(cmd) (script dummy, fixture l.64) | oui |
| `tests/nr/test_hub_n.py` | BLOCS_ISOLES | a : subprocess python (hub uvicorn); d : reseau localhost | test_hub_n.py:255 subprocess.Popen([sys.executable, 'tools/nokido_web_hub.py', '--port', port]) ; :275 httpx.Client vers ce hub | oui |
| `tests/nr/test_hub_nr.py` | hors suite | d : reseau localhost reel (:8766) | test_hub_nr.py:242 urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5) | oui |
| `tests/nr/test_import_all_nr.py` | hors suite | a : subprocess python x ~590 modules; b : glob app; c : sqlite timeout=30 (code appele) | test_import_all_nr.py:71 subprocess.run([sys.executable, '-c', script], timeout=15) pour CHAQUE app/forge_*.py (l.146) | oui |
| `tests/nr/test_indexation_gardes_nr.py` | PURE | c : sqlite timeout=120 (code appele) | test_indexation_gardes_nr.py:125 idx.main(['--apply']) -> tools/forge_rag_index_fingerprint.py:130 sqlite3.connect(timeout=120) | oui |
| `tests/nr/test_ingestion_sans_troncature_muette_nr.py` | PURE | b : lecture + ast de app/ et tools/ (liste SOURCES) | test_ingestion_sans_troncature_muette_nr.py:135 for p in SOURCES: read_text + ast.parse ; SOURCES = rglob app+tools a la COLLECTE (l.55-58) | oui (+ `import pytest`) |
| `tests/nr/test_intent_multi_verbe_nr.py` | PURE | b : rglob app+tools + ast | test_intent_multi_verbe_nr.py:268 (RACINE / dossier).rglob('*.py') + ast.parse (~2300) | oui |
| `tests/nr/test_job_runner_garde_et_pdf_cap_nr.py` | PURE | a : subprocess python (code appele, job detache) | test_job_runner_garde_et_pdf_cap_nr.py:109 fjr.launch_job('C:/tmp/nr_cible_wrapper_compile.py') -> spawn reel du wrapper | oui |
| `tests/nr/test_journal_shadow_observable_nr.py` | PURE | a : subprocess git (code appele) | test_journal_shadow_observable_nr.py:106 rr.observer(...) -> app/forge_retrieval_router.py:226 engine_commit() -> l.202 subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], timeout=15) | oui |
| `tests/nr/test_journaux_graphe_acces_nr.py` | PURE | b : lecture de app/ et tools/ (2 niveaux) | test_journaux_graphe_acces_nr.py:170 recenser() -> glob('*.py') + sous-dossiers + read_text sur ROOT (4 tests) | oui |
| `tests/nr/test_key_rotation_ledger_concurrent_nr.py` | PURE | a : subprocess python x6 | test_key_rotation_ledger_concurrent_nr.py:65 6x subprocess.Popen([sys.executable, ecrivain, ...]) + communicate(timeout=120) | oui |
| `tests/nr/test_lats_cycle_complet_nr.py` | PURE | a : subprocess git; a : subprocess pytest (code appele) | test_lats_cycle_complet_nr.py:90 subprocess.run(['git', 'init', '-q'], check=True) | non (deja : `@pytest.mark.timeout(120) sur test_cycle_complet_garde_bac_…`) |
| `tests/nr/test_lats_garde_mutation_nr.py` | PURE | a : subprocess git | test_lats_garde_mutation_nr.py:229 subprocess.run(['git', 'init', '-q'], check=True) | non (deja : `l.31 pytestmark = pytest.mark.timeout(120)`) |
| `tests/nr/test_lecteurs_directs_reserves_2b6_nr.py` | PURE | b : rglob app+tools + lecture | test_lecteurs_directs_reserves_2b6_nr.py:47 (ROOT / d).rglob('*.py') + read_text (>500 exiges) | oui (+ `import pytest`) |
| `tests/nr/test_lectures_reservees_hors_guichet_cliquet_nr.py` | PURE | b : rglob app+tools + lecture | test_lectures_reservees_hors_guichet_cliquet_nr.py:104 (ROOT / d).rglob('*.py') + read_text | oui (+ `import pytest`) |
| `tests/nr/test_like_prefixe_indexable_nr.py` | PURE | b : rglob app+tools + lecture | test_like_prefixe_indexable_nr.py:46 base.rglob('*.py') + read_text (app, tools) | oui (+ `import pytest`) |
| `tests/nr/test_liveness_correlation_nr.py` | PURE | a : subprocess schtasks (code appele, Windows) | test_liveness_correlation_nr.py:85 N.autorites() -> app/forge_nervous_map.py:271 subprocess.run(['schtasks', '/query', '/fo', 'csv', '/nh'], timeout=30) | oui |
| `tests/nr/test_m2m_hors_embeddings_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_m2m_hors_embeddings_nr.py:150 split.copier(dst, True, source=src) -> tools/forge_m2m_db_split.py:94 sqlite3.connect(cible, timeout=30.0) | oui |
| `tests/nr/test_maitre_decouple_des_cles_nr.py` | PURE | a : subprocess wmic/powershell (code appele, Windows) | test_maitre_decouple_des_cles_nr.py:70 snap.derive_backup_salt(...) -> app/forge_snapshot.py:131 subprocess.check_output(['wmic', ...], timeout=3) puis l.141 powershell (timeout=3) | oui |
| `tests/nr/test_maitre_est_attribuable_nr.py` | PURE | b : rglob app+tools + lecture | test_maitre_est_attribuable_nr.py:650 base.rglob('*.py') + read_text (app, tools) | oui |
| `tests/nr/test_memory_junction_nr.py` | PURE | a : subprocess git | test_memory_junction_nr.py:137 subprocess.run(['git','-C',ROOT,'check-ignore','-q','memory/x.md'], timeout=30) | oui (+ `import pytest`) |
| `tests/nr/test_module_cards_sans_scan_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_module_cards_sans_scan_nr.py:54 fmc.ingest_cards() -> tools/forge_module_cards.py:230 sqlite3.connect(DB, timeout=30) | oui |
| `tests/nr/test_modules_parsables_nr.py` | PURE | b : rglob app+tools + lecture | test_modules_parsables_nr.py:60 base.rglob('*.py') + read_text (~2400, lu une fois pour 5 tests) | oui (+ `import pytest`) |
| `tests/nr/test_namespace_nokido_nr.py` | PURE | b : subprocess git ls-files | test_namespace_nokido_nr.py:238 subprocess.run(['git','-C',ROOT,'ls-files','--',zone], timeout=180) | oui (+ `import pytest`) |
| `tests/nr/test_network_scapy_paresseux_nr.py` | PURE | a : subprocess python | test_network_scapy_paresseux_nr.py:61 subprocess.run([sys.executable, '-c', code], timeout=120) | oui (+ `import pytest`) |
| `tests/nr/test_new_tools_nr.py` | hors suite | d : reseau reel (GitHub, arXiv, PyPI, HuggingFace, OpenRouter); d : reseau localhost Ollama | test_new_tools_nr.py:505 disc._search_github(...) -> tools/forge_source_discovery.py:927 httpx.get ; :547 extract_content('https://pypi.org/...') ; :691 keep_warm -> requests.post ; :712 fetch_openro… | oui |
| `tests/nr/test_niveaux_de_preuve_service_nr.py` | PURE | b : rglob app+tools + ast | test_niveaux_de_preuve_service_nr.py:98 base.rglob('*.py') + ast.parse (app, tools) | oui (+ `import pytest`) |
| `tests/nr/test_nokido_headless_nr.py` | hors suite | a : subprocess python (boot complet) | test_nokido_headless_nr.py:35 subprocess.run([sys.executable, 'app/Nokido.py', '--test-boot'], timeout=30) | oui |
| `tests/nr/test_nokido_launcher_cli_nr.py` | PURE | a : subprocess python x2 | test_nokido_launcher_cli_nr.py:57 subprocess.run([sys.executable, 'tools/nokido_launcher.py', ...], timeout=60) (2 lancements) | oui |
| `tests/nr/test_note_apres_frontmatter_nr.py` | PURE | a : subprocess git (code appele) | test_note_apres_frontmatter_nr.py:48 datation.traiter(page, True, racine=tmp_path) -> tools/forge_docs_datation.py:60 subprocess.run(['git', ..., 'log', '-1', ...], timeout=20) | oui (+ `import pytest`) |
| `tests/nr/test_npsc_decouverte_nr.py` | PURE | a : subprocess git (code appele) | test_npsc_decouverte_nr.py:69 reco.decouvrir(ROOT / '_repertoire_inexistant_npsc') -> tools/forge_npsc_scan.py:124 subprocess.run(['git', ..., 'ls-files', '-z'], timeout=120) | oui (+ `import pytest`) |
| `tests/nr/test_npsc_nr.py` | PURE | a : subprocess git (code appele); b : parcours du depot (git grep *.py) | test_npsc_nr.py:311 juge.executer_exigence({'globs': ['*.py'], ...}, ROOT) -> tools/forge_npsc.py:131 subprocess.run(['git', '-C', ROOT, 'grep', '-l', '-I', '-E', '-e', motif, '--', '*.py'], timeout=… | oui |
| `tests/nr/test_nr_coverage_ratchet_nr.py` | PURE | b : glob tests/nr + lecture | test_nr_coverage_ratchet_nr.py:38 NR.glob('*.py') + read_text (~2200 fichiers) | oui |
| `tests/nr/test_nr_instables_nr.py` | PURE | a : subprocess pytest (code appele) | test_nr_instables_nr.py:68 fni.main(['--passes', '2', t]) -> tools/forge_nr_instables.py:82 subprocess.run(cmd) (pytest x2) | non (deja : `@pytest.mark.timeout(120) sur test_chemin_reel_nomme_le_tes…`) |
| `tests/nr/test_opencode_web_ferme_nr.py` | PURE | a : subprocess python | test_opencode_web_ferme_nr.py:297 subprocess.run([sys.executable, OUTIL, '--verifier'], timeout=60) | oui |
| `tests/nr/test_pair_accuses_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_pair_accuses_nr.py:66 postal._conn() -> app/forge_postal.py:73 sqlite3.connect(DB, timeout=30) | oui |
| `tests/nr/test_point_entree_par_chemin_nr.py` | PURE | a : subprocess python | test_point_entree_par_chemin_nr.py:140 subprocess.run([sys.executable, chemin, '--help'], timeout=120) | oui (+ `import pytest`) |
| `tests/nr/test_points_d_entree_racine_avant_nokido_agent_nr.py` | PURE | b : lecture de tous les tools/*.py | test_points_d_entree_racine_avant_nokido_agent_nr.py:94 (ROOT / 'tools').glob('*.py') + read_text + ast.parse (1090 fichiers) | oui (+ `import pytest`) |
| `tests/nr/test_pool_timeout_promesse_non_tenue_nr.py` | PURE | b : lecture de tous les app/*.py et tools/*.py | test_pool_timeout_promesse_non_tenue_nr.py:81 rep.glob('*.py') + read_text via recenser() sur ROOT | oui (+ `import pytest`) |
| `tests/nr/test_pouls_canon_nr.py` | PURE | b : subprocess git ls-files | test_pouls_canon_nr.py:59 subprocess.run(['git','-C',ROOT,'ls-files','--','app/*.py','tools/*.py'], timeout=120) | oui |
| `tests/nr/test_prefect_manager_appel_vivant_nr.py` | PURE | b : rglob app + lecture | test_prefect_manager_appel_vivant_nr.py:23 APP.rglob('*.py') + read_text de chaque fichier (1224) | oui (+ `import pytest`) |
| `tests/nr/test_preuve_survit_au_worktree_nr.py` | PURE | a : subprocess git | test_preuve_survit_au_worktree_nr.py:47 subprocess.run(['git', ...], timeout=180) + git worktree reel via forge_worktree.create_proof | oui |
| `tests/nr/test_provenance_note_agent_nr.py` | PURE | a : subprocess git (+ hook post-commit python) | test_provenance_note_agent_nr.py:39 subprocess.run(['git', *args]) sans timeout ; le hook post-commit copie lance sys.executable a chaque commit (l.62-66) | oui |
| `tests/nr/test_provenance_veille_dans_prompt_nr.py` | PURE | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_provenance_veille_dans_prompt_nr.py:51 forge_agent_proxy._get_rag_context() -> qualifier_resultats() -> app/forge_epistemic_retrieve.py:43 sqlite3.connect(DB reel, timeout=30) | oui |
| `tests/nr/test_ps1_parse_gate_nr.py` | PURE | a : subprocess powershell (code appele, Windows) | test_ps1_parse_gate_nr.py:87 gate._ps1_parse_gate(['tools/nokido_start.ps1']) -> tools/forge_git_gate.py:364 subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', ...], timeout=60) | oui |
| `tests/nr/test_purge_garde_main_nr.py` | PURE | a : subprocess python | test_purge_garde_main_nr.py:45 subprocess.run([sys.executable, '-c', code], timeout=120) | oui (+ `import pytest`) |
| `tests/nr/test_purge_journaux_opsec_nr.py` | PURE | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_purge_journaux_opsec_nr.py:38 flr._purge_journaux_securite(dry=True) -> tools/forge_log_retention.py:1434 sqlite3.connect(DB reel, timeout=30) | oui |
| `tests/nr/test_purge_veille_epargne_les_ratees_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_purge_veille_epargne_les_ratees_nr.py:61 R._purge_watch_chains() -> tools/forge_log_retention.py:350 sqlite3.connect(DB, timeout=30) | oui (+ `import pytest`) |
| `tests/nr/test_purge_worktrees_de_preuve_nr.py` | PURE | a : subprocess python | test_purge_worktrees_de_preuve_nr.py:136 subprocess.run([sys.executable, '-c', code], cwd=tools, timeout=120) | oui |
| `tests/nr/test_push_sovereign_sha_certifie_nr.py` | PURE | a : subprocess git | test_push_sovereign_sha_certifie_nr.py:29 subprocess.run(['git', ...]) sans timeout (depot tmp, 4 tests) | oui (+ `import pytest`) |
| `tests/nr/test_py314t_readiness_parallelisme_nr.py` | PURE | a : subprocess python (code appele) | test_py314t_readiness_parallelisme_nr.py:88 deps_absentes(sys.executable, [...]) -> tools/forge_py314t_readiness.py:237 subprocess.run([exe, ...]) | oui (+ `import pytest`) |
| `tests/nr/test_pypi_patch_tests_nr.py` | PURE | b : lecture de tout tests/nr (code appele) | test_pypi_patch_tests_nr.py:57 pt.fichiers_candidats() -> tools/forge_pypi_patch_tests.py:216 NR.glob('*.py') + read_text (~2200) | oui |
| `tests/nr/test_rag_contrat_proxy_nr.py` | PURE | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_rag_contrat_proxy_nr.py:52 proxy._get_rag_context() -> qualifier_resultats() -> app/forge_epistemic_retrieve.py:43 sqlite3.connect(DB reel, timeout=30) | oui |
| `tests/nr/test_refacto_nr.py` | hors suite | b : rglob racine + lecture | test_refacto_nr.py:620 ROOT.rglob('*.py') (toute la racine, sandbox compris) | oui |
| `tests/nr/test_release_lock_provenance_nr.py` | PURE | a : subprocess python | test_release_lock_provenance_nr.py:348 subprocess.run([sys.executable, '-c', ...]) | oui |
| `tests/nr/test_restart_garde_le_hub_nr.py` | PURE | a : subprocess cmd.exe (.bat); a : subprocess powershell (code appele) | test_restart_garde_le_hub_nr.py:237 subprocess.run(['cmd.exe', '/c', BAT, '--action', 'list'], timeout=60) | oui |
| `tests/nr/test_retrieval_router_shadow_nr.py` | PURE | a : subprocess git (code appele) | test_retrieval_router_shadow_nr.py:125 rr.observer(...) -> app/forge_retrieval_router.py:202 subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], timeout=15) | oui |
| `tests/nr/test_revocation_chemins_connus_nr.py` | PURE | b : rglob app+tools + ast | test_revocation_chemins_connus_nr.py:146 (racine / sous).rglob('*.py') + ast.parse (app, tools) | oui |
| `tests/nr/test_route_authz_inventaire_nr.py` | PURE | b : rglob tools+app (py/html/js/ts) + lecture | test_route_authz_inventaire_nr.py:481 base.rglob('*') + read_text des .py/.html/.js/.ts (tools, app) | oui (+ `import pytest`) |
| `tests/nr/test_selecteur_only_nr.py` | PURE | a : subprocess python (ci_local) | test_selecteur_only_nr.py:153 subprocess.run([sys.executable, 'tools/ci_local.py', '--only', 'ruff critique'], timeout=180) | oui (+ `import pytest`) |
| `tests/nr/test_self_correction_roundtrip_nr.py` | PURE | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_self_correction_roundtrip_nr.py:55 fsc.anchor_solution() -> app/forge_self_correction.py:629 sqlite3.connect(_DB reel, timeout=30.0), jusqu'a 5 reprises (l.79) | oui (+ `import pytest`) |
| `tests/nr/test_session_start_rappel_audit_nr.py` | PURE | a : subprocess python x2 | test_session_start_rappel_audit_nr.py:179 subprocess.run([sys.executable, SCRIPT, '--changement-modele'], timeout=60) | oui (+ `import pytest`) |
| `tests/nr/test_sha_courant_nr.py` | PURE | a : subprocess git (code appele) | test_sha_courant_nr.py:47 ci._sha_courant(env={}) -> tools/ci_local.py:2562 subprocess.run(['git', 'rev-parse', ...]) | oui |
| `tests/nr/test_socle_attente_bornee_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_socle_attente_bornee_nr.py:145 fsc.anchor_solution() -> app/forge_self_correction.py:629 sqlite3.connect(tmp, timeout=30.0) | oui (+ `import pytest`) |
| `tests/nr/test_soif_bloquee_par_dependance_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_soif_bloquee_par_dependance_nr.py:75 ev.coverage_dense() -> app/forge_epistemic_veille.py:191 sqlite3.connect(timeout=30) | oui |
| `tests/nr/test_ssrf_backends_crawl_nr.py` | PURE | d : resolution DNS reelle (code appele) | test_ssrf_backends_crawl_nr.py:73 WF._url_interdite(url publique) -> tools/forge_web_egress.py:58 socket.gethostbyname(host) sans borne | oui |
| `tests/nr/test_startup_nr.py` | hors suite | b : lecture + compile de tous les app/forge_*.py | test_startup_nr.py:212 APP_DIR.glob('forge_*.py') + read_text + compile (586 fichiers, 3 tests) | oui |
| `tests/nr/test_stop_epargne_les_jobs_detaches_nr.py` | PURE | a : subprocess powershell (code appele, Windows) | test_stop_epargne_les_jobs_detaches_nr.py:87 gate._ps1_parse_gate(['tools/nokido_stop.ps1']) -> tools/forge_git_gate.py:364 subprocess.run([powershell, ...], timeout=60) | oui |
| `tests/nr/test_suite_pure_ratchet_nr.py` | PURE | a : subprocess git (boucle); b : lecture des NR de la suite | test_suite_pure_ratchet_nr.py:132 subprocess.run(['git','check-ignore','-q',cible], timeout=20) pour chaque exigence de chaque NR pur lu | oui (+ `import pytest`) |
| `tests/nr/test_superviseur_bilan_coffre_nr.py` | PURE | a : subprocess python x2 | test_superviseur_bilan_coffre_nr.py:58 subprocess.run(PY_ISOLE + [py], timeout=60) | oui (+ `import pytest`) |
| `tests/nr/test_swebench_hors_rag_nr.py` | PURE | a : subprocess python | test_swebench_hors_rag_nr.py:81 subprocess.run([sys.executable, '-c', code], timeout=110) | non (deja : `@pytest.mark.timeout(120) sur test_chemin_reel_chaque_runne…`) |
| `tests/nr/test_symboles_source_unique_nr.py` | PURE | b : rglob app+tools + ast | test_symboles_source_unique_nr.py:130 base.rglob('*.py') + ast.parse (DOSSIERS) | oui (+ `import pytest`) |
| `tests/nr/test_token_usage_unique_writer_nr.py` | PURE | b : lecture de tous les app/*.py et tools/*.py | test_token_usage_unique_writer_nr.py:111 racine.glob('*.py') + read_text (app, tools) | oui (+ `import pytest`) |
| `tests/nr/test_tpm_isolation_nest_pas_non_exportabilite_nr.py` | PURE | b : lecture de tous les app/*.py et tools/*.py | test_tpm_isolation_nest_pas_non_exportabilite_nr.py:85 (RACINE / sous).glob('*.py') + read_text | oui |
| `tests/nr/test_transient_gen6_llm_local_nr.py` | PURE | d : reseau localhost sans serveur simule (:8091) | test_transient_gen6_llm_local_nr.py:66 executor.etat_llm_local() -> app/forge_transient_executor.py:111 urlopen('http://127.0.0.1:8091/completion', timeout=20) ; :135 executer -> l.209 urlopen(..., t… | oui |
| `tests/nr/test_tui_136_adaptateurs_nr.py` | PURE | a : subprocess python (TUI) | test_tui_136_adaptateurs_nr.py:46 subprocess.run([sys.executable, '-c', code], timeout=120) | non (deja : `@pytest.mark.timeout(150) sur test_lancement_reel_charge_le…`) |
| `tests/nr/test_ui_gate_interpreteur_nr.py` | PURE | a : subprocess git (code appele) | test_ui_gate_interpreteur_nr.py:223 ci_local._sha_courant(env={}) -> tools/ci_local.py:2562 git rev-parse (timeout=10) | oui (+ `import pytest`) |
| `tests/nr/test_veille_campagne_run_nr.py` | PURE | b : lecture de tous les tools/*.py et app/*.py | test_veille_campagne_run_nr.py:102 d.glob('*.py') + read_text (tools, app) | oui |
| `tests/nr/test_veille_clone_chemins_windows_nr.py` | PURE | a : subprocess git | test_veille_clone_chemins_windows_nr.py:35 subprocess.run(['git', ...]) sans timeout + git clone/archive reel (V.clone) | non (deja : `l.25 pytestmark = pytest.mark.timeout(120)`) |
| `tests/nr/test_veille_gel_et_pertinence_nr.py` | PURE | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_veille_gel_et_pertinence_nr.py:137 ra.research_agent() -> app/forge_research_agent.py:373 get_agent_memory() -> app/forge_memory_archival.py:316 sqlite3.connect(RAG/embeddings.db, timeout=30) | oui (+ `import pytest`) |
| `tests/nr/test_veille_intake_autolance_nr.py` | PURE | a : subprocess git | test_veille_intake_autolance_nr.py:99 subprocess.run(['git', 'init', ...], check=True) | non (deja : `@pytest.mark.timeout(120) sur test_dump_repo_chemin_reel_re…`) |
| `tests/nr/test_veille_non_mesuree_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_veille_non_mesuree_nr.py:38 ce.ChainExecutor(db_path=tmp) -> app/forge_chain_executor.py:73 sqlite3.connect(timeout=30) + busy_timeout=30000 | oui |
| `tests/nr/test_veille_reprise_et_budget_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_veille_reprise_et_budget_nr.py:37 ce.ChainExecutor(db_path=tmp) -> app/forge_chain_executor.py:73 sqlite3.connect(timeout=30) + busy_timeout=30000 | oui (+ `import pytest`) |
| `tests/nr/test_veille_substance_nr.py` | PURE | a : subprocess git | test_veille_substance_nr.py:91 subprocess.run(['git', 'init', ...], check=True) + dump_repo (git clone reel) | non (deja : `@pytest.mark.timeout(120) sur test_dump_repo_chemin_reel_re…`) |
| `tests/nr/test_veille_verdict_chaine_nr.py` | PURE | c : sqlite timeout=30 (code appele) | test_veille_verdict_chaine_nr.py:182 ce.ChainExecutor(db_path=db) ; :183 ex._get_conn() -> app/forge_chain_executor.py:73 sqlite3.connect(timeout=30) | oui |
| `tests/nr/test_wheel_paquets_declares_nr.py` | PURE | b : subprocess git ls-files | test_wheel_paquets_declares_nr.py:49 subprocess.run(['git','-C',ROOT,'ls-files'], timeout=180) | oui (+ `import pytest`) |
| `tests/nr/test_workspace_guard_message_nr.py` | PURE | a : subprocess python | test_workspace_guard_message_nr.py:56 subprocess.run([sys.executable, '-c', src], timeout=120) | oui |
| `tests/nr/test_worktree_preuve_non_interference_nr.py` | PURE | a : subprocess git | test_worktree_preuve_non_interference_nr.py:66 subprocess.run(['git', ...], timeout=120) | oui |
| `tests/test_8770_dead_zone_removal.py` | hors suite | b : rglob tools+app + lecture | test_8770_dead_zone_removal.py:50 scan_dir.rglob('*.py') + read_text (tools, app) | oui (+ `import pytest`) |
| `tests/test_delivery_integrity.py` | hors suite | c : sqlite timeout=30 (code appele); a : git + gh reels (code appele) | test_delivery_integrity.py:244 di.scan() -> git/gh reels + app/forge_delivery_integrity.py:636 sqlite3.connect(DB reel, timeout=30) | oui |
| `tests/test_dispatch_network.py` | hors suite | d : reseau reel (scan LAN) | test_dispatch_network.py:100 run(handle_scan(app, '')) -> app/forge_dispatch_network.py:186 socket.create_connection((ip, port), timeout=0.3) sur localhost/24 (3 ports, 50 threads) | oui |
| `tests/test_docker_action_routing.py` | hors suite | c : docker reel + sqlite timeout=30 (code appele) | test_docker_action_routing.py:17 ToolRegistry().dispatch('docker_action', {'argv': ['ps','-a']}) -> handle_docker_action (docker reel) ; app/forge_postal.py:73 timeout=30 | oui |
| `tests/test_evolution_cable.py` | PURE | a : subprocess git (code appele) | test_evolution_cable.py:49 loops.record_evolution_experience(...) -> app/forge_autonomous_loops.py:545 subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short=8', 'HEAD'], timeout=10) | oui (+ `import pytest`) |
| `tests/test_forge_alignment_shadow_audit.py` | hors suite | a : subprocess opa (code appele) | test_forge_alignment_shadow_audit.py:19 run_audit() -> app/forge_policy_rego.py:148 subprocess.run([opa, 'eval', ...], timeout=5) par scenario | oui |
| `tests/test_forge_embed_worker_isolated.py` | hors suite | a : subprocess notepad.exe / python | test_forge_embed_worker_isolated.py:52 subprocess.Popen(['notepad.exe']) ; :78 Popen([sys.executable, '-c', 'time.sleep(10)']) | oui |
| `tests/test_forge_guarded_mutation_loop.py` | hors suite | b : os.walk tests/ + lecture (code appele) | test_forge_guarded_mutation_loop.py:6 calculate_tests_hash() -> app/forge_guarded_mutation_loop.py:94 os.walk(tests) + read_bytes de chaque .py (~2400) | oui |
| `tests/test_forge_policy_rego.py` | hors suite | a : subprocess opa (code appele) | test_forge_policy_rego.py:19 evaluate(inp) -> app/forge_policy_rego.py:148 subprocess.run([opa, 'eval', ...], timeout=5) | oui |
| `tests/test_forge_scorecard_symbolic.py` | PURE | a : subprocess pylint (code appele); b : lecture+ast de tous les app/forge_*.py (code appele) | test_forge_scorecard_symbolic.py:43 evaluate_symbolic(p) -> app/forge_scorecard.py:409 subprocess.run([sys.executable,'-m','pylint',...], timeout=20) ; :110 _critical_nodes() -> :319 glob + ast.parse… | oui (+ `import pytest`) |
| `tests/test_integration_ollama.py` | hors suite | d : reseau reel (Ollama); a : subprocess (MCP stdio) | test_integration_ollama.py:322 urllib.request.urlopen(OLLAMA_URL + '/api/tags', timeout=5) ; :471 subprocess MCP stdio | oui |
| `tests/test_job_runner_garde_rss.py` | hors suite | a : subprocess python (job reel) | test_job_runner_garde_rss.py:74 subprocess.Popen([sys.executable, wrap]) + attente du .rc (launch_job reel) | oui |
| `tests/test_m2m_protocol.py` | hors suite | c : sqlite timeout=30 (code appele) | test_m2m_protocol.py:90 fp.post(...) -> app/forge_postal.py:73 sqlite3.connect(tmp, timeout=30) | oui |
| `tests/test_netcfg_proxy_debug.py` | hors suite | d : reseau localhost reel | test_netcfg_proxy_debug.py:48 urllib.request.urlopen(req, timeout=5) | oui (+ `import pytest`) |
| `tests/test_netcfg_proxy_direct.py` | hors suite | c : reseau + sqlite (code appele) | test_netcfg_proxy_direct.py:26 ToolRegistry(root_dir=ROOT).dispatch('netcfg_ping') -> app/forge_mcp_registry.py:2798 urlopen | oui (+ `import pytest`) |
| `tests/test_post_commit_doctrine.py` | hors suite | a : subprocess git (code appele) | test_post_commit_doctrine.py:79 pc.vectorise_file(f) -> tools/forge_post_commit.py:439 _get_commit_sha() -> l.507 subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=tmp_path) SANS timeout | oui |
| `tests/test_rag_singleton.py` | hors suite | b : lecture de tous les app/*.py | test_rag_singleton.py:73 (ROOT / 'app').glob('*.py') + read_text (626) | oui |
| `tests/test_research_agent_academic_fallback.py` | hors suite | c : sqlite timeout=30 sur la VRAIE base (code appele); d : reseau SearXNG reel (code appele) | test_research_agent_academic_fallback.py:47 fra.research_agent() -> app/forge_memory_archival.py:316 sqlite3.connect(RAG/embeddings.db, timeout=30) ; _search NON remplace dans ce test | oui |
| `tests/test_research_agent_router_souverain.py` | hors suite | c : sqlite timeout=30 sur la VRAIE base (code appele) | test_research_agent_router_souverain.py:47 fra.research_agent() -> app/forge_memory_archival.py:316 sqlite3.connect(RAG/embeddings.db, timeout=30) | oui |
| `tests/test_run_guard.py` | hors suite | a : subprocess python | test_run_guard.py:27 subprocess.run([sys.executable, tmp], timeout=30) | oui (+ `import pytest`) |
| `tests/test_wiring.py` | hors suite | d : reseau reel (scan LAN) | test_wiring.py:547 run(fdn.handle_scan(app, '')) -> app/forge_dispatch_network.py:186 socket.create_connection sur localhost/24 | oui |

<details><summary>177 candidats ecartes a la lecture (tracabilite)</summary>

| fichier | raison de l'ecart |
|---|---|
| `tests/biblio/test_topics_extractive.py` | urlopen remplace (l.26) ; hors PURE_TESTS |
| `tests/nr/test_actions_ci_epinglees_nr.py` | petit dossier (9 workflows) |
| `tests/nr/test_antiregression_outils_nr.py` | ROOT monkeypatche vers tmp_path (l.125) et _git remplace (l.132) : parcours d'un arbre de 3 fichiers |
| `tests/nr/test_appui_forge_dev_mode_nr.py` | arm() refuse AVANT toute ACL (autorite absente l.51 / jeton illisible l.79) |
| `tests/nr/test_appui_hook_recon_first_nr.py` | git log (timeout 5) seulement si un module forge_* est nomme dans la charge ; charges de test sans module ; hors PURE_TESTS |
| `tests/nr/test_archaeology_conversations_nr.py` | phase3_intentions et _vestiges_non_bruit remplaces (l.45, l.54, l.69) |
| `tests/nr/test_backfill_sans_relecture_nr.py` | l.76 sqlite3.connect remplace par une connexion tmp timeout=5 ; brain_batch (reseau) remplace l.79 |
| `tests/nr/test_backlog_serie_temporelle_nr.py` | compteurs remplace par la fixture isole ; glob sur isole.parent (tmp) |
| `tests/nr/test_bench_http_nr.py` | serveur SIMULE (fixture serveur) |
| `tests/nr/test_body_regulation_instruction_nr.py` | subprocess.run remplace (l.48) |
| `tests/nr/test_boucle_raccordee_gain_nr.py` | record_evolution_experience remplace (l.81) ; juge double injecte |
| `tests/nr/test_bump_superrepo_garde_distant_nr.py` | subprocess.run remplace (l.60) |
| `tests/nr/test_bump_superrepo_ordre_nr.py` | git, _git_distant et publier remplaces (l.49-51) |
| `tests/nr/test_capability_freshness_nr.py` | fcf.sp.run remplace ; instrument absent -> OUTIL_ABSENT avant lancement |
| `tests/nr/test_cascade_route_gouvernee_nr.py` | routeur double + appels directs interdits/remplaces (_call_llm) |
| `tests/nr/test_census_free_tier_nr.py` | urlopen remplace (l.146) ; lire remplace (l.155) ; hors PURE_TESTS |
| `tests/nr/test_ci_dependabot_quarantaine_nr.py` | petit dossier (9 workflows) |
| `tests/nr/test_ci_gate_trois_etats_nr.py` | subprocess.Popen remplace (l.57) |
| `tests/nr/test_ci_proof_reachability_nr.py` | NOKIDO_PROOF_WORKTREE retire et _PROOF_DIR a None : le controle git du worktree de preuve n'est pas atteint (sortie 'absent') |
| `tests/nr/test_ci_quand_ram_dispo_nr.py` | main([]) refuse (rc 2) avant tout appel ; _tenter_ci remplace dans les autres tests |
| `tests/nr/test_ci_reference_worktree_nr.py` | la sonde remplace subprocess.run et leve AVANT execution ; iterdir sur des dossiers de preuve tmp |
| `tests/nr/test_ci_rouges_couverts_nr.py` | fps.git remplace par _Git (l.125, l.137) ; API simulee par la fixture api |
| `tests/nr/test_ci_suite_pure_ligne_de_commande_nr.py` | list2cmdline ne lance rien ; Popen remplace (l.48) |
| `tests/nr/test_circadian_postcondition_nr.py` | programme de phases FACTICE injecte ; aucune phase reelle lancee |
| `tests/nr/test_circadien_producteur_pip_audit_nr.py` | urlopen remplace par un double |
| `tests/nr/test_coder_liveness_composite_nr.py` | _sonde_http_coder et sondes remplacees par _monter |
| `tests/nr/test_confiance_troisieme_etat_nr.py` | _call_llm remplace dans chaque test |
| `tests/nr/test_context_firewall_nr.py` | parcours sur tmp_path |
| `tests/nr/test_critique_exige_deux_sondes_nr.py` | urlopen remplace par un double |
| `tests/nr/test_ctl_sans_boucle_par_le_hub_nr.py` | _call, _via_hub remplaces (l.40-41) ; subprocess.run remplace (l.64) |
| `tests/nr/test_delegation_ressources_hub_nr.py` | hub SIMULE ; sinon port 9 (ferme) -> refus immediat |
| `tests/nr/test_demander_ordre_nr.py` | refus en amont : le chemin de lancement n'est pas atteint |
| `tests/nr/test_dep_manager_allowlist_nr.py` | run remplace et dry_run |
| `tests/nr/test_digest_affectation_organe_nr.py` | _llm_json remplace (l.87) |
| `tests/nr/test_dist_publish_orphelin_et_verdict_nr.py` | fdp.run remplace dans chaque test |
| `tests/nr/test_docker_bail_usage_nr.py` | daemon_up remplace dans chaque test |
| `tests/nr/test_docs_datation_nr.py` | subprocess.run ou date_du_dernier_commit remplaces ; traiter() sur page illisible sort avant git |
| `tests/nr/test_embed_batch_cascade_politique_nr.py` | socket.getaddrinfo remplace |
| `tests/nr/test_embed_campagne_suspend_nr.py` | _un_lot (qui ouvre la base) remplace par _simule |
| `tests/nr/test_endpoint_profiling_nr.py` | urlopen remplace ; hors PURE_TESTS |
| `tests/nr/test_ensure_service_lmstudio_nr.py` | urlopen, _jouer, _sonde_lmstudio, subprocess.run, _lmstudio_sert remplaces test par test ; hors PURE_TESTS |
| `tests/nr/test_ensure_service_restart_gate_nr.py` | _installe remplace (rend False) : ensure() sort en 'NON INSTALLE' avant toute commande de service |
| `tests/nr/test_epistemic_page_sans_balayage_nr.py` | ep._conn remplace (_brancher) vers une base tmp |
| `tests/nr/test_forge_handoff_worker_nr.py` | un_cycle(0) sort avant tout acces postal (tools/forge_handoff_worker.py:166 `if pool <= 0: return`) |
| `tests/nr/test_forge_history_secret_audit_nr.py` | audit_exhaustif remplace |
| `tests/nr/test_forge_release_gate_nr.py` | _git remplace ; ctrl_miroir_a_jour sans miroir sort avant git |
| `tests/nr/test_forge_secret_rotation_check_nr.py` | empreintes_historiques et urlopen remplaces ; type inconnu sort avant la sonde |
| `tests/nr/test_fusion_ports_sondes_en_parallele_nr.py` | _port_listens remplace |
| `tests/nr/test_generation_capture_untracked_nr.py` | parcours sur tmp_path |
| `tests/nr/test_git_egress_protection_branche_nr.py` | les tests sans doublure sortent avant git (suppression, branche neuve, option force : app/forge_git_egress.py:187-197) |
| `tests/nr/test_git_gate_soupape_etroite_nr.py` | fixture gate : tous les controles (_ts_parse_gate, _quality_warn, _scan_secrets...) remplaces par des doubles (l.24-35) |
| `tests/nr/test_goap_preuve_annote_nr.py` | LLM factice injecte ; analyze_trajectories ouvre la vraie base avec le timeout sqlite par DEFAUT (5 s, < 30) |
| `tests/nr/test_health_services_http_en_parallele_nr.py` | urlopen simule |
| `tests/nr/test_hf_providers_bge_nr.py` | _lire remplace dans chaque test |
| `tests/nr/test_homeostat_soi_non_soi_nr.py` | superviseur SIMULE (HTTPServer du test, fixture l.118) ; l.136 vise le port 9 ferme (refus immediat) ; request_resources entierement double |
| `tests/nr/test_hook_integrity_doublon_nr.py` | simple listage des noms de tools/ (aucune lecture de contenu) ; settings fabriques sous tmp_path |
| `tests/nr/test_hub_o.py` | httpx factice ; 127.0.0.1:1 avec timeout 0,1 s |
| `tests/nr/test_hub_sse.py` | serveur simule en processus (_TinySSEServer, fixture sse_backend) ; ReverseProxy.__init__ ne se connecte pas |
| `tests/nr/test_hub_web.py` | constructeurs seulement, aucune connexion ouverte |
| `tests/nr/test_hub_ws_auth.py` | serveurs simules en processus ; hors PURE_TESTS |
| `tests/nr/test_introspect_jugeable_nr.py` | forge_panorama_builder.scan_forge_modules remplace par la fixture |
| `tests/nr/test_introspect_verbe_unique_nr.py` | scan_forge_modules remplace ; graphe fabrique par la fixture graphe |
| `tests/nr/test_isolation_flow_nr.py` | les 3 cas testes sortent avant _est_ancetre (wip / suppression / branche non protegee) : aucun git lance ; _wip_branch et suite_nr purs |
| `tests/nr/test_jeton_projete_nr.py` | parcours sur tmp_path |
| `tests/nr/test_juge_evaluateur_hors_portee_nr.py` | run remplace |
| `tests/nr/test_keeper_organe_nr.py` | sonde 127.0.0.1:8765 bornee a 4 s |
| `tests/nr/test_liveness_registre_organes_nr.py` | petit dossier sandbox/ (heartbeats), noms seulement |
| `tests/nr/test_memory_compactor_reingest_nr.py` | forge_memory_ingest.ingerer remplace (effets de bord doubles) |
| `tests/nr/test_memory_compactor_sans_compaction_nr.py` | fixture effets_de_bord_patches : ingestion et ledger doubles |
| `tests/nr/test_memory_ledger_sync_rapide_nr.py` | forge_memory_ingest remplace par un module factice (l.151-154), sync/prune doubles |
| `tests/nr/test_mesure_deportee_versionnee_nr.py` | petit dossier (5 fichiers) |
| `tests/nr/test_mesure_journaux_nr.py` | parcours sur tmp_path ; ROOT et chemins rediriges |
| `tests/nr/test_miroir_public_lit_la_politique_nr.py` | _politique_publique rend une politique illisible -> fail-closed avant git ; ailleurs _git remplace |
| `tests/nr/test_mtls_handshake_nr.py` | serveur mTLS FOURNI par la fixture (loopback, port 0) ; borne client probe.TIMEOUT_CLIENT_S et skip si ILLISIBLE 2 fois |
| `tests/nr/test_mutation_test_nr.py` | subprocess.run remplace a la main (l.90-101) avant chaque appel de _git_propre |
| `tests/nr/test_observabilite_nr.py` | _reconstruire_index_fts sort des que PYTEST_CURRENT_TEST est pose (app/forge_circadian.py) ; subprocess.run remplace a la main (l.277) ; sondes loopback bornees a 0,2-0,4 s |
| `tests/nr/test_openrouter_pool_free_nr.py` | urlopen remplace (_coupe / _servir) |
| `tests/nr/test_outils_publication_effet_nr.py` | parcours sur tmp_path ; _git remplace |
| `tests/nr/test_pages_ui_8766_saines_nr.py` | petit ensemble (13 fichiers) |
| `tests/nr/test_pair_quarantaine_geste_owner_nr.py` | approuver sort a tools/forge_pair_quarantaine.py:278 ('non ouvert aux pairs') avant lancer_deliberation (Popen l.329) |
| `tests/nr/test_pair_quarantaine_nr.py` | lancer_deliberation (Popen) n'est atteint que pour genre 'deliberer', remplace l.104 ; faits/messages n'y passent pas |
| `tests/nr/test_pillar_arbiter_nr.py` | urlopen remplace (leve si atteint) |
| `tests/nr/test_pip_audit_nomme_son_interpreteur_nr.py` | comparaison de chaine, aucun lancement |
| `tests/nr/test_pip_audit_sortie_relative_nr.py` | depot fabrique sous tmp_path |
| `tests/nr/test_portail_sans_mojibake_nr.py` | dossier moyen (142 fichiers), sous le seuil retenu |
| `tests/nr/test_post_commit_sans_scan_nr.py` | db_snapshot=False : cold_backup/forge_snapshot (timeout=30) jamais atteint ; post_check _vie_legere ouvre la base tmp avec timeout=10 |
| `tests/nr/test_pouls_service_http_nr.py` | serveur SIMULE du test (_serveur) ou port libre ferme ; fil daemon ; attentes de 1,5-2 s |
| `tests/nr/test_probe_service_nr.py` | serveur SIMULE (fixture serveur) ; port ferme ; http_timeout court |
| `tests/nr/test_provider_views_auth_nr.py` | jeton vide : refus 503 avant toute connexion httpx |
| `tests/nr/test_proxy_fil_sans_tour_vide_nr.py` | chemin opt-in : LAFORGE_PROXY_MEMORY=1 / LAFORGE_PROXY_MEMORY_WRITE=1 (defaut OFF, app/forge_agent_proxy.py:3496/3538) ; a revoir si Nokido.env les active |
| `tests/nr/test_proxy_journalise_echec_fournisseur_nr.py` | memoire du proxy opt-in (LAFORGE_PROXY_MEMORY*, defaut OFF) et pas de thread_id |
| `tests/nr/test_ps_sandbox_mode_inconnu_failclosed_nr.py` | mode hors contrat refuse en tete de run (app/forge_ps_sandbox.py:240) avant toute commande |
| `tests/nr/test_regeneration_commissure_nr.py` | memory_keeper.remember et refine_and_anchor remplaces |
| `tests/nr/test_regulation_learner_nr.py` | anchor=False : anchor_solution (timeout=30) n'est jamais appele (tools/forge_regulation_learner.py:186) |
| `tests/nr/test_release_gate_arbre_nr.py` | _git remplace par _status dans chaque test |
| `tests/nr/test_retrieval_sweep_et_rfc_freshness_nr.py` | _amont (le fetch rfc-index) remplace dans chaque test |
| `tests/nr/test_revue_fail_closed_nr.py` | petit dossier (12 fichiers) |
| `tests/nr/test_robots_rfc9309_nr.py` | refus robots injecte : le crawl s'arrete avant urlopen |
| `tests/nr/test_router_repli_oauth_capacite_nr.py` | _neutraliser remplace les deux replis et l'emission nerveuse |
| `tests/nr/test_rss_watcher_ne_perd_plus_d_alerte_nr.py` | _ingest remplace ; fixture hub_double : urlopen et store_chunks doubles |
| `tests/nr/test_runtime_smoke_etats_nr.py` | _http et sonde de port doubles (_cabler) ; demarrer=True seulement avec port deja pris -> INDETERMINE avant Popen ; main teste avec smoke remplace |
| `tests/nr/test_sauvegarde_cible_fixe_nr.py` | parcours sur tmp_path ; copy_tree remplace |
| `tests/nr/test_scalene_cmd_interpreteur_nr.py` | construit une commande, ne la lance pas |
| `tests/nr/test_scorecard_axe_non_mesure_nr.py` | subprocess.run remplace pour toute commande pylint (FileNotFoundError simulee) |
| `tests/nr/test_sonde_cles_nr.py` | urlopen remplace dans chaque test (l.56, l.117) ; les glob ne visent qu'un fichier nomme |
| `tests/nr/test_sse_deconnexion_nr.py` | petit ensemble (28 fichiers) |
| `tests/nr/test_success_oplog_nr.py` | _git simule (_git_simule) ; evaluer recoit un lanceur factice (lambda) a la place du sous-processus |
| `tests/nr/test_successor_repr_nr.py` | sonde :8765/supervisor/status bornee a 2 s (app/forge_body_world_model.py:47) |
| `tests/nr/test_swarm_nr.py` | boucle locale (le test est son propre serveur) ; hors PURE_TESTS ; ATTENTION : test_broadcast() est APPELE au niveau module (l.178) -> execute a la collecte |
| `tests/nr/test_task_executor_jeton_par_appel_nr.py` | urlopen remplace |
| `tests/nr/test_tool_call_probe_modeles_nr.py` | urlopen remplace (l.34) ; interroger remplace (l.64) |
| `tests/nr/test_tous_modules_nr.py` | par test : 1 fichier lu ; le cout est a la COLLECTE (~2300 chemins, ~4600 items parametres) ; PURE + ci.yml |
| `tests/nr/test_transient_gen4_execution_nr.py` | capacite m2m.validate locale ; l'urlopen :8091 n'est atteint que pour la capacite LLM ; le test l.153 prouve zero reseau et zero subprocess |
| `tests/nr/test_transient_gen5_seconde_capacite_nr.py` | capacite census.organ locale ; l'urlopen :8091 est reserve a la capacite LLM |
| `tests/nr/test_tui_rag_via_hub_nr.py` | _warmup_app_index (l'indexeur qui parcourt app/) remplace l.103 ; logger.info coupe la suite l.106 |
| `tests/nr/test_tuile_orpheline_nr.py` | dossier moyen (142 fichiers) ; fichier de BLOCS_ISOLES (portail anyio) |
| `tests/nr/test_ui_delier_cdn_nr.py` | petits dossiers (12 css cote design_handoff) |
| `tests/nr/test_ui_gate_autodetecte_nr.py` | port ferme en boucle locale, borne 1 s |
| `tests/nr/test_ui_manifest_nr.py` | sonde de port remplacee |
| `tests/nr/test_vault_outils_nr.py` | urlopen remplace |
| `tests/nr/test_vec_ledger_settings_nr.py` | tasklist seulement si psutil manque ET sous Windows, borne 2 s (app/forge_settings.py:190) ; verrou sous tmp_path |
| `tests/nr/test_veille_arxiv_html_nr.py` | urlopen remplace par _servir |
| `tests/nr/test_veille_capacite_nr.py` | _check_deps remplace (_neuf) |
| `tests/nr/test_veille_dumps_hors_depot_nr.py` | parcours sur tmp_path |
| `tests/nr/test_veille_e2e_check_nr.py` | port declare ferme : etage_service sort avant _http (l.107) |
| `tests/nr/test_veille_github_changement_nr.py` | lanceur git FACTICE injecte (_Git) |
| `tests/nr/test_veille_github_selection_nr.py` | ingesteur GitHub FACTICE |
| `tests/nr/test_veille_modele_vivant_nr.py` | urlopen remplace |
| `tests/nr/test_veille_moisson_nr.py` | embed remplace ; dense sort avant tout appel |
| `tests/nr/test_veille_moteurs_muets_nr.py` | urlopen remplace |
| `tests/nr/test_veille_registre_nr.py` | parcours sur tmp_path |
| `tests/nr/test_vitals_channels_evenementiels_nr.py` | sonde :8765 bornee a 0,5 s (app/forge_vitals_channels.py:648) ; skip si injoignable |
| `tests/nr/test_wasm_defaut_start_et_motif_nr.py` | pont double (_cervelet_avec_pont), natif absent ou remplace ; health_spin : subprocess.run remplace (l.134) |
| `tests/nr/test_watch_alerts_identite_canonique_nr.py` | fixture monde : APP_DIR, TOOLS, ROOT et DB_PATH rediriges vers tmp_path (l.50-53) |
| `tests/nr/test_watchdog_gardes_nr.py` | fixture banc : Popen et etat declare doubles ; compute_score_and_gaps ne sonde que 127.0.0.1:8765 avec timeout=4 (borne) |
| `tests/nr/test_wiki_modules_bilingue_nr.py` | la page generee porte deja sa date : traiter ne consulte pas git (tools/forge_docs_datation.py:140) |
| `tests/nr/test_wiki_openwiki_nr.py` | petit dossier (53 pages) |
| `tests/nr/test_wiring_identite_noeud_nr.py` | ROOT et modules() rediriges vers un faux depot tmp (l.66-67, l.189-190) |
| `tests/nr/test_workflow_refs_nr.py` | petit dossier (9 workflows) |
| `tests/test_commands_adapter.py` | commandes refusees / usage avant tout appel ; _hub_call et urlopen remplaces ailleurs ; hors PURE_TESTS |
| `tests/test_docker_boot_timeout_adaptatif.py` | subprocess.run remplace |
| `tests/test_eviction_par_capacite.py` | _supervisor_ports et psutil doubles (_wire) ; hors PURE_TESTS |
| `tests/test_forge_agent_lats.py` | _git_reset_clean remplace / rollback desactive ; hors PURE_TESTS |
| `tests/test_forge_circadian.py` | dry_run ; _restart_service (seul porteur de l'urlopen, app/forge_circadian.py:730) remplace l.100 ; reconstruction FTS refusee sous pytest ; PURE + ci.yml |
| `tests/test_forge_docker_test_a_vide.py` | _restaurer sort avant docker (etat absent / politiques 'no') ; _isoler : _d remplace ; hors PURE_TESTS |
| `tests/test_forge_dspy_router.py` | urlopen remplace ; signature inconnue refusee avant (l.28) |
| `tests/test_forge_handoff_multiprovider.py` | _call_router, _call_ollama_chat, _call_router_provider remplaces ; hors PURE_TESTS |
| `tests/test_forge_handoff_planning_mode.py` | routeur LLM remplace |
| `tests/test_forge_lats.py` | test_fn FACTICE injecte : default_apply_and_test (git apply) jamais appele |
| `tests/test_forge_local_inference_pool.py` | backends FACTICES injectes |
| `tests/test_forge_mcp_registry_unicode.py` | dispatch rejette (security_reject) au debut (app/forge_mcp_registry.py:642-657), avant postal/reseau ; hors PURE_TESTS |
| `tests/test_forge_pydantic_tools.py` | seuls view_file_content / edit_file_block sont appeles ; _run_pytest (app/forge_pydantic_tools.py:140) n'est pas atteint |
| `tests/test_forge_qdrant_sidecar.py` | serveur simule dans un thread du test (SidecarHTTPServer port=0) ; hors PURE_TESTS ; erreur de collecte ici (qdrant_client absent) |
| `tests/test_forge_scorecard.py` | _run_quality_gate et _llm_judge remplaces ; sans task_desc le juge est saute ; PURE + ci.yml |
| `tests/test_forge_scorecard_evaluate_patch.py` | _llm_judge remplace ; AST en echec ou task_desc vide : aucun appel ; PURE + ci.yml |
| `tests/test_forge_scorecard_refine_judge.py` | urlopen remplace ; judge_one en dry_run avec _llm_judge remplace (l.166) ou sans bloc de code |
| `tests/test_forge_searxng_keeper.py` | _docker remplace (install_docker) ; hors PURE_TESTS |
| `tests/test_forge_supervisor_ctl.py` | urlopen remplace |
| `tests/test_forge_swebench_repo_cache.py` | manifest concordant : retour a tools/forge_swebench_repo_cache.py:143 avant _clone_or_reuse |
| `tests/test_goap_execution.py` | le chemin d'expansion n'est pris que si le dispatch LEVE (app/forge_goap.py:606) ; les doublures rendent des dict |
| `tests/test_goap_intuition.py` | rend une fermeture ; l'appel HTTP n'est pas execute |
| `tests/test_key_rotation_403_visibility.py` | pool de cles epuise : retour ERR:key_pool_exhausted avant urlopen |
| `tests/test_nokido_loops.py` | dossiers TemporaryDirectory ; hors PURE_TESTS (et erreur de collecte NameError AgenticEngine) |
| `tests/test_nokido_tui_adapters.py` | 6 sondes loopback de 0,5 s (tools/nokido_tui.py:183) : borne 3 s |
| `tests/test_p1_gate_intent_aware.py` | get_snapshot remplace ; chemin noop sans eviction |
| `tests/test_pool_balancer.py` | backends FACTICES |
| `tests/test_pool_reliability.py` | backends FACTICES |
| `tests/test_predict_impact_sr.py` | sonde :8765 bornee a 2 s |
| `tests/test_rag_injection_filter.py` | get_embeddings remplace ; sidecar FAISS en loopback borne 1,5 s (tools/forge_faiss_sidecar.py:213) |
| `tests/test_security_phase23.py` | _git remplace (l.46, l.68) ; hors PURE_TESTS |
| `tests/test_self_awareness.py` | sonde :8765 bornee a 2 s (app/forge_self_awareness.py:53) |
| `tests/test_sensor_fusion_probe.py` | _port_listens et registre doubles ; hors PURE_TESTS |
| `tests/test_service_capabilities.py` | forge_port_reconcile et world-model factices ; hors PURE_TESTS |
| `tests/test_skill_curator.py` | _anchor remplace ; bases tmp ; hors PURE_TESTS |
| `tests/test_symbiose_live.py` | coroutine sans marque asyncio en mode STRICT : pytest ne l'execute pas ; chemin sys.path Windows code en dur |
| `tests/test_tui_adapters_phase2.py` | urlopen remplace |
| `tests/test_tui_adapters_v3.py` | urlopen remplace |

</details>

## 2. Collecte

Mesures sous Linux, Python 3.11 (le depot vise 3.12+ / 3.14), pytest 9.x ; `ci.yml` epingle
pytest < 9 -- le mecanisme en cause est identique en 8.4.2 (verifie dans les sources et par la
mesure). Les chiffres absolus ne se transposent pas a Windows (voir Limites).

### 2.1 Le poste dominant : ~900 fichiers passes en arguments

`tools/ci_local.py` (l.4769 `_args_depuis_fichier(...)`, puis `pytest @liste ... --capture=no
--timeout=30`) passe la suite pure fichier par fichier. `tests/nr/` est un paquet
(`__init__.py`, ~2 200 entrees) : pour CHAQUE argument fichier, `Session.collect` re-collecte le
paquet parent avec `handle_dupes=False`, ce qui contourne `_collection_cache`
(`_pytest/main.py`, meme code en 8.4.2 et 9.x). Le cout vaut donc (nombre d'arguments) x
(taille du paquet) -- deux quantites qui grandissent ensemble avec la suite. Profil de la
collecte complete : 1,97 million d'appels a `Package.collect`, le temps part dans `pathlib`,
`pytest_ignore_collect` et la creation des noeuds -- pas dans les imports.

| mesure (collect-only) | fichiers en arguments | un seul argument, filtre | memes tests ? |
|---|---:|---:|---|
| liste ci_local (901 fichiers), conditions ci_local, pytest 9 | **237,5 s** | **9,8 s** | oui (12 991) |
| idem, pytest 8.4.2 (celui de `ci.yml`) | 244,6 s | -- | -- |
| reproduction, 100 premiers NR de PURE_TESTS | 28,9 s | 1,2 s | oui (876) |
| reproduction, 200 premiers NR de PURE_TESTS | 55,3 s | 1,6 s | oui (1 603) |
| reproduction, 400 premiers NR de PURE_TESTS | 103,7 s | 3,2 s | oui (8 096) |

(Les deux premieres lignes : mesure du recensement ; les trois dernieres : reproduction
independante pour ce rapport -- memes tests et memes erreurs de collecte d'environnement
dans les deux formes. Le cout par argument est a peu pres constant (0,26 a 0,29 s ici) : c'est le
re-parcours du paquet `tests/nr`, qui grandit lui-meme avec la suite.)

**Sous Windows, c'est pire** : pour chaque noeud qui ne correspond pas, pytest compare les
chemins par le systeme de fichiers (`os.path.samefile` en 8.4.2, `samefile_nofollow` en 9) --
deux `stat` par comparaison, ~4 millions sur NTFS avec l'antivirus. Non mesure ici ; c'est tres
probablement l'essentiel des 6 a 9 minutes constatees. En mode xdist, **chaque worker** refait
cette collecte.

**Proposition (non appliquee)** : un seul argument racine (`tests/`) et un greffon charge par
`-p` qui ignore les `test_*.py` absents de la liste, lue dans une variable d'environnement.
JUnit, `--timeout=30`, conftests et `__init__.py` inchanges. Le greffon d'essai utilise pour les
mesures (hors depot) tient en quelques lignes :

    def pytest_ignore_collect(collection_path, config):
        p = Path(collection_path)
        if p.is_file() and p.name.startswith("test_") and p.suffix == ".py":
            return str(p.resolve()) not in AUTORISES or None   # None : laisser pytest decider
        return None

A integrer avec soin dans `ci_local` : le mode « selection partielle » et `BLOCS_ISOLES`
reposent aussi sur la liste d'arguments.

### 2.2 La capture de pytest cassee par le depot, pas par pytest 9

La commande du brief (`-X importtime -m pytest --collect-only -q ... tests/`), capture active,
**tronque la collecte en silence** : `ValueError: I/O operation on closed file` dans
`_pytest/capture.py`, 16 196 tests au lieu de 17 400. Cause observee : des modules qui
remplacent `sys.stdout` a l'import (sous `if hasattr(sys.stdout, "buffer")`, vrai sous capture)
-- `tools/forge_goap_hub_bridge.py:20-21`, `tools/forge_self_patcher.py:21-22`, et
`tools/paste_clean.py:32` si l'encodage n'est pas utf-8. Le `TextIOWrapper` cree enveloppe le
fichier de capture et le ferme quand il est ramasse. `ci.yml` impute ce symptome a un « bug de
pytest 9.0.x » et le contourne (`pytest<9`, `--capture=no`) ; la cause est dans le depot.
Proposition : ne reconfigurer la sortie que sous `if __name__ == "__main__"` (ou
`sys.stdout.reconfigure(...)`, qui ne remplace pas l'objet). Les mesures de reference ont ete
prises en `--capture=no`, comme `ci_local`.

### 2.3 Top 20 des imports a la collecte (`-X importtime`, temps cumule)

Les imports ne pesent que ~5,4 s des ~13 s de collecte de `tests/` (le reste : execution des
modules de test, parametrisation). `-X importtime` ne voit ni les modules de test (charges par
`importlib`) ni les modules du pont `nokido_agent`. Les paquets parents qui ne font que
transmettre le cout d'un enfant sont exclus ; les lignes « dans (n) » s'emboitent, ne pas les
additionner.

| # | module | cumul (s) | qui l'importe depuis les tests | fichiers de test (directs / via chaine) | import paresseux possible ? (proposition) |
|---|---|---:|---|---|---|
| 1 | **torch** | **1,858** | `app/forge_mcp_registry.py:56` importe `forge_spike_router.evaluate_intent`, qui importe torch au niveau module (l.35-37) | 3 / **36** (33 via le registre) | **Oui** : importer `evaluate_intent` dans la fonction qui l'appelle (seul usage) ; isoler les `nn.Module` de `forge_spike_router`. Gain ~1,5 s par processus (bloc isole, worker xdist) et fin de la dependance dure a torch (voir 2.4). |
| 2 | **mcp_server_tools** | **0,790** | importe par 3 tests ; `FastMCP("Nokido")` et **50** decorateurs `@mcp.tool()` executes a l'import | 3 / 3 | **Oui** : sortir les fonctions pures testees (jeton, garde de bind) dans un module sans FastMCP ; construire le serveur dans `build_server()`. |
| 3 | mcp | 0,672 | dans (2) | 0 / 3 | couvert par (2) |
| 4 | **app.web_hub.app** | **0,603** | 16 tests (auth, config, dashboard...) ; porte fastapi et httpx | 16 / 16 | **Oui** : les tests d'un helper ou d'une constante importent le sous-module, pas l'application ; cote app, fabrique `create_app()`. |
| 5 | app.web_hub.provider_views | 0,186 | dans (4) | 2 / 18 | non : 10 ms isole (bruit de mesure) |
| 6 | rich.console | 0,178 | dans (3) via `httpx._main` | 0 / 3 | couvert par (2) |
| 7 | aiohttp.test_utils | 0,151 | greffon `pytest_aiohttp` charge automatiquement | 0 / 0 | artefact : absent sous `ci_local` (autoload coupe) |
| 8 | numpy | 0,141 | dans (1) | 9 / 43 | non : importe par 106 modules |
| 9 | textual.app | 0,137 | `tools/nokido_tui.py` l.57-60 | 0 / 5 | **Oui** : les fonctions testees n'ont pas besoin de textual ; importer les widgets dans la construction de l'UI |
| 10 | fastapi.openapi.models | 0,116 | dans (4) | 0 / 16 | couvert par (4) |
| 11 | asyncssh | 0,114 | `app/forge_pty_widget.py` l.62 (try au niveau module) | 0 / 2 | **Oui** : `HAS_ASYNCSSH` par `importlib.util.find_spec`, import dans la connexion |
| 12 | hypothesis | 0,108 | `test_proprietes_generatives_nr` (+ greffon auto) | 1 / 1 | non (paye par le seul test concerne) |
| 13 | nokido_agent.app.forge_web | 0,082 | `app/forge_rag_engine.py:207` | 1 / 9 | **Oui** : resoudre `web_search` a la premiere recherche web (evite bs4/httpx a 8 tests RAG) |
| 14 | requests | 0,082 | `tools/forge_auto_compact.py:22` | 0 / 2 | **Oui** : import dans la fonction qui fait l'appel |
| 15 | bs4.builder | 0,052 | dans (13) | 0 / 9 | couvert par (13) |
| 16 | pydantic_core.core_schema | 0,048 | dans (3) | 0 / 3 | non (charge par fastapi) |
| 17 | jsonschema | 0,045 | dans (3) | 0 / 3 | couvert par (2) |
| 18 | app.web_hub.wired_routes | 0,044 | dans (4) | 1 / 17 | couvert par (4) |
| 19 | cuda.bindings.driver | 0,040 | dans (1) (roue CUDA de PyPI) | 0 / 34 | couvert par (1) |
| 20 | charset_normalizer.api | 0,036 | dans (14) | 0 / 2 | couvert par (14) |

Priorite : (1) torch, puis (2) et (4). Dans un processus sequentiel unique ces imports ne se
paient qu'une fois ; le gain compte surtout par processus (chaque bloc isole, chaque worker
xdist, chaque sous-processus pytest lance par un test).

### 2.4 Dependance dure a torch

`torch` n'est declare que dans `requirements-ml.txt`, mais `forge_mcp_registry` le tire au
niveau module. Sans torch : **13 erreurs de collecte de plus** (19 fois `cannot import name
'ToolRegistry'`), et les fichiers en `pytest.importorskip("...forge_mcp_registry")` disparaissent
en silence (163 tests de moins). `app/forge_mcp_registry.py` est dans `CRITICAL_FILES` : a
traiter par l'owner. (A noter aussi : `mcp` n'est pas declare dans `requirements.txt`, et
`mcp` 2.x casse l'import de `FastMCP` -- la collecte meurt sur `SystemExit("mcp SDK requis")`.)

### 2.5 Code execute pendant la collecte -- hors de portee de pytest-timeout

Un blocage a la COLLECTE fige la session sans limite : pytest-timeout ne couvre que
l'execution des tests. Aucun de ces fichiers n'est dans `PURE_TESTS`, sauf mention :

| fichier | ce qui s'execute a l'import |
|---|---|
| `tests/test_hub_netcfg_ping.py` | POST vers le hub `:8766` **sans timeout** (l.28), avec un jeton lu au coffre ; aucun test |
| `tests/test_mutation_pipeline.py` | generation Ollama reelle au niveau module (timeout 60 s x 3 modeles) ; aucun test |
| `tests/nr/test_swarm_nr.py` | ses controles a l'import : UDP loopback, ecriture dans `sandbox/events.db` |
| `tests/test_fonctionnel.py`, `tests/test_handlers_functional.py` | batteries de controles au niveau module |
| `tests/nr/test_ingestion_sans_troncature_muette_nr.py` (PURE) | `rglob` de `app/` et `tools/` au niveau module (parametres) |
| `tests/nr/test_tous_modules_nr.py` (PURE) | glob `**/*.py` au niveau module (~4 600 items parametres) |

Proposition : deplacer ces effets dans des fixtures ou des tests ; le glob de parametres peut
rester, il est borne par la taille du depot.

## 3. Limites

- **Linux, pas Windows.** pytest-timeout y tourne en methode `signal`, pas `thread` ; les
  comparaisons de chemins de 2.1 ne coutent rien sous Linux ; `wmic`, `schtasks`, `powershell`
  ne sont pas exerces. Les durees absolues ne se transposent pas.
- **Python 3.11** pour les mesures de collecte (dependances installees dans cet interpreteur) :
  une erreur de collecte artificielle (`app/forge_code.py:1746`, f-string PEP 701). Les
  verifications des marques ont ete faites en 3.11 (collecte) et 3.14 (AST, compilation).
- **Dependances** : torch pris sur PyPI (roue CUDA), `mcp<2` ajoute a la main ; absents :
  `qdrant_client`, PySide6, pywin32, modules `sandbox.*` (dossier ignore). Aucun service local
  (hub, superviseur, Ollama, llama) : les appels reseau echouent vite ici, alors qu'ils partent
  reellement sur le poste de l'owner -- plusieurs risques « reseau » ne se manifestent que la.
- **Greffons** charges automatiquement dans certaines mesures (hypothesis, aiohttp, xdist...),
  absents sous `ci_local` (autoload coupe) ; la mesure « conditions ci_local » en tient compte.
- La marque est posee sur la PREUVE d'un risque, pas sur une duree mesuree : certains risques
  sont conditionnels (binaire `opa` present, LLM local sur :8091, Windows). 120 s est la borne
  deja retenue dans le depot ; elle protege la session, elle ne dit rien de la duree normale
  du test.

