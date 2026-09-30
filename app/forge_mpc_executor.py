"""
Phase C — MPC real execute_fn.
Maps action_dict (from forge_mpc) → actual hub tool call → (state_text, cost, success).
Wires forge_mpc.run_mpc_loop() to real hub actions.
"""

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).parent.parent
_HUB = "http://127.0.0.1:8766"
_TOKEN = ""  # reads from env if needed

try:
    import os

    _TOKEN = get_secret("FORGE_MCP_TOKEN") or ""
except Exception:
    pass


# ---------------------------------------------------------------------------
# Hub call helper
# ---------------------------------------------------------------------------


def _hub_call(tool: str, args: dict, timeout: int = 30) -> str:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    req = urllib.request.Request(f"{_HUB}/mcp", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            content = data.get("result", {}).get("content", [])
            return content[0].get("text", "") if content else str(data)
    except Exception as e:
        return f"ERR:{e}"


# ---------------------------------------------------------------------------
# Action parser — maps action description → hub tool + args
# ---------------------------------------------------------------------------

_KEYWORD_MAP = [
    # (regex, tool, args_builder) — order matters: more specific first
    (r"\b(check|monitor|health|status|worker|hub)\b", "hub", lambda d: {"action": "worker_status"}),
    (
        r"\b(task|assign|schedule|queue)\b",
        "task",
        lambda d: {"action": "assign", "description": d[:200], "agent": "agt_qwen"},
    ),
    (r"\b(search|query|find|retrieve|lookup|rag)\b", "rag", lambda d: {"action": "search", "query": d[:200]}),
    (r"\b(ingest|index|crawl|embed)\b", "rag", lambda d: {"action": "ingest", "text": d[:300], "source": "mpc_action"}),
    (r"\b(run|execute|shell|command|bash)\b", "run", lambda d: {"action": "shell", "code": f"echo '[mpc] {d[:100]}'"}),
]


def _parse_action(description: str) -> tuple[str, dict]:
    desc_low = description.lower()
    for pattern, tool, builder in _KEYWORD_MAP:
        if re.search(pattern, desc_low):
            return tool, builder(description)
    # fallback: ask the hub LLM
    return "ask", {"provider": "ollama", "message": description[:300], "max_tokens": 200}


# ---------------------------------------------------------------------------
# execute_fn — the real MPC executor
# ---------------------------------------------------------------------------


def execute_fn(action: dict) -> tuple[str, float, bool]:
    """
    Execute a plan action via hub.
    Returns: (new_state_text, actual_cost, success)
    Compatible with forge_mpc.run_mpc_loop(execute_fn=execute_fn).
    """
    from nokido_agent.app.forge_state_encoder import encode_state, get_current_state_text
    from nokido_agent.app.forge_cost_module import total_cost

    description = action.get("description", "")
    tool, args = _parse_action(description)

    t0 = time.time()
    result = _hub_call(tool, args, timeout=30)
    elapsed = time.time() - t0

    is_err = str(result).startswith("ERR")
    success = not is_err

    # State AFTER action
    try:
        new_state_text = get_current_state_text()
    except Exception:
        new_state_text = f"after:{description[:80]}|result:{str(result)[:100]}"

    # Cost needs a goal embedding — caller should inject goal, but we use default
    goal_text = "system stable, all tasks completed, hub healthy, no errors"
    new_state_emb = encode_state(new_state_text)
    goal_emb = encode_state(goal_text)
    actual_cost = total_cost(new_state_emb, goal_emb)

    return new_state_text, actual_cost, success


# ---------------------------------------------------------------------------
# High-level: run real MPC from hub state
# ---------------------------------------------------------------------------


def run_real_mpc(
    goal_text: str = "system stable, all tasks completed, hub healthy",
    max_steps: int = 5,
    horizon: int = 2,
    n_candidates: int = 3,
) -> dict:
    """
    Full closed-loop MPC with real hub execution.
    Returns summary dict.
    """
    from nokido_agent.app.forge_state_encoder import get_current_state_text
    from nokido_agent.app.forge_mpc import run_mpc_loop

    state_text = get_current_state_text()
    result = run_mpc_loop(
        goal_text=goal_text,
        state_text=state_text,
        max_steps=max_steps,
        horizon=horizon,
        n_candidates=n_candidates,
        execute_fn=execute_fn,
    )

    return {
        "success": result.success,
        "n_steps": len(result.steps),
        "n_replans": result.n_replans,
        "avg_predicted_cost": result.total_predicted_cost,
        "avg_actual_cost": result.total_actual_cost,
        "steps": [
            {
                "action": s.action["description"][:60],
                "predicted": round(s.predicted_cost, 4),
                "actual": round(s.actual_cost, 4) if s.actual_cost else None,
                "surprise": s.surprise,
            }
            for s in result.steps
        ],
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[mpc_executor] parsing test\n")
    tests = [
        "check hub health and monitor worker status",
        "search RAG for recent errors",
        "run task to clear queue",
        "execute shell to list logs",
        "ingest latest traces into knowledge base",
        "analyze system stability and optimize resources",
    ]
    for t in tests:
        tool, args = _parse_action(t)
        print(f"  [{tool:6s}] {t[:55]}")
        print(f"           args={json.dumps(args)[:80]}")
