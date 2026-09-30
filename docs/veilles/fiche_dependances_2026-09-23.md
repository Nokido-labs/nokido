# Fiche de sortie — Veille Dépendances (v2 2026-09-27 ; v1 2026-09-23)

Corpus : `watch:deps:` — 35 pages, 1 850 chunks actifs, 0 chunk `active=0` écarté
(dossier `sandbox/workspace/veille_fiches_dossier_2026-09-27.md`, job `job_8a190f5556bb`).
**Limite DITE** : PATTERNS = ce que chaque page annonce (extrait porteur lu) ; le contenu des changelogs n'a PAS été
relu — une rupture non citée ici n'est pas absente. Les annotations « (N modules) » viennent du sujet rédigé à
l'ingestion (inventaire `C:/tmp/dependances_nokido.json`, 23/09) : DECLARED, pas mesuré ce jour.

## 1. PATTERNS
| # | Pattern | Source |
|---|---|---|
| D1 | Rupture de version majeure à migrer (API retirées, dépréciations) | `numpy.org/…/numpy_2_0_migration_guide` (103 modules) ; `cryptography.io/…/changelog/` ; notes de version starlette, playwright, faiss, asyncssh (19 modules) |
| D2 | Python 3.14 et build sans GIL (free-threading) | `docs.python.org/3.14/whatsnew/3.14` ; `…/howto/free-threading-python` |
| D3 | Boucle asyncio bloquée : mode debug, `run_in_executor` | `…/library/asyncio-dev` ; `…/library/asyncio-eventloop` |
| D4 | Pools BORNÉS : threadpool (FastAPI, Starlette), pool de connexions (httpx), connecteurs et timeouts (aiohttp, 47 modules) | `fastapi.tiangolo.com/async/` ; starlette `threadpool.md` ; `python-httpx.org/advanced/resource-limits/` ; `docs.aiohttp.org/…/client_advanced` |
| D5 | Sur-souscription de threads natifs | `onnxruntime.ai/…/threading`, `…/memory` ; PyTorch `threading_environment_variables.md` |
| D6 | Sémantique transactionnelle sqlite3 (autocommit, isolation_level) | `docs.python.org/3/library/sqlite3` |
| D7 | Routage LLM avec repli | `docs.litellm.ai/docs/routing` |
| D8 | Permissions et modules du runtime du superviseur | `docs.deno.com/…/security/`, `…/modules/` |
| D9 | Paquet importé mais absent d'un runtime | pyzmq (annotation d'ingestion « 28 modules, NON installe » — CORRIGÉE par la mesure du 27/09, section 2) |

## 2. NOKIDO_EXISTING
| Pattern | fichier:ligne | Constat |
|---|---|---|
| audit CVE | `tools/forge_pip_audit_mesure.py:84` `_sortie` ; `:51` `enveloppe_meta` | pip-audit en JSON, rapport attaché à SON environnement. PRÉSENT. |
| réconciliation | `tools/forge_deps_reconcilier.py:11`, `:75` `rapport_courant` | croise MANIFESTE (`requirements*.txt`), ENVIRONNEMENT et pip-audit ; lit le rapport le plus récent (piège payé le 07/09). PRÉSENT. |
| re-mesure périodique | `app/forge_circadian.py:234` `_mesurer_dependances_vulnerables` | pip-audit déporté (egress) par le rythme circadien. PRÉSENT. |
| CI | `tools/ci_local.py` (dimension code, `tools/forge_full_audit.py:8`) | pip-audit dans la CI locale. PRÉSENT. |
| bilan CVE | commit `dd63687e4` (07/09) | 45 CVE → 11, litellm importable hors ligne. MEASURED à cette date. |
| propagation CVE | `app/forge_graph_cve_propagation.py:9` `propagate_cve` ; `tools/forge_cve_propagation_graph.py:46` `CVEPropagationGraph` | DEUX implémentations — doublon probable, à instruire par le census. |
| source CVE | `tools/forge_cve_rag_ingest.py:14` `NVD_URL = …/json/cve/1.1/nvdcve-1.1-recent.json.gz` | **MEASURED 27/09 : 403 Forbidden**, alors que l'API 2.0 du même hôte répond 200 depuis le même compte (`services.nvd.nist.gov/rest/json/cves/2.0`, utilisée par `forge_cve_nvd_download.py`) : le flux est refusé, pas le réseau. OSV (`forge_cve_osv_fallback.py`) : 405/404 attendus sur HEAD (point POST, chemin paramétré) — non concluant, pas une panne. Mesure : `sandbox/workspace/mesure_nvd_flux_2026-09-27.json`. |
| veille des ruptures | `app/forge_ingest_pipeline.py:116` catégorie `watch_alerts` (release, changelog, breaking, deprecated, advisory, cve) | PRÉSENT mais NON ALIMENTÉ depuis le 19/09 : `NokidoRSSWatcher` refusé GATE_DENIED, ring 4 contre ring 3 requis (bb P2 `veille_watch_alerts_gate_denied_2026-09-24`). |
| runtimes (v1) | miniforge base (SQLite 3.53.4 depuis le 23/09) · `laforge_py314` (3.53.0) | OBSERVED le 23/09. |
| threadpool (v1) | Starlette à 40 | la v1 le disait MEASURED ; mesure d'origine non retrouvée le 27/09 → DECLARED. |
| pyzmq (D9) | :5557 DISABLED depuis 2026-06-03 | **MEASURED 27/09 (AST, app/ + tools/)** : `zmq` installé dans miniforge base, ABSENT de `laforge_py314`. 32 importeurs (pas 28) : 18 import différé gardé, 3 gardés au niveau module, 5 différés NON gardés, **6 cassent à l'import** sous py314 — dont `tools/forge_embed_backfill_brain.py:19` et `tools/forge_rag_llama_query.py:33` ; les 4 autres sont des `tools/tmp_*`. Mesure : `sandbox/workspace/mesure_pyzmq_2026-09-27.json`. |

