"""forge_bench_misses.py — Analyse des echecs de retrieval BEIR.

Pour chaque requete, calcule le rang du chunk gold. Pour les misses (gold hors
top-10), verifie si le chunk rank-1 vient de la MEME source que le gold
(= quasi-doublon -> qrels single-gold trop strict, pas un vrai echec) et dump
les pires misses pour inspection.

Run : run action=trusted_script path=tools/forge_bench_misses.py
"""

import json
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


def main() -> None:
    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    meta = {c["id"]: c for c in sample}
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
    qvecs = []
    for i in range(0, len(valid), 32):
        qvecs.extend(_embed([q["text"] for q in valid[i : i + 32]]))
    qmat = _norm(qvecs)
    sims = qmat @ cmat.T

    misses = []
    same_src = same_dom = 0
    for qi, q in enumerate(valid):
        gold = [cpos[c] for c in qrels[q["_id"]] if c in cpos][0]
        order = np.argsort(-sims[qi])
        rank = int(np.where(order == gold)[0][0]) + 1
        if rank > 10:
            r1 = cids[order[0]]
            gsrc, gdom = meta[cids[gold]]["source"], meta[cids[gold]]["domain"]
            if meta[r1]["source"] == gsrc:
                same_src += 1
            if meta[r1]["domain"] == gdom:
                same_dom += 1
            misses.append(
                {
                    "q": q["text"],
                    "rank": rank,
                    "gold": {"src": gsrc, "dom": gdom, "txt": meta[cids[gold]]["text"][:200]},
                    "top3": [
                        {
                            "src": meta[cids[order[k]]]["source"],
                            "dom": meta[cids[order[k]]]["domain"],
                            "score": round(float(sims[qi][order[k]]), 3),
                            "txt": meta[cids[order[k]]]["text"][:200],
                        }
                        for k in range(3)
                    ],
                }
            )

    nm = len(misses)
    print(f"[misses] {nm}/{len(valid)} requetes ratent le top-10")
    if nm:
        print(
            f"  rank-1 = MEME source que le gold : {same_src}/{nm} "
            f"({100 * same_src // nm}%) -- quasi-doublon, miss artificiel"
        )
        print(f"  rank-1 = meme domaine            : {same_dom}/{nm} ({100 * same_dom // nm}%)")
    (BENCH / "misses.json").write_text(
        json.dumps(misses, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print("\n=== 8 misses (apercu) ===")
    for m in misses[:8]:
        print(f"\nQ (rang gold {m['rank']}) : {m['q'][:160]}")
        print(f"  GOLD [{m['gold']['dom']}] {m['gold']['src'][:62]}")
        print(f"       {m['gold']['txt'][:150]!r}")
        for k, t in enumerate(m["top3"]):
            print(f"  top{k + 1} [{t['dom']}] {t['src'][:55]} s={t['score']}")
            print(f"       {t['txt'][:150]!r}")


if __name__ == "__main__":
    main()
