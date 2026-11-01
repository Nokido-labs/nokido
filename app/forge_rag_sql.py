"""SQL bornees du chemin `rag action=search` (levier 1, 24/10).

MESURE 24/10 : deux `rag search` ont expire a 120 s, le hub a lu 81 Go en 40 min.
CAUSE : `_load_dense_cache` (mode dense delegue) faisait
`SELECT id, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL`. `ext`/`folder` sont
des colonnes VIRTUELLES calculees depuis `source`, qui suit `text` dans la ligne : lire
`source` (ou `embedding`) oblige a parcourir la chaine de pages debordement de `text`,
donc balayage des ~45 Go a chaque recharge du cache.

CORRECTIF : ne lire QUE des index couvrants.
  ids avec embedding = (tous les id, index PK couvrant) MOINS (id sans embedding, index
  partiel `idx_embedding_null`, couvrant). Aucune page de texte touchee, aucune ecriture.
  `ext` n'est plus precharge : lu a la demande pour les <= 50 candidats (SQL_EXT_PAR_IDS).
"""

import sqlite3

__FORGE_COLOR__ = "memoire/rag-sql-borne : requetes de la recherche RAG par index couvrants, jamais de balayage"

SQL_IDS_TOUS = "SELECT id FROM rag_chunks INDEXED BY sqlite_autoindex_rag_chunks_1"
# INDEXED BY : sans lui, le planificateur de la base vivante prend `idx_emb_null_origin`
# (partiel sur origin, NON couvrant) et relit chaque ligne -- disque sature le 24/10.
SQL_IDS_SANS_EMBEDDING = "SELECT id FROM rag_chunks INDEXED BY idx_embedding_null WHERE embedding IS NULL"
SQL_FTS_CANDIDATS = (
    "SELECT c.id FROM rag_chunks_fts JOIN rag_chunks c "
    "ON c.rowid = rag_chunks_fts.rowid "
    "WHERE rag_chunks_fts MATCH ? AND c.embedding IS NOT NULL "
    "ORDER BY bm25(rag_chunks_fts, 1.2, 0.5) LIMIT 50"
)
SQL_META_PAR_IDS = "SELECT id, source, domain, text FROM rag_chunks WHERE id IN (%s)"
SQL_EXT_PAR_IDS = "SELECT id, ext FROM rag_chunks WHERE id IN (%s)"


def ids_avec_embedding(conn):
    """Ids portant un embedding, par differences d'index couvrants (jamais de balayage de la table)."""
    try:
        sans = {r[0] for r in conn.execute(SQL_IDS_SANS_EMBEDDING)}
    except sqlite3.OperationalError as e:
        # `idx_embedding_null` n'est cree par aucun code (base vivante seulement) : une
        # base neuve ne l'a pas -- elle est petite, le choix du planificateur suffit.
        if "no such index" not in str(e):
            raise
        sans = {r[0] for r in conn.execute("SELECT id FROM rag_chunks WHERE embedding IS NULL")}
    return [r[0] for r in conn.execute(SQL_IDS_TOUS) if r[0] and r[0] not in sans]


def ext_par_ids(conn, ids):
    """{id: ext} des seuls ids demandes (lecture par cle PK)."""
    voulus = [i for i in dict.fromkeys(ids or []) if i]
    out = {}
    for k in range(0, len(voulus), 500):
        lot = voulus[k:k + 500]
        for cid, ext in conn.execute(SQL_EXT_PAR_IDS % ",".join("?" * len(lot)), lot):
            out[cid] = ext or ""
    return out
