#!/usr/bin/env python3
"""forge_code_reindex.py — reindexer BULK EFFICACE du code -> RAG (standalone, sans warmup).

Pourquoi pas l'engine : (1) RAGEngine.__init__ charge 173k chunks (warmup lent) ; (2) son
get_embeddings tombe sur Ollama :11434 (foire en standalone), PAS le vrai embedder. Ici on
embed via forge_embed_router (-> :8099 BGE-M3 1024D) + encode_blob (BLOB canonique, compatible
forge_faiss_sidecar + _decode_embedding_blob). Par fichier : chunk (mots) + embed batch +
DELETE source + INSERT OR REPLACE UNIQUEMENT ce fichier (id sha déterministe = dedup). Idempotent.

  --dirs app tools   dirs (défaut app)   --limit N   max fichiers   --sleep 0.0   pause/fichier
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

# Racine DERIVEE du fichier (phase 0 du renommage vers Nokido) : tools/ -> parent.parent.
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
from nokido_agent.app import forge_embed_router as _er  # noqa

_SKIP = ("_attic", "archive", "node_modules", ".git", "__pycache__")


def _chunks(text: str, source: str, words: int = 120, overlap: int = 20) -> list[str]:
    """Chunker mots simple (~120 mots ≈ 600 chars), préfixe [Doc: src]. Code-friendly."""
    toks = text.split()
    out, i = [], 0
    while i < len(toks):
        seg = " ".join(toks[i:i + words]).strip()
        if seg:
            out.append(f"[Doc: {source}] " + seg)
        i += max(1, words - overlap)
    if not out and text.strip():
        out = [f"[Doc: {source}] " + text.strip()[:2000]]
    return out


def _cid(source: str, text: str) -> str:
    return "code_" + hashlib.sha256((source + "|" + text).encode("utf-8")).hexdigest()[:16]


def reindex(dirs: list[str], limit: int, sleep_s: float) -> None:
    files: list[Path] = []
    for d in dirs:
        files += sorted((ROOT / d).rglob("*.py"))
    files = [f for f in files if not any(x in str(f) for x in _SKIP)]
    if limit:
        files = files[:limit]
    print(f"[reindex] {len(files)} fichiers, embed via forge_embed_router -> :8099", flush=True)

    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    done = ctot = skip = 0
    t0 = time.time()
    for p in files:
        src = str(p.relative_to(ROOT)).replace("\\", "/")
        try:
            text = p.read_text("utf-8", "ignore")
            if len(text.strip()) < 30:
                skip += 1
                continue
            chs = _chunks(text, src)
            vecs = _er.embed_batch_fast(chs)
            if not vecs or all(v is None for v in vecs):
                print(f"  [skip embed] {src}", flush=True)
                skip += 1
                continue
            now = _dt.datetime.utcnow().isoformat()
            conn.execute("DELETE FROM rag_chunks WHERE source = ?", (src,))  # clean slate
            for txt, v in zip(chs, vecs):
                if v is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO rag_chunks"
                    "(id, text, source, domain, role_hint, embedding, meta, ingested_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (_cid(src, txt), txt, src, "code", "chat", _er.encode_blob(v), "{}", now),
                )
            conn.commit()
            done += 1
            ctot += len(chs)
            if done % 25 == 0:
                print(f"  {done}/{len(files)} · {ctot} chunks · {int(time.time() - t0)}s", flush=True)
            if sleep_s:
                time.sleep(sleep_s)
        except Exception as ex:  # noqa
            print(f"  [X] {src}: {type(ex).__name__}: {ex}", flush=True)
    conn.close()
    print(f"DONE: {done}/{len(files)} fichiers, {ctot} chunks, {skip} skip, {int(time.time() - t0)}s", flush=True)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+", default=["app"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.0)
    a = ap.parse_args(argv)
    reindex(a.dirs, a.limit, a.sleep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
