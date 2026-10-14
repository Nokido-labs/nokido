# Fiche de sortie — Veille V8 « Priorité, tables de reprise par phases & délestage sous surcharge (AGC Luminary099) » (2026-10-13)

Rédigée par AGY (branche `agent/antigravity`, commit `11f842332`) ; revue et corrigée par Claude le 2026-10-13
(Executive d'après ses commentaires d'origine, existant Nokido complété, GAP 1 rectifié).

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1 (supervision & reprise de job), V4 (exécution durable & store SQLite), V5 (homéostasie, délestage & éviction) et V7 (DAG, OneMCPMultiplexer & conscience opérationnelle).

## 1. PATTERNS (sources RAG : `raw.githubusercontent.com/chrislgarry` Luminary099, `doneyles.com` Tales, `ALSJ` a11.1201-pa, `wikipedia` AGC)

| Pattern | Source primaire | Mécanisme & Enseignement |
|---|---|---|
| **Executive à priorités, coopératif** | Luminary099 `EXECUTIVE.agc` (`NOVAC`, `FINDVAC`, `CHANGJOB`, `PRIOCHNG`, `ENDOFJOB`, `JOBSLEEP`/`JOBWAKE`) | Les commentaires d'origine : `NOVAC` = « demande de job SANS zone VAC », `FINDVAC` = « demande de job AVEC zone VAC (jobs interprétés) », `CHANGJOB` = « suspendre un job pour qu'un job plus prioritaire soit servi » — le job courant CÈDE la main à des points prévus (échange du core set 0 avec `NEWJOB`), il n'est pas préempté n'importe où. `PRIOCHNG` change une priorité et rescanne ; `ENDOFJOB` libère core set et zone VAC puis sert la plus haute priorité active. Ressources BORNÉES : core sets et zones VAC en nombre fixe. |
| **Waitlist temporelle (tâches courtes différées)** | Luminary099 `WAITLIST.agc` | Tâches courtes exécutées sous interruption d'horloge sans core set ; elles se replanifient elles-mêmes ou lancent un job long par l'Executive (Wikipedia AGC). Distinction fondamentale entre *tâche temporisée légère* et *job d'arrière-plan*. |
| **Tables de reprise par groupes et phases (`Restart Protection`)** | Luminary099 `RESTART_TABLES.agc`, `FRESH_START_AND_RESTART.agc` | Chaque groupe de redémarrage retient sa PHASE courante ; après un GOJAM, le logiciel « redémarre tout programme qui tournait à ce moment » d'après les tables (ex. du source : « un redémarrage du groupe 5 en phase 7 relance SOMEJOB en FINDVAC, priorité 23 ») ; certains groupes sont vidés, d'autres préservés (« tous sauf le groupe 2 »). |
| **Saturation nommée (`1201 / 1202`) puis BAILOUT** | `ALARM_AND_ABORT.agc`, Eyles | 1202 = core sets épuisés (« Executive alarm, no core sets »), 1201 = zones VAC épuisées. Au lieu de geler, l'AGC lève une alarme NOMMÉE et redémarre : seuls les travaux inscrits aux tables repartent de leur phase. Règle décidée AVANT le vol : 1202 « go » sauf si trop fréquente ou trajectoire déviée. |
| **Vol de cycles par un périphérique** | Don Eyles (*Tales*), ALSJ a11.1201-pa | Pendant Apollo 11, l'interface du radar de rendez-vous volait environ 13 % du cycle (Eyles) ; le guidage a continué, l'affichage de basse priorité a été délesté. |

## 2. NOKIDO_EXISTING (vérifié dans le CODE par MCP, fichier:ligne)

