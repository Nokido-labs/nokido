"""
tools/migrate_embeddings_dim.py — Migration FAISS 384D→1024D (MiniLM→BGE-M3)
Re-embedde les chunks 384D via brain_worker ZMQ :5557
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"


def _embed_zmq(text: str, timeout_ms: int = 10000) -> list[float] | None:
    try:
        import zmq

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        sock.connect("tcp://127.0.0.1:5557")
        sock.send_json({"text": text, "model": "bge-m3"})
        resp = sock.recv_json()
        sock.close()
        return resp.get("embedding") or resp.get("vector")
    except Exception as e:
        print(f"  ZMQ error: {e}", file=sys.stderr)
        return None


def migrate(db_path: Path, dry_run: bool, batch_size: int = 50):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        "SELECT id, text, embedding FROM rag_chunks WHERE embedding IS NOT NULL"
    ).fetchall()

    to_migrate = [(r[0], r[1]) for r in rows if len(json.loads(r[2])) == 384]
    print(
        f"Total chunks: {len(rows)} | 384D (to migrate): {len(to_migrate)} | 1024D: {len(rows) - len(to_migrate)}"
    )

    if dry_run:
        print("[DRY RUN] Aucune modification.")
        conn.close()
        return

    migrated, failed = 0, 0
    for chunk_id, text in tqdm(to_migrate, desc="re-embedding 384→1024", unit="chunks"):
        new_vec = _embed_zmq(text)
        if new_vec is None or len(new_vec) != 1024:
            failed += 1
            continue
        conn.execute(
            "UPDATE rag_chunks SET embedding=? WHERE id=?", (json.dumps(new_vec), chunk_id)
        )
        migrated += 1
        if migrated % batch_size == 0:
            conn.commit()
            time.sleep(0.05)

    conn.commit()
    conn.close()
    print(f"Migrated: {migrated} | Failed: {failed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    migrate(Path(args.db), args.dry_run)
