"""
tools/forge_orchestrate_react.py — ReAct agentic loop for Nokido
Uses Ollama qwen3:8b with native function calling.
Structure ReAct : Thought -> Action -> Observation -> Final Answer.
"""

import json
import sys
import time
from pathlib import Path

import requests

HUB = "http://127.0.0.1:8766/mcp"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

TOKEN = get_secret("FORGE_MCP_TOKEN") or ""
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

REACT_SYSTEM_PROMPT = """Tu es l'agent ReAct de Nokido (Ollama qwen3:8b).
Résous la tâche étape par étape.
Processus :
1. Thought: Réfléchis à ce que tu dois faire.
2. Action: Appelle un outil si nécessaire.
3. Observation: Analyse le résultat.
4. Répète jusqu'à trouver la réponse.
5. Final Answer: Donne la réponse finale claire.

Utilise le function calling natif d'Ollama.
"""


def _hub(tool, **args):
    try:
        r = requests.post(
            HUB,
            headers=HEADERS,
            json={"method": "tools/call", "params": {"name": tool, "arguments": args}},
            timeout=60,
        )
        r.raise_for_status()
        res = r.json()
        if "error" in res:
            return f"ERR: {res['error']}"
        return res.get("result", {}).get("content", [{}])[0].get("text", "")
    except Exception as e:
        return f"ERR network: {e}"


def get_tools_schema(ring=2):
    try:
        r = requests.post(
            HUB,
            headers=HEADERS,
            json={"method": "tools/list", "params": {"ring": ring}},
            timeout=10,
        )
        tools = r.json().get("result", {}).get("tools", [])
        openai_tools = []
        for t in tools:
            if t["name"] in ("orchestrate", "react_orchestrate"):
                continue
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                }
            )
        return openai_tools
    except:
        return []


OLLAMA_CHAT = "http://127.0.0.1:11434/v1/chat/completions"
REACT_MODEL = "qwen3:8b"


def _ollama_chat(messages, tools):
    payload = {
        "model": REACT_MODEL,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    r = requests.post(OLLAMA_CHAT, json=payload, timeout=120)
    r.raise_for_status()
    choice = r.json()["choices"][0]["message"]
    return choice.get("content", ""), choice.get("tool_calls", [])


def run_react(task: str, ring: int = 2, max_steps: int = 10) -> dict:
    t0 = time.time()
    tools = get_tools_schema(ring)
    messages = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    trace = []

    for i in range(max_steps):
        content, tool_calls = _ollama_chat(messages, tools)

        msg = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)

        if not tool_calls:
            if "Final Answer:" in (content or "") or i >= max_steps - 1:
                break
            messages.append({"role": "user", "content": "Continue ou donne la Final Answer."})
            continue

        # Exécution des tool calls
        for tc in tool_calls:
            fn = tc.get("function", tc)
            t_name = fn["name"]
            t_args = (
                json.loads(fn["arguments"])
                if isinstance(fn.get("arguments"), str)
                else fn.get("arguments", {})
            )

            obs = _hub(t_name, **t_args)
            trace.append({"step": i, "tool": t_name, "args": t_args, "obs": obs[:200]})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{i}"),
                    "name": t_name,
                    "content": obs[:1000],
                }
            )

    return {
        "goal": task,
        "trace": trace,
        "result": messages[-1]["content"],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        res = run_react(" ".join(sys.argv[1:]))
        print(json.dumps(res, indent=2, ensure_ascii=False))
