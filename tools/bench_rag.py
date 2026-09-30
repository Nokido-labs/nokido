"""tools/bench_rag.py - A/B benchmark RAG (CPU+IO mixed, goulot critique UX).

Per Gemini Web 2026-05-29 plan ordonné #1 (priorité absolue) :
- 100 requêtes pré-définies forcant FAISS + AST scan
- Mesure p50/p95/p99 latence (pas la moyenne -- variance noyée)
- Snapshot JSON dans sandbox/perf_history/ pour diff cross-env
- Aucune dépendance externe (stdlib + numpy/faiss déjà OK)

Usage:
    LAFORGE_PYTHON tools/bench_rag.py
    LAFORGE_PYTHON tools/bench_rag.py --runs 200 --queries 30
    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe tools/bench_rag.py --label py314_gil

Comparaison cross-env:
    LAFORGE_PYTHON tools/bench_rag.py --label py312_base
    schtasks /Change /TN LaForge-Master /TR ...PY314...  # bascule supervisor
    schtasks /Run /TN LaForge-Master
    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe tools/bench_rag.py --label py314_gil
    # Diff via tools/bench_rag_compare.py (not written yet)
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PERF_HIST = ROOT / "sandbox" / "perf_history"

# Query set forçant à la fois recherche sémantique (FAISS) + AST scan + BM25.
# Mix domaines = pas de cache hit accidentel.
BENCHMARK_QUERIES = [
    "How does Nokido handle Python free-threading on 3.14t ?",
    "AST scan of forge_rag_engine for chunk_lock",
    "BGE-M3 ONNX embedding 1024D pipeline",
    "RAG hybrid retrieval BM25 + dense fusion RRF",
    "Semantic firewall pre_flight DLP redact pattern",
    "Sovereign Membrane HMAC alias persistence per mission",
    "MCP hub :8766 routing tool calls authentication",
    "LATS Language Agent Tree Search UCB1 exploration",
    "AMI LeCun JEPA target network EMA update",
    "DPAPI machine vault secret rotation policy",
    "Live bridge mmap json_set RLock 3.14t safety",
    "forge_endocrine bounded queue thread safe",
    "ProcessPool to ThreadPool migration pattern",
    "ONNX session run thread-safe concurrent calls",
    "Active inference free energy minimization",
    "Liquid Neural Network CfC continuous time",
    "Cerebras gpt-oss-120b 50k tokens free tier",
    "FAISS IndexFlatIP cosine similarity batch",
    "veille agent SearXNG OpenAlex arxiv cascade",
    "Quality gate AST pylint coverage TODO scan",
]


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _bench_query(search_fn, query: str, runs_per_query: int) -> dict:
    """Time `runs_per_query` invocations of search_fn(query). Return latencies (ms)."""
    latencies = []
    last_n_results = 0
    last_tier = ""
    for _ in range(runs_per_query):
        t0 = time.perf_counter()
        try:
            r = search_fn(query)
            last_n_results = len(r.get("results", []))
            last_tier = r.get("tier", "?")
        except Exception as e:
            return {"query": query, "error": str(e)[:200], "latencies_ms": latencies}
        latencies.append((time.perf_counter() - t0) * 1000)
    return {
        "query": query,
        "latencies_ms": latencies,
        "n_results": last_n_results,
        "tier": last_tier,
    }


def _runtime_meta() -> dict:
    from nokido_agent.app.forge_python_runtime import IS_FREE_THREADED, current_env_alias

    return {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "executable": sys.executable,
        "env_alias": current_env_alias(),
        "free_threaded": IS_FREE_THREADED,
        "platform": sys.platform,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5, help="Runs per query (default 5)")
    ap.add_argument("--queries", type=int, default=20, help="Number of queries (default 20, max=len(BENCHMARK_QUERIES))")
    ap.add_argument("--label", default="auto", help="Snapshot label (default=current_env_alias)")
    ap.add_argument("--no-save", action="store_true", help="Print results without saving snapshot")
    args = ap.parse_args()

    queries = BENCHMARK_QUERIES[: args.queries]
    print(f"[bench_rag] {sys.version.split()[0]} ({sys.executable})")
    print(f"[bench_rag] queries={len(queries)} runs_per_query={args.runs}")

    # Use preflight_check_verbose (sync, 3-tier fallback: RAGEngine -> FTS5 -> LIKE).
    # This is the real entry point used everywhere in Nokido.
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        def search_fn(q: str) -> dict:
            return preflight_check_verbose(q, "", limit=10)

        warmup = search_fn(queries[0])
        warmup_tier = warmup.get("tier", "?")
    except Exception as e:
        print(f"[bench_rag] FAIL: cannot init preflight_check: {e}", file=sys.stderr)
        return 1

    print(f"[bench_rag] preflight ready: warmup_tier={warmup_tier} warmup_results={len(warmup.get('results', []))}")

    per_query_results = []
    all_latencies: list[float] = []
    t_total = time.perf_counter()

    for i, q in enumerate(queries, 1):
        print(f"  [{i:>3d}/{len(queries)}] {q[:60]:<60}", end=" ", flush=True)
        r = _bench_query(search_fn, q, args.runs)
        if "error" in r:
            print(f"FAIL {r['error'][:60]}")
        else:
            lat = r["latencies_ms"]
            print(f"p50={_percentile(lat,50):>7.1f}ms p95={_percentile(lat,95):>7.1f}ms tier={r['tier']} n={r['n_results']}")
            all_latencies.extend(lat)
        per_query_results.append(r)

    total_s = time.perf_counter() - t_total

    snapshot = {
        "runtime": _runtime_meta(),
        "label": args.label if args.label != "auto" else _runtime_meta()["env_alias"],
        "config": {"runs_per_query": args.runs, "queries_count": len(queries)},
        "rag_state": {
            "warmup_tier": warmup_tier,
        },
        "summary": {
            "total_runs": len(all_latencies),
            "total_duration_s": round(total_s, 2),
            "p50_ms": round(_percentile(all_latencies, 50), 2),
            "p95_ms": round(_percentile(all_latencies, 95), 2),
            "p99_ms": round(_percentile(all_latencies, 99), 2),
            "mean_ms": round(statistics.mean(all_latencies), 2) if all_latencies else 0,
            "stdev_ms": round(statistics.stdev(all_latencies), 2) if len(all_latencies) > 1 else 0,
        },
        "per_query": per_query_results,
    }

    print()
    print(f"== bench_rag SUMMARY ==")
    print(f"  total: {snapshot['summary']['total_runs']} runs in {snapshot['summary']['total_duration_s']}s")
    print(f"  p50  : {snapshot['summary']['p50_ms']:>8.1f} ms")
    print(f"  p95  : {snapshot['summary']['p95_ms']:>8.1f} ms")
    print(f"  p99  : {snapshot['summary']['p99_ms']:>8.1f} ms")
    print(f"  mean : {snapshot['summary']['mean_ms']:>8.1f} ms (stdev {snapshot['summary']['stdev_ms']:.1f})")

    if not args.no_save:
        PERF_HIST.mkdir(parents=True, exist_ok=True)
        out = PERF_HIST / f"bench_rag_{snapshot['label']}_{snapshot['runtime']['ts'][:19].replace(':', '')}.json"
        out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"  saved: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