## 3. EVIDENCE
- **MEASURED** : 45 → 11 CVE (07/09) ; SQLite 3.51.1 → 3.53.4 dans miniforge (23/09, geste owner).
- **PRÉSENT** : outils de la section 2, lus en recon le 27/09, non exécutés.
- **DECLARED** : comptes d'importeurs par paquet (inventaire d'ingestion du 23/09) ; threadpool à 40.

## 4. GAPS
1. **Veille des ruptures aveugle depuis le 19/09** : 35 dépendances suivies, aucune alerte possible tant que
   `watch_alerts` n'est pas alimenté. Déjà P2 au blackboard.
2. **pyzmq selon le runtime** : 2 outils réels et 4 scripts `tmp_*` cassent à l'import sous `laforge_py314` ; 5 autres
   cassent à l'appel. Quel runtime lance ces outils : non mesuré.
3. **Source CVE NVD 1.1 refusée (403)** — FERMÉ le 27/09. `forge_cve_rag_ingest` n'échouait PAS en silence :
   `_download` laissait remonter l'`HTTPError` (code lu, aucun `except`). Aucun appelant trouvé (app/, tools/,
   services.toml, lanceurs .ps1). Outil GELÉ : il refuse en le disant, avant réseau et base, et nomme son
   successeur `forge_cve_nvd_download` (API 2.0).
4. **Deux modules de propagation CVE**.
5. **Aucun budget global de threads** (D4, D5) : threadpool Starlette + ORT + PyTorch + asyncio sur la même machine,
   jamais mesurés ensemble (cf. l'incident du GIL tenu 47 % du temps, RULES_SHARED).
6. (v1) Écart SQLite 3.53.4 / 3.53.0 entre runtimes, sans NR de version.

## 5. MINIMAL_EXPERIMENT (lecture seule ; rien d'armé sans feu vert owner)
a. FAIT 27/09 (`job_38ae24b76cca`) — classement STATIQUE des imports (AST) plutôt qu'un import à froid, qui aurait
   exécuté le code des modules (effets de bord) : résultats en section 2.
b. FAIT 27/09 (`job_61e4751ff67e`) — HEAD puis GET d'un octet, URL lues dans les sources : NVD 1.1 → 403, API 2.0 → 200.
c. (v1) Écritures et lectures WAL concurrentes depuis les deux runtimes : banc de contention de la fiche V6.

## 6. NR (rouge d'abord)
- ÉCRIT 27/09 : `tests/nr/test_cve_ingest_nvd11_gele_nr.py` (déclaré dans `PURE_TESTS`) — `run()` lève `OutilGele`
  avant tout `urlopen` et sans créer la base ; le `__main__` rend un code non nul, dit « GELÉ » et nomme
  `forge_cve_nvd_download`. Rouge (les deux chemins tentaient le réseau) puis vert. Remplace le NR prévu
  `test_source_cve_muette_n_est_pas_zero_cve`, devenu sans objet : l'outil n'était pas muet.
- (v1) Avertissement au démarrage si la version SQLite d'un runtime s'écarte de la version de référence.

## 7. DECISION
- **FAIT 27/09 (accord owner)** : `forge_cve_rag_ingest` GELÉ au profit de `forge_cve_nvd_download` (API 2.0),
  plutôt que repointé — le successeur existe déjà ; en écrire un second serait un doublon. NR ci-dessus.
- **Décision owner** : les 2 outils zmq non gardés → garder l'import, ou fixer leur runtime (miniforge).
- **ADOPT (geste owner)** : rendre à `NokidoRSSWatcher` le ring requis (gap 1, déjà au blackboard).
- **DEFER** : free-threading 3.14t (D2), pas avant d'avoir mesuré la contention du GIL et la compatibilité des
  extensions C (numpy, onnxruntime, faiss) ; budget global de threads (gap 5), mesurer d'abord ; doublon CVE
  (gap 4), census puis geler l'un — jamais supprimer.
- **REJECT** : mettre à jour une dépendance automatiquement à la lecture d'un changelog — contrat V6 : jamais de
  modification automatique d'une découverte.
- **(v1, maintenu)** : standardiser SQLite 3.53.4 sur les runtimes — geste owner (conda).
