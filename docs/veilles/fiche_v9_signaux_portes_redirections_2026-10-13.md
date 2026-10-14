# Fiche de sortie — Veille V9 « Signaux réactifs, portes logiques temporelles & redirections de flux (MARI / Kaonomi) » (2026-10-13)

Rédigée par AGY (branche `agent/antigravity`, commit `fc983da9a`) ; revue et corrigée par Claude le 2026-10-13
(existant Nokido complété : causalité de la moelle, modes ombre, quorums ; niveaux de preuve rectifiés).

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1 (m2m, supervision), V5 (homéostasie, système endocrinien & SNN), V6 (infrastructure & bus d'événements) et V7 (orchestration, conscience opérationnelle & routage).

## 1. PATTERNS (sources RAG : `github.com/kaonomi-net/mari` README, samples Forex, RelayFilterDoor, Redirections, Blackboard, Streams)

| Pattern | Source primaire | Mécanisme & Enseignement |
|---|---|---|
| **Signaux légers typés (`Signals`)** | MARI `MARI.Framework.Core.Abstractions.Signals`, `ISignalService` | Événement réactif asynchrone découplé portant un identifiant et une charge typée minimale (`SignalDefinition`, `SignalMessage`). Recommandation MARI : rattacher des identifiants simples et non de gros objets. |
| **Portes logiques temporelles (`Doors & LogicalAggregators`)** | MARI `MARI.Framework.Core.Abstractions.Doors`, sample Forex `Program.cs` | Une porte (`DoorDefinition`) agrège plusieurs signaux sur une fenêtre glissante (`TimeSpan.FromSeconds(T)`), évalue une expression booléenne (`(A and B) or C` via `UseLogicalAggregator`) et ne déclenche l'aval que si la conjonction temporelle est satisfaite. |
| **Porte filtre-relais (`RelayFilterDoor`)** | MARI `samples/RelayFilterDoor` | Condition sur la charge du signal (type, seuil) : vérifiée → relayé vers une séquence ou un stockage dédié ; sinon filtré. |
| **Redirections d'implémentation (`Redirections`)** | MARI `samples/Redirections` | Changer à la volée l'implémentation résolue pour un grain/service sans toucher aux appelants : *localement* (un appel, variante A/B) ou *globalement* (bascule de secours). |
| **Découplage Déclencheur → Séquence** | MARI `Sequence.Build()`, `Trigger.Cron()`, `Trigger.Stream()` | Séparation entre ce qui déclenche (horloge, flux, porte) et la chaîne d'action ordonnée (`Use<T>().Call().Return`). |

## 2. NOKIDO_EXISTING (vérifié dans le CODE, fichier:ligne)

- **`app/forge_byte_router.py:225-257`** : anticipation d'outils (`_anticipate_tools`), métadonnées (`_br_ts`, `_br_agent`), sonde passive `on_tool_call`, plafonds de débit (`_RATE_LIMITS` → `PermissionError`). → **VERIFIED**.
- **`app/forge_event_stream.py:468-485`** : `to_byte_router_sentinel(event)` → sentinelle binaire de 13 octets (`kind_code + eid_bytes + ts_hash`). → **VERIFIED** (format) ; NB : la sonde du chemin chaud a compté 0 événement sur ce bus en 5 min le 13/10 — ce n'est pas le chemin réel des requêtes du hub.
- **`app/forge_snn_monitor.py:63, 112, 166-174`** : 3 neurones LIF (`snn.Leaky(beta=0.95)`), intégration de l'écart au seuil (`_ecart * _SNN_GAIN`), réfractaire de 1800 s (`_REFRACTORY_S`). → **MEASURED** (19 099 échantillons rejoués, 16 épisodes de détresse ; le gain 32 est un gain de capteur, pas un speedup).
- **`app/forge_hormones.py`** (`subscribe`, `_push_to_subscribers`, `_expires_at`) : demi-vie, actif jusqu'à `3 * half_life`, diffusion vers `_SUBSCRIBERS` avec `_redact_dict`. → **VERIFIED** ; depuis `8c9832c28` (13/10) les événements jetés faute de place sont comptés (`system_state()["evenements_jetes"]`) au lieu d'être perdus en silence.
- **`app/forge_trace_spine.py:232-239`** (moelle) : chaque registre déclare ses `cles_causales` (`session_id` ; `corr_id`, `parent_id` ; `correlation_id`) — la corrélation de signaux entre organes passe déjà par des clés causales explicites, alimentées par `forge_organ_afferent.emettre`. → **VERIFIED** (oubli de la version AGY).
- **Modes OMBRE (champion/challenger d'une décision)** — oubli de la version AGY :
  - `app/forge_authz_shadow.py:1-35` : observation d'autorisation sur :8766, « SHADOW, ne refuse RIEN », verdicts `SHADOW_ALLOW` / `SHADOW_DENY` / `AUTHZ_UNKNOWN` ;
  - `app/forge_swarm_router.py:55` : « MODE SHADOW par défaut : la décision est calculée et rendue, JAMAIS appliquée » ;
  - `app/forge_rag_truth.py:14-24` : « Triple Validation + Shadow Index ».
  → **VERIFIED** : un nouveau régime de décision se fait déjà tourner À CÔTÉ de l'ancien avant d'être promu — c'est la moitié « évaluation de variante » des `Redirections` MARI.
- **Quorums multi-observateurs** : `app/forge_rag_truth.py` (9 occurrences de `quorum`), `app/forge_swarm_router.py` (2). → **VERIFIED** (oubli de la version AGY). S'y ajoute la doctrine « une sonde unique ne décide pas » (`RULES_SHARED.md`).
- **Conjonction de deux observateurs, ad hoc** : `app/forge_sandbox_exec.py` `_ram_dementie` (commit `ff41b0fee`, 13/10) — le refus RAM du gate P1 est annulé si la mesure directe (GlobalMemoryStatusEx) le dément. → **VERIFIED** ; c'est exactement une porte `AND` à deux signaux, mais écrite à la main dans un seul module.
- **`app/forge_engrid_engine.py:12`** : `_apply_lateral_inhibition → Reconciler + veto silo PAYLOAD`. → **DECLARED** (veto inter-perspectives, pas une porte combinatoire temporelle).
- **`app/forge_cognitive_router.py`** : cascade (`call_cascade`) et redirection d'inférence local/cloud selon quota et complexité. → **VERIFIED**.
- **Blackboard partagé** (`blackboard_read_zone`, `blackboard_propose_fact`), zone `discovered_facts`. → **VERIFIED** (usage) ; le compte de « 124 faits » est celui d'AGY, non re-mesuré ici.
- **Pool `to_thread` du hub** (`sandbox/hotpath_probe_rapport.json`) : file 0 sur 564 échantillons, 2 à 5 threads occupés sur 20. → **MEASURED**. L'écriture RAG synchrone dans la boucle asyncio relevée par la revue d'osmorégulation (`bb:discovered_facts:revue_claude_osmoregulation_*`) porte sur `forge_session_context.py` de la branche AGY, NON fusionnée : sa correction est **DECLARED** tant que la revue n'est pas close.

## 3. EVIDENCE

| Élément | Niveau | Justification / Mesure |
|---|---|---|
| Sentinelle binaire 13 octets | **VERIFIED** | `forge_event_stream.py:468` |
| Détection d'impulsions LIF avec réfractaire | **MEASURED** | `forge_snn_monitor.py`, 19 099 mesures rejouées |
| Signalisation hormonale à demi-vie, pertes comptées | **VERIFIED** | `forge_hormones.py`, `8c9832c28` |
| Clés causales entre registres de la moelle | **VERIFIED** | `forge_trace_spine.py:232-239` |
| Variante évaluée en ombre avant promotion | **VERIFIED** | `forge_authz_shadow.py`, `forge_swarm_router.py:55`, `forge_rag_truth.py` |
| Quorum d'observateurs | **VERIFIED** | `forge_rag_truth.py`, `forge_swarm_router.py` |
| Redirection d'inférence | **VERIFIED** | `forge_cognitive_router.py` |
| Porte `AND` à deux signaux | **ad hoc** | `forge_sandbox_exec._ram_dementie`, un seul module |
| Porte temporelle GÉNÉRIQUE (fenêtre + expression) | **absente** | chaque conjonction est réécrite dans son module |
| Redirection d'implémentation d'un outil MCP | **absente** | l'ombre existe pour des DÉCISIONS (authz, routage swarm), pas pour l'implémentation d'un outil |

## 4. GAPS

1. **Pas de porte temporelle composable.** Les briques existent (quorums, clés causales, second observateur, LIF) mais chaque conjonction est écrite à la main dans son module : le second observateur RAM du gate P1 n'est pas réutilisable par l'admission de `forge_ensure_service`, qui décide encore sur un instant. Une porte `(A and B) dans T s` réutiliserait le même prédicat partout.
2. **Signal et stockage synchrone** : un signal ne doit pas porter d'I/O lourde sur la boucle réactive (cas `forge_session_context.py` en revue). MARI : identifiants légers, travail lourd après la porte.
3. **Ombre limitée aux décisions** : l'évaluation en ombre existe (authz, swarm, vérité RAG) mais pas pour l'IMPLÉMENTATION d'un outil MCP (`rag`, `search`) ; une variante d'outil ne peut pas tourner à côté de la version servie sans toucher au registre.

## 5. MINIMAL_EXPERIMENT (pure, 0 réseau, sans écrivain RAG)

`TemporalDoorEngine` dans une fixture : signaux `SIG_PRESSURE_RAM` et `SIG_WAL_BUSY` ; porte `DOOR_EVICTION_TRIGGER` en `AND` sur 1,0 s ; `SIG_PRESSURE_RAM` à t0 → porte FERMÉE ; `SIG_WAL_BUSY` à t0 + 0,4 s → porte OUVERTE ; `SIG_WAL_BUSY` à t0 + 2,5 s seul → FERMÉE. Premier client réel visé : la décision RAM du gate P1 et de l'admission Docker (même prédicat, deux sites).

## 6. NR

`test_mari_porte_logique_temporelle_signaux_nr` : (1) une porte `AND` ne s'ouvre jamais sur un seul signal ; (2) elle ne s'ouvre que si tous les signaux coïncident dans la fenêtre ; (3) l'impulsion produite est légère (identifiant de porte + horodatage), découplée de l'exécution aval ; (4) un signal ILLISIBLE n'ouvre ni ne ferme la porte : il la rend `UNKNOWN`, dit.

## 7. DECISION

- **CONSERVER** la sentinelle 13 octets, le LIF, les clés causales de la moelle, les modes ombre et les quorums : ce sont les briques d'une porte, déjà là.
- **ÉTENDRE, ne pas créer à côté** : la porte temporelle factorise les conjonctions existantes (second observateur RAM d'abord) ; son emplacement se choisit après `introspect` sur le domaine (moelle ou endocrine), pas dans un module neuf parallèle.
- **GARDER** les signaux légers : aucune I/O synchrone lourde à l'émission.
- **ÉTENDRE l'ombre** aux implémentations d'outils seulement sur besoin mesuré (une variante d'outil réellement candidate).
- **NE PAS** implémenter de framework d'acteurs virtuels (type Orleans / MARI C#).
