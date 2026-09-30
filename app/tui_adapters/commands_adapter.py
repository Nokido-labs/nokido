"""commands_adapter — slash commands hérités v13.6, raccordés au code moderne.

Mapping v13.6 @cmd → moderne v3 /cmd :
  /run, /rag, /mem, /agentic, /evolve, /loop, /role, /model,
  /ollama, /audit, /apply, /code, /test, /sandbox, /nlu,
  /estim, /chain, /scan

Drop : @diag (Ctrl+H/S), @ids, @workflow, @ci, @switch,
       @services (Ctrl+S), @ragas, @proxy, @mode

Chaque handler : async fn(args: str) -> str  (lignes \\n séparées pour
affichage RichLog).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"
HUB_URL = "http://127.0.0.1:8766/mcp"
WEBHUB = "http://127.0.0.1:7400"
SUPERVISOR = "http://127.0.0.1:8765"


# ── Hub helper ────────────────────────────────────────────────────────────


def _hub_token() -> str:
    import os as _os

    tok = _os.environ.get("FORGE_MCP_TOKEN", "")
    if tok:
        return tok
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("FORGE_MCP_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def _hub_call(name: str, arguments: dict, timeout: float = 30.0) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    ).encode()
    headers = {"Content-Type": "application/json", "X-Agent-Name": "NAAROB_TUI"}
    tok = _hub_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(HUB_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data
    except Exception as e:
        return {"error": str(e)[:200]}


def _extract_text(resp: dict) -> str:
    try:
        content = resp.get("result", {}).get("content")
        if isinstance(content, list) and content:
            t = content[0].get("text", "")
            return str(t)[:1500]
        if isinstance(resp.get("result"), str):
            return resp["result"][:1500]
        if "error" in resp:
            return f"ERR: {resp['error']}"
        return json.dumps(resp)[:800]
    except Exception:
        return str(resp)[:400]


# ── Handlers ──────────────────────────────────────────────────────────────


async def cmd_run(args: str) -> str:
    """/run <cmd> — exécution shell via hub run + danger check."""
    if not args.strip():
        return "usage: /run <commande>"
    sudo = False
    cmd = args.strip()
    if cmd.startswith("-sudo "):
        sudo = True
        cmd = cmd[6:].strip()
    danger_keywords = ("rm -rf", "sudo rm", "dd if=", "mkfs", "shutdown", ":(){:|:&};:", "format c:", "del /s")
    for kw in danger_keywords:
        if kw in cmd.lower():
            return f"⚠ BLOQUÉ — pattern dangereux: '{kw}' (utilise /ssh-send si SSH live)"
    resp = _hub_call("run", {"action": "shell", "code": cmd, "timeout": 20})
    text = _extract_text(resp)
    prefix = f"$ {cmd}"
    if sudo:
        prefix = f"# {cmd}  (sudo)"
    return f"{prefix}\n{text}"


async def cmd_rag(args: str) -> str:
    """/rag <query> — recherche RAG via hub (timeout 60s — RAGEngine peut être lent)."""
    if not args.strip():
        return "usage: /rag <query>"
    resp = _hub_call("rag", {"action": "search", "topic": args.strip(), "limit": 8}, timeout=60)
    return _extract_text(resp)


async def cmd_mem(args: str) -> str:
    """/mem <query> — alias /rag (lessons + chunks)."""
    return await cmd_rag(args)


async def cmd_agentic(args: str) -> str:
    """/agentic <skill> — check_competence + library_lookup."""
    if not args.strip():
        return "usage: /agentic <skill>"
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_agentic_engine import AgenticEngine

        eng = AgenticEngine()
        lib = eng.library_lookup(args.strip())
        out = [f"library_lookup('{args.strip()}'):"]
        if lib:
            out.append(json.dumps(lib, indent=2, ensure_ascii=False)[:600])
        else:
            out.append("  (pas dans skill_library)")
        out.append("")
        out.append(f"entropy_level: {eng.entropy_level()}  color: {eng.entropy_color()}")
        summary = eng.get_skill_summary()[:8]
        out.append(f"top skills ({len(summary)}):")
        for s in summary:
            out.append(f"  {s['status']:10} {s['name']:20} score={s['score']:.2f} uses={s['uses']}")
        return "\n".join(out)
    except Exception as e:
        return f"ERR: {type(e).__name__}: {e}"


async def cmd_evolve(args: str) -> str:
    """/evolve [status] — état forge_self_patcher + auto_evolution_loop."""
    sandbox = ROOT / "sandbox"
    parts = []
    for name in ("self_patcher.heartbeat", "auto_evolution_loop.heartbeat"):
        p = sandbox / name
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                parts.append(f"{name}: {json.dumps(d, ensure_ascii=False)[:200]}")
            except Exception:
                parts.append(f"{name}: <unparseable>")
        else:
            parts.append(f"{name}: absent")
    applied_dir = sandbox / "patch_applied"
    if applied_dir.exists():
        n = len(list(applied_dir.glob("*.md")))
        parts.append(f"patches appliqués: {n}")
    proposals = list(sandbox.glob("evolution_proposal_*.md"))
    parts.append(f"propositions pending: {len(proposals)}")
    return "\n".join(parts)


async def cmd_loop(args: str) -> str:
    """/loop — alias /evolve."""
    return await cmd_evolve(args)


async def cmd_role(args: str) -> str:
    """/role [name] — switch ou liste rôles via hub `role` tool."""
    if not args.strip():
        resp = _hub_call("role", {"action": "list"})
    else:
        resp = _hub_call("role", {"action": "switch", "role": args.strip()})
    return _extract_text(resp)


async def cmd_model(args: str) -> str:
    """/model [name] — switch provider ollama / liste."""
    arg = args.strip()
    if not arg:
        # list models via ollama
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
                data = json.loads(r.read())
            names = [m["name"] for m in data.get("models", [])][:15]
            return "Ollama models:\n  " + "\n  ".join(names)
        except Exception as e:
            return f"ollama down: {e}"
    return f"(switch model={arg} — pousser via /role ou variable LAFORGE_MODEL)"


async def cmd_ollama(args: str) -> str:
    """/ollama [list|show <m>|ps] — relais ollama API."""
    parts = args.split() if args else ["list"]
    sub = parts[0].lower()
    try:
        if sub == "list":
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
                d = json.loads(r.read())
            lines = []
            for m in d.get("models", [])[:20]:
                size_gb = m.get("size", 0) / 1024 / 1024 / 1024
                lines.append(f"  {m['name']:35} {size_gb:.1f} GB")
            return "Ollama models:\n" + "\n".join(lines)
        if sub == "ps":
            with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as r:
                d = json.loads(r.read())
            return json.dumps(d, indent=2)[:800]
        if sub == "show" and len(parts) > 1:
            body = json.dumps({"name": parts[1]}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/show",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read())
            return json.dumps(d, indent=2)[:600]
        return "usage: /ollama [list|ps|show <model>]"
    except Exception as e:
        return f"ollama err: {e}"


async def cmd_audit(args: str) -> str:
    """/audit — ouvre :7400/reports navigateur."""
    try:
        webbrowser.open(f"{WEBHUB}/reports")
        return f"→ ouvert {WEBHUB}/reports"
    except Exception as e:
        return f"open fail: {e}"


async def cmd_apply(args: str) -> str:
    """/apply — état forge_self_patcher (alias /evolve)."""
    return await cmd_evolve(args)


async def cmd_code(args: str) -> str:
    """/code <spec> — lance software creator pipeline."""
    if not args.strip():
        return "usage: /code <spec module>\n  Lance test_software_creator_e2e via hub `run` action=python."
    spec_short = args.strip().replace('"', "")[:300]
    pycode = (
        "import sys; sys.path.insert(0, r'%s/app');"
        " from forge_spec_clarifier import detect_ambiguities, formalize_spec;"
        " amb = detect_ambiguities(%r);"
        " print('ambiguities:', amb)" % (str(ROOT), spec_short)
    )
    resp = _hub_call("run", {"action": "python", "code": pycode, "timeout": 30})
    return _extract_text(resp)


async def cmd_test(args: str) -> str:
    """/test [path] — lance pytest via hub (timeout 90s)."""
    target = args.strip() or "tests/"
    cmd = f"%USERPROFILE%/miniforge3/python.exe -m pytest {target} -x -q --no-header --tb=short"
    resp = _hub_call("run", {"action": "shell", "code": cmd, "timeout": 90}, timeout=120)
    return _extract_text(resp)


async def cmd_sandbox(args: str) -> str:
    """/sandbox <code python> — exec via hub action=python (timeout 60s)."""
    if not args.strip():
        return "usage: /sandbox <code python>"
    resp = _hub_call("run", {"action": "python", "code": args.strip(), "timeout": 30}, timeout=60)
    return _extract_text(resp)


async def cmd_nlu(args: str) -> str:
    """/nlu <text> — classify via forge_nlu PredictiveRouter (intent={chat,action,rag})."""
    if not args.strip():
        return "usage: /nlu <text>"
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_nlu import get_router_if_ready

        router = get_router_if_ready()
        if router is None:
            return (
                "PredictiveRouter pas prêt (training samples insuffisants).\n"
                "Fallback regex disponible via hybrid_classify(text, static_fn)."
            )
        vote = router.predict(args.strip())
        return f"intent     = {vote.intent}\nconfidence = {vote.confidence:.3f}\nconfident  = {vote.confident}"
    except Exception as e:
        return f"forge_nlu err: {type(e).__name__}: {e}"


async def cmd_estim(args: str) -> str:
    """/estim — rapport coût token monitor."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_token_monitor import daily_report, ALERT_DAILY_BUDGET_USD

        rep = daily_report()
        cost = rep.get("daily_cost_usd", 0)
        return (
            f"daily_cost ${cost:.4f} / budget ${ALERT_DAILY_BUDGET_USD}\n"
            f"by_provider: {json.dumps(rep.get('by_provider', {}), indent=2)[:500]}"
        )
    except Exception as e:
        return f"token_monitor indisponible: {e}"


