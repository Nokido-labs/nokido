"""forge_bench_segment.py — Metriques BEIR segmentees par type de gold.

Investigation non-destructive : re-joue le retrieval BEIR et separe les
metriques selon que le chunk gold de chaque requete est du gitingest externe
ou du vrai contenu Nokido. Si Nokido >> gitingest -> la mediocrite globale
vient de la pollution du corpus, pas du retrieval. Aucune ecriture DB.

Run : run action=trusted_script path=tools/forge_bench_segment.py
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
PORT = 8099
DIM = 1024
KS = [1, 5, 10]


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


def _seg(source: str) -> str:
    return "gitingest" if (source or "").lower().startswith("gitingest") else "laforge"


def main() -> None:
    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    src = {c["id"]: c["source"] for c in sample}
    ids = [c["id"] for c in sample]
    idpos = {cid: i for i, cid in enumerate(ids)}

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
    sims = qmat @ cmat.T

    seg = {"gitingest": [], "laforge": []}
    for qi, q in enumerate(valid):
        goldid = next(c for c in qrels[q["_id"]] if c in cpos)
        gold = cpos[goldid]
        order = np.argsort(-sims[qi])
        rank = int(np.where(order == gold)[0][0]) + 1
        seg[_seg(src.get(goldid, ""))].append(rank)

    print(f"=== BEIR segmente par type de gold ({len(valid)} requetes) ===\n")
    for name, ranks in seg.items():
        if not ranks:
            continue
        r = np.array(ranks)
        n = len(r)
        line = f"  {name:<11} n={n:<4}"
        for k in KS:
            line += f" R@{k}={(r <= k).mean():.3f}"
        mrr = np.mean([1.0 / x if x <= 10 else 0.0 for x in r])
        ndcg = np.mean([1.0 / math.log2(x + 1) if x <= 10 else 0.0 for x in r])
        line += f" MRR@10={mrr:.3f} NDCG@10={ndcg:.3f}"
        print(line)


if __name__ == "__main__":
    main()
