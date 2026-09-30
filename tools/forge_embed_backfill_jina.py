#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_embed_backfill_jina.py — backfill cloud des embeddings NULL via Jina.

POURQUOI (2026-06-03) : la veille / l'egress indexent des chunks avec embedding
NULL quand AUCUN embedder n'est dispo dans leur contexte — l'embedder LOCAL
(BGE-M3 ONNX :5557) fait `bad allocation` (OOM, cf memory), et le cloud échoue
car les contextes trusted/ChainExecutor ont l'egress internet BLOQUÉ. Résultat :
corpus non cherchable. Ce tool contourne le split de contextes (AUCUN n'a à la
fois egress + DB + vault) via 3 phases :

  prep  (trusted)        : lit les chunks NULL + clé jina (vault) -> in.json
  embed (run_job online) : in.json -> Jina API (egress) -> out.json   [ARGLESS = défaut]
  apply (trusted)        : out.json -> UPDATE rag_chunks.embedding (BLOB f32)

Le call Jina mirror forge_embed_router._jina_call (model jina-embeddings-v3,
dimensions=1024, task retrieval.passage => compatible corpus BGE-M3 1024D) mais
est STANDALONE ici : on ne peut pas importer forge_embed_router dans le contexte
sandbox-online (deps zmq/vault absentes). Le BLOB d'apply réutilise encode_blob
du router (contexte trusted) pour un format identique à l'ingest.

Usage :
  trusted_script forge_embed_backfill_jina.py  (script_args="prep")
  run_job        forge_embed_backfill_jina.py  online=true        # phase embed
  trusted_script forge_embed_backfill_jina.py  (script_args="apply")
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

DB = r"%NOKIDO_DATA%\embeddings.db"  # realpath direct (pas le symlink C:, cf memory)
IN = r"C:\tmp\embed_backfill_in.json"
OUT = r"C:\tmp\embed_backfill_out.json"
DOMAINS = ("knowledge_github", "watch_veille")
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
APP = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app")
JINA_URL = "https://api.jina.ai/v1/embeddings"


def prep() -> int:
    """trusted : chunks NULL (id,text) + clé jina -> in.json."""
    sys.path.insert(0, APP)
    try:
        from nokido_agent.app.forge_secrets import get_secret
        key = get_secret("JINA_API_KEY") or ""
    except Exception:
        key = get_secret("JINA_API_KEY") or ""
    conn = sqlite3.connect(DB, timeout=15)
    rows = []
    for dom in DOMAINS:
        for cid, text in conn.execute(
            "SELECT id,text FROM rag_chunks WHERE domain=? AND embedding IS NULL", (dom,)
        ):
            rows.append({"id": cid, "text": (text or "")[:8000]})
    conn.close()
    os.makedirs(os.path.dirname(IN), exist_ok=True)
    with open(IN, "w", encoding="utf-8") as fh:
        json.dump({"key": key, "rows": rows}, fh, ensure_ascii=False)
    print(f"prep: {len(rows)} chunks NULL -> {IN} (key={'yes' if key else 'NO'})")
    return 0


def embed() -> int:
    """run_job online (egress) : in.json -> Jina batch -> out.json."""
    with open(IN, encoding="utf-8") as fh:
        d = json.load(fh)
    key, rows = d["key"], d["rows"]
    if not key:
        print("embed: ABORT no jina key in in.json")
        return 2
    out, B = [], 64
    for i in range(0, len(rows), B):
        batch = rows[i : i + B]
        body = json.dumps({
            "model": "jina-embeddings-v3",
            "task": "retrieval.passage",
            "dimensions": 1024,
            "input": [r["text"][:8000] for r in batch],
        }).encode()
        req = urllib.request.Request(
            JINA_URL, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key.strip(),
                "User-Agent": "Mozilla/5.0 LaForge-Embed",
                "Accept": "application/json",
            },
        )
        data = json.loads(urllib.request.urlopen(req, timeout=90).read())
        items = data.get("data", [])
        for j, it in enumerate(items):
            v = it.get("embedding")
            if v:
                out.append({"id": batch[j]["id"], "vec": v})
        print(f"embed: batch {i // B} -> {len(items)} vecs")
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    print(f"embed: {len(out)} vecs (dim {len(out[0]['vec']) if out else 0}) -> {OUT}")
    return 0


def apply() -> int:
    """trusted : out.json -> UPDATE rag_chunks.embedding (BLOB f32 via encode_blob)."""
    sys.path.insert(0, APP)
    from nokido_agent.app.forge_embed_router import encode_blob
    with open(OUT) as fh:
        out = json.load(fh)
    conn = sqlite3.connect(DB, timeout=15)
    n = 0
    for o in out:
        vec = o["vec"]
        if not vec or len(vec) < 256:
            continue
        conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (encode_blob(vec), o["id"]))
        n += 1
    conn.commit()
    # contrôle : combien restent NULL sur les domaines ciblés
    left = sum(
        conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain=? AND embedding IS NULL", (dom,)
        ).fetchone()[0]
        for dom in DOMAINS
    )
    conn.close()
    print(f"apply: {n} embeddings écrits ; NULL restants (domaines ciblés)={left}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "embed"
    raise SystemExit({"prep": prep, "embed": embed, "apply": apply}[cmd]())
