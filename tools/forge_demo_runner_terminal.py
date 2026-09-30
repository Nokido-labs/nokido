"""
forge_demo_runner_terminal — paced Nokido terminal demo for screen recording.

Lance les 5 sequences (health / tools / RAG / firewall / caption) avec
des pauses calibrees (~50s total) pour qu un recorder externe (ScreenToGif,
ShareX, Win+G) capture une demo lisible.

USAGE
    # 1. Ouvre Windows Terminal, fond noir, police 14-16pt, ~100x30.
    # 2. Lance ScreenToGif Recorder (F7) cadre sur la fenetre.
    # 3. Execute ce script.
    # 4. Stop ScreenToGif (F8) a la fin de la sequence.
    # 5. Save GIF (Encoder: System, Quality: 80, Loop: Forever, ~15 FPS).

    LAFORGE_PYTHON tools/forge_demo_runner_terminal.py

OPTIONS
    --hub URL         (default http://127.0.0.1:8766)
    --speed FACTOR    (default 1.0 ; 1.5 pour version pressee)
    --no-color        (desactive ANSI pour env sans support)
    --skip-ask        (skip step LLM ask -- si Ollama down)

Anti-dup OK : gen_demo_gifs.py (Playwright headless) produit des GIFs
synthetiques cross-OS ; ce script vise au contraire de vraies captures
d ecran via outil externe.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fetch_bearer() -> str:
    """Recupere le token CLAUDE depuis le vault DPAPI. Silencieux (ne print pas)."""
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        return get_secret("FORGE_TOKEN_CLAUDE") or get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        return ""


# ─── ANSI helpers ──────────────────────────────────────────────────────────

_USE_COLOR = True


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def banner(title: str) -> None:
    print()
    print(_c("34", "─" * 60))
    print(_c("1;34", f"  {title}"))
    print(_c("34", "─" * 60))
    time.sleep(0.4)


def typed(cmd: str, hold: float = 0.6) -> None:
    sys.stdout.write(_c("36", "$ "))
    for ch in cmd:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.015)
    sys.stdout.write("\n")
    sys.stdout.flush()
    time.sleep(hold)


def _hub_post(url: str, payload: dict, token: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Agent-Name"] = "CLAUDE"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))


def _hub_get(url: str) -> str:
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


# ─── Sequences ─────────────────────────────────────────────────────────────


def seq_intro() -> None:
    print()
    print(_c("1;36", "━" * 60))
    print(_c("1;36", "  Nokido — Local-First Sovereign AI Hub"))
    print(_c("1;36", "━" * 60))
    time.sleep(1.0)


def seq_health(hub: str) -> None:
    banner("1. Hub health")
    typed(f"curl -s {hub}/health")
    print(_c("32", _hub_get(f"{hub}/health")))


def seq_tools(hub: str, token: str) -> None:
    banner("2. MCP tools exposed")
    typed(f"curl -X POST {hub}/mcp  (tools/list)")
    resp = _hub_post(f"{hub}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token)
    tools = resp.get("result", {}).get("tools", [])
    for t in tools[:8]:
        name = t.get("name", "?")
        desc = (t.get("description") or "").split("\n")[0][:42]
        print(f"  {_c('1;33', '•')} {name:32s}  {desc}")
    print(_c("90", f"  ... ({len(tools)} total)"))


def seq_rag(hub: str, token: str) -> None:
    banner("3. RAG semantic search — BGE-M3 1024D + BM25 + reranker")
    typed("rag.search 'neuromorphic computing' limit=3")
    resp = _hub_post(
        f"{hub}/mcp",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "rag",
                "arguments": {"action": "search", "topic": "neuromorphic computing", "limit": 3},
            },
        },
        token,
    )
    content = resp.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "")
        for line in text.split("\n")[:8]:
            print(f"  {line[:78]}")


def seq_firewall() -> None:
    banner("4. SemanticFirewall — pre-flight redaction (canary + DLP)")
    typed("fw.pre_flight 'My API key is sk-proj-secret123; what is RAG?'")
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall  # type: ignore

        fw = get_firewall()
        pf = fw.pre_flight(
            "My API key is sk-proj-secret123; what is RAG?",
            context="",
            ring=2,
        )
        if pf.ok:
            print(_c("32", "  ✓ OK after redaction"))
            print(f"  safe_task : {pf.safe_task[:120]}")
            print(f"  aliases   : {len(pf.mapping)} sensitive tokens replaced")
        else:
            print(_c("31", f"  ✗ blocked : {pf.reason}"))
    except Exception as e:
        print(_c("31", f"  (firewall unavailable: {e})"))


def seq_caption() -> None:
    print()
    print(_c("1;32", "━" * 60))
    print(_c("1;32", "  github.com/Nokido-labs/nokido  ·  AGPLv3  ·  local-first"))
    print(_c("1;32", "  29 providers · HumanEval 87.8 · BFCL 90-96"))
    print(_c("1;32", "━" * 60))
    time.sleep(3.0)


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    ap.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Pause multiplier between sequences (1.0=normal, 1.5=fast)",
    )
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--skip-firewall", action="store_true")
    args = ap.parse_args()

    global _USE_COLOR
    if args.no_color:
        _USE_COLOR = False

    token = _fetch_bearer()
    if not token:
        print(
            _c("31", "WARN: vault FORGE_TOKEN_CLAUDE introuvable -- continue sans auth"),
            file=sys.stderr,
        )

    pause = 1.5 / args.speed

    seq_intro()
    time.sleep(pause)

    seq_health(args.hub)
    time.sleep(pause)

    seq_tools(args.hub, token)
    time.sleep(pause)

    seq_rag(args.hub, token)
    time.sleep(pause)

    if not args.skip_firewall:
        seq_firewall()
        time.sleep(pause)

    seq_caption()
    return 0


if __name__ == "__main__":
    sys.exit(main())