- **`app/forge_event_stream.py:109-115`** : `_PRIORITY = {"deadline": 0, "user_msg": 1, "system": 2, "tool_result": 3, "external": 4}` — ordonnancement par priorité discrète dans la boucle réactive. → **VERIFIED** (suites `test_event_stream`). NB : la sonde du chemin chaud a mesuré 0 événement sur ce bus en 5 min (13/10) : ce n'est pas le chemin réel des requêtes du hub.
- **`app/forge_runtime.py:108-110`** : `PRIO_USER = 0`, `PRIO_WARMUP = 5`, `PRIO_BACKGROUND = 10` — `PriorityQueue` ZeroMQ vers `brain_worker.py`. → **VERIFIED** (port :5557 éteint par politique depuis le 03/06).
- **`app/forge_autonomous_orchestrator.py:118-123`** : `AGENT_PRIORITY` par criticité dans le DAG. → **DECLARED** (pas de préemption d'un nœud en cours ; ASL ≥ 4 requis pour l'outil MCP).
- **`app/forge_durable.py:30-45`** : `durable_steps` / `durable_runs` sur SQLite, reprise à la première étape incomplète. → **DECLARED** (analogue d'étape, pas de phase systémique ; non adopté par la chaîne de veille).
- **Reprise par sous-phase de la chaîne de veille** : `agent_chain_nodes` (statut par étape) et `crawl_fait` (reprise du crawl par URL, `app/forge_chain_executor.py` `_call_crawl`). → **VERIFIED** (NR `test_veille_reprise_et_budget_nr`).
- **Délestage du superviseur par COÛT** (commit `d2f9ab6be` « la rafale RAM déleste par coût et ne fauche plus la régulation ») : sous rafale RAM, les services sont délestés selon leur coût. → **DECLARED** (implémenté ; effet en charge à mesurer).
- **Gardes d'admission** : gate P1 (`app/forge_sandbox_exec.py` `spawn_as_sandbox`) et réveil de Docker (`tools/forge_ensure_service.py` `_ram_pct`) refusent sur la RAM. → **MEASURED** le 13/10 : la RAM oscille de 69 à 90 % en quelques minutes ; les deux gardes ont décidé sur un INSTANT (97,6 % puis 87,7 %), démenti 20 s plus tard. Second observateur ajouté au gate P1 (`ff41b0fee`).
- **`app/forge_bounded_queue.py`** : file bornée (`BoundedQueue`) et écrivain différé (`EcrivainDiffere`). → **VERIFIED** : `EcrivainDiffere` est importé par `app/forge_intention_journal.py:27` et `app/forge_promcp_profiler.py:63`, `BoundedQueue` par `tools/forge_handoff_worker.py:128` (la mention « importé par PERSONNE » de `RULES_SHARED.md` est périmée).
- **`app/forge_hormones.py:178-194`** : `q.put_nowait()` + `except Exception: pass` — une hormone jetée faute de place n'était ni comptée ni dite. → **MEASURED** (corrigé le 13/10 : compteur `evenements_jetes` exposé dans `system_state()`).
- **Pool `to_thread` du hub** (`sandbox/hotpath_probe_rapport.json`) : file d'attente 0 sur 564 échantillons, 5 threads occupés au plus sur 20. → **MEASURED** (le travail lourd est déporté hors du hub : le hub n'est pas le goulet).
- **`app/forge_session_context.py`** (osmorégulation, branche `agent/antigravity`) : en revue (3e passage : écrivain RAG hors voie gouvernée). → **DECLARED** tant qu'elle n'est pas fusionnée.

## 3. EVIDENCE

| Élément | Niveau | Justification / Mesure |
|---|---|---|
| Priorité d'événements (`deadline` > `user` > `external`) | **VERIFIED** | `forge_event_stream.py:109` |
| Reprise par sous-phase (chaîne de veille) | **VERIFIED** | `agent_chain_nodes`, `crawl_fait`, NR de reprise |
| Charge du pool `to_thread` du hub | **MEASURED** | sonde : file 0, 5/20 threads |
| Oscillation de la RAM sous charge réelle | **MEASURED** | campagne du 13/10 : 69-90 % en quelques minutes |
| Gardes d'admission décidant sur un instant | **MEASURED** | 2 refus le 13/10 démentis par deux observateurs |
| Délestage par coût du superviseur | **DECLARED** | effet sous charge non mesuré |
| Alarme nommée sur saturation (type 1201/1202) | **partielle** | hormones jetées désormais comptées ; ailleurs, files pleines encore muettes |
| Table de phases macro du système | **absente** | aucun registre ne dit dans quelle « phase de vol » le corps opère |

## 4. GAPS

1. **Les gardes décident sur un INSTANT d'un signal en rafales.** Le délestage existe (superviseur, par coût) ; ce qui manque est la distinction AGC entre surcharge SOUTENUE (délester) et PIC (laisser passer) : décider sur une fenêtre courte, pas sur un échantillon.
2. **Saturation muette vs alarme nommée** : une file pleine doit compter et dire ce qu'elle jette (fait pour les hormones le 13/10 ; à étendre aux autres files bornées).
3. **Pas de phases macroscopiques** : `forge_durable.py` gère des étapes fines, pas des phases de mission indiquant ce qui survit à un redémarrage et ce qui est sacrifiable.

## 5. MINIMAL_EXPERIMENT (pure, 0 réseau, sans écrivain RAG)

Ordonnanceur pur `PhasePriorityScheduler` dans une fixture : trois phases (`BOOT`, `MISSION_CRITIQUE`, `MAINTENANCE`), cinq emplacements ; afflux de tâches basses et une tâche vitale ; à saturation, alarme typée `ALARM_OVERFLOW_1202`, purge des basses, phase courante conservée, tâche vitale servie.

## 6. NR

`test_agc_phase_preemption_et_delestage_1202_nr` : (1) une saturation lève une alarme typée, jamais un rejet muet ; (2) sous saturation, `P_CRITICAL` servie et `P_LOW` purgée ; (3) la phase enregistrée survit à la purge.

## 7. DECISION

- **CONSERVER** les priorités de `forge_event_stream.py` et de `forge_runtime.py`.
- **COMPLÉTER** les files internes : compter et dire ce qui est jeté (hormones faites le 13/10).
- **DÉCIDER SUR FENÊTRE** dans les gardes d'admission (gate P1, réveil Docker) : plancher des dernières secondes plutôt qu'un échantillon.
- **ADOPTER** les tables de reprise par phase pour les workflows lourds (moisson, ingestion, validation).
- **NE PAS** introduire d'ordonnanceur préemptif dans le hub : sa file est vide sous charge réelle, le travail lourd est déjà déporté.
