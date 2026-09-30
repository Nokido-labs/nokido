"""forge_bench_beir.py — Benchmark retrieval BEIR-style sur l'echantillon Nokido.

Etape 3 du benchmark (preuve BEIR). Corpus = sample.jsonl (embeddings bge-m3
relus depuis embeddings.db), queries/qrels = forge_bench_questions. Retrieval
dense (cosine), metriques IR standard : NDCG@10, Recall@{1,5,10,100}, MAP, MRR@10.

Embedding des requetes via le llama-server bge-m3 (:8099) -- exactement le meme
embedder (Q8 GGUF, pooling CLS) que celui ayant produit les embeddings du corpus.

Run : run action=trusted_script path=tools/forge_bench_beir.py  (si server :8099 up)
      sinon sous user (demarrage llama-server depuis llama-vulkan).
"""

import json
import math
import sqlite3
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
DB = ROOT / "RAG" / "embeddings.db"
PORT = 8099
SERVER = __import__("os").path.expanduser(r"~\llama-vulkan\llama-server.exe")
GGUF = str(ROOT / "data" / "llm_models" / "bge-m3-Q8_0.gguf")
DIM = 1024
KS = [1, 5, 10, 100]


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server() -> bool:
    """Demande au superviseur (:8765) de demarrer le service NokidoLlamaEmbed.
    Fallback Popen direct (ne marche que si le compte accede a llama-vulkan)."""
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8765/supervisor/restart/NokidoLlamaEmbed", data=b"", timeout=10
        )
        print("[beir] superviseur sollicite (NokidoLlamaEmbed)", flush=True)
    except Exception:
        try:
            subprocess.Popen(
                [
                    SERVER,
                    "-m",
                    GGUF,
                    "--embedding",
                    "--pooling",
                    "cls",
                    "-ngl",
                    "99",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PORT),
                    "-c",
                    "8192",
                    "-b",
                    "2048",
                    "--ubatch-size",
                    "2048",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[beir] fallback Popen direct llama-server", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[beir] demarrage impossible: {e}", flush=True)
            return False
    for _ in range(90):
        time.sleep(2)
        if _server_up():
            return True
    return False


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


def _decode(blob) -> list:
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
    for f in ("sample.jsonl", "queries.jsonl", "qrels.json"):
        if not (BENCH / f).exists():
            raise SystemExit(f"[beir] {f} absent")

    # 1. corpus + embeddings depuis la DB
    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
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
            if v is not None and cid in idpos:
                emb[idpos[cid]] = v
    con.close()
    keep = [i for i, v in enumerate(emb) if v is not None]
    corpus_ids = [ids[i] for i in keep]
    corpus_pos = {cid: i for i, cid in enumerate(corpus_ids)}
    corpus_mat = _norm([emb[i] for i in keep])
    print(f"[beir] corpus : {len(corpus_ids)}/{len(ids)} chunks embeddes", flush=True)

    # 2. queries + qrels
    queries = []
    for _l in (BENCH / "queries.jsonl").open(encoding="utf-8"):
        _l = _l.strip()
        if not _l:
            continue
        try:
            queries.append(json.loads(_l))
        except json.JSONDecodeError:
            continue
    # qrels reconstruit (mapping deterministe qid 'q{i:04d}' -> picked[i])
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
            qrels[q["_id"]] = {picked[idx]["id"]: 1}
    valid = [
        q for q in queries if q["_id"] in qrels and any(c in corpus_pos for c in qrels[q["_id"]])
    ]
    print(f"[beir] requetes exploitables : {len(valid)}/{len(queries)}", flush=True)
    if not valid:
        raise SystemExit("[beir] aucune requete exploitable")

    # 3. embedding des requetes (meme bge-m3 que le corpus)
    if not _server_up():
        print("[beir] llama-server :8099 down -> demarrage...", flush=True)
        if not _start_server():
            raise SystemExit("[beir] llama-server injoignable -- relancer sous user")
    qvecs = []
    for i in range(0, len(valid), 32):
        qvecs.extend(_embed([q["text"] for q in valid[i : i + 32]]))
        print(f"[beir] requetes embeddees {min(i + 32, len(valid))}/{len(valid)}", flush=True)
    qmat = _norm(qvecs)

    # 4. retrieval dense + metriques
    sims = qmat @ corpus_mat.T
    agg = {f"recall@{k}": 0.0 for k in KS}
    agg.update({"ndcg@10": 0.0, "map": 0.0, "mrr@10": 0.0})
    for qi, q in enumerate(valid):
        gold = [corpus_pos[c] for c in qrels[q["_id"]] if c in corpus_pos]
        order = np.argsort(-sims[qi])[: max(KS)]
        rank = {int(idx): r for r, idx in enumerate(order, start=1)}
        best = min((rank.get(g, 10**9) for g in gold), default=10**9)
        for k in KS:
            if best <= k:
                agg[f"recall@{k}"] += 1.0
        if best <= 10:
            agg["ndcg@10"] += 1.0 / math.log2(best + 1)
            agg["mrr@10"] += 1.0 / best
        if best < 10**9:
            agg["map"] += 1.0 / best

    n = len(valid)
    res = {k: round(v / n, 4) for k, v in agg.items()}
    res["n_queries"] = n
    res["n_corpus"] = len(corpus_ids)
    (BENCH / "beir_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print("[beir] === RESULTATS (dense bge-m3) ===")
    for k in (
        "recall@1",
        "recall@5",
        "recall@10",
        "recall@100",
        "mrr@10",
        "ndcg@10",
        "map",
        "n_queries",
        "n_corpus",
    ):
        print(f"  {k:<12} {res[k]}")


if __name__ == "__main__":
    main()
