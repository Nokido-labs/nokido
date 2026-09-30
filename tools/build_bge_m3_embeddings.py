#!/usr/bin/env python3
"""
build_bge_m3_embeddings.py — Génère les embeddings BGE-M3 (1024d) pour les
domaines prioritaires de rag_chunks et les stocke en BLOB float32 binaire.

Domaines indexés: forge_core, code, nokido_code, security, conv
Domaines skippés: beir_* (benchmark data, BM25 suffit)

Usage:
    LAFORGE_PYTHON tools/build_bge_m3_embeddings.py [--domain code] [--batch 8] [--limit 0]
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import struct
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bge_m3_build")

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"
FTS_LOCK = ROOT / "RAG" / "fts_rebuild.lock"

PRIORITY_DOMAINS = ["forge_core", "code", "nokido_code", "security", "conv"]
DEFAULT_BATCH = 8
BGE_M3_MODEL = "BAAI/bge-m3"


OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
OLLAMA_MODEL = "bge-m3"  # bge-m3:latest dans Ollama — 24+ chunks/s vs 1/s CPU Python


def _wait_fts_lock(max_wait: int = 60) -> None:
    """Attend que le lock FTS rebuild soit libéré (max max_wait secondes)."""
    waited = 0
    while FTS_LOCK.exists() and waited < max_wait:
        log.debug("FTS rebuild en cours, attente 2s...")
        time.sleep(2)
        waited += 2
    if waited >= max_wait:
        log.warning("FTS lock toujours présent après %ds, on continue quand même", max_wait)


def load_model():
    """Retourne None — on utilise Ollama directement (pas de modèle local à charger)."""
    import urllib.request

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({"model": OLLAMA_MODEL, "input": "ping"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    dim = len(d["embeddings"][0])
    log.info("Ollama bge-m3 OK — dim=%d", dim)
    return None  # sentinel: use Ollama path


def fetch_chunks(
    domains: list[str], limit: int = 0, recode_old: bool = False
) -> list[tuple[str, str]]:
    """Retourne (id, text) pour les chunks à encoder.

    recode_old=True : inclut aussi les chunks ayant un embedding de mauvaise dim
    (ex: MiniLM 384d → à re-encoder en BGE-M3 1024d).
    Détection via json_array_length(embedding) != 1024.
    """
    con = sqlite3.connect(str(RAG_DB))
    ph = ",".join("?" * len(domains))
    if recode_old:
        # Binary float32: 384d=1536 bytes, 768d=3072 bytes — both need recode to 1024d
        # Binary 1024d=4096 bytes → keep. JSON 1024d (>8000 bytes, starts '[') → keep.
        sql = f"""
            SELECT id, text FROM rag_chunks
            WHERE domain IN ({ph})
              AND (
                embedding IS NULL OR embedding = ''
                OR length(embedding) IN (1536, 3072)
              )
            ORDER BY domain, rowid
        """
    else:
        sql = f"""
            SELECT id, text FROM rag_chunks
            WHERE domain IN ({ph})
              AND (embedding IS NULL OR embedding = '')
            ORDER BY domain, rowid
        """
    if limit > 0:
        sql += f" LIMIT {limit}"
    rows = con.execute(sql, domains).fetchall()
    con.close()
    label = "à recoder (dim!=1024 incl.)" if recode_old else "sans embedding"
    log.info("Chunks %s: %d (domaines: %s)", label, len(rows), ", ".join(domains))
    return rows


def count_already_done(domains: list[str]) -> int:
    con = sqlite3.connect(str(RAG_DB))
    ph = ",".join("?" * len(domains))
    n = con.execute(
        f"SELECT COUNT(*) FROM rag_chunks WHERE domain IN ({ph}) AND embedding IS NOT NULL AND embedding != ''",
        domains,
    ).fetchone()[0]
    con.close()
    return n


def embed_and_store(model, chunks: list[tuple[str, str]], batch_size: int = DEFAULT_BATCH) -> int:
    _wait_fts_lock()
    con = sqlite3.connect(str(RAG_DB), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=30000")
    stored = 0
    total = len(chunks)
    t_start = time.time()

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]

        try:
            import urllib.request as _ur

            # Truncate to 512 chars: attention is quadratic, 512 captures semantic essence
            truncated = [t[:512] for t in texts]
            payload = json.dumps({"model": OLLAMA_MODEL, "input": truncated}).encode()
            req = _ur.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _ur.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            vecs = d["embeddings"]
        except Exception as e:
            log.warning("Batch %d encode error: %s", i // batch_size, e)
            continue

        for chunk_id, vec in zip(ids, vecs):
            blob = struct.pack(f"{len(vec)}f", *vec)
            con.execute(
                "UPDATE rag_chunks SET embedding = ? WHERE id = ?",
                (blob, chunk_id),
            )

        _wait_fts_lock()
        con.commit()
        stored += len(batch)

        elapsed = time.time() - t_start
        rate = stored / elapsed if elapsed > 0 else 0
        remaining = (total - stored) / rate if rate > 0 else 0
        log.info(
            "[%d/%d] %.0f chunks/s — reste ~%.0fs",
            stored,
            total,
            rate,
            remaining,
        )

    con.close()
    return stored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", nargs="*", default=PRIORITY_DOMAINS, help="Domaines à traiter")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--limit", type=int, default=0, help="0 = pas de limite")
    parser.add_argument(
        "--recode-old",
        action="store_true",
        help="Recoder aussi les chunks avec embedding dim!=1024 (migration MiniLM 384d -> BGE-M3 1024d)",
    )
    args = parser.parse_args()

    if not RAG_DB.exists():
        log.error("RAG DB introuvable: %s", RAG_DB)
        sys.exit(1)

    already = count_already_done(args.domain)
    log.info("Déjà encodés (domaines cibles): %d", already)

    chunks = fetch_chunks(args.domain, args.limit, recode_old=args.recode_old)
    if not chunks:
        log.info("Rien à faire — tous les chunks ont déjà un embedding BGE-M3 1024d.")
        return

    model = load_model()
    t0 = time.time()
    stored = embed_and_store(model, chunks, args.batch)
    elapsed = time.time() - t0

    log.info("=== TERMINÉ: %d embeddings BGE-M3 (1024d) en %.0fs ===", stored, elapsed)
    log.info("Redémarrer brain_worker + hub pour recharger le FAISS index.")


if __name__ == "__main__":
    main()
