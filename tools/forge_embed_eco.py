# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_embed_eco_2_onnx

forge_embed_eco.py — Drain ECO du backlog HOT en BGE-M3 ONNX sur **CPU**
(onnxruntime CPUExecutionProvider + lib `tokenizers`). ZÉRO DirectML => ZÉRO BSOD
0x119 [[incident_bsod_2026-05-24_directml_brainworker]]. ZÉRO transformers/
sentence-transformers/huggingface-hub => contourne l'env base ML cassé
(hf-hub 1.4.1 vs transformers<1.0, [[jepa_finetune_verdict_2026-06-01]]).

Tourne MÊME dans le sandbox `run` (onnxruntime+tokenizers ne trippent pas le
workspace_guard, contrairement à torch). V: writable en realpath direct.

Réutilise HOT_TIER_SQL (forge_tier_policy) — ne touche QUE le tier hot.

SÉCURITÉ VECTEURS : `--verify` re-embed un chunk DÉJÀ vectorisé avec les 2 poolings
candidats (CLS = last_hidden_state[:,0] ; POOLED = 2e sortie du modèle) et compare
par COSINUS au vecteur stocké. Le pooling gagnant (cos>=0.95) est retenu pour le
drain. Si aucun >=0.95 => STOP (pas de vecteurs incompatibles injectés).

USAGE (base-python OU hub run) :
    forge_embed_eco.py --verify
    forge_embed_eco.py --drain --limit 2000 --batch 32
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_tier_policy import HOT_TIER_SQL  # noqa: E402

ONNX_DIR = Path(os.environ.get("LAFORGE_BGE_M3_ONNX", str(ROOT / "models" / "bge_m3_onnx")))
DB = os.path.realpath(str(ROOT / "RAG" / "embeddings.db"))  # -> %NOKIDO_DATA%\ (writable ; symlink C: foire sur -wal)
MAX_LEN = 512
_POOL = "cls"  # fixé par verify() : "cls" | "pooled"

_SESS = None
_TOK = None


def _decode(blob):
    from nokido_agent.app.forge_rag_engine import _decode_embedding_blob

    return _decode_embedding_blob(blob)


