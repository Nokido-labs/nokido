"""forge_bench_ragtool.py — Bench du hub `rag` tool (pipeline dense).

Replique la logique de handle_rag action=search version dense : embed la
requete (:8099) + cosine sur le tier chaud (15.7k) + rerank cross-encoder
(:8100). Mesure le retrieval sur les questions du benchmark sur le VRAI corpus
que le rag tool interroge. Valide aussi le pipeline avant restart du hub.

Run : run action=trusted_script path=tools/forge_bench_ragtool.py
"""

import json
import math
import struct
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
DB = ROOT / "RAG" / "embeddings.db"
KS = [1, 5, 10]


def _load_jsonl(p: Path) -> list:
    out = []
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _post(port: int, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _metrics(ranks: list) -> str:
    r = np.array(ranks)
    out = " ".join(f"R@{k}={(r <= k).mean():.3f}" for k in KS)
    mrr = np.mean([1.0 / x if x <= 10 else 0.0 for x in r])
    ndcg = np.mean([1.0 / math.log2(x + 1) if x <= 10 else 0.0 for x in r])
    return f"{out} MRR@10={mrr:.3f} NDCG@10={ndcg:.3f}"


def main() -> None:
    import sqlite3

    # corpus = tier chaud reel (ce que le rag tool interroge)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    ids, vecs, text, csrc = [], [], {}, {}
    for cid, src, txt, emb in con.execute(
        "SELECT id, source, text, embedding FROM rag_chunks WHERE embedding IS NOT NULL"
    ):
        v = None
        if isinstance(emb, bytes) and len(emb) == 4096:
            v = struct.unpack("1024f", emb)
        elif isinstance(emb, (bytes, str)):
            try:
                jv = json.loads(emb)
                if isinstance(jv, list) and len(jv) == 1024:
                    v = jv
            except Exception:
                pass
        if v is None or not cid:
            continue
        ids.append(cid)
        vecs.append(v)
        text[cid] = txt
        csrc[cid] = src or ""
    con.close()
    cmat = np.asarray(vecs, dtype=np.float32)
    cmat /= np.linalg.norm(cmat, axis=1, keepdims=True) + 1e-9
    cpos = {c: i for i, c in enumerate(ids)}

    def _file_of(s: str) -> str:
        s = (s or "").split("#")[0]
        i = s.rfind("_part")
        if i > 0 and s[i + 5 :].isdigit():
            s = s[:i]
        return s

    cfile = {}
    for c in ids:
        cfile.setdefault(_file_of(csrc[c]), []).append(c)
    print(f"[ragtool] corpus tier chaud : {len(ids)} chunks", flush=True)

    sample = _load_jsonl(BENCH / "sample.jsonl")
    gchunks = [c for c in sample if 250 <= len(c["text"]) <= 4000]
    gstep = max(1, len(gchunks) // 120)
    picked = gchunks[::gstep][:120]
    queries = _load_jsonl(BENCH / "queries.jsonl")
    gold = {}
    for q in queries:
        try:
            idx = int(q["_id"].lstrip("q"))
        except ValueError:
            continue
        if idx >= len(picked):
            continue
        # multi-gold : tous les chunks du meme fichier source = pertinents
        gset = {cpos[c] for c in cfile.get(_file_of(picked[idx].get("source", "")), [])}
        if picked[idx]["id"] in cpos:
            gset.add(cpos[picked[idx]["id"]])
        if gset:
            gold[q["_id"]] = gset
    valid = [q for q in queries if q["_id"] in gold]
    print(f"[ragtool] {len(valid)} requetes", flush=True)

    qvecs = []
    for i in range(0, len(valid), 32):
        d = _post(8099, "/v1/embeddings", {"input": [q["text"] for q in valid[i : i + 32]]})
        qvecs.extend(it["embedding"] for it in sorted(d["data"], key=lambda x: x.get("index", 0)))
    qmat = np.asarray(qvecs, dtype=np.float32)
    qmat /= np.linalg.norm(qmat, axis=1, keepdims=True) + 1e-9

    dense_r, rr_r = [], []
    for qi, q in enumerate(valid):
        gset = gold[q["_id"]]
        order = np.argsort(-(qmat[qi] @ cmat.T))
        d_rank = next((r for r, idx0 in enumerate(order, 1) if int(idx0) in gset), 999)
        dense_r.append(d_rank)
        cand = [int(x) for x in order[:50]]
        try:
            res = _post(
                8100,
                "/v1/rerank",
                {
                    "model": "x",
                    "query": q["text"],
                    "documents": [(text[ids[c]] or "")[:512] for c in cand],
                },
            )["results"]
            res = sorted(res, key=lambda x: -x.get("relevance_score", 0.0))
            reranked = [cand[x["index"]] for x in res]
            rr_r.append(next((r for r, c in enumerate(reranked, 1) if c in gset), d_rank))
        except Exception:
            rr_r.append(d_rank)

    print(f"\n=== rag tool pipeline dense ({len(valid)} req, corpus {len(ids)}) ===")
    print(f"  dense        {_metrics(dense_r)}")
    print(f"  dense+rerank {_metrics(rr_r)}")
    (BENCH / "ragtool_results.json").write_text(
        json.dumps(
            {
                "dense": _metrics(dense_r),
                "rerank": _metrics(rr_r),
                "n": len(valid),
                "corpus": len(ids),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
