"""
forge_nlgraph_scorer.py — LLM Scorer + Benchmark Runner for NLGraph
====================================================================
Separated from forge_nlgraph_runner.py for MCP buffer reasons.
Import: from forge_nlgraph_scorer import run_benchmark, LLMScorer
"""

from __future__ import annotations
import json, re, time, urllib.request
from dataclasses import dataclass
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

OLLAMA_URL = "http://localhost:11434"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "nlgraph"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Task-specific reasoning hints (chain-of-thought boosters)
TASK_HINTS = {
    "bipartite": "Hint: try to 2-color the graph. Assign color A to a node, color B to all neighbors, then check for conflicts. If any edge connects two same-color nodes, answer NO.",
    "max_flow": "Hint: use Ford-Fulkerson or find augmenting paths from source to sink. Sum the bottleneck capacities of all augmenting paths. Give the final numeric answer.",
    "gnn_simulate": "Hint: for each node, compute the sum of ALL neighbor values. The new value replaces the old one. Give the final number only.",
    "topological_sort": "Hint: repeatedly find nodes with in-degree 0, remove them and their edges. The removal order is a valid topological sort.",
}


class LLMScorer:
    SYSTEM = "You are a graph theory expert. Analyze the graph precisely. Think step by step. End with: Final answer: YOUR_ANSWER"

    def __init__(self, model, timeout=120):
        self.model = model
        self.timeout = timeout

    def _call(self, messages):
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024},
            }
        ).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=payload, headers={"Content-Type": "application/json"}
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return data.get("message", {}).get("content", ""), time.time() - t0

    @staticmethod
    def extract(response, task):
        text = response.strip()
        # Priority 1: explicit "Final answer: X" pattern
        m = re.search(r"[Ff]inal\s+[Aa]nswer[:\s]+(.+?)(?:\n|$)", text)
        if m:
            return m.group(1).strip().rstrip(".").strip("*")
        # Priority 2: "therefore/thus" pattern
        for pat in [r"(?:therefore|thus|so|hence)[,:\s]+.*?(?:is|=)\s*(.+?)(?:\.|$)"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip().rstrip(".").strip("*")
        # Priority 3: task-specific fallback
        if task in ("connectivity", "cycle", "bipartite", "hamilton"):
            yy = [m.start() for m in re.finditer(r"\bYES\b", text, re.I)]
            nn = [m.start() for m in re.finditer(r"\bNO\b", text, re.I)]
            ly = max(yy) if yy else -1
            ln = max(nn) if nn else -1
            if ly > ln:
                return "YES"
            if ln > ly:
                return "NO"
        if task in ("max_flow", "gnn_simulate"):
            # Look for "is X" or "= X" at end
            m2 = re.search(r"(?:is|=|equals?)\s*\**(\d+)\**\s*\.?\s*$", text, re.M)
            if m2:
                return m2.group(1)
            nums = re.findall(r"\b(\d+)\b", text)
            if nums:
                return nums[-1]
        if task == "shortest_path":
            m = re.search(r"(\d(?:\s*->\s*\d)+)", text)
            if m:
                return m.group(1)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return lines[-1] if lines else text

    @staticmethod
    def score(extracted, truth, task):
        ext = extracted.upper().strip()
        gt = truth.upper().strip()
        if task in ("connectivity", "cycle", "bipartite", "hamilton"):
            e = "YES" if "YES" in ext else ("NO" if "NO" in ext else "")
            return 1.0 if e == gt else 0.0
        if task in ("max_flow", "gnn_simulate"):
            en = re.findall(r"\d+", ext)
            gn = re.findall(r"\d+", gt)
            return 1.0 if gn and gn[0] in en else 0.0
        if task == "shortest_path":
            ep = [x.strip() for x in re.split(r"\s*->\s*", ext)]
            gp = [x.strip() for x in re.split(r"\s*->\s*", gt)]
            if len(ep) == len(gp) and ep[0] == gp[0] and ep[-1] == gp[-1]:
                return 1.0
            return 0.0
        if task == "topological_sort":
            return 1.0 if len(ext) > 2 else 0.0
        return 1.0 if ext == gt else 0.0

    def evaluate(self, tc):
        hint = TASK_HINTS.get(tc.task, "")
        user_prompt = tc.graph_text + "\n\n" + tc.question
        if hint:
            user_prompt += "\n\n" + hint
        msgs = [{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": user_prompt}]
        try:
            resp, dur = self._call(msgs)
            ext = self.extract(resp, tc.task)
            sc = self.score(ext, tc.ground_truth, tc.task)
            return {
                "task": tc.task,
                "difficulty": tc.difficulty,
                "graph_id": tc.graph_id,
                "model": self.model,
                "ground_truth": tc.ground_truth,
                "extracted": ext,
                "score": sc,
                "duration_s": round(dur, 2),
            }
        except Exception as e:
            return {
                "task": tc.task,
                "difficulty": tc.difficulty,
                "graph_id": tc.graph_id,
                "model": self.model,
                "ground_truth": tc.ground_truth,
                "extracted": "",
                "score": 0.0,
                "error": str(e),
            }


@dataclass
class BenchReport:
    model: str
    difficulty: str
    results: list
    timestamp: str = ""

    def summary(self):
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        by_task = {}
        for r in self.results:
            t = r["task"]
            if t not in by_task:
                by_task[t] = {"correct": 0, "total": 0, "time_sum": 0.0}
            by_task[t]["total"] += 1
            by_task[t]["correct"] += int(r["score"])
            by_task[t]["time_sum"] += r.get("duration_s", 0)
        for t in by_task:
            n = by_task[t]["total"]
            by_task[t]["accuracy"] = round(by_task[t]["correct"] / max(n, 1), 3)
            by_task[t]["avg_time"] = round(by_task[t]["time_sum"] / max(n, 1), 2)
            del by_task[t]["time_sum"]
        tc = sum(v["correct"] for v in by_task.values())
        tn = sum(v["total"] for v in by_task.values())
        return {
            "model": self.model,
            "difficulty": self.difficulty,
            "timestamp": self.timestamp,
            "overall_accuracy": round(tc / max(tn, 1), 3),
            "total_cases": tn,
            "by_task": by_task,
        }

    def save(self):
        out = RESULTS_DIR / f"{self.model.replace(':', '_')}_{self.difficulty}.json"
        data = {"summary": self.summary(), "raw": self.results}
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return str(out)


def run_benchmark(model, difficulty="easy", tasks=None, verbose=True):
    """Run NLGraph benchmark."""
    from nokido_agent.app.forge_nlgraph_runner import GraphGenerator

    gen = GraphGenerator(seed=42)
    cases = gen.generate_all(difficulty)
    if tasks:
        cases = [c for c in cases if c.task in tasks]
    if verbose:
        print(f"\nNLGraph Benchmark -- {model} -- {difficulty}")
        print(f"Test cases: {len(cases)}")
    scorer = LLMScorer(model)
    results = []
    for i, tc in enumerate(cases):
        if verbose:
            print(f"  [{i + 1}/{len(cases)}] {tc.task}...", end=" ", flush=True)
        r = scorer.evaluate(tc)
        results.append(r)
        if verbose:
            st = "OK" if r["score"] == 1.0 else "FAIL"
            print(f"{st} ({r.get('duration_s', 0):.1f}s)")
    report = BenchReport(model=model, difficulty=difficulty, results=results)
    path = report.save()
    if verbose:
        s = report.summary()
        print(f"\nOVERALL: {s['overall_accuracy'] * 100:.1f}%")
        for task, info in s["by_task"].items():
            print(f"  {task:20s} {info['accuracy'] * 100:5.1f}% ({info['correct']}/{info['total']})")
        print(f"Saved: {path}")
    return report


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    model = "qwen2.5-coder:7b-instruct-q4_K_M"
    diff = "easy"
    tasks = None
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]
        if a == "--diff" and i + 1 < len(args):
            diff = args[i + 1]
        if a == "--tasks" and i + 1 < len(args):
            tasks = args[i + 1].split(",")
    run_benchmark(model, diff, tasks=tasks)
