"""
tools/forge_orchestrate_loop.py — Autonomous agentic loop via GOAP
Uses forge_goap.GoalPlanner + execute_plan + hub dispatch.
"""

import asyncio
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

SYNTH_PROMPT = """/no_think Synthetise les resultats suivants pour le goal: {goal}
Steps: {steps_summary}
Reponds en 3-5 phrases, points cles uniquement."""


def _hub(tool: str, **args) -> str:
    r = requests.post(
        HUB,
        headers=HEADERS,
        json={"method": "tools/call", "params": {"name": tool, "arguments": args}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("result", {}).get("content", [{}])[0].get("text", "")


async def _hub_async(tool: str, **args) -> str:
    """Version async de _hub — libère l'event loop (évite deadlock hub→hub)."""
    return await asyncio.to_thread(_hub, tool, **args)


def _ask(prompt: str, provider: str = "ollama", max_tokens: int = 600) -> str:
    raw = _hub("ask", provider=provider, message=prompt, max_tokens=max_tokens)
    try:
        d = json.loads(raw)
        return d.get("text", raw) if isinstance(d, dict) else raw
    except Exception:
        return raw


async def _hub_dispatch(intent: dict) -> dict:
    """Dispatch un intent JSON-RPC vers le hub MCP."""
    method = intent.get("method", "")
    params = intent.get("params", {})

    if method in ("run_python", "llm_call"):
        code = params.get("code") or params.get("prompt", "")
        raw = await _hub_async("run", action="python", code=code)
        try:
            res = json.loads(raw)
            r = res[0] if isinstance(res, list) else res
            return {
                "ok": r.get("ok", True),
                "stdout": r.get("stdout", ""),
                "stderr": r.get("stderr", ""),
            }
        except Exception:
            return {"ok": True, "stdout": raw}

    elif method == "run_shell":
        cmd = params.get("command", "")
        raw = await _hub_async("run", action="shell", commands=[cmd])
        try:
            res = json.loads(raw)
            r = res[0] if isinstance(res, list) else res
            return {
                "ok": r.get("ok", True),
                "stdout": r.get("stdout", ""),
                "stderr": r.get("stderr", ""),
            }
        except Exception:
            return {"ok": True, "stdout": raw}

    elif method in ("rag_search", "embed"):
        query = params.get("query", params.get("text", ""))
        raw = await _hub_async("rag", action="search", topic=query, limit=params.get("limit", 5))
        return {"ok": True, "results": raw}

    elif method in ("rag_ingest", "ingest"):
        raw = await _hub_async(
            "rag",
            action="index",
            task_id=params.get("task_id", ""),
            result=params.get("text", params.get("content", params.get("result", ""))),
            topic=params.get("topic", params.get("query", "")),
        )
        return {"ok": True, "result": raw}

    elif method == "read_file":
        path = params.get("path", "")
        raw = await _hub_async("read", path=path, limit=params.get("limit", 200))
        return {"ok": True, "content": raw}

    elif method == "web_search":
        raw = await _hub_async("web_search", query=params.get("query", ""))
        return {"ok": True, "result": raw}

    elif method == "crawl":
        raw = await _hub_async("crawl", url=params.get("url", ""))
        return {"ok": True, "result": raw}

    elif method == "get_file_skeleton":
        raw = await _hub_async("get_file_skeleton", file_path=params.get("file_path", ""))
        return {"ok": True, "result": raw}

    elif method == "read_function_body":
        raw = await _hub_async("read_function_body", file_path=params.get("file_path", ""),
                               function_name=params.get("function_name", ""))
        return {"ok": True, "result": raw}

    elif method == "get_function_dependencies":
        raw = await _hub_async("get_function_dependencies",
                               function_name=params.get("function_name", ""),
                               file_path=params.get("file_path", ""))
        return {"ok": True, "result": raw}

    elif method == "blackboard_read_zone":
        raw = await _hub_async("blackboard_read_zone", zone_name=params.get("zone_name", ""))
        return {"ok": True, "result": raw}

    elif method == "blackboard_propose_fact":
        raw = await _hub_async("blackboard_propose_fact",
                               zone_name=params.get("zone_name", ""),
                               fact=params.get("fact", ""),
                               category=params.get("category", ""),
                               trust=params.get("trust", 0.5))
        return {"ok": True, "result": raw}

    else:
        return {"ok": False, "error": f"unsupported method: {method}"}


async def _fast_path(goal: str, rag_ctx: str, t0: float) -> dict:
    """Fallback sans GOAP — RAG context direct, pas de synthesis Ollama (trop lent)."""
    return {
        "goal": goal,
        "mode": "fast_path",
        "rag_context": rag_ctx[:1200] if rag_ctx else "",
        "synthesis": "GOAP planning timeout — RAG context retourné directement.",
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def _deterministic_synthesis(goal: str, steps) -> str:
    """Synthèse DÉTERMINISTE (plans template) : formate les sorties tool brutes.
    Zéro LLM -> pas d'hallucination, pas de latence Ollama. steps = trajectory.steps."""
    import json as _j

    lines = ["Analyse (plan déterministe, sans LLM) :"]
    for st in steps:
        intent = st.intent if isinstance(st.intent, dict) else {}
        method = intent.get("method", "?")
        res = st.result
        if method == "get_function_dependencies":
            d = res if isinstance(res, dict) else None
            if d is None:
                try:
                    d = _j.loads(res)
                except Exception:
                    d = None
            if isinstance(d, dict):
                callers = d.get("callers", []) or []
                cl = "; ".join(
                    f"{c.get('caller')} ({c.get('file')}:{c.get('line')} {c.get('via')})"
                    for c in callers
                ) or "aucun"
                lines.append(f"• `{d.get('function')}` dans {d.get('file')}")
                lines.append(f"  callers ({len(callers)}) : {cl}")
                lines.append(f"  callees : {', '.join(d.get('callees', []) or []) or 'aucun'}")
                continue
        if method == "read_function_body":
            first = str(res).split('\n', 1)[0] if res else "(vide)"
            lines.append(f"• corps [{st.status}] : {first}")
            continue
        if method == "get_file_skeleton":
            first = str(res).split('\n', 1)[0] if res else "(vide)"
            lines.append(f"• squelette [{st.status}] : {first}")
            continue
        lines.append(f"• {method} [{st.status}] : {str(res)[:160]}")
    return "\n".join(lines)


def _run_loop_durable(goal: str, run_id: str, max_steps: int = 20) -> dict:
    """Orchestrate DURABLE event-sourced (replay-on-restart via forge_durable_workflow).
    SYNC (à lancer dans un thread) : chaque étape = une activity memoizée. Au re-run
    du même run_id (après restart hub), les étapes complétées sont REJOUÉES depuis le
    store (zéro double effet de bord), reprise à la 1re incomplète. Pont async→sync :
    asyncio.run() des morceaux async dans le thread (aucune boucle courante)."""
    import asyncio as _aio
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parent))                      # tools/
    _s.path.insert(0, str(_P(__file__).resolve().parent.parent / "app"))       # app/
    from nokido_agent.tools.forge_durable_workflow import durable_run
    from nokido_agent.app.forge_goap import GoalPlanner

    def _plan():
        plan = _aio.run(GoalPlanner.plan(goal, context={}, ring_max=2))
        return {"plan_id": getattr(plan, "plan_id", "?"),
                "actions": [a for sg in plan.subgoals for a in sg.actions]}

    def _wf(ctx):
        plan = ctx.activity("plan", _plan)
        steps = []
        for i, action in enumerate(plan["actions"][:max_steps]):
            res = ctx.activity(f"step_{i}", (lambda a=action: _aio.run(_hub_dispatch(a))))
            steps.append({"intent": action.get("method"), "status": "completed", "result": res})
        return {"goal": goal, "plan_id": plan["plan_id"], "steps": steps, "durable": True}

    return durable_run(run_id, _wf)


def durable_run_status(run_id: str) -> dict | None:
    """Lit l'état d'un run durable depuis le WorkflowStore (survit au restart)."""
    try:
        import sys as _s
        from pathlib import Path as _P

        _s.path.insert(0, str(_P(__file__).resolve().parent))
        from nokido_agent.tools.forge_durable_workflow import WorkflowStore

        st = WorkflowStore()
        row = st.conn.execute(
            "SELECT status, result_json FROM workflow_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return None
        import json as _j

        return {"status": row[0], "result": _j.loads(row[1]) if row[1] else None}
    except Exception:
        return None


async def _run_loop_async(goal: str, ring_max: int = 2, max_steps: int = 20) -> dict:
    t0 = time.time()

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from nokido_agent.app.forge_goap import GoalPlanner, execute_plan

    # 1. RAG preflight (async pour ne pas bloquer event loop)
    ctx_raw = await _hub_async("rag", action="search", topic=goal, limit=5)
    context = {"rag": ctx_raw[:800]} if ctx_raw else {}

    # 2. GOAP plan. Budget covers one planning call + one retry
    #    (~40-50s each with num_predict=420); fast_path is the fallback.
    try:
        plan = await asyncio.wait_for(
            # 180s (>120s) : laisse le 1er plan ABOUTIR sur APU (sinon fast_path
            # systématique -> tools jamais exécutés). L'appel MCP synchrone peut
            # timeout côté client mais le hub finit + peuple le cache de plans
            # -> les runs suivants (cache hit) sont instantanés. Boucle autonome OK.
            GoalPlanner.plan(goal, context=context, ring_max=ring_max),
            timeout=180.0,
        )
    except TimeoutError:
        return await _fast_path(goal, ctx_raw or "", t0)

    if plan.error or not plan.subgoals:
        return {
            "goal": goal,
            "error": plan.error or "no subgoals",
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    # 3. Execute (with step cap)
    if max_steps and plan.action_count() > max_steps:
        # Trim subgoals to stay under cap
        kept, total = [], 0
        for sg in plan.subgoals:
            if total >= max_steps:
                break
            cut = plan.subgoals[0].__class__(name=sg.name, actions=sg.actions[: max_steps - total])
            kept.append(cut)
            total += len(cut.actions)
        plan.subgoals = kept

    trajectory = await execute_plan(plan, dispatch_fn=_hub_dispatch)

    steps_done = []
    for step in trajectory.steps:
        out = step.result
        # step.result peut être un DICT (run/rag -> {stdout/result}) OU un STR
        # (get_file_skeleton/get_function_dependencies retournent une string via
        # _hub_dispatch {"ok":True,"result":<str>} -> _execute_subgoal extrait le str).
        if isinstance(out, dict):
            output = str(out.get("stdout") or out.get("result") or out)
        else:
            output = str(out) if out is not None else ""
        intent = step.intent if isinstance(step.intent, dict) else {}
        steps_done.append(
            {
                "intent": intent.get("method", "?"),
                "status": step.status,
                "output": output[:200],
            }
        )

    # 4. Synthesis
    if getattr(plan, "plan_id", "") == "tmpl":
        # Plan template -> synthèse DÉTERMINISTE (formate les sorties tool, zéro LLM :
        # ni hallucination ni latence Ollama ~30s).
        synthesis = _deterministic_synthesis(goal, trajectory.steps)
    else:
        steps_summary = "\n".join(
            f"- {s['intent']}: {s['status']} — {s['output'][:80]}" for s in steps_done
        )
        synthesis = await asyncio.to_thread(
            _ask, SYNTH_PROMPT.format(goal=goal, steps_summary=steps_summary), "ollama", 300
        )

    return {
        "goal": goal,
        "plan_id": plan.plan_id,
        "subgoals": len(plan.subgoals),
        "actions_total": plan.action_count(),
        "steps_done": len(steps_done),
        "steps": steps_done,
        "synthesis": synthesis,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def run_loop(goal: str, ring_max: int = 2, max_steps: int = 20) -> dict:
    return asyncio.run(_run_loop_async(goal, ring_max=ring_max, max_steps=max_steps))


if __name__ == "__main__":
    goal = (
        " ".join(sys.argv[1:])
        or "analyser la structure de app/forge_goap.py et lister ses classes publiques"
    )
    print(f"[orchestrate] goal: {goal}")
    result = run_loop(goal)
    print(json.dumps(result, indent=2, ensure_ascii=False))
