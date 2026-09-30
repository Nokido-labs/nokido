# -*- coding: utf-8 -*-
"""forge_kaggle_embed_import.py — Chantier A3 : import GATÉ des vecteurs Kaggle.

Lit C:/tmp/kaggle_embed/out/vecs_*.npz (ids + dense 1024D fp16 BGE-M3).

GATE DE COHERENCE OBLIGATOIRE avant tout import massif (leçon bench : jamais
mélanger deux embedders non prouvés compatibles) : échantillon aléatoire de
48 chunks -> re-embed via l'embedder SOUVERAIN :8099 (BGE-M3 GGUF Q8, pooling
CLS, forge_embed_router) -> cosinus normalisé. Import SEULEMENT si
mean >= 0.985 ET min >= 0.95. Sinon ABORT (aucune écriture).

Écriture : UPDATE rag_chunks SET embedding=<BLOB float32 1024> WHERE id=?
AND embedding IS NULL (idempotent : ne écrase jamais le drain local).
Lots de 2000 + busy_timeout (contention drain).

Run : run_job détaché (offline) une fois les .npz déposés dans out/.
"""
import glob
import json
import random
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np

# Chemins DERIVES du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
IN_DIR = Path(r"C:\tmp\kaggle_embed\out")
GATE_N = 48
GATE_MEAN = 0.985
GATE_MIN = 0.95

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def main() -> int:
    files = sorted(glob.glob(str(IN_DIR / "vecs_*.npz")))
    if not files:
        print(f"ABORT: aucun vecs_*.npz dans {IN_DIR}")
        return 2

    # ── Charge tout (ids -> vec fp16) ────────────────────────────────────────
    pairs = []
    for f in files:
        z = np.load(f, allow_pickle=False)
        ids, vecs = z["ids"], z["vecs"]
        if vecs.shape[1] != 1024:
            print(f"ABORT: {f} dim {vecs.shape[1]} != 1024")
            return 2
        pairs.append((ids, vecs))
        print(f"loaded {Path(f).name}: {vecs.shape}", flush=True)
    total = sum(len(i) for i, _ in pairs)
    print(f"total vecteurs: {total}", flush=True)

    # ── GATE : échantillon vs :8099 ──────────────────────────────────────────
    from nokido_agent.app.forge_embed_router import embed as sovereign_embed

    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    rng = random.Random(42)
    sample = []
    for ids, vecs in pairs:
        for _ in range(max(1, GATE_N // len(pairs))):
            k = rng.randrange(len(ids))
            sample.append((str(ids[k]), vecs[k]))
    sims = []
    for cid, kvec in sample[:GATE_N]:
        row = con.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
        if not row or not row[0]:
            continue
        sv = sovereign_embed(row[0])
        if not sv or len(sv) != 1024:
            continue
        sims.append(float(np.dot(_norm(kvec), _norm(sv))))
    if len(sims) < GATE_N // 2:
        print(f"ABORT: gate insuffisant ({len(sims)} comparaisons, :8099 down ?)")
        con.close()
        return 2
    mean_s, min_s = float(np.mean(sims)), float(np.min(sims))
    print(f"GATE: n={len(sims)} cos mean={mean_s:.4f} min={min_s:.4f}", flush=True)
    if mean_s < GATE_MEAN or min_s < GATE_MIN:
        print(f"ABORT: gate FAIL (requis mean>={GATE_MEAN} min>={GATE_MIN}) — AUCUNE écriture")
        con.close()
        return 3

    # ── Import idempotent par lots ───────────────────────────────────────────
    written = skipped = 0
    for ids, vecs in pairs:
        batch = []
        for i in range(len(ids)):
            blob = struct.pack("1024f", *np.asarray(vecs[i], dtype=np.float32))
            batch.append((blob, str(ids[i])))
            if len(batch) >= 2000:
                cur = con.executemany(
                    "UPDATE rag_chunks SET embedding=? WHERE id=? AND embedding IS NULL", batch)
                written += cur.rowcount
                skipped += len(batch) - cur.rowcount
                con.commit()
                batch = []
                print(f"progress: written={written} skipped={skipped}", flush=True)
        if batch:
            cur = con.executemany(
                "UPDATE rag_chunks SET embedding=? WHERE id=? AND embedding IS NULL", batch)
            written += cur.rowcount
            skipped += len(batch) - cur.rowcount
            con.commit()
    con.close()
    print("RESULT:", json.dumps({"written": written, "skipped_already_embedded": skipped,
                                 "gate_mean": round(mean_s, 4), "gate_min": round(min_s, 4)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
