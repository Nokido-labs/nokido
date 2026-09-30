#!/usr/bin/env python3
"""forge_qdrant_parity.py — Gate de parité vector-search (baseline faiss vs Qdrant).

Chantier SSoT RAG 2026. Rejoue les qvec EXACTS d'une baseline (capturée sur le
sidecar faiss :8097 — mêmes vecteurs query, zéro bruit de réembedding) contre
search_hybrid du sidecar Qdrant, et calcule overlap@10/@30 + latences.

GATE DE CUTOVER : mean_overlap10 >= 0.8 (mesuré 2026-07-06 : exact+INT8-rescore
= 1.00 à p50 61.5ms sur 544k points ; HNSW défauts = 0.66 -> rebuild index
m>=32 requis avant de quitter exact).

Usage :
  LAFORGE_PYTHON tools/forge_qdrant_parity.py
      [--baseline C:\\tmp\\rag_parity_baseline.json] [--out verdict.json]
      [--host 127.0.0.1] [--port 6333]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/rag : gate de parite vector-search faiss contre Qdrant"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qdrant_client import QdrantClient

from nokido_agent.tools.forge_qdrant_sidecar import search_hybrid


def run(baseline_path: str, out_path: str, host: str, port: int) -> dict:
    base = json.load(open(baseline_path, encoding="utf-8"))
    client = QdrantClient(host=host, port=port, timeout=60)

    verdict = {"ts": time.time(), "baseline": baseline_path, "per_query": {}}
    o10s, o30s, lats = [], [], []
    for qid, entry in base["results"].items():
        f10 = [r[0] for r in entry["top"][:10]]
        f30 = [r[0] for r in entry["top"][:30]]
        t0 = time.time()
        res = search_hybrid(client, query_dense=entry["qvec"], top_k=30)
        ms = int((time.time() - t0) * 1000)
        ids = [str(r["id"]) for r in res]
        o10 = len(set(f10) & set(ids[:10])) / max(1, len(f10))
        o30 = len(set(f30) & set(ids[:30])) / max(1, len(f30))
        o10s.append(o10)
        o30s.append(o30)
        lats.append(ms)
        verdict["per_query"][qid] = {"overlap10": o10, "overlap30": o30, "ms": ms}
        print(f"{qid} overlap@10={o10:.2f} @30={o30:.2f} {ms}ms", flush=True)

    verdict["summary"] = {
        "mean_overlap10": round(statistics.mean(o10s), 3),
        "mean_overlap30": round(statistics.mean(o30s), 3),
        "min_overlap10": min(o10s),
        "lat_p50_ms": statistics.median(lats),
        "lat_max_ms": max(lats),
        "gate_08": statistics.mean(o10s) >= 0.8,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=1)
    print("VERDICT:", json.dumps(verdict["summary"]), flush=True)
    return verdict


def main() -> int:
    p = argparse.ArgumentParser(description="Gate de parité faiss->Qdrant")
    p.add_argument("--baseline", default=r"C:\tmp\rag_parity_baseline.json")
    p.add_argument("--out", default=r"C:\tmp\rag_parity_verdict_native.json")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6333)
    a = p.parse_args()
    v = run(a.baseline, a.out, a.host, a.port)
    return 0 if v["summary"]["gate_08"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
