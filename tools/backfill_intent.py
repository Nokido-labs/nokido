import asyncio
import datetime
import hashlib
import sqlite3
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

# Chemins DERIVES du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
_RACINE = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE))
sys.path.insert(0, str(_RACINE / "app" / "services"))

LOG = str(_RACINE / "sandbox" / "intent_backfill.log")
DB = str(_RACINE / "RAG" / "embeddings.db")
EMBED_URL = "http://127.0.0.1:11434/api/embeddings"
MODEL = "bge-m3"


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def embed(text):
    import aiohttp

    async with aiohttp.ClientSession() as s:
        async with s.post(
            EMBED_URL,
            json={"model": MODEL, "prompt": text[:1200]},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            if r.status == 200:
                d = await r.json()
                v = d.get("embedding")
                if v:
                    return np.array(v, dtype=np.float32)
    return None


async def main():
    log("=== BACKFILL INTENT EMBEDDINGS ===")
    conn = sqlite3.connect(DB, timeout=60)
    rows = conn.execute(
        "SELECT id, title, description, task_type FROM agent_tasks "
        "WHERE forge_verdict='approved' AND status='done' "
        "AND intent_embedding IS NULL"
    ).fetchall()
    log(f"Taches a indexer: {len(rows)}")

    done, skip, err = 0, 0, 0
    for tid, title, desc, ttype in rows:
        # Construire le texte d'intention enrichi
        text = f"{ttype}: {title}. {desc}".strip()
        if len(text) < 5:
            text = f"{ttype} task"
        h = hashlib.md5(text.encode()).hexdigest()
        v = await embed(text)
        if v is not None and v.shape[0] == 1024:
            blob = v.astype(np.float32).tobytes()
            conn.execute(
                "UPDATE agent_tasks SET intent_embedding=?, intent_hash=? WHERE id=?",
                (blob, h, tid),
            )
            done += 1
        else:
            err += 1

        if (done + err) % 10 == 0:
            conn.commit()
            log(f"  progress: {done} ok | {err} err | {len(rows) - done - err} restants")

    conn.commit()
    conn.close()
    log(f"DONE: {done} indexes | {err} erreurs | {skip} skips")


asyncio.run(main())
