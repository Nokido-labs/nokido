"""forge_qdrant_bench.py — banc qualite AVANT de basculer la recherche sur Qdrant.

Etape (3) du chantier Qdrant. La bascule de `_rag_dense_search` (CRITICAL_FILE) sur
Qdrant ne se decide PAS a l'aveugle : ce banc mesure si Qdrant HNSW (approx) recupere
les MEMES candidats denses que la matrice numpy exacte du hub, sur des requetes
representatives. Overlap top-k eleve -> bascule sure ; faible -> ne pas basculer.

Lecture seule (n'ecrit rien, ne touche pas le hub). Rejouable.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import db_path  # noqa: E402
from nokido_agent.tools.forge_faiss_sidecar import _decode_emb  # noqa: E402

COLLECTION = "nokido_sovereign_rag"
REQUETES = [
    "attestation contredite enveloppe SUCCESS contenu ERROR",
    "autorite par origine trust_weight doctrine docset",
    "eviction par capacite service critique embedder",
    "docker sawtooth wsl vhd verrou keeper",
    "npu vitisai vaiml crash instruction illegale",
    "sync continue outbox trigger qdrant",
]


def _embed(q: str) -> list[float]:
    body = json.dumps({"input": [q]}).encode()
    req = urllib.request.Request("http://127.0.0.1:8099/v1/embeddings", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["data"][0]["embedding"]


def _qdrant(qv: list[float], k: int) -> list[tuple[str, float]]:
    body = json.dumps({"vector": {"name": "dense", "vector": qv}, "limit": k,
                       "with_payload": True}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:6333/collections/{COLLECTION}/points/search",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        hits = json.loads(r.read())["result"]
    return [(h["payload"].get("chunk_id"), h["score"]) for h in hits]


def _exact_topk(conn: sqlite3.Connection, cand_ids: list[str], qv: np.ndarray, k: int) -> list[str]:
    """Reference EXACTE sur le meme jeu de candidats : cosine brute-force numpy.

    On ne recharge pas 546k vecteurs (2.2 Go) : on prend l'UNION des candidats Qdrant
    de toutes les requetes comme pool, et on classe exactement dedans. Si Qdrant est
    un bon ANN, son ordre approx doit coller a l'ordre exact sur ce pool.
    """
    if not cand_ids:
        return []
    qm = ",".join("?" * len(cand_ids))
    rows = conn.execute(
        f"SELECT id, embedding FROM rag_chunks WHERE id IN ({qm}) AND embedding IS NOT NULL",
        cand_ids).fetchall()
    scored = []
    qn = qv / (np.linalg.norm(qv) + 1e-9)
    for cid, blob in rows:
        v = _decode_emb(blob)
        if v is None:
            continue
        v = v / (np.linalg.norm(v) + 1e-9)
        scored.append((cid, float(np.dot(qn, v))))
    scored.sort(key=lambda x: -x[1])
    return [c for c, _ in scored[:k]]


def main() -> int:
    K = 10
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
    total_overlap = 0.0
    print(f"{'requete':46} {'qdrant/exact top-%d overlap' % K:>26}")
    print("-" * 76)
    for q in REQUETES:
        qv = _embed(q)
        t = time.time()
        qhits = _qdrant(qv, K)
        dt = (time.time() - t) * 1000
        qids = [c for c, _ in qhits]
        exact = _exact_topk(conn, qids, np.asarray(qv, dtype=np.float32), K)
        # overlap = combien du top-K exact est dans le top-K qdrant (sur le meme pool)
        inter = len(set(qids[:K]) & set(exact[:K]))
        denom = max(len(exact[:K]), 1)
        ov = inter / denom
        total_overlap += ov
        print(f"{q[:46]:46} {inter}/{denom} = {ov:.0%}   ({dt:.0f}ms)")
    conn.close()
    moy = total_overlap / len(REQUETES)
    print("-" * 76)
    print(f"overlap moyen : {moy:.0%}")
    print("VERDICT :", "bascule SURE (overlap >= 90%)" if moy >= 0.9 else
          "PRUDENCE : Qdrant approx s'ecarte de l'exact, ne pas basculer sans reglage HNSW")
    return 0


if __name__ == "__main__":
    sys.exit(main())