def _encode_blob(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def _load():
    global _SESS, _TOK
    if _SESS is None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        _so = ort.SessionOptions()
        # ECO : cap les threads intra-op pour NE PAS peg tous les cœurs (anti-saturation
        # qui a fait tomber le hub en run synchrone). LAFORGE_EMBED_THREADS (def 4).
        _so.intra_op_num_threads = int(os.environ.get("LAFORGE_EMBED_THREADS", "4"))
        _SESS = ort.InferenceSession(
            str(ONNX_DIR / "model.onnx"), sess_options=_so, providers=["CPUExecutionProvider"]
        )
        _TOK = Tokenizer.from_file(str(ONNX_DIR / "tokenizer.json"))
        _TOK.enable_truncation(max_length=MAX_LEN)
        _TOK.enable_padding(pad_id=1, pad_token="<pad>")  # XLM-R/BGE-M3 pad=1
    return _SESS, _TOK


def _run(texts: list[str]):
    """Retourne (last_hidden_state[b,seq,1024] f32, pooled[b,1024] f32)."""
    sess, tok = _load()
    encs = tok.encode_batch(texts)
    ids = np.array([e.ids for e in encs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    outs = sess.run(None, {"input_ids": ids, "attention_mask": mask})
    lhs = outs[0].astype(np.float32)
    pooled = outs[1].astype(np.float32) if len(outs) > 1 else lhs[:, 0]
    return lhs, pooled


def _l2(v):
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


EXPECT_DIM = 1024  # canonique BGE-M3 — JAMAIS écrire une autre dim (sinon index ragged)


def embed(texts: list[str], pool: str | None = None) -> np.ndarray:
    """Embeddings 1024D L2-normalisés. pool: cls|pooled (défaut module _POOL)."""
    pool = pool or _POOL
    lhs, pooled = _run(texts)
    vec = lhs[:, 0] if pool == "cls" else pooled
    out = _l2(vec)
    if out.shape[-1] != EXPECT_DIM:  # garde anti-mix dimensionnel
        raise ValueError(f"dim {out.shape[-1]} != {EXPECT_DIM} — refus d'écrire (cohabitation 384/1024 = index cassé)")
    return out


def audit() -> dict:
    """Audit dimensionnel : détecte un mix 384D/1024D (legacy MiniLM vs BGE-M3) qui
    casserait la recherche vectorielle. Groupe par taille de blob + modèle."""
    import sqlite3

    c = sqlite3.connect(DB)
    rows = c.execute(
        "SELECT LENGTH(embedding) bytes, COUNT(*) n, "
        "GROUP_CONCAT(DISTINCT COALESCE(embedding_model,'?')) models "
        "FROM rag_chunks WHERE embedding IS NOT NULL "
        "GROUP BY bytes ORDER BY n DESC LIMIT 12"
    ).fetchall()
    c.close()
    out = [{"bytes": r[0], "approx_dim_f32": (r[0] // 4 if r[0] else None), "n": r[1], "models": r[2]} for r in rows]
    print("DIM AUDIT (4096o=1024D, 1536o=384D, autre=JSON/anomalie) :")
    for r in out:
        print(f"  {r}")
    mix = len({r["bytes"] for r in out if r["bytes"] and r["bytes"] in (4096, 1536)}) > 1
    print("MIX 384/1024 DÉTECTÉ" if mix else "Pas de mix 384/1024 BLOB")
    return {"groups": out, "mix": mix}


def verify() -> bool:
    """Teste les 2 poolings vs un vecteur stocké ; fixe _POOL au gagnant. True si OK."""
    global _POOL
    import sqlite3

    c = sqlite3.connect(DB)
    row = c.execute(
        "SELECT text, embedding FROM rag_chunks WHERE embedding IS NOT NULL AND LENGTH(text)>40 LIMIT 1"
    ).fetchone()
    c.close()
    if not row:
        print("VERIFY: aucun vecteur de référence")
        return False
    stored = np.array(_decode(row[1]), dtype=np.float32)
    best, best_cos = None, -1.0
    for pool in ("cls", "pooled"):
        fresh = embed([row[0]], pool=pool)[0]
        if fresh.shape != stored.shape:
            print(f"  {pool}: dim {fresh.shape} != base {stored.shape}")
            continue
        cos = float(np.dot(stored, fresh) / (np.linalg.norm(stored) * np.linalg.norm(fresh) + 1e-9))
        print(f"  pool={pool}: cosinus={cos:.4f}")
        if cos > best_cos:
            best, best_cos = pool, cos
    if best and best_cos >= 0.95:
        _POOL = best
        print(f"VERIFY OK -> pool={best} (cos={best_cos:.4f}), drain autorisé")
        return True
    print(f"VERIFY MISMATCH (meilleur cos={best_cos:.4f} < 0.95) -> STOP")
    return False


def drain(limit: int, batch: int) -> dict:
    if not verify():
        return {"error": "verify échoué — pipeline incompatible, drain annulé"}
    import sqlite3

    c = sqlite3.connect(DB, timeout=15)
    rows = c.execute(
        f"SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND {HOT_TIER_SQL} ORDER BY rowid LIMIT ?",
        (limit,),
    ).fetchall()
    total = len(rows)
    print(f"DRAIN: {total} chunks hot (CPU pool={_POOL} batch={batch})", flush=True)
    done, t0 = 0, time.monotonic()
    for i in range(0, total, batch):
        part = rows[i : i + batch]
        vecs = embed([t for _, t in part])
        for (cid, _), v in zip(part, vecs):
            c.execute("UPDATE rag_chunks SET embedding=?, embedding_model=? WHERE id=?",
                      (_encode_blob(v), "bge-m3-eco-cpu", cid))
        c.commit()
        done += len(part)
        if (i // batch) % 5 == 0 or done == total:
            print(f"  {done}/{total} ({done / max(time.monotonic() - t0, 0.1):.1f}/s)", flush=True)
    c.close()
    return {"embedded": done, "secs": round(time.monotonic() - t0, 1), "pool": _POOL}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Drain eco BGE-M3 ONNX CPU du backlog hot.")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--audit", action="store_true", help="audit dimensionnel (mix 384/1024 ?)")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=32)
    a = ap.parse_args(argv)
    print(f"[eco] onnx={ONNX_DIR} db={DB}")
    if a.audit:
        print(json.dumps(audit(), ensure_ascii=False))
    elif a.drain:
        print(json.dumps(drain(a.limit, a.batch), ensure_ascii=False))
    elif a.verify:
        verify()
    else:
        ap.error("--verify | --drain | --audit requis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
