# Registre de substance des veilles — 2026-09-23

Direction owner : Nokido ne se mesure pas au nombre de veilles ingérées mais aux **décisions et mécanismes
vérifiables** qu'elles ont ajoutés au corps. Invariant : une veille n'ajoute JAMAIS une capacité parce qu'elle
décrit une technique ; elle ajoute une hypothèse, une décision ou une expérience tant que Nokido n'a pas apporté
la preuve.

États : **ADOPTÉ** (dans l'architecture, avec preuve) · **À EXPÉRIMENTER** (protocole mesurable, pas intégré) ·
**SURVEILLANCE** (intéressant, aucune action justifiée) · **REJETÉ** (documenté pour ne pas y revenir).
Source de chaque ligne : la fiche `docs/veilles/fiche_*_2026-09-23.md` citée ; preuves = commits / mesures du jour.

## 1. ADOPTÉ — dans le corps, preuve à l'appui

| mécanisme | veille | constat → preuve | composant | confiance | non mesuré |
|---|---|---|---|---|---|
| Un retrait (`active=0`) s'APPLIQUE à la recherche lexicale | hybride | 655 216 chunks retirés remontaient ⇒ `0690e3a84` ; témoin `CcToolchain` : 2 résultats AVANT restart, 0 APRÈS ; contrôle positif `llmlingua` OK | `forge_mcp_registry._rag_bm25_search` | haute (test + runtime) | chemin DENSE (embedders éteints) |
| Verdict de fin de job GRADUÉ, jamais le seul `rc` (`DECLARE ≠ VERIFIED`) | V2 évaluation | vague 5 `rc=0` sans bilan ; `9dfadbb3a` ; 6/6 corrects sur vrais jobs, puis en usage réel (ARRÊT de garde 6f nommé seul) | `forge_job_watch_cli.lire_bilan` | haute | l'état VERIFIED lui-même (preuve en base) |
| `journal_size_limit` : le WAL est RAMENÉ à la limite après checkpoint | SQLite/WAL | vu agir en prod : 730,6 → 64,0 Mo (17:24:55) | réglage base | haute | — |
| Lecteur long = un organe précis, corrigé À LA SOURCE (pas de nouveau mécanisme) | SQLite/WAL (« corriger CET organe ») | piège + EXPLAIN : hook post-commit 1 722 s / 58,5 Go ⇒ **1,5 s** (`24f6b1c5e`, `c1d3f99f4`, `6d2eff956`) ; 2 épisodes fermés à la sortie du dernier post_commit | `forge_post_commit`, `forge_module_cards` | haute | commit PENDANT une ingestion ; repli hub-401 (test seul) |
| Liveness adaptée à ce qu'elle protège (post_check dédié, pas un audit complet) | V1 supervision (liveness ≠ readiness) | `_vie_legere` 17 ms, table vidée détectée | hook post-commit | haute | autres appelants de `_light_health` |
| SQLite ≥ 3.51.3 sur les runtimes | dépendances / V6 | 3.53.4 (base) et 3.53.0 (py314) | environnements | haute | un env contractuel unique (à terme) |
| Flux partout, priorité mémoire basse, déclaration du besoin | RAM | appliqué avant le 23/09 | `request_resources`, jobs | moyenne | part évictible réelle des 3,6 Go Python |
| Admission / garde disque / gates | V5 homéostasie | garde 30 Go a arrêté 6f proprement 2× (rc=5, nommé) | `run_job`, ingesteur | haute | — |
| Réinjection mémoire par hooks | V3 mémoire | CONSERVÉ (vérifié efficace) | hooks session | haute | — |

## 2. À EXPÉRIMENTER — protocole mesurable, rien d'intégré

| mécanisme | veille | pourquoi pas encore | expérience / NR | composant visé |
|---|---|---|---|---|
| Cycle de vie de TÂCHE contraint (`CREATED→ACCEPTED→WORKING→COMPLETED→VERIFIED`, refus nommés) | V1 M2M | `OK_DONE` peut arriver sans `ACCEPTED` ; mais `forge_task_queue` = 0 import, état INCONNU | fonction pure `transition()` + `test_m2m_cycle_de_vie_tache_nr` ; instruire `forge_task_queue` d'abord | validateur M2M ou `forge_task_queue` |
| trace_id propagé de bout en bout | V1 observabilité | `correlation_id` = session ; `forge_trace_spine` 0 import | MESURE lecture seule d'un `run_job` réel (étape × identifiant) | `forge_trace_spine` s'il vit |
| Preuve d'exécution graduée par mécanisme (CODE → INVOQUÉ → ARTEFACT → EFFET) | self-audit (V2/V5) | instruments actuels : 1/6 vérités retrouvées, « 0 zone morte » = faux calme | transposer l'échelle de `forge_capability_contracts` ; NR de calibration | `reachability_ledger` + `WIRING_PROBES` |
| Confiance DÉRIVÉE d'une distribution sur réponses fermées + seuils par conséquence | typesafe | cascade = heuristique / auto-déclaration, seuil unique 0,6 | calibration comparée (ECE) ; préalable : logprobs locaux exposés ? | `RoutingDecision`, `forge_frugal_cascade` |
| Reranker sur nos requêtes | typesafe (rerank CLERC) | bge local = BM25 sur tâche de raisonnement (3/40 vs 2/40, 13/40 vs 15/40) | mesurer sur NOS requêtes avant de réactiver l'étage | `NokidoLlamaReranker` (disabled) |
| `forge_durable` pour la campagne de veille | V4 exécution durable | `DurableWorkflow` JAMAIS exécuté (`durable.db` absente) | expérience §5 de la fiche V4 ; idempotence du dump/raffinage à démontrer | `forge_durable` |
| Délestage côté demande (file d'admission) | RAM, V5 | refus d'admission = offre seulement | à concevoir sur `forge_bounded_queue` (existe, 0 importeur) | admission |
| Sonde « famine WAL » DANS le corps | V1 supervision (b) | le piège actuel est EXTERNE (tâche SYSTEM owner), pas un organe | signal endocrine, observer avant d'enforcer ; `test_famine_wal_signalee_nr` | homéostasie |
| Émetteur des tirs du capteur SNN (gain 32) | SNN | config 32 confirmée ; `forge_snn_monitor` n'écrit AUCUNE trace de tir ⇒ comportement prod non mesurable | émetteur mesure-seule, puis comparaison au rejeu (16/16, ~4,6 FP/j) | `forge_snn_monitor` |
| Nettoyage MDX avant ingestion | typesafe | 18/114 pages : JS inline ingéré avec la prose | NR `test_veille_sans_composant_mdx_nr` ; moteur `C:/tmp/veille_urls.py` NON versionné | moteur de veille |
| Typage épisode / fait / règle + validité temporelle | V3 mémoire | après mesure (a) de la fiche | — | mémoire |
| Banc de pannes à partir des incidents RÉELS | V6 infra | crash hot-swap, WAL, disque = matière disponible | DETECTED/RECOVERED/LOST/TTR | infra |
| Intensité de redémarrage MaxR/MaxT explicite | V1 supervision (a) | respawn refusé 11× (16/07) = garde, pas contrat | lecture de `supervisor.ts` | superviseur |

## 3. SURVEILLANCE — intéressant, aucune action justifiée aujourd'hui

| sujet | veille | raison |
|---|---|---|
| Jeton d'idempotence, bail + fencing token, dead-letter queue | V1 M2M | phase suivante, dépend du cycle de vie de tâche |
| Noms d'attributs OTel GenAI (`gen_ai.*`) | V1 observabilité | aligner APRÈS la mesure de propagation |
| Threadpool Starlette (alerte à 40 threads) | dépendances | aucun incident mesuré qui l'implique |
| Circuit breaker hub ↔ organes | V1 supervision | à VÉRIFIER dans `forge_agent_proxy` avant d'affirmer l'absence |
| Boucle P→E (proposer → appliquer) | V5 | `forge_proposal_applier` existe, désarmé : armement = geste owner |
| Corpus de code 6f (dépôts ingérés) | 6f | corpus de RÉFÉRENCE ; aucune substance mécanisme extraite à ce jour — ne pas le compter comme capacité |

## 4. REJETÉ — pour ne pas y revenir

| sujet | veille | raison |
|---|---|---|
| API cloud TypeSafe / Jev comme dépendance | typesafe | propriétaire, limites instables, contraire au local-first ; réexaminable sur mesure + feu vert owner |
| « Gain SNN ×32 » comme accélération à reproduire | SNN | contresens : 32 est le GAIN du capteur LIF (`d7a130d91`), pas un speedup |
| « 12,2× moins cher » comme avantage d'un modèle | typesafe | arithmétique générique (document envoyé une fois) ; vrai pour tout modèle facturé à l'entrée |
| TRUNCATE plus agressif du WAL | SQLite | tient le verrou d'écriture, a provoqué des `database is locked` |
| Cross-encoder thématique comme étage de précision sur requêtes de raisonnement | typesafe (rerank) | = BM25 mesuré ; ne pas supposer un gain |

## 5. Tableau de bord (ce que les veilles ont RÉELLEMENT ajouté au corps le 23/09)

- **ADOPTÉ avec preuve** : 9 mécanismes, dont 4 nouveaux dans le code aujourd'hui (filtre actif, verdict gradué,
  hook sans balayage ×3, liveness dédiée) — tous avec NR et, pour 3 d'entre eux, observation en production.
- **À EXPÉRIMENTER** : 13 protocoles, chacun avec sa mesure ou son NR nommé ; **aucun** intégré sans preuve.
- **REJETÉ** : 5, dont 2 contresens de lecture évités (×32 SNN, 12,2× TypeSafe).
- **Non encore extrait** : la substance mécanisme du corpus 6f (dépôts de code) — ingéré ≠ compris.
