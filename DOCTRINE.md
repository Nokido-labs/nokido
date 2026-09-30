# DOCTRINE.md — Règles NON NÉGOCIABLES du traitement RAG

SSoT de l'**ingestion**. Troisième pilier à côté de `RULES_SHARED.md` (le capacitif :
*ce qu'on peut faire*) et `COGNITION.md` (le cognitif : *comment penser*). Celui-ci dit
**comment la connaissance entre dans le corps**, et il n'admet pas d'exception.

Écrit le 2026-07-25 sur rappel explicite de l'owner, après trois violations mesurées
le même jour. Une règle qu'on répète est une règle qui n'est pas outillée : elle est
donc ici, indexée, opposable, et vérifiable par une requête.

---

## 1. LE LEXICAL PRIME. Toujours. Sans exception.

**Tout chunk écrit dans `rag_chunks` est inséré dans `rag_fts` dans la MÊME
transaction, AVANT toute vectorisation.**

L'ordre est impératif :

```
1. DELETE rag_fts  (anciennes versions)      ← purge
2. INSERT rag_chunks                          ← la matière
3. INSERT rag_fts                             ← LE LEXICAL, immédiat
4. commit                                     ← la connaissance est CHERCHABLE ICI
5. embed / vectorisation                      ← raffinage SECONDAIRE, différable
```

**Pourquoi** — le lexical est exact, ne dépend d'aucun embedder, coûte quelques
millisecondes, et répond même quand la vectorisation est en retard de plusieurs heures.
Le vecteur est un *raffinage* : il ajoute la proximité sémantique, il ne remplace jamais
la capacité de retrouver un terme exact.

**Un chunk sans entrée FTS et sans vecteur n'existe pas.** Il est en base, il est
perdu. Aucune erreur ne le signale : c'est le pire mode de défaillance, celui qui se
lit comme un succès.

**Violations mesurées le 2026-07-25 :**
- `_index_doctrine` (post-commit) écrivait `rag_chunks` + vectorisait, **jamais** `rag_fts` :
  **121 chunks de doctrine en base, 0 en FTS**. `RULES_SHARED`, `CLAUDE.md` et
  `COGNITION.md` étaient introuvables par mot exact — depuis toujours.
- Le pipeline de veille embarquait la vectorisation *inline*, si bien qu'un embedder
  saturé faisait écrire **2 008 chunks sans vecteur** en silence.

## 2. `rag_fts` n'a AUCUN trigger — toute écriture est DOUBLE

Il n'existe pas de synchronisation automatique entre `rag_chunks` et `rag_fts`.
Chaque écriture doit être faite deux fois, explicitement.

Et **jamais `INSERT OR IGNORE`** sur `rag_fts` : la table n'a pas de clef qui
déclencherait un remplacement, donc l'ancien texte SURVIT. Après réécriture d'un chunk,
le lexical servirait la version périmée. Toujours **`DELETE` puis `INSERT`**.

## 3. La vectorisation est un raffinage, jamais un prérequis

Elle se fait **après** le commit lexical, et son échec ne doit jamais empêcher
l'ingestion. Un embedder muet ⇒ on journalise, on laisse `embedding NULL`, le daemon
rattrape. Ce qui ne se rattrape pas, c'est un chunk jamais indexé.

## 4. Une écriture perdue sur verrou est une faute

`database is locked` ne se traite pas par un abandon silencieux : `forge_db_path.write_retry(op)`
reprend l'écriture avec recul croissant et jitter. Ouvrir en écriture = `open_writer()`
(autocommit + WAL + busy_timeout), **jamais** `sqlite3.connect()` nu, qui tient un verrou
implicite jusqu'au commit et fait échouer les voisins.

## 5. Distinguer « rien trouvé » de « je n'ai pas pu voir »

Un crawl bloqué par une authentification, un scanner sans droit de lecture, un service
arrêté : tous rendent « vide ». Ingérer ce vide fabrique du faux savoir. Le refus doit
être **imprimé et nommé**, jamais converti en chunk.

---

## Vérifier (aucune de ces requêtes ne doit rien rendre d'anormal)

```sql
-- Chunks invisibles au lexical : DOIT être 0 sur les domaines vivants
SELECT c.domain, count(*) AS sans_fts
FROM rag_chunks c LEFT JOIN rag_fts f ON f.chunk_id = c.id
WHERE f.chunk_id IS NULL GROUP BY c.domain ORDER BY 2 DESC;

-- La doctrine est-elle cherchable par mot exact ?
SELECT count(*) FROM rag_fts WHERE domain='doctrine' AND text LIKE '%LEXICAL PRIME%';
```

Liens : `RULES_SHARED.md` (capacitif), `COGNITION.md` (cognitif), `CLAUDE.md` (protocole).
