"""tools/bench_chain.py - A/B benchmark chain_executor pipeline pur (mock LLM).

Per Gemini Web 2026-05-29 plan ordonné #2 :
- Mock la réponse réseau LLM = isole UNIQUEMENT le pipeline Python
- Valide présence outils dans payload AVANT chrono (garde-fou conformité prod)
- Mesure parsing JSON + callbacks + post-process latence pure
- Snapshot JSON vers sandbox/perf_history/

Variance humaine et réseau = noyée. Mesure pure CPU pipeline.

Usage:
    LAFORGE_PYTHON tools/bench_chain.py
    LAFORGE_PYTHON tools/bench_chain.py --runs 500 --label py312_base
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


# ── Mock LLM response (realistic shape, no network) ───────────────────────────
MOCK_LLM_RESPONSE = {
    "id": "chatcmpl-mock-bench-001",
    "object": "chat.completion",
    "created": 1735000000,
    "model": "mock-bench",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": (
                    "Analyzing the Nokido architecture, I found 3 relevant chunks "
                    "matching your query. The semantic firewall pre_flight gates "
                    "all cloud LLM calls through DLP redaction + injection detection. "
                    "Sovereign Membrane wraps payloads with HMAC alias persistence."
                ) * 4,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "rag_search",
                            "arguments": '{"query": "semantic firewall", "limit": 10}',
                        },
                    },
                    {
                        "id": "call_002",
                        "type": "function",
                        "function": {
                            "name": "ast_scan",
                            "arguments": '{"path": "app/forge_semantic_firewall.py"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 1024, "completion_tokens": 256, "total_tokens": 1280},
}

# ── Mock tools definitions (realistic OpenAI/Anthropic shape) ─────────────────
MOCK_TOOLS_PAYLOAD = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the RAG index for semantically similar chunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "domain": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ast_scan",
            "description": "Parse a Python file via ast module and return symbol map.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "include_docstrings": {"type": "boolean", "default": False},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_run",
            "description": "Execute a shell command in the project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_s": {"type": "integer", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
]


def _validate_payload_tools(payload: dict) -> bool:
    """Per Gemini Web 2026-05-29 : valide présence + intégrité des tools AVANT send.

    Sans le GIL en 3.14t, un thread concurrent peut altérer la liste tools entre
    construction et send -> payload tronqué -> LLM hallucine.

    Snapshot immuable + check structure complète.
    """
    tools = payload.get("tools")
    if not tools or not isinstance(tools, list):
        return False
    for t in tools:
        if not isinstance(t, dict):
            return False
        if t.get("type") != "function":
            return False
        fn = t.get("function")
        if not isinstance(fn, dict):
            return False
        if not fn.get("name") or not fn.get("parameters"):
            return False
    return True


def _build_payload(query: str, tools: list, context: list) -> dict:
    """Construit un payload API LLM réaliste."""
    return {
        "model": "mock-bench",
        "messages": [
            {"role": "system", "content": "You are Nokido AI."},
            *context,
            {"role": "user", "content": query},
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 1024,
    }


def _parse_response(raw: dict) -> dict:
    """Pipeline parsing typique du chain_executor."""
    parsed = {
        "content": "",
        "tool_calls": [],
        "usage": raw.get("usage", {}),
    }
    for choice in raw.get("choices", []):
        msg = choice.get("message", {})
        parsed["content"] = msg.get("content", "")
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            parsed["tool_calls"].append(
                {"id": tc.get("id"), "name": fn.get("name"), "args": args}
            )
    return parsed


def _bench_cycle() -> tuple[float, float, float]:
    """Une cycle complet : build_payload + validate + serialize + parse_response.

    Returns:
        (build_ms, validate_ms, parse_ms) latences par phase.
    """
    # Phase 1 : build payload (construction dict + tools assembly)
    t0 = time.perf_counter()
    payload = _build_payload(
        query="Analyze the semantic firewall pipeline",
        tools=MOCK_TOOLS_PAYLOAD,
        context=[
            {"role": "user", "content": "Previous q"},
            {"role": "assistant", "content": "Previous a"},
        ],
    )
    t_build = (time.perf_counter() - t0) * 1000

    # Phase 2 : validate (garde-fou Gemini, OBLIGATOIRE 3.14t)
    t0 = time.perf_counter()
    if not _validate_payload_tools(payload):
        raise RuntimeError("payload validation failed -- aborting cycle")
    # Serialize = mimique json.dumps avant send réseau
    serialized = json.dumps(payload, ensure_ascii=False)
    _ = len(serialized)  # force eval
    t_validate = (time.perf_counter() - t0) * 1000

    # Phase 3 : parse response (mock = même structure que vrais LLM)
    t0 = time.perf_counter()
    parsed = _parse_response(MOCK_LLM_RESPONSE)
    assert parsed["tool_calls"], "parsed tool_calls should not be empty"
    t_parse = (time.perf_counter() - t0) * 1000

    return t_build, t_validate, t_parse


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


def _runtime_meta() -> dict:
    try:
        from nokido_agent.app.forge_python_runtime import IS_FREE_THREADED, current_env_alias

        env_alias = current_env_alias()
        free_threaded = IS_FREE_THREADED
    except Exception:
        env_alias = "unknown"
        free_threaded = False
    return {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "executable": sys.executable,
        "env_alias": env_alias,
        "free_threaded": free_threaded,
        "platform": sys.platform,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1000, help="Number of cycles (default 1000)")
    ap.add_argument("--label", default="auto")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    print(f"[bench_chain] {sys.version.split()[0]} ({sys.executable})")
    print(f"[bench_chain] runs={args.runs}")

    builds, validates, parses = [], [], []
    t_total = time.perf_counter()

    for i in range(args.runs):
        b, v, p = _bench_cycle()
        builds.append(b)
        validates.append(v)
        parses.append(p)
        if (i + 1) % max(1, args.runs // 10) == 0:
            print(f"  [{i + 1:>5d}/{args.runs}]", end=" ", flush=True)
    total_s = time.perf_counter() - t_total
    print()

    def _summary(samples: list[float]) -> dict:
        return {
            "p50_ms": round(_percentile(samples, 50), 4),
            "p95_ms": round(_percentile(samples, 95), 4),
            "p99_ms": round(_percentile(samples, 99), 4),
            "mean_ms": round(statistics.mean(samples), 4),
            "stdev_ms": round(statistics.stdev(samples), 4) if len(samples) > 1 else 0,
        }

    rt = _runtime_meta()
    snapshot = {
        "runtime": rt,
        "label": args.label if args.label != "auto" else rt["env_alias"],
        "config": {"runs": args.runs},
        "phases": {
            "build_payload": _summary(builds),
            "validate_serialize": _summary(validates),
            "parse_response": _summary(parses),
        },
        "total_duration_s": round(total_s, 2),
        "cycles_per_s": round(args.runs / total_s, 1) if total_s > 0 else 0,
    }

    print(f"== bench_chain SUMMARY ==")
    for phase, s in snapshot["phases"].items():
        print(f"  {phase:<20s} p50={s['p50_ms']:>6.3f}ms p95={s['p95_ms']:>6.3f}ms p99={s['p99_ms']:>6.3f}ms mean={s['mean_ms']:>6.3f}ms")
    print(f"  TOTAL: {args.runs} cycles in {total_s:.2f}s -> {snapshot['cycles_per_s']} cycles/s")

    if not args.no_save:
        PERF_HIST.mkdir(parents=True, exist_ok=True)
        out = PERF_HIST / f"bench_chain_{snapshot['label']}_{rt['ts'][:19].replace(':', '')}.json"
        out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"  saved: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
