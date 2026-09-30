"""forge_bench_rerank.py — Benchmark retrieval dense vs dense+reranker.

Etape 3-4 du benchmark. Recupere top-50 dense (bge-m3, :8099) puis re-classe
via le cross-encoder bge-reranker-v2-m3 (:8100). Compare les metriques IR
dense-seul vs dense->rerank. Corpus = sample.jsonl propre.

Run : run action=trusted_script path=tools/forge_bench_rerank.py
"""

import json
import math
import sqlite3
import struct
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
DB = ROOT / "RAG" / "embeddings.db"
EMB_PORT, RR_PORT = 8099, 8100
DIM = 1024
KS = [1, 5, 10]
TOPN = 50  # candidats dense reclasses (cout reranker ~lineaire)
DOC_CHARS = 450  # troncature doc pour le reranker (vitesse sur iGPU)


def _post(port: int, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def _embed(texts: list) -> list:
    d = _post(EMB_PORT, "/v1/embeddings", {"input": texts})
    return [it["embedding"] for it in sorted(d["data"], key=lambda x: x.get("index", 0))]


def _rerank(query: str, docs: list) -> list:
    """Retourne les indices de docs reclasses (meilleur d'abord)."""
    d = _post(RR_PORT, "/v1/rerank", {"query": query, "documents": docs})
    res = d.get("results", d.get("data", []))
    res = sorted(res, key=lambda x: -x.get("relevance_score", x.get("score", 0)))
    return [r["index"] for r in res]


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


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    for p, name in [(EMB_PORT, "embed"), (RR_PORT, "reranker")]:
        if not _health(p):
            raise SystemExit(f"[rerank] llama-server {name} :{p} down")

    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    ids = [c["id"] for c in sample]
    idpos = {cid: i for i, cid in enumerate(ids)}
    text = {c["id"]: c["text"] for c in sample}

    def _file_of(s: str) -> str:
        """Source -> fichier (strip suffixes #chunkN et _partN)."""
        s = (s or "").split("#")[0]
        i = s.rfind("_part")
        if i > 0 and s[i + 5 :].isdigit():
            s = s[:i]
        return s

    file_ids = {}
    for c in sample:
        file_ids.setdefault(_file_of(c.get("source", "")), []).append(c["id"])

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
    print(f"[rerank] corpus {len(cids)} chunks", flush=True)

    queries = []
    for _l in (BENCH / "queries.jsonl").open(encoding="utf-8"):
        _l = _l.strip()
        if not _l:
            continue
        try:
            queries.append(json.loads(_l))
        except json.JSONDecodeError:
            continue
    # qrels reconstruit depuis le mapping deterministe qid 'q{i:04d}' -> picked[i]
    # (replique forge_bench_questions ; robuste a un question-gen interrompu).
    gchunks = [c for c in sample if 250 <= len(c["text"]) <= 4000]
    gstep = max(1, len(gchunks) // 120)
    picked = gchunks[::gstep][:120]
    qrels = {}
    for q in queries:
        try:
            idx = int(q["_id"].lstrip("q"))
        except ValueError:
            continue
        if idx < len(picked):
            # multi-gold : tous les chunks du meme fichier source = pertinents
            fkey = _file_of(picked[idx].get("source", ""))
            qrels[q["_id"]] = file_ids.get(fkey, [picked[idx]["id"]])
    valid = [q for q in queries if q["_id"] in qrels and any(c in cpos for c in qrels[q["_id"]])]
    qmat = _norm(
        [
            v
            for i in range(0, len(valid), 32)
            for v in _embed([q["text"] for q in valid[i : i + 32]])
        ]
    )
    print(f"[rerank] {len(valid)} requetes — retrieval + rerank...", flush=True)

    dense_r, rr_r = [], []
    for qi, q in enumerate(valid):
        gold = {cpos[c] for c in qrels[q["_id"]] if c in cpos}
        order = np.argsort(-(qmat[qi] @ cmat.T))
        d_rank = next((r for r, idx0 in enumerate(order, 1) if int(idx0) in gold), 999)
        dense_r.append(d_rank)
        cand = [int(x) for x in order[:TOPN]]
        new = _rerank(q["text"], [text[cids[c]][:DOC_CHARS] for c in cand])
        reranked = [cand[i] for i in new]
        rr_r.append(next((r for r, c in enumerate(reranked, 1) if c in gold), d_rank))
        if (qi + 1) % 40 == 0:
            print(f"[rerank] {qi + 1}/{len(valid)}", flush=True)

    print(f"\n=== Dense vs Dense+Reranker ({len(valid)} requetes, corpus {len(cids)}) ===")
    print(f"  dense          {_metrics(dense_r)}")
    print(f"  dense+rerank   {_metrics(rr_r)}")
    (BENCH / "rerank_results.json").write_text(
        json.dumps(
            {
                "dense": _metrics(dense_r),
                "rerank": _metrics(rr_r),
                "n": len(valid),
                "corpus": len(cids),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
