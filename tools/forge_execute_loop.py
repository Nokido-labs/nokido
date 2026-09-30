"""
tools/forge_execute_loop.py — Autonomous execute loop.
Token economy: RAG search + file reads + Ollama → synthesis without Claude round-trips.
Gain: -50% Claude tokens on multi-file exploration tasks.

Usage:
    python tools/forge_execute_loop.py "Comment fonctionne forge_semantic_firewall?"
    python tools/forge_execute_loop.py --task "..." --max-steps 10 --out result.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(it, **kw):  # type: ignore
        return it


HUB = "http://localhost:8766"
TOKEN = os.getenv("FORGE_MCP_TOKEN", "")
ROOT = Path(__file__).parent.parent


# ── Hub calls ─────────────────────────────────────────────────────────────────


def _hub(tool: str, args: dict, timeout: int = 30) -> Any:
    body = json.dumps(
        {
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{HUB}/mcp", data=body, headers=headers, method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        result = resp.get("result", resp.get("error", ""))
        if isinstance(result, list):
            return result[0].get("text", "") if result else ""
        return str(result)
    except urllib.error.URLError as e:
        return f"[HUB_ERROR] {e}"


def rag_search(query: str, top_k: int = 5) -> str:
    return _hub("rag", {"query": query, "top_k": top_k})


def read_file(path: str) -> str:
    return _hub("read", {"path": path})


def ask_ollama(prompt: str, model: str = "laforge-qwen") -> str:
    return _hub("ask", {"prompt": prompt, "provider": "ollama", "model": model}, timeout=120)


def run_python(code: str) -> str:
    return _hub("run", {"action": "python", "code": code}, timeout=60)


# ── ReAct step ────────────────────────────────────────────────────────────────

SYSTEM = """Tu es un assistant technique expert sur Nokido. Réponds en JSON strict:
{
  "thought": "raisonnement interne",
  "action": "rag_search|read_file|run_python|finish",
  "action_input": "argument pour l'action (string)",
  "confidence": 0.0-1.0
}
- rag_search: cherche dans la base RAG (query = mots-clés)
- read_file: lit un fichier (path relatif à LaForge/)
- run_python: exécute du code Python simple (< 10 lignes)
- finish: répond à la question (action_input = réponse finale markdown)
Ne répète pas des actions déjà faites. Confidence >= 0.8 pour finish."""


def react_step(task: str, history: list[dict]) -> dict:
    ctx_parts = [f"Tâche: {task}\n"]
    for i, h in enumerate(history[-6:]):
        ctx_parts.append(f"Étape {i + 1}: {h['action']}({h.get('input', '')[:80]})")
        if h.get("obs"):
            ctx_parts.append(f"  → {str(h['obs'])[:200]}")
    ctx_parts.append("\nQuelle est la prochaine action?")
    prompt = SYSTEM + "\n\n" + "\n".join(ctx_parts)

    raw = ask_ollama(prompt)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        return {"thought": raw[:100], "action": "finish", "action_input": raw, "confidence": 0.5}


# ── Execute loop ──────────────────────────────────────────────────────────────


def execute_loop(task: str, max_steps: int = 15) -> str:
    """
    ReAct loop: think → act → observe until finish or max_steps.
    Returns the final answer string.
    """
    history: list[dict] = []
    final_answer = ""

    steps = range(max_steps)
    try:
        steps = tqdm(steps, desc="execute_loop", unit="step")
    except Exception:
        pass

    for step_n in steps:
        step = react_step(task, history)
        action = step.get("action", "finish")
        action_input = step.get("action_input", "")
        confidence = step.get("confidence", 0.0)

        obs = ""
        if action == "rag_search":
            obs = rag_search(action_input)
        elif action == "read_file":
            path = str(ROOT / action_input.lstrip("/").lstrip("\\"))
            obs = read_file(path)[:3000]
        elif action == "run_python":
            obs = run_python(action_input)
        elif action == "finish":
            final_answer = action_input
            history.append({"action": action, "input": action_input[:80], "obs": ""})
            break
        else:
            obs = f"[UNKNOWN_ACTION] {action}"

        history.append(
            {
                "action": action,
                "input": action_input[:80],
                "obs": str(obs)[:400],
                "confidence": confidence,
            }
        )

        if confidence >= 0.8 and action == "finish":
            break

        time.sleep(0.1)

    if not final_answer:
        # Synthesize from observations
        all_obs = "\n".join(h.get("obs", "") for h in history if h.get("obs"))
        final_answer = ask_ollama(
            f"Synthétise en markdown: Tâche={task!r}\nDonnées collectées:\n{all_obs[:4000]}"
        )

    return final_answer


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Nokido autonomous execute loop")
    parser.add_argument("task", nargs="?", help="Task to execute")
    parser.add_argument("--task", dest="task_opt", help="Task (alternative)")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--out", help="Output file (markdown)")
    parser.add_argument("--model", default="laforge-qwen")
    args = parser.parse_args()

    task = args.task or args.task_opt
    if not task:
        parser.error("Specify a task: forge_execute_loop.py 'Question?'")

    print(f"[execute_loop] Task: {task}")
    print(f"[execute_loop] Max steps: {args.max_steps} | Model: {args.model}")
    print()

    t0 = time.time()
    answer = execute_loop(task, max_steps=args.max_steps)
    elapsed = time.time() - t0

    print(f"\n{'─' * 60}")
    print(answer)
    print(f"{'─' * 60}")
    print(f"\n[execute_loop] Done in {elapsed:.1f}s")

    if args.out:
        Path(args.out).write_text(
            f"# Execute Loop Result\n\n**Task:** {task}\n\n{answer}\n", encoding="utf-8"
        )
        print(f"[execute_loop] Saved → {args.out}")


if __name__ == "__main__":
    main()
