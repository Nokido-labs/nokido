#!/usr/bin/env python
"""tools/forge_rag_embed_daemon.py — Embedde les chunks RAG dont embedding IS NULL.

Requiert brain_worker ZMQ sur :5557.
Protocole: submit {"cmd":"submit","type":"embed","texts":[...]} → task_id
           check  {"cmd":"check","task_id":"..."} → {status, data}
"""

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
ZMQ_ADDR = "tcp://127.0.0.1:5557"
BATCH = 50
SLEEP_S = 2
LOG_EVERY = 100
POLL_INTERVAL = 0.05  # 50ms entre check polls
POLL_TIMEOUT = 30  # abandon après 30s


def _zmq_call(sock, msg: dict) -> dict:
    sock.send(json.dumps(msg).encode("utf-8"))
    if sock.poll(10_000):  # 10s timeout
        return json.loads(sock.recv().decode("utf-8"))
    return {"ok": False, "error": "zmq timeout"}


def _get_embedding(text: str, sock) -> bytes | None:
    """Submit embed via ZMQ REQ, poll until completed, return float32 bytes."""
    try:
        import numpy as np

        # submit
        rep = _zmq_call(sock, {"cmd": "submit", "type": "embed", "texts": [text[:500]]})
        if not rep.get("ok"):
            return None
        task_id = rep.get("task_id", "")
        if not task_id:
            return None
        # poll check
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            r = _zmq_call(sock, {"cmd": "check", "task_id": task_id})
            status = r.get("status", "")
            if status == "completed":
                data = r.get("data")
                # data = [[float,...]] ou {"vecs":[[float,...]],...}
                if isinstance(data, dict):
                    vecs = data.get("vecs", [])
                else:
                    vecs = data or []
                if not vecs:
                    return None
                vec = vecs[0]
                return np.array(vec, dtype="float32").tobytes()
            if status == "error":
                return None
            time.sleep(POLL_INTERVAL)
        return None
    except Exception:
        return None


def run_once(conn: sqlite3.Connection, sock) -> int:
    rows = conn.execute(
        "SELECT id, text FROM rag_chunks WHERE embedding IS NULL LIMIT ?", (BATCH,)
    ).fetchall()
    if not rows:
        return 0
    updated = 0
    for chunk_id, text in rows:
        emb = _get_embedding(text, sock)
        if emb:
            conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (emb, chunk_id))
            updated += 1
    conn.commit()
    return updated


def main() -> None:
    try:
        import zmq
    except ImportError:
        print("[embed_daemon] ERREUR: pyzmq non installé — pip install pyzmq")
        return

    print(f"[embed_daemon] start — DB={DB} ZMQ={ZMQ_ADDR} batch={BATCH} sleep={SLEEP_S}s")
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(ZMQ_ADDR)

    conn = sqlite3.connect(str(DB), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    total = 0
    try:
        while True:
            n = run_once(conn, sock)
            total += n
            if n:
                if total % LOG_EVERY < BATCH:
                    null_count = conn.execute(
                        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"
                    ).fetchone()[0]
                    print(f"[embed_daemon] {total} embedded | {null_count} remaining")
            else:
                print(f"[embed_daemon] idle — {total} total embedded, sleeping {SLEEP_S}s")
            time.sleep(SLEEP_S)
    except KeyboardInterrupt:
        print(f"[embed_daemon] stopped — {total} chunks embedded")
    finally:
        conn.close()
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
