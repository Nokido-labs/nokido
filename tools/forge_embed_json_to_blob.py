"""forge_embed_json_to_blob.py — Convertit les embeddings JSON-TEXT en BLOB binaire.

Stocker un vecteur 1024d en JSON texte = ~22 Ko/vecteur (chiffres en texte) au
lieu de 4096 o en float32 binaire : poids x5, parsing lent, RAM. Le JSON ne sert
qu'au transport HTTP ; le stockage persistant doit etre binaire.

Ce script reencode tout embedding stocke en TEXT (JSON) vers un BLOB
struct.pack('1024f'). Idempotent. Trigger snapshot retire pour l'UPDATE de masse.

Run : run action=trusted_script path=tools/forge_embed_json_to_blob.py
"""

import json
import sqlite3
import struct
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def main() -> None:
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    rows = con.execute(
        "SELECT rowid, embedding FROM rag_chunks "
        "WHERE embedding IS NOT NULL AND typeof(embedding)='text'"
    ).fetchall()
    print(f"[json2blob] embeddings JSON-TEXT a convertir : {len(rows)}")
    if not rows:
        con.close()
        return

    trg = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='auto_snapshot_before_update'"
    ).fetchone()
    conv = bad = 0
    t0 = time.time()
    try:
        if trg and trg[0]:
            con.execute("DROP TRIGGER auto_snapshot_before_update")
        for rowid, emb in rows:
            try:
                v = json.loads(emb)
            except Exception:
                bad += 1
                continue
            if isinstance(v, list) and len(v) == 1024:
                con.execute(
                    "UPDATE rag_chunks SET embedding=? WHERE rowid=?",
                    (struct.pack("1024f", *v), rowid),
                )
                conv += 1
            else:
                bad += 1
        con.commit()
    finally:
        if trg and trg[0]:
            con.execute(trg[0])
            con.commit()
            print("[json2blob] trigger auto_snapshot_before_update recree")

    left = con.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL AND typeof(embedding)='text'"
    ).fetchone()[0]
    con.close()
    print(f"[json2blob] {conv} convertis en BLOB, {bad} ignores, {time.time() - t0:.1f}s")
    print(f"[json2blob] embeddings TEXT restants : {left}")


if __name__ == "__main__":
    main()
