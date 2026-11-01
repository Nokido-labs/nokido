# Enquete : debit disque du NokidoMemoryConsolidator (26/10/2026)

Roadmap bug_hamilton_oscillation_sleep_wake_20261019, point 2. Symptome : ~49,5 Mo/s de lecture disque.
Methode : lecture des fichiers en entier ; `EXPLAIN QUERY PLAN` SEUL (aucune requete executee) sur la base vivante,
ouverte en `mode=ro`. `db_path()` (app/forge_db_path.py:548) rend `%NOKIDO_DATA%\embeddings.db` (51 972 714 496 octets).
`execution_traces.db` vit a cote : `%NOKIDO_DATA%\execution_traces.db`.

## 1. Service

- `proxy_deno/core/services.toml:1946-1954` : `name = "NokidoMemoryConsolidator"`, `cmd = "${PYTHON}"`,
  `args = ["tools/forge_memory_consolidator.py", "--daemon"]`, `disabled = false` (rallume le 18/10, ligne 1947).
- Intervalle 43 200 s : `tools/forge_memory_consolidator.py:46`.

## 2. Requetes SQL executees et plans (EXPLAIN)

| # | Fichier:ligne | Requete | Base | Plan EXPLAIN |
|---|---|---|---|---|
| 1 | tools/forge_memory_consolidator.py:108-115 | `SELECT ... FROM traces WHERE success=1 AND cost_after<? AND ts>? AND task_type IS NOT NULL AND action_json NOT LIKE '%system_tick%' ORDER BY cost_after LIMIT 5000` | execution_traces.db | `SEARCH traces USING INDEX idx_ts (ts>?)` + `USE TEMP B-TREE FOR ORDER BY` |
| 2 | tools/forge_memory_consolidator.py:186 | `SELECT 1 FROM rag_chunks WHERE id=?` | embeddings.db | `SEARCH rag_chunks USING COVERING INDEX sqlite_autoindex_rag_chunks_1 (id=?)` |
| 3 | tools/forge_memory_consolidator.py:188-191 | `INSERT OR REPLACE INTO rag_chunks (id,source,text)` | embeddings.db | EXPLAIN sans ligne de plan (insert) |
| 4 | tools/forge_memory_consolidator.py:230 | `DELETE FROM rag_chunks WHERE id=?` (retour arriere seulement) | embeddings.db | `SEARCH rag_chunks USING INDEX sqlite_autoindex_rag_chunks_1 (id=?)` |
| 5 | app/forge_guarded_change.py:69 (appele l.163 avant, l.199 apres le cycle) | `SELECT COUNT(*) FROM rag_chunks` | embeddings.db | **`SCAN rag_chunks USING COVERING INDEX idx_rag_chunks_json_extract_meta_ingested_a`** |
| 6 | app/forge_health_diagnostic.py:209 (via forge_guarded_change.py:85 -> `_light_health`, l.190) | `SELECT MAX(rowid) FROM rag_chunks` | embeddings.db | `SEARCH rag_chunks` |
| 7 | app/forge_health_diagnostic.py:211-213 | `SELECT COUNT(*) ... WHERE rowid>? AND embedding IS NULL` | embeddings.db | `SEARCH rag_chunks USING INTEGER PRIMARY KEY (rowid>?)` |
| 8 | app/forge_health_diagnostic.py:223-225 | `SELECT length(embedding) ... WHERE embedding IS NOT NULL AND length(embedding)>0 LIMIT 50` | embeddings.db | **`SCAN rag_chunks`** (table, sans index) |
| 9 | app/forge_health_diagnostic.py:233 | `SELECT MAX(rowid) FROM rag_chunks` | embeddings.db | `SEARCH rag_chunks` |
| 10 | app/forge_health_diagnostic.py:238-241 | `SELECT hash, COUNT(*) ... WHERE rowid>? AND hash IS NOT NULL AND hash!='' GROUP BY hash HAVING COUNT(*)>1` | embeddings.db | **`SEARCH rag_chunks USING COVERING INDEX idx_rag_chunks_hash (hash>?)`** (la borne rowid n'est pas une cle de cet index) |
| 11 | app/forge_health_diagnostic.py:246-248 | `SELECT domain FROM rag_chunks WHERE rowid>?` | embeddings.db | `SEARCH rag_chunks USING INTEGER PRIMARY KEY (rowid>?)` |
| 12 | app/forge_health_diagnostic.py:252-255 | `SELECT AVG/MIN/MAX/COUNT(quality_score) ... WHERE rowid>? AND quality_score IS NOT NULL` | embeddings.db | `SEARCH rag_chunks USING INTEGER PRIMARY KEY (rowid>?)` |
| 13 | app/forge_health_diagnostic.py:397-405 | `SELECT name FROM sqlite_master ...` | embeddings.db | `SCAN sqlite_master` (catalogue, negligeable) |
| 14 | app/forge_health_diagnostic.py:413 | `SELECT 1 FROM "<table>" LIMIT 5`, une fois par table du catalogue | embeddings.db | non explique (table dynamique) ; `LIMIT 5` borne la lecture |

Chemin d'appel : `run_consolidation_cycle` (consolidator:257) ouvre `guarded_change` ; celui-ci appelle `_rag_total()` (forge_guarded_change.py:163),
puis `_light_health()` (l.190) -> `audit_rag_chunks(conn)` (forge_health_diagnostic.py:103, non force) et `audit_tables_empty`.
`_ventiler_la_dette` (l.131) -> `forge_memory_availability.snapshot` (forge_memory_availability.py:297-324) : lecture d'un fichier JSON, aucune requete.
Le cache `_RAG_CACHE` (forge_health_diagnostic.py:85) est en memoire du process : un cycle du consolidateur (processus a part) repart a froid.

Les requetes 5-14 ne s'executent que si des traces existent : `run_consolidation_cycle` retourne avant `guarded_change` quand `total_traces == 0`
(consolidator:247-248).

## 3. Conclusions

**Requetes qui balaient :**
1. `SELECT COUNT(*) FROM rag_chunks` (forge_guarded_change.py:69), execute 2 fois par cycle (l.163 et l.199) : `SCAN ... COVERING INDEX idx_rag_chunks_json_extract_meta_ingested_a`, parcours d'un index couvrant de toute la table (base de 52 Go ; ~7 M entrees d'apres le commentaire forge_health_diagnostic.py:203-204). Meme motif que DeportEmbed.
2. `SELECT length(embedding) ... LIMIT 50` (forge_health_diagnostic.py:223) : `SCAN rag_chunks` sur la table ; le `LIMIT 50` arrete le parcours aux 50 premiers non-NULL. Cout borne si les premiers rowid sont vectorises ; non mesure (execution interdite).
3. Requete des doublons (forge_health_diagnostic.py:238) : plan `SEARCH` sur `idx_rag_chunks_hash (hash>?)`, mais la borne porte sur `hash`, non sur `rowid` ; `rowid>?` n'est pas une cle de cet index, donc le parcours couvre l'index entier. Le commentaire (l.231-232) presente la requete comme limitee a l'echantillon : le plan ne le confirme pas.

