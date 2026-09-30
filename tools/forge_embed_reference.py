#!/usr/bin/env python3
"""forge_embed_reference.py — priority-embed CIBLÉ du domain='reference' (saute la queue 142k cold).

La veille a landé ~566 chunks reference (Axe B/FTS) mais l'embed daemon FIFO les laisse NULL
(backlog 142k). Ce job embed UNIQUEMENT domain='reference' via :8099 BGE-M3 (souverain GPU) ->
rend la veille SÉMANTIQUE (Axe A) tout de suite. ADMISSION-GATED (anti-embolie : le reencode brut
a wedgé le hub), borné, throttlé, déporté. Idempotent (ne touche que embedding IS NULL).
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "RAG" / "embeddings.db"
BATCH = 32
CAP = int(os.environ.get("EMBED_REF_CAP", "2000"))

from nokido_agent.app.forge_embed_router import embed_batch_fast  # noqa: E402


def main() -> int:
    rel = None
    try:
        from nokido_agent.app.forge_lane_admission import admit, release

        dec = admit("embed_reference", "claude", heavy=True)
        if not dec.get("admit", True):
            print({"skip": "admission refused (anti-embolie)", "dec": dec})
            return 0
        rel = release
    except Exception as e:  # noqa: BLE001
        print({"admission": f"unavailable: {e}"})

    done = failed = 0
    try:
        con = sqlite3.connect(str(DB), timeout=30)
        con.execute("PRAGMA busy_timeout=30000")
        rows = con.execute(
            "SELECT id, text FROM rag_chunks WHERE domain='reference' AND embedding IS NULL LIMIT ?",
            (CAP,),
        ).fetchall()
        con.close()
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            vecs = embed_batch_fast([r[1] or "" for r in chunk], batch_size=BATCH)
            con = sqlite3.connect(str(DB), timeout=30)
            con.execute("PRAGMA busy_timeout=30000")
            for (cid, _t), v in zip(chunk, vecs):
                if v:
                    con.execute(
                        "UPDATE rag_chunks SET embedding=? WHERE id=?",
                        (np.array(v, dtype=np.float32).tobytes(), cid),
                    )
                    done += 1
                else:
                    failed += 1
            con.commit()
            con.close()
            time.sleep(0.5)  # throttle anti-saturation :8099 / WAL
    finally:
        if rel:
            try:
                rel("embed_reference", "claude")
            except Exception:
                pass
    print({"embedded": done, "failed": failed, "total_null": len(rows)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
