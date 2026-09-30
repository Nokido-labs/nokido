"""forge_qdrant_sync_daemon.py — sync CONTINUE SQLite -> Qdrant (pattern outbox).

Le probleme mesure le 24-07 : Qdrant etait peuple par forge_qdrant_fill lance A LA
MAIN, jamais reactualise, donc PERIME (une recherche rendait des docsets NodeJS la
ou la doctrine du jour etait attendue). L'embedder ecrit SQLite mais pas Qdrant.
Sans sync continue, toute bascule de la recherche sur Qdrant sert du perime.

DESIGN — outbox par TRIGGER, pas d'instrumentation du code :
  * un trigger `AFTER UPDATE OF embedding` (et AFTER INSERT) pousse l'id dans une
    file `qdrant_sync_pending`. Il capte TOUTE ecriture d'embedding quelle que soit
    sa source (auto-trigger, reingestion, _save_embeddings...) sans toucher un seul
    appelant.
  * il se declenche APRES le garde `forge_tier_guard` (BEFORE UPDATE, RAISE IGNORE
    sur cold-legacy) : un UPDATE ignore n'aboutit pas, donc l'AFTER ne tire pas.
    Le cold-tier (sdk_gitingest, BM25-only) reste ainsi HORS Qdrant, par design.
  * ce daemon draine la file par lots vers Qdrant, puis efface les ids traites.
    Idempotent, redemarrable, ne perd rien (la file survit aux morts).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient

# RACINE AVANT le premier import `nokido_agent` (2026-09-24, mesure) : l'insertion venait
# APRES, le service mourait en ModuleNotFoundError a chaque demarrage (relance en boucle).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_faiss_sidecar import _decode_emb  # noqa: E402
from nokido_agent.tools.forge_qdrant_sidecar import COLLECTION_NAME, init_sovereign_db, upsert_chunks  # noqa: F401,E402
from nokido_agent.app.forge_db_path import open_writer  # noqa: E402

HEARTBEAT = ROOT / "sandbox" / "qdrant_sync_daemon.heartbeat"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qdrant_sync_pending (
    chunk_id TEXT PRIMARY KEY,
    queued_at REAL
);
CREATE TRIGGER IF NOT EXISTS qdrant_sync_on_embed_update
    AFTER UPDATE OF embedding ON rag_chunks
    FOR EACH ROW WHEN NEW.embedding IS NOT NULL
    BEGIN
        INSERT OR IGNORE INTO qdrant_sync_pending(chunk_id, queued_at)
        VALUES (NEW.id, strftime('%s','now'));
    END;
CREATE TRIGGER IF NOT EXISTS qdrant_sync_on_embed_insert
    AFTER INSERT ON rag_chunks
    FOR EACH ROW WHEN NEW.embedding IS NOT NULL
    BEGIN
        INSERT OR IGNORE INTO qdrant_sync_pending(chunk_id, queued_at)
        VALUES (NEW.id, strftime('%s','now'));
    END;
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def drain_once(conn: sqlite3.Connection, client: QdrantClient, limit: int = 512) -> dict:
    """Draine un lot de la file vers Qdrant. Rend {vus, upsertes, invalides}."""
    # CROSS JOIN, pas JOIN : SQLite y lit un ORDRE DE BOUCLE impose (documente),
    # file d'attente en boucle externe, rag_chunks cherche par sa cle primaire.
    # Mesure 2026-09-06 sur la base reelle (EXPLAIN QUERY PLAN) : avec JOIN, le
    # planificateur mettait rag_chunks en boucle EXTERNE (`SCAN c`, 1,3 M lignes
    # et leurs blobs) pour 40 lignes en attente, toutes les 30 s -- les 112 Mo/s
    # de lecture permanente qui ont fait couper ce service le 05/09, 5e incarnation
    # du balayage complet. Le plan est verrouille par NR (test_qdrant_sync_plan_nr).
    rows = conn.execute(
        "SELECT p.chunk_id, c.embedding, c.source, c.domain "
        "FROM qdrant_sync_pending p CROSS JOIN rag_chunks c ON c.id = p.chunk_id "
        "WHERE c.embedding IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        # File contient peut-etre des ids dont l'embedding est reparti a NULL
        # (retraction) : les purger pour ne pas boucler a vide.
        conn.execute(
            "DELETE FROM qdrant_sync_pending WHERE chunk_id IN "
            "(SELECT p.chunk_id FROM qdrant_sync_pending p "
            " LEFT JOIN rag_chunks c ON c.id = p.chunk_id "
            " WHERE c.id IS NULL OR c.embedding IS NULL LIMIT ?)",
            (limit,),
        )
        conn.commit()
        return {"vus": 0, "upsertes": 0, "invalides": 0}

    batch, faits, bad = [], [], 0
    for cid, blob, source, domain in rows:
        v = _decode_emb(blob)
        if v is None or not np.isfinite(v).all():
            bad += 1
            faits.append(cid)  # invalide DEFINITIF : sortir de la file
            continue
        batch.append({"id": cid, "dense": v.tolist(), "path": source or "", "domain": domain or ""})
        faits.append(cid)

    ok = 0
    if batch:
        try:
            ok = upsert_chunks(client, batch)
        except Exception as e:  # noqa: BLE001 - un lot KO ne vide pas la file
            print(f"[qdrant-sync] upsert lot KO ({e}) -> point par point", flush=True)
            faits, ok = [], 0
            for item in batch:
                try:
                    ok += upsert_chunks(client, [item])
                    faits.append(item["id"])
                except Exception:
                    bad += 1  # laisse dans la file pour re-essai
    # N'efface QUE ce qui a ete traite (upserte ou invalide definitif).
    if faits:
        qmarks = ",".join("?" * len(faits))
        conn.execute(f"DELETE FROM qdrant_sync_pending WHERE chunk_id IN ({qmarks})", faits)
        conn.commit()
    return {"vus": len(rows), "upsertes": ok, "invalides": bad}


def _beat(msg: str) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`
    # absent, et serialise proprement au lieu d'un JSON construit a la main (une
    # apostrophe dans `msg` cassait le fichier, qui devenait ILLISIBLE au superviseur).
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("qdrant_sync_daemon", note=msg)


def run(host: str, grpc_port: int, interval: int, once: bool) -> int:
    client = QdrantClient(host=host, grpc_port=grpc_port, prefer_grpc=True, timeout=120)
    init_sovereign_db(client=client)
    # PATTERN PROUVE, pas un `sqlite3.connect()` nu (mesure 2026-08-20).
    # Ce daemon ecrit EN CONTINU (drain de la file qdrant) dans la meme base que
    # le drain d'embedding. Avec un connect nu, le module sqlite3 ouvre une
    # transaction IMPLICITE au premier INSERT et la garde jusqu'au commit : le
    # voisin echoue alors malgre son busy_timeout. C'est exactement ce que le
    # message de `write_retry` designe — « chercher un sqlite3.connect() nu chez
    # l'ecrivain concurrent » — et c'est ce qui a tue le drain d'embedding
    # (mort 33 min, 241 862 chunks en attente) pendant une salve d'ingestions.
    # `open_writer` : autocommit + WAL + busy_timeout, benche « 0 contention »
    # sous N workers (decision archi 2026-06-04).
    conn = open_writer(timeout=60.0)
    init_schema(conn)
    print("[qdrant-sync] schema + triggers en place", flush=True)

    while True:
        total = 0
        while True:
            r = drain_once(conn, client)
            total += r["upsertes"]
            if r["vus"] == 0:
                break
        depth = conn.execute("SELECT COUNT(*) FROM qdrant_sync_pending").fetchone()[0]
        _beat(f"drained {total}, pending {depth}")
        if once:
            print(f"[qdrant-sync] once: {total} upsertes, {depth} en attente", flush=True)
            conn.close()
            return 0
        time.sleep(max(5, interval))


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync continue SQLite -> Qdrant (outbox)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--grpc-port", type=int, default=6334)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    return run(a.host, a.grpc_port, a.interval, a.once)


if __name__ == "__main__":
    sys.exit(main())