**Requetes servies par un index (SEARCH) :** 1 (idx_ts, tri temporaire), 2, 4, 6, 7, 9, 11, 12.

**Index / remede :**
- COUNT(*) (n°5) : aucun index ne le rend sans parcours. Remede : retirer `_rag_total` du gate ou le remplacer par `SELECT MAX(rowid)` (plan `SEARCH rag_chunks`, lignes 6/9), comme deja fait en forge_health_diagnostic.py:209.
- Doublons (n°10) : borner de facon que le plan soit `SEARCH ... USING INTEGER PRIMARY KEY (rowid>?)` (plan observe pour 7, 11, 12) ; la cle rowid suffit, aucun nouvel index.
- `length(embedding)` (n°8) : une borne `rowid > ?` donnerait `SEARCH ... INTEGER PRIMARY KEY`.
- Requete 1 (traces) : deja servie par `idx_ts`.

Non verifie : le debit reel de chaque requete (rien n'a ete execute), donc la part de chacune dans les 49,5 Mo/s n'est pas chiffree ; la cause est designee par le plan, pas par une mesure.

## 4. Le service tourne-t-il ?

`logs/supervisor/NokidoMemoryConsolidator.log` (57 lignes, dernieres) :
- `2026-10-26 23:49:22 ... daemon started ... pid=18496` ;
- `23:49:22 Found 2894 high-value traces in 1 task_types` ; `Consolidating tool_call (2894 traces)` ;
- `23:49:25 [guarded_change:INFO] memory_consolidator: consolidation - OK (2.6s)` ;
- `23:49:25 Sleeping 43200s`.

Le journal montre aussi des demarrages a 22:37:15 (pid 15976), 23:13:52 (pid 15708) et 23:49:22 (pid 18496), avec « Premier cycle differe de 2502s » et « 306s » : le daemon est relance environ toutes les 36 a 37 minutes (cause non etablie ici). A chaque redemarrage dont le delai est ecoule, un cycle s'execute et avec lui les requetes 5-14. Le journal ne dit pas si le pid 18496 est vivant a l'instant de lecture ; derniere ligne : « Sleeping 43200s ».
