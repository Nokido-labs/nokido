"""forge_bench_diagnose.py — Diagnostic cohérence des embeddings du corpus RAG.

Investigation qualite retrieval. Pour N chunks de l'echantillon, re-embedde le
texte via :8099 (bge-m3 CLS) et compare (cosine) a l'embedding STOCKE en base.
Corpus sain -> self-cosine ~0.99. Valeurs basses = embeddings incoherents
(pooling/modele different) => cause directe d'un retrieval faible.
Split par rowid vs checkpoint rebuild (5072335) pour isoler un trou.

Run : run action=trusted_script path=tools/forge_bench_diagnose.py
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
CKPT = 5072335
N = 250


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


def _cos(a, b) -> float:
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def main() -> None:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3)
    except Exception:
        raise SystemExit("[diag] llama-server :8099 down")

    sample = [json.loads(l) for l in (BENCH / "sample.jsonl").open(encoding="utf-8")]
    step = max(1, len(sample) // N)
    picked = sample[::step][:N]

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    stored = {}
    for c in picked:
        r = con.execute("SELECT rowid, embedding FROM rag_chunks WHERE id=?", (c["id"],)).fetchone()
        if r:
            stored[c["id"]] = (r[0], _decode(r[1]))
    con.close()

    todo = [(c["id"], c["text"][:2000]) for c in picked if c["id"] in stored and stored[c["id"]][1]]
    fresh = {}
    for i in range(0, len(todo), 32):
        batch = todo[i : i + 32]
        for (cid, _), v in zip(batch, _embed([t for _, t in batch])):
            fresh[cid] = v
        print(f"[diag] re-embed {min(i + 32, len(todo))}/{len(todo)}", flush=True)

    cos_all, below, above = [], [], []
    for cid, (rowid, vec) in stored.items():
        if cid not in fresh or not vec:
            continue
        c = _cos(vec, fresh[cid])
        cos_all.append(c)
        (below if rowid <= CKPT else above).append(c)

    arr = np.array(cos_all)
    print(f"\n[diag] {len(arr)} chunks — self-cosine (stocke vs re-embed bge-m3 CLS)")
    print(f"  mean={arr.mean():.4f}  median={np.median(arr):.4f}  min={arr.min():.4f}")
    for lo, hi, lbl in [
        (0.99, 1.01, ">=0.99 sain"),
        (0.95, 0.99, "0.95-0.99"),
        (0.90, 0.95, "0.90-0.95"),
        (0.50, 0.90, "0.50-0.90 SUSPECT"),
        (-1.0, 0.50, "<0.50 CASSE"),
    ]:
        print(f"  {lbl:<20} {int(((arr >= lo) & (arr < hi)).sum())}")
    if below:
        print(f"  rowid<=ckpt ({len(below):>3}) mean={np.mean(below):.4f}")
    if above:
        print(f"  rowid> ckpt ({len(above):>3}) mean={np.mean(above):.4f}")


if __name__ == "__main__":
    main()
