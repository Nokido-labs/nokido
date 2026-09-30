"""forge_bench_engine.py — Bench du RAGEngine REEL (FAISS+BM25+RRF+rerank).

Instancie le vrai RAGEngine (chemin de production) et mesure le retrieval sur
les questions du benchmark, avec et sans rerank. Match par contenu (le gold
text doit apparaitre dans le content retourne). Compare au bench standalone.

Run : run action=trusted_script path=tools/forge_bench_engine.py
"""

import asyncio
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
BENCH = ROOT / "sandbox" / "rag_bench"
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


def _metrics(ranks: list) -> str:
    import numpy as np

    r = np.array(ranks)
    out = " ".join(f"R@{k}={(r <= k).mean():.3f}" for k in KS)
    mrr = np.mean([1.0 / x if x <= 10 else 0.0 for x in r])
    ndcg = np.mean([1.0 / math.log2(x + 1) if x <= 10 else 0.0 for x in r])
    return f"{out} MRR@10={mrr:.3f} NDCG@10={ndcg:.3f}"


def main() -> None:
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
        if idx < len(picked):
            gold[q["_id"]] = picked[idx]["text"]
    valid = [q for q in queries if q["_id"] in gold]
    print(f"[engine] {len(valid)} requetes", flush=True)

    # Bootstrap settings : get_settings() lit __main__.settings en priorite.
    import __main__ as _main

    try:
        from app.core.settings import create_settings as _cs

        _main.settings = _cs()
        print("[engine] settings bootstrap OK", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[engine] bootstrap ECHEC: {type(e).__name__}: {e}", flush=True)
        raise

    from nokido_agent.app.forge_rag_engine import RAGEngine

    eng = RAGEngine()
    print("[engine] RAGEngine instancie", flush=True)

    async def run(rerank: bool) -> list:
        ranks = []
        errs = 0
        for q in valid:
            gt = (gold[q["_id"]] or "").strip()[:150]
            try:
                docs = await eng.search(q["text"], k=20, rerank=rerank, compress=False)
            except TypeError:
                docs = await eng.search(q["text"], k=20, rerank=rerank)
            except Exception as e:  # noqa: BLE001
                errs += 1
                if errs <= 3:
                    print(f"[engine] search err: {type(e).__name__}: {str(e)[:120]}", flush=True)
                ranks.append(999)
                continue
            rank = 999
            for r, d in enumerate(docs, 1):
                if gt and gt in (d.get("content", "") or ""):
                    rank = r
                    break
            ranks.append(rank)
        return ranks

    no_rr = asyncio.run(run(False))
    print(f"[engine] sans rerank : {_metrics(no_rr)}", flush=True)
    rr = asyncio.run(run(True))
    print(f"[engine] avec rerank : {_metrics(rr)}", flush=True)

    print(f"\n=== RAGEngine reel ({len(valid)} requetes) ===")
    print(f"  sans rerank : {_metrics(no_rr)}")
    print(f"  avec rerank : {_metrics(rr)}")
    (BENCH / "engine_results.json").write_text(
        json.dumps(
            {"no_rerank": _metrics(no_rr), "rerank": _metrics(rr), "n": len(valid)}, indent=2
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
