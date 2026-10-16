---
name: forge-database-state
description: "À utiliser avant de lire ou d'écrire une base SQLite de Nokido (RAG, messages, tâches, journaux), ou face à « database is locked », une colonne absente, un compteur incohérent, une requête lente, depuis toute surface. Donne quelle base porte quel état, les primitives d'accès, les interrupteurs et les pièges de mesure payés."
---

# forge-database-state — les bases de Nokido : qui porte quoi, comment y toucher

Créée le 15/10 : Codex, AGY et Gemini web la demandaient, en complément de
`forge-memory-ssot` (qui dit QUELLE mémoire consulter ; celle-ci dit comment toucher la
base qui la porte). Primitives relues dans `app/forge_db_path.py` le 15/10.

## Quelle base porte quel état

| état | accès | note |
|---|---|---|
| RAG : `rag_chunks`, index `rag_chunks_fts` et `rag_fts`, `provider_scores`, `watch_jobs`… | `forge_db_path.db_path()` | la grosse base (`embeddings.db`, plus de 20 Go) |
| messages entre agents (`agent_messages`) | `forge_db_path.open_m2m(timeout)`, `m2m_path()` | suit l'interrupteur `sandbox/m2m.switch` |
| tâches (`tasks`) | `forge_db_path.open_tasks(timeout)`, `tasks_path()` ; côté exécuteur `forge_task_executor.TASKS_DB` | interrupteur dédié |
| journaux (`inspector_log`…) | `forge_db_path.journal_path(nom)`, `lecteur_journal(...)` | suivent `sandbox/journaux.switch` |
| autorité | `forge_db_path.authority_path()` | interrupteur dédié |
| tableau noir | outils `blackboard_*` | le hub est l'écrivain unique et sérialisé : jamais de SQL direct |

- **Ne jamais écrire un chemin de base en dur** : le demander au module propriétaire
  (`forge_db_path`, `TASKS_DB`). Un état partagé par plusieurs processus bascule par un
  interrupteur global lu à chaque appel ; un site qui bascule seul écrit d'un côté
  pendant que les autres lisent de l'autre.

## Écrire

- `open_writer(timeout, path)` : autocommit, WAL, `busy_timeout`.
- `write_retry(op, attempts=6, ...)` exécute `op(conn)` et le REPREND sur verrou, avec
  recul croissant et gigue ; toute autre erreur remonte aussitôt. Mesure du 25/07 : trois
  veilles lancées pendant une ingestion avaient été PERDUES sur « database is locked ».
- `ecrire_chunk(conn, source, domain, texte, cap=None)` écrit un chunk avec l'`id`
  canonique `chunk_id(source, texte)` = `sha256(source|texte)[:16]` ; un `cap` DIT ce
  qu'il écarte (15 500 chunks amputés en silence avant le 12/09).
- **Jamais `sqlite3.connect()` nu en écriture** : il garde un verrou implicite et fait
  perdre les écritures des voisins.
- Écriture longue ou lourde : un `run_job` côté hub, jamais depuis un processus client,
  jamais dans la boucle du hub. Les modifications lourdes de `embeddings.db` sont un
  chantier dédié, avec mesures avant/après (constitution).

## Lire

- Diagnostic : `sqlite3.connect("file:<chemin>?mode=ro", uri=True)`, lecture seule.
- `active` dans un WHERE sur `rag_chunks` = scan de 45 Go : écrire `+active`.
- Jamais `LIKE` pour chercher dans le RAG (règle d'or 1) : un `LIKE '%…%'` sur
  `rag_chunks` gèle qui l'exécute.
- Une requête SQLite synchrone dans le hub bloque sa boucle : le moteur passe par
  `to_thread`. Contre-exemple du 15/10 : l'outil `memory`, en panne sur des colonnes
  disparues (`rag_chunks.content`, `provider_scores.provider_id`) — un schéma se lit
  (`PRAGMA table_info`), il ne se suppose pas.

## Pièges de mesure

- Deux `COUNT` en autocommit = deux instantanés : un écart se mesure dans UNE transaction.
- Deux index ne se comparent pas par `rowid`, qui n'a de sens que dans sa table : par
  CONTENU (`MATCH` sur un terme témoin). Le `rowid` n'est pas non plus une position :
  MAX(rowid) valait 2 318 899 pour 711 085 lignes (29/07).
- `embedding IS NULL` n'est jamais `FAILED` : sans événement d'échec émis par le
  producteur, les états honnêtes sont `PENDING`, `REFUSED_BY_POLICY` ou `UNKNOWN`.
- Un job d'écriture a un CPU quasi nul : croiser avec la croissance du WAL (un job tué
  à 0,9 s de CPU travaillait, son WAL faisait 982 Mo).
- `checkpoint_wal(seuil_mo, truncate, attente_s)` existe pour un WAL qui gonfle : lire
  sa docstring avant usage ; ne jamais supprimer un `-wal` à la main.
- Une purge efface `watch_jobs` et `agent_chain_nodes` ; le TTL du tableau noir a
  effacé la roadmap le 13/10 : une ligne absente ne prouve pas qu'une chose n'a pas eu lieu.
