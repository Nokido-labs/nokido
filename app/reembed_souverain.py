import json
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path

# Config
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"
MODEL = "bge-m3:latest"  # Modèle attendu par le GraphRAG (dim 1024)
EXPECTED_DIM = 1024


def get_embedding(text):
    # Tentative 1: LM Studio (port 1234, OpenAI-compat)
    try:
        payload = json.dumps({"model": "local-model", "input": text[:2000]}).encode()
        req = urllib.request.Request(
            "http://localhost:1234/v1/embeddings", data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            vec = data.get("data", [{}])[0].get("embedding", [])
            if len(vec) == EXPECTED_DIM:
                return vec
    except:
        pass

    # Tentative 2: Ollama (port 11434)
    try:
        payload = json.dumps({"model": MODEL, "prompt": text[:2000]}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embeddings", data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            vec = data.get("embedding", [])
            if len(vec) == EXPECTED_DIM:
                return vec
    except:
        pass

    return None


def main():
    print(f"🚀 [RE-EMBED SOUVERAIN] Démarrage sur {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # On ne traite que les chunks NULL ou de mauvaise dimension
    rows = conn.execute("SELECT id, text FROM rag_chunks WHERE embedding IS NULL").fetchall()
    total = len(rows)
    print(f"🎯 {total} chunks à traiter.")

    count = 0
    errors = 0
    t0 = time.time()

    for rid, text in rows:
        vec = get_embedding(text)
        if vec:
            blob = struct.pack(f"{len(vec)}f", *vec)
            conn.execute("UPDATE rag_chunks SET embedding = ? WHERE id = ?", (blob, rid))
            count += 1
        else:
            errors += 1

        if count % 20 == 0:
            conn.commit()
            print(f"  [{count}/{total}] Progress... (Errors: {errors})")

        if errors > 10:
            print("❌ Trop d'erreurs (Ollama/LMS non-réactifs). Arrêt.")
            break

    conn.commit()
    conn.close()

    dur = round(time.time() - t0, 1)
    print(f"\n✅ FINI : {count} chunks ré-embeddés en {dur}s. Erreurs: {errors}")


if __name__ == "__main__":
    main()
