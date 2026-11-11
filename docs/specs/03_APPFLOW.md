# 03 — AppFlow : machines d'etat et flux mesures

> Genere par `tools/forge_spec_extractor.py` (introspection deterministe, aucun horodatage) -- commit `bffa9f1a0`. Ne pas editer : relancer l'extracteur.


## 1. ETAT STATIQUE — Machines d'etat et topologie (genere au commit)

> Chaque machine d'etat et chaque service declare est extrait par AST ou lecture deterministe du depot.

### 1.1 Machines d'etat et transitions du coeur

- **(a) Admission d'un job** (`app/forge_job_runner.py`) : points d'entree `admettre_lancement` (`app/forge_job_runner.py:116`)
- **(a-bis) Regulateur de lanes et ressources** (`app/forge_lane_admission.py`) : points d'entree `check_ressources` (`app/forge_lane_admission.py:539`), `current` (`app/forge_lane_admission.py:229`), `admit` (`app/forge_lane_admission.py:644`) ; constantes : `MAX_RAM_PCT=85.0` (`app/forge_lane_admission.py:56`), `RAM_ECART_PTS=10.0` (`app/forge_lane_admission.py:376`)
- **(b) Cycle de la soif et du soin** (`tools/forge_epistemic_daemon.py`) : points d'entree `run_once` (`tools/forge_epistemic_daemon.py:921`), `_interoceptive_split` (`tools/forge_epistemic_daemon.py:290`), `effecteur_enquete` (`tools/forge_epistemic_daemon.py:797`), `_decision_examen` (`tools/forge_epistemic_daemon.py:537`) ; constantes : `VETO_EXAMEN_S=900.0` (`tools/forge_epistemic_daemon.py:896`)
- **(c) Auto-amelioration (self-patcher)** (`tools/forge_self_patcher.py`) : points d'entree `run_once` (`tools/forge_self_patcher.py:916`), `_essayer_patch` (`tools/forge_self_patcher.py:856`), `_submit_to_judge` (`tools/forge_self_patcher.py:638`) ; constantes : `PASSES_MAX=2` (`tools/forge_self_patcher.py:852`), `VERDICTS_RETENUS=('SURVIT', 'AMELIORE')` (`tools/forge_self_patcher.py:398`)
- **(c-bis) Juge de mutation et held-out** (`app/forge_mutation_judge.py`) : points d'entree `evolution_autorisee` (`app/forge_mutation_judge.py:209`), `mutable` (`app/forge_mutation_judge.py:288`), `juger_module` (`app/forge_mutation_judge.py:471`), `juger_gain` (`app/forge_mutation_judge.py:811`), `juger_held_out` (`app/forge_mutation_judge.py:913`), `juger_module_avec_gain` (`app/forge_mutation_judge.py:932`)
- **(d) Bancs BFCL / HumanEval** (`tools/forge_bfcl_runner.py`) : points d'entree `run` (`tools/forge_bfcl_runner.py:634`) ; constantes : `CANARI_N=3` (`tools/forge_bfcl_runner.py:631`)
- **(e) Garde d'ingestion de contenu de tiers** (`app/forge_prompt_guard.py`) : points d'entree `analyser_contenu_tiers` (`app/forge_prompt_guard.py:392`), `admis_a_l_ingestion` (`app/forge_prompt_guard.py:449`)
- **(f) Publication publique et caviardage** (`tools/forge_dist_publish.py`) : points d'entree `sync_snapshot` (`tools/forge_dist_publish.py:761`), `_sans_motifs` (`tools/forge_dist_publish.py:603`), `_caviarder_sujets` (`tools/forge_dist_publish.py:630`), `_verifier_sujets_prives` (`tools/forge_dist_publish.py:671`)
- **(g) Regulation RAM et eviction/reprise** (`app/forge_resource_manager.py`) : points d'entree `_reveiller_les_evinces` (`app/forge_resource_manager.py:4726`), `_admettre_reprises` (`app/forge_resource_manager.py:5330`) ; constantes : `_VETO_SOMMEIL_MAX_S=1800.0` (`app/forge_resource_manager.py:1151`), `_SUPERVISOR_WAKE_RAM_THRESHOLD=65.0` (`app/forge_resource_manager.py:1114`)

### 1.2 Topologie declarative des services essentiels (`proxy_deno/core/services.toml`)

| Service | Wave | Essentiel | Mode declare | Commande cible |
|---|---|---|---|---|
| `NokidoDenoProxy` | 2 | oui | essentiel | `${DENO}` |
| `NokidoDenoWebHub` | 5 | oui | essentiel | `${DENO}` |
| `NokidoMCP` | 1 | oui | essentiel | `${PY314}` |
| `NokidoNetcfgMCP` | 1 | oui | essentiel | `${PYTHON}` |
| `NokidoNetcfgProxy` | 1 | oui | essentiel | `${DENO}` |
| `NokidoOllama` | 1 | oui | essentiel | `${OLLAMA_EXE}` |

## 2. ETAT DYNAMIQUE — Pointeurs vers les sources vivantes (aucun chiffre fige)

> Les etats d'execution (services vivants, baux de lanes, RAM disponible, files de taches) changent en continu et ne sont jamais figes en prose.

| Dimension dynamique | Pointeur vers la source vivante | Contrat de lecture |
|---|---|---|
| Vitalite des services (port / process / heartbeat) | `nokido_agent.app.forge_sensor_fusion_probe::probe_all` et `tools/forge_feature_checklist.py::section_services` | croise `services.toml` x port x process x heartbeat |
| Baux de lanes actifs et jobs detaches | `nokido_agent.app.forge_lane_admission::current` (`LAFORGE_LANES_DB`) et `tools/forge_job_watch_cli.py --job <id>` | lecture WAL + verification sur artefact (rc != preuve) |
| Signes vitaux et pression RAM / CPU | `nokido_agent.app.forge_ssot::point`, `GET /api/vitals` et `sandbox/health_diagnostic.json` | 2 observateurs (sampler + live) avant eviction/reprise |
| Etat de la soif et propositions d'evolution | `sandbox/self_care_state.json` et `sandbox/evolution/` | suivi chronique et candidats soumis au juge |
