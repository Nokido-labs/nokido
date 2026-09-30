# bench_llamacpp_vs_ollama.py — Compare latence/qualite llama.cpp vs Ollama
# Usage: python tools/bench_llamacpp_vs_ollama.py
# Prerequis: Ollama doit etre demarre, llama-cli accessible
import json
import os
import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from nokido_agent.app.forge_llamacpp_scorer import LlamaCppScorer
from nokido_agent.app.forge_nlgraph_runner import GraphGenerator
from nokido_agent.app.forge_nlgraph_scorer import LLMScorer

TASKS = ["connectivity", "bipartite", "hamilton"]
CASES_PER_TASK = 3
OUT = os.path.join(
    os.path.dirname(__file__), "..", "benchmarks", "nlgraph", "llamacpp_vs_ollama.json"
)


def main():
    gen = GraphGenerator(seed=42)
    all_cases = gen.generate_all("easy")

    ollama = LLMScorer("qwen2.5-coder:7b-instruct-q4_K_M", timeout=120)
    llamacpp = LlamaCppScorer()

    results = {"ollama": {}, "llamacpp": {}}

    for task in TASKS:
        cases = [c for c in all_cases if c.task == task][:CASES_PER_TASK]
        for backend_name, scorer in [("ollama", ollama), ("llamacpp", llamacpp)]:
            ok, total_time = 0, 0.0
            for tc in cases:
                r = scorer.evaluate(tc)
                ok += int(r.get("score", 0))
                total_time += r.get("duration_s", 0)
                st = "OK" if r.get("score") else "FAIL"
                print(f"  [{backend_name:8s}] {task}: {st} ({r.get('duration_s', 0):.1f}s)")

            results[backend_name][task] = {
                "correct": ok,
                "total": len(cases),
                "total_time": round(total_time, 1),
                "avg_time": round(total_time / max(len(cases), 1), 1),
            }
        print()

    # Summary
    print("=" * 60)
    print(f"{'Task':20s} {'Ollama':>12s} {'llama.cpp':>12s} {'Speedup':>10s}")
    print("-" * 60)
    for task in TASKS:
        o = results["ollama"][task]
        l = results["llamacpp"][task]
        speedup = o["avg_time"] / max(l["avg_time"], 0.1)
        print(
            f"{task:20s} {o['correct']}/{o['total']} ({o['avg_time']:.0f}s)  {l['correct']}/{l['total']} ({l['avg_time']:.0f}s)  {speedup:.1f}x"
        )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
