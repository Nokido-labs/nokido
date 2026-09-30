"""
forge_benchmark_runner.py — Golden Dataset benchmark runner.

Dispatches tasks via multi_llm_daemon swarm (task.assign),
polls agent_messages for results, scores pass/fail.

Metrics: pass_rate, avg_time_s, domain breakdown.
Output: RAG/benchmark_results/bench_{timestamp}.jsonl

Usage:
    python tools/forge_benchmark_runner.py [--agent groq] [--max 20] [--quick]
"""

import argparse
import json
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "RAG" / "golden_dataset.jsonl"
RESULTS = ROOT / "RAG" / "benchmark_results"
import sys
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402  # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
DB_PATH = Path(m2m_path())
HUB_URL = "http://127.0.0.1:8766"
RESULTS.mkdir(exist_ok=True)


# ── Hub helpers ──────────────────────────────────────────────────────────────


def _post_mcp(tool: str, arguments: dict, timeout: int = 30) -> dict:
    body = {"method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    req = urllib.request.Request(
        f"{HUB_URL}/mcp",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def dispatch_task(task: dict, agent: str = "groq") -> str:
    """Send task.assign to swarm via hub, return frame_id."""
    resp = _post_mcp(
        "task",
        {
            "action": "assign",
            "task_id": task["id"],
            "agent": agent,
            "intent": task.get("domain", "benchmark"),
            "description": task["description"],
        },
    )
    content = resp.get("result", {}).get("content", [{}])
    text = content[0].get("text", "{}") if content else "{}"
    try:
        return json.loads(text).get("frame_id", "")
    except Exception:
        return ""


def poll_result(frame_id: str, timeout_s: int = 60) -> str:
    """Poll agent_messages until task.result arrives for this frame_id."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            rows = conn.execute(
                "SELECT result FROM agent_messages "
                "WHERE correlation_id=? AND method='task.result' LIMIT 1",
                (frame_id,),
            ).fetchall()
            if rows and rows[0]["result"]:
                raw = rows[0]["result"]
                # task.assign results are JSON: {"job_id":..., "result":"[OK]..."}
                try:
                    d = json.loads(raw)
                    return d.get("result", raw)
                except Exception:
                    return raw
            time.sleep(2)
    finally:
        conn.close()
    return "[TIMEOUT]"


def score(result: str, task: dict) -> bool:
    if not result or result.startswith("[TIMEOUT]"):
        return False
    if "[ERR" in result and "[ERR hub_shell]" not in result:
        # [ERR hub_shell] means dispatch worked but command failed — still count as attempted
        pass
    expected = task.get("expected_contains", "")
    if expected:
        return expected.lower() in result.lower()
    return "[OK]" in result or not result.startswith("[ERR")


# ── Runner ───────────────────────────────────────────────────────────────────


def run(
    dataset: Path = DATASET,
    agent: str = "groq",
    max_tasks: int | None = None,
    dispatch_delay: float = 1.5,
) -> dict:
    tasks = []
    for line in dataset.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    if max_tasks:
        tasks = tasks[:max_tasks]

    print(f"[bench] {len(tasks)} tasks | agent={agent}")
    results = []
    t_total = time.time()

    for i, task in enumerate(tasks):
        print(f"  [{i + 1}/{len(tasks)}] {task['id']} ({task['domain']}) ...", flush=True)
        t0 = time.time()
        frame_id = dispatch_task(task, agent)
        if not frame_id:
            results.append(
                {
                    "id": task["id"],
                    "domain": task["domain"],
                    "pass": False,
                    "elapsed_s": 0,
                    "result": "[ERR dispatch]",
                }
            )
            continue

        result = poll_result(frame_id, timeout_s=task.get("timeout_s", 60))
        elapsed = round(time.time() - t0, 2)
        passed = score(result, task)
        status = "PASS" if passed else "FAIL"
        print(f"     {status} {elapsed}s | {result[:100]}")
        results.append(
            {
                "id": task["id"],
                "domain": task["domain"],
                "pass": passed,
                "elapsed_s": elapsed,
                "result": result[:500],
            }
        )
        time.sleep(dispatch_delay)

    elapsed_total = round(time.time() - t_total, 1)

    # ── Score ─────────────────────────────────────────────────────────────────
    passed_n = sum(1 for r in results if r["pass"])
    pass_rate = round(passed_n / len(results) * 100, 1) if results else 0.0
    avg_time = round(sum(r["elapsed_s"] for r in results) / len(results), 2) if results else 0

    by_domain: dict = {}
    for r in results:
        d = r["domain"]
        by_domain.setdefault(d, {"pass": 0, "total": 0})
        by_domain[d]["total"] += 1
        if r["pass"]:
            by_domain[d]["pass"] += 1

    summary = {
        "ts": datetime.now().isoformat(),
        "agent": agent,
        "n_tasks": len(results),
        "passed": passed_n,
        "pass_rate": pass_rate,
        "avg_time_s": avg_time,
        "total_s": elapsed_total,
        "by_domain": by_domain,
        "results": results,
    }

    # ── Save ──────────────────────────────────────────────────────────────────
    ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS / f"bench_{ts_slug}.jsonl"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 50}")
    print(f"PASS RATE : {pass_rate}%  ({passed_n}/{len(results)})")
    print(f"AVG TIME  : {avg_time}s | TOTAL: {elapsed_total}s")
    for dom, s in by_domain.items():
        pct = round(s["pass"] / s["total"] * 100)
        print(f"  {dom:12s}: {s['pass']}/{s['total']} ({pct}%)")
    print(f"Saved -> {out}")

    # ── Anchor ────────────────────────────────────────────────────────────────
    try:
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"Golden Dataset benchmark run — {len(results)} tasks",
            solution=f"pass_rate={pass_rate}% agent={agent} avg={avg_time}s",
            example=f"python tools/forge_benchmark_runner.py --agent {agent}",
            domain="systeme",
        )
    except Exception:
        pass

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent", default="groq", help="LLM agent for dispatch (groq|mistral|ollama...)"
    )
    parser.add_argument(
        "--max", type=int, default=None, dest="max_tasks", help="Max tasks to run (default: all)"
    )
    parser.add_argument("--quick", action="store_true", help="Run first 5 tasks only (smoke test)")
    args = parser.parse_args()

    if args.quick:
        args.max_tasks = 5

    run(agent=args.agent, max_tasks=args.max_tasks)
