# Fiche de sortie — Veille V4 « Exécution durable / orchestration » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1 (reprise de job non automatique), V2 (grader d'issue), V3 (état de campagne hors contexte).

## 1. PATTERNS (`watch:durable:%`, + LangGraph checkpoints `watch:agents_longs:%`)

| Pattern | Source |
|---|---|
| Workflow = code déterministe + **historique d'événements** ; reprise = REJEU de l'historique, les activités déjà faites ne se ré-exécutent pas | Temporal workflows, event history |
| **Timers durables** (une attente survit au redémarrage) | Temporal timers |
| Exécution durable adossée à une **base SQL** (étapes enregistrées transactionnellement) | DBOS architecture ; Restate |
| *Pending writes* : les écritures des nœuds réussis d'une étape sont gardées pour ne pas les rejouer si un nœud frère échoue | LangGraph checkpoint README |
| **Saga** : chaque étape a sa compensation ; **outbox** transactionnel (état + message dans la même transaction) | microservices.io |
| **Consommateur idempotent** ; « exactly-once » = at-least-once + idempotence | microservices.io ; Confluent |
| Verrou distribué + **fencing token** | Kleppmann |

## 2. NOKIDO_EXISTING

- **`app/forge_durable.py`** : « durable execution (Temporal pattern) on Nokido SQLite » — workflow reprenable par
  `run_id`, rejoue les étapes terminées depuis le store, reprise après crash de `forge_chain_executor`, API d'adoption
  (liste d'étapes → `{nom: résultat}`). 0 import statique ; mentionné par `forge_chain_executor`, `forge_mcp_registry`,
  `tools/forge_durable_workflow.py` → invocation à ÉTABLIR.
- `forge_chain_executor` : reprise du crawl par URL + deadline globale (PROUVÉ 30/08).
- `run_job` : détaché, survit au redémarrage du hub (MESURÉ aujourd'hui : `job_e9ebab46c04e` a survécu à la relance),
  lanes, cap RSS, `.rc` / `.json` / `.log`.
- Idempotence des ingestions : `chunk_id = sha256(source+texte)` + `INSERT OR IGNORE` (reprises sans doublon,
  MESURÉ aujourd'hui : passes « +0 chunks, N skip »).
- Prefect : importé par **11 modules**, **NON installé** (inventaire du jour) → imports optionnels ou code mort/cassé : INCONNU.

## 3. EVIDENCE

| Élément | Niveau |
|---|---|
| `run_job` survit au redémarrage | **MEASURED** (23/09) |
| Idempotence des ingestions | **MEASURED** (23/09) |
| Reprise `forge_chain_executor` | **VERIFIED** (NR PROUVÉ 30/08) |
| `forge_durable` (rejeu d'étapes) | **DECLARED** — utilisé en production ? non établi |
| Reprise AUTOMATIQUE d'un job tué | **absente** — 6 relances MANUELLES aujourd'hui (RSS, verrou, disque) |

## 4. GAPS

1. **Les jobs de veille ne sont pas des workflows durables** : la campagne d'aujourd'hui (dump → contrôle → ingestion)
   est une suite de scripts relancés à la main ; la brique `forge_durable` existe mais n'est pas adoptée par eux.
2. Pas de **compensation** : un dump écrit puis refusé à l'ingestion n'a pas d'étape de retour (aujourd'hui : suppression
   manuelle du dump tribixbite).
3. Prefect : 11 importeurs d'une dépendance absente — dette à instruire (ne pas l'installer par réflexe).

## 5. MINIMAL_EXPERIMENT (sans écrivain RAG)

Lire `forge_durable` + `tools/forge_durable_workflow.py` et ses LOG : qui l'appelle, quand, avec quels `run_id` —
statut réel (VIVANT / INVOQUÉ / DORMANT). Puis, sur fixture : une campagne de 3 étapes factices, tuée entre 2 et 3,
relancée avec le même `run_id` → l'étape 1-2 n'est PAS rejouée.

## 6. NR

`test_campagne_veille_durable_rejeu_nr` : invariant « relancer une campagne avec le même run_id ne ré-exécute aucune
étape terminée et reprend la première non terminée » (fixture, 0 réseau, 0 écriture RAG).

## 7. DECISION

- **ADOPTER l'existant** (`forge_durable`) pour la campagne de veille si l'expérience §5 le confirme — surtout ne pas
  écrire un second moteur (règle anti-dup ; Temporal/DBOS = références de conception, pas des dépendances).
- UNKNOWN : usage réel de `forge_durable` ; 11 importeurs de Prefect.
- Lien V1/V2 : V1 « reprise de job non automatique » ⇒ `forge_durable` est la brique candidate ; V2 fournit le grader
  qui dit si l'étape est RÉUSSIE (et pas seulement terminée) avant de la marquer faite dans l'historique.
- Contre-preuve à chercher : un rejeu n'est sûr que si chaque étape est IDEMPOTENTE — vrai pour l'ingestion
  (INSERT OR IGNORE), à démontrer pour le dump (écriture de fichier) et pour le raffinage (UPDATE).
