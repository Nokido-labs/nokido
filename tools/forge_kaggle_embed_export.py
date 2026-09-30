# -*- coding: utf-8 -*-
"""forge_kaggle_embed_export.py — Chantier A : export des chunks PUBLICS
(embedding NULL) vers des shards jsonl.gz pour embedding BGE-M3 sur Kaggle GPU.

PERIMETRE STRICT (liste blanche, go user 2026-07-05) : domains PUBLICS
uniquement — reference / sdk_gitingest / nagios_core / vitis_ai / gitingest
(docs vendors, RFC, SDKs open-source). AUCUN domaine prive (nokido_code,
conv, ami, lessons, mcp_result...) ne sort de la machine.

Sortie : C:/tmp/kaggle_embed/chunks_NN.jsonl.gz (id, text), ~80MB/shard.
Idempotent : re-export ecrase. Lancement : run_job detache (lecture ~1.2GB).
"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
OUT = Path(r"C:\tmp\kaggle_embed")
PUBLIC_DOMAINS = ("reference", "sdk_gitingest", "nagios_core", "vitis_ai", "gitingest")
SHARD_ROWS = 70000  # ~8 shards

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(str(DB), timeout=60)
con.execute("PRAGMA busy_timeout=60000")

q = ("SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND domain IN (%s)"
     % ",".join("?" * len(PUBLIC_DOMAINS)))
cur = con.execute(q, PUBLIC_DOMAINS)

shard, n_in_shard, total = 0, 0, 0
fh = gzip.open(OUT / f"chunks_{shard:02d}.jsonl.gz", "wt", encoding="utf-8")
for cid, text in cur:
    if not cid or not text:
        continue
    fh.write(json.dumps({"id": cid, "text": text}, ensure_ascii=False) + "\n")
    n_in_shard += 1
    total += 1
    if n_in_shard >= SHARD_ROWS:
        fh.close()
        print(f"shard {shard:02d} done ({n_in_shard} rows)", flush=True)
        shard += 1
        n_in_shard = 0
        fh = gzip.open(OUT / f"chunks_{shard:02d}.jsonl.gz", "wt", encoding="utf-8")
fh.close()
con.close()
print(f"EXPORT DONE: {total} chunks publics -> {shard + 1} shards dans {OUT}", flush=True)
