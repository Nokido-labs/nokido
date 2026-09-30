"""Reingestion PROPRE des dumps gitingest : purge -> reingere -> vectorise.

Contexte (mesure 24-07) : domain=sdk_gitingest portait 24 267 chunks, TOUS sans
embedding, dont ~11 600 a SOURCE DEGRADEE (« Directory structure: », « # SECTION: »)
parce que le parseur lisait le mauvais separateur. Le parseur est repare
(forge_gitingest_sdk_ingest, deux formats) ; ce script rejoue l'ingestion en
remplacant, pas en empilant, puis vectorise via l'embedder de production.

Long (24k chunks a ~31/s ≈ 13 min) + ressource partagee (la base RAG) : a lancer
1x en run_job detache, JAMAIS en rafale d'appels fins. Idempotent par construction
(purge complete du domaine avant reinsertion).

Etapes, dans UNE transaction de purge puis inserts :
  1. compter l'existant (traçabilite)
  2. DELETE domain=sdk_gitingest (rag_chunks + rag_fts)
  3. reingerer les 14 dumps avec le parseur repare
  4. vectoriser les chunks neufs par lots via forge_embed_router
"""
from __future__ import annotations

import sqlite3
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_db_path import db_path  # noqa: E402
from nokido_agent.tools import forge_gitingest_sdk_ingest as gi  # noqa: E402


def _log(msg: str) -> None:
    print(f"[reingest] {msg}", flush=True)


def main() -> int:
    db = db_path()
    con = sqlite3.connect(db, timeout=60)
    try:
        avant = con.execute("SELECT COUNT(*) FROM rag_chunks WHERE domain='sdk_gitingest'").fetchone()[0]
        degradees = con.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain='sdk_gitingest' "
            "AND (source LIKE 'Directory structure%' OR source LIKE '# SECTION%' "
            "OR source LIKE '====%' OR source='' OR instr(source,' ')>0)"
        ).fetchone()[0]
        _log(f"existant : {avant} chunks, dont {degradees} a source degradee")

        # 2. PURGE — remplacer, pas empiler (sinon nouveaux ids = doublons).
        con.execute("DELETE FROM rag_chunks WHERE domain='sdk_gitingest'")
        try:
            con.execute("DELETE FROM rag_fts WHERE domain='sdk_gitingest'")
        except sqlite3.OperationalError:
            pass
        con.commit()
        _log(f"purge : {avant} chunks retires")
    finally:
        con.close()

    # 3. REINGESTION — parseur repare (deux formats), INSERT propre.
    con = sqlite3.connect(db, timeout=60)
    ins = skip = 0
    try:
        dumps = sorted((ROOT / "docs").glob("gitingest_*.txt"))
        for fp in dumps:
            i, s = gi.ingest_file(fp, con)
            ins += i
            skip += s
            _log(f"  {fp.name}: +{i} ({s} ignores)")
    finally:
        con.close()
    _log(f"reingestion : {ins} chunks inseres")

    # 4. PAS de vectorisation : sdk_gitingest est un TIER FROID par design.
    # Le trigger `forge_tier_guard` (BEFORE UPDATE OF embedding) fait RAISE(IGNORE)
    # sur ce domaine (classe 'cold-legacy') : les dumps de libs externes restent
    # BM25-only, ils ne consomment pas d'embedding dense. Mesure 24-07 : une premiere
    # version de ce script « comptait » 15313 vectorisations alors que le trigger les
    # ignorait TOUTES (rowcount 0) — une fausse attestation. On ne contourne pas un
    # garde-fou intentionnel ; on constate le tier et on verifie l'index BM25, qui
    # EST le canal de recherche de ce tier.
    con = sqlite3.connect(db, timeout=60)
    try:
        fts = con.execute(
            "SELECT COUNT(*) FROM rag_fts WHERE domain='sdk_gitingest'"
        ).fetchone()[0]
    finally:
        con.close()
    _log(f"TERMINE : {ins} reingeres (tier froid cold-legacy, BM25-only) ; "
         f"{fts} indexes rag_fts ; vectorisation refusee par forge_tier_guard (par design)")
    return 0


def _reste_null(db: str) -> int:
    con = sqlite3.connect(db, timeout=30)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain='sdk_gitingest' AND embedding IS NULL"
        ).fetchone()[0]
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
