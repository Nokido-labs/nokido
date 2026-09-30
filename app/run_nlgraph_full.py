#!/usr/bin/env python3
# run_nlgraph_full.py — Benchmark NLGraph complet (execution autonome)
# Usage: python app/run_nlgraph_full.py
# Resultats: benchmarks/nlgraph/scoreboard_v5_hints.json
import sys, os, json, time, traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from nokido_agent.app.forge_nlgraph_runner import GraphGenerator
from nokido_agent.app.forge_nlgraph_scorer import LLMScorer, TASK_HINTS

MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"
DIFF = "easy"
OUT = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "nlgraph", "scoreboard_v5_hints.json")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    gen = GraphGenerator(seed=42)
    scorer = LLMScorer(MODEL, timeout=120)
    all_cases = gen.generate_all(DIFF)

    tasks = [
        "connectivity",
        "cycle",
        "shortest_path",
        "bipartite",
        "topological_sort",
        "max_flow",
        "gnn_simulate",
        "hamilton",
    ]

    results = {}
    for task in tasks:
        cases = [c for c in all_cases if c.task == task]
        ok, total, times = 0, 0, []
        print(f"\n--- {task} ({len(cases)} cases) ---")
        for tc in cases:
            try:
                r = scorer.evaluate(tc)
                total += 1
                s = int(r["score"])
                ok += s
                d = r.get("duration_s", 0)
                times.append(d)
                st = "OK" if s else "FAIL"
                print(f"  {st} ({d:.0f}s) truth={tc.ground_truth[:15]} got={r.get('extracted', '')[:15]}")
            except Exception as e:
                total += 1
                print(f"  ERR: {e}")

        results[task] = {
            "correct": ok,
            "total": total,
            "accuracy": round(ok / max(total, 1), 3),
            "avg_time": round(sum(times) / max(len(times), 1), 1),
        }
        print(f"  => {task}: {ok}/{total} ({ok / max(total, 1) * 100:.0f}%)")

        # Save intermediate results after each task
        _save(results)

    print(f"\n{'=' * 50}")
    print(f"FINAL — {MODEL} — {DIFF}")
    total_ok = sum(v["correct"] for v in results.values())
    total_n = sum(v["total"] for v in results.values())
    print(f"OVERALL: {total_ok}/{total_n} ({total_ok / max(total_n, 1) * 100:.1f}%)")
    for t in tasks:
        if t in results:
            r = results[t]
            print(f"  {t:20s} {r['correct']:2d}/{r['total']:2d} ({r['accuracy'] * 100:5.1f}%) avg={r['avg_time']:.0f}s")


def _save(results):
    data = {
        "model": MODEL,
        "difficulty": DIFF,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hints": list(TASK_HINTS.keys()),
        "by_task": results,
    }
    total_ok = sum(v["correct"] for v in results.values())
    total_n = sum(v["total"] for v in results.values())
    data["overall_accuracy"] = round(total_ok / max(total_n, 1), 3)
    data["total_cases"] = total_n
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
