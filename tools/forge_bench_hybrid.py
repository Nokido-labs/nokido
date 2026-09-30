"""forge_bench_hybrid.py — Compare retrieval dense / BM25 / hybride RRF.

Investigation : le BEIR initial = dense pur. Le vrai RAGEngine de Nokido fait
dense + BM25 + fusion RRF. Ce script mesure les 3 sur le meme echantillon ->
montre si l'hybride corrige la mediocrite du dense. Non-destructif.

Run : run action=trusted_script path=tools/forge_bench_hybrid.py
"""

import json
import math
import re
import sqlite3
import struct
import urllib.request
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
DB = ROOT / "RAG" / "embeddings.db"
PORT = 8099
DIM = 1024
KS = [1, 5, 10]
RRF_K = 60
_TOK = re.compile(r"\w+")


def _embed(texts: list) -> list:
    body = json.dumps({"input": texts}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return [it["embedding"] for it in sorted(d["data"], key=lambda x: x.get("index", 0))]


def _decode(blob):
    if isinstance(blob, bytes) and len(blob) == DIM * 4:
        return list(struct.unpack(f"{DIM}f", blob))
    if isinstance(blob, (bytes, str)):
        try:
            v = json.loads(blob)
            if isinstance(v, list) and len(v) == DIM:
                return v
        except Exception:
            pass
    return None


def _norm(mat) -> np.ndarray:
    m = np.asarray(mat, dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _metrics(ranks: list) -> str:
    r = np.array(ranks)
    out = " ".join(f"R@{k}={(r <= k).mean():.3f}" for k in KS)
    mrr = np.mean([1.0 / x if x <= 10 else 0.0 for x in r])
    ndcg = np.mean([1.0 / math.log2(x + 1) if x <= 10 else 0.0 for x in r])
    return f"{out} MRR@10={mrr:.3f} NDCG@10={ndcg:.3f}"


def main() -> None:
    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    ids = [c["id"] for c in sample]
    idpos = {cid: i for i, cid in enumerate(ids)}
    text = {c["id"]: c["text"] for c in sample}

    emb = [None] * len(ids)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for i in range(0, len(ids), 900):
        batch = ids[i : i + 900]
        ph = ",".join("?" * len(batch))
        for cid, blob in con.execute(
            f"SELECT id, embedding FROM rag_chunks WHERE id IN ({ph})", batch
        ):
            v = _decode(blob)
            if v and cid in idpos:
                emb[idpos[cid]] = v
    con.close()
    keep = [i for i, v in enumerate(emb) if v is not None]
    cids = [ids[i] for i in keep]
    cpos = {c: i for i, c in enumerate(cids)}
    cmat = _norm([emb[i] for i in keep])
    print(f"[hybrid] corpus {len(cids)} chunks — build BM25...", flush=True)
    bm25 = BM25Okapi([_TOK.findall(text[c].lower()) for c in cids])

    queries = [json.loads(l) for l in (BENCH / "queries.jsonl").open(encoding="utf-8")]
    qrels = json.loads((BENCH / "qrels.json").read_text(encoding="utf-8"))
    valid = [q for q in queries if q["_id"] in qrels and any(c in cpos for c in qrels[q["_id"]])]
    qmat = _norm(
        [
            v
            for i in range(0, len(valid), 32)
            for v in _embed([q["text"] for q in valid[i : i + 32]])
        ]
    )
    print(f"[hybrid] {len(valid)} requetes — retrieval...", flush=True)

    dense_r, bm25_r, hyb_r = [], [], []
    for qi, q in enumerate(valid):
        gold = cpos[next(c for c in qrels[q["_id"]] if c in cpos)]
        dsc = qmat[qi] @ cmat.T
        bsc = np.array(bm25.get_scores(_TOK.findall(q["text"].lower())))
        d_order = np.argsort(-dsc)
        b_order = np.argsort(-bsc)
        d_rank = {int(idx): r for r, idx in enumerate(d_order, 1)}
        b_rank = {int(idx): r for r, idx in enumerate(b_order, 1)}
        rrf = np.array(
            [1.0 / (RRF_K + d_rank[i]) + 1.0 / (RRF_K + b_rank[i]) for i in range(len(cids))]
        )
        h_order = np.argsort(-rrf)
        dense_r.append(int(np.where(d_order == gold)[0][0]) + 1)
        bm25_r.append(int(np.where(b_order == gold)[0][0]) + 1)
        hyb_r.append(int(np.where(h_order == gold)[0][0]) + 1)

    print(f"\n=== Retrieval compare ({len(valid)} requetes, corpus {len(cids)}) ===")
    print(f"  dense   {_metrics(dense_r)}")
    print(f"  bm25    {_metrics(bm25_r)}")
    print(f"  hybride {_metrics(hyb_r)}")


if __name__ == "__main__":
    main()