async def cmd_chain(args: str) -> str:
    """/chain <agents...> — forge_handoff swarm execution."""
    if not args.strip():
        return "usage: /chain <agent1> <agent2> ...\n  Exemple: /chain agt_claude agt_gemini"
    agents = args.strip().split()
    resp = _hub_call("orchestrate", {"action": "handoff", "agents": agents, "task": "chain demo"})
    return _extract_text(resp)


async def cmd_scan(args: str) -> str:
    """/scan — ouvre :7400/recon navigateur."""
    try:
        webbrowser.open(f"{WEBHUB}/recon")
        return f"→ ouvert {WEBHUB}/recon"
    except Exception as e:
        return f"open fail: {e}"


async def cmd_help_extra(args: str) -> str:
    """/cmds — liste complète des commandes slash héritées v13.6."""
    lines = [
        "Commandes slash (héritage v13.6 → moderne) :",
        "  /run <cmd>        exec shell via hub (danger check)",
        "  /rag <query>      recherche RAG",
        "  /mem <query>      alias /rag",
        "  /agentic <skill>  check_competence forge_agentic_engine",
        "  /evolve           état self_patcher + auto_evolution_loop",
        "  /loop             alias /evolve",
        "  /apply            alias /evolve",
        "  /role [name]      switch ou liste rôles",
        "  /model [name]     liste/switch model Ollama",
        "  /ollama [list|ps|show <m>]   relais Ollama API",
        "  /audit            ouvre :7400/reports navigateur",
        "  /code <spec>      software creator pipeline",
        "  /test [path]      pytest via hub",
        "  /sandbox <code>   exec python via hub",
        "  /nlu <text>       classify intent",
        "  /estim            rapport coût token monitor",
        "  /chain a1 a2 ...  forge_handoff swarm chain",
        "  /scan             ouvre :7400/recon navigateur",
        "  /ssh <h> <p> <u>  ouvre session PTY",
        "  /ssh-send <cmd>   inject dans PTY",
        "  /ssh-close        ferme PTY",
        "",
        "Dropped (v13.6 → couvert ailleurs) :",
        "  @diag → Ctrl+H (health) + Ctrl+S (services)",
        "  @services → Ctrl+S",
        "  @switch → Tab (cycle pane)",
        "  @workflow, @ci, @ids, @ragas, @proxy, @mode → out of scope",
    ]
    return "\n".join(lines)


# ── Registry ──────────────────────────────────────────────────────────────

COMMANDS: dict[str, Callable[[str], Awaitable[str]]] = {
    "/run": cmd_run,
    "/rag": cmd_rag,
    "/mem": cmd_mem,
    "/agentic": cmd_agentic,
    "/disco": cmd_agentic,  # alias v13.6
    "/evolve": cmd_evolve,
    "/loop": cmd_loop,
    "/apply": cmd_apply,
    "/role": cmd_role,
    "/model": cmd_model,
    "/ollama": cmd_ollama,
    "/audit": cmd_audit,
    "/code": cmd_code,
    "/test": cmd_test,
    "/sandbox": cmd_sandbox,
    "/nlu": cmd_nlu,
    "/estim": cmd_estim,
    "/chain": cmd_chain,
    "/scan": cmd_scan,
    "/cmds": cmd_help_extra,
}


async def dispatch(text: str) -> str | None:
    """Route /cmd vers handler. Retourne None si pas reconnu."""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    h = COMMANDS.get(cmd)
    if h is None:
        return None
    try:
        return await h(args)
    except Exception as e:
        return f"[{cmd} err] {type(e).__name__}: {e}"


def known() -> list[str]:
    return sorted(COMMANDS.keys())
