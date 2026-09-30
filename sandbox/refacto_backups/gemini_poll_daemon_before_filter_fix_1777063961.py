from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_gemini_poll_daemon
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.25|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: daemon polling autonome pour Gemini CLI (pattern D2 Autonomous)
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__  = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.25|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
tools/gemini_poll_daemon.py - Autonomous polling daemon pour Gemini (Pattern D2)
=================================================================================

Le probleme resolu :
  Le pattern D (collab Claude <-> Gemini via notify/poll) est asynchrone par conception.
  Gemini CLI n'execute des tools QUE quand un humain tape un prompt.
  Donc les notify envoyees par Claude restent en attente indefiniment.

Solution Pattern D2 :
  Un daemon Python qui tourne en arriere-plan et poll le Hub Nokido toutes les N
  secondes. Quand une notif est recue, 2 comportements possibles :

  Mode PASSIVE (defaut) : logge + ecrit dans ~/.gemini/inbox.md pour visibilite
                          humaine. Gemini CLI peut etre prompte a consulter l'inbox.

  Mode ACTIVE          : appelle directement l'API Gemini pour traiter la tache
                         (requiert GEMINI_API_KEY + librairie google-genai). Ecrit
                         la reponse comme nouvelle notify vers CLAUDE.

Configuration via env :
  FORGE_MCP_TOKEN         : token Bearer Hub (lu depuis Nokido.env)
  FORGE_HUB_URL           : URL Hub (defaut http://127.0.0.1:8766)
  GEMINI_POLL_INTERVAL_S  : intervalle poll en secondes (defaut 30)
  GEMINI_POLL_MODE        : passive | active (defaut passive)
  GEMINI_API_KEY          : requis en mode active
  GEMINI_MODEL            : modele (defaut gemini-2.5-flash)
  GEMINI_INBOX_PATH       : fichier markdown pour notifs recues
                            (defaut ~/.gemini/inbox.md)

Usage :
  python tools/gemini_poll_daemon.py                 # mode passive, 30s
  GEMINI_POLL_MODE=active python tools/gemini_poll_daemon.py

Integration avec forge_services_launcher :
  python tools/forge_services_launcher.py            # inclus si GEMINI_POLL_ENABLED=1
  python tools/forge_services_launcher.py --only gemini_poll

Protocole :
  1. Boucle every N seconds
  2. POST /mcp method=tools/call name=poll -> liste notifs
  3. Filter : garder celles qui mentionnent Gemini ou sont non-addressees
  4. Mode passive : append dans inbox.md avec timestamp + ID
  5. Mode active : invoke Gemini API avec le contexte, parser la reponse,
                   appeler tools/call name=notify pour repondre a Claude

Heartbeat : le daemon ecrit sa date de derniere iteration dans
sandbox/gemini_poll_daemon.heartbeat pour monitoring.
"""

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
SANDBOX.mkdir(exist_ok=True)

HUB_URL = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766").rstrip("/")
POLL_INTERVAL = int(os.environ.get("GEMINI_POLL_INTERVAL_S", "30"))
POLL_MODE = os.environ.get("GEMINI_POLL_MODE", "passive").lower()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
INBOX_PATH = Path(os.environ.get("GEMINI_INBOX_PATH",
                                  str(Path.home() / ".gemini" / "inbox.md")))
HEARTBEAT = SANDBOX / "gemini_poll_daemon.heartbeat"
LOG_FILE = SANDBOX / "gemini_poll_daemon.log"

_SHUTDOWN = False


def log(msg: str, level: str = "INFO") -> None:
    """Log sur stderr + fichier."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:>5}] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_token() -> str:
    """Lit FORGE_MCP_TOKEN depuis env ou Nokido.env."""
    tok = os.environ.get("FORGE_MCP_TOKEN", "")
    if tok:
        return tok
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FORGE_MCP_TOKEN="):
                return line.split("=", 1)[1].split("#")[0].strip()
    return ""


def mcp_call(method: str, params: dict | None = None,
             token: str = "", timeout: int = 15) -> dict:
    """Appel JSON-RPC au Hub MCP."""
    body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 99999,
            "method": method}
    if params is not None:
        body["params"] = params

    req = urllib.request.Request(
        f"{HUB_URL}/mcp",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "GEMINI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": {"code": e.code, "message": e.reason,
                          "body": e.read().decode("utf-8", errors="replace")[:200]}}
    except Exception as e:
        return {"error": {"message": f"{type(e).__name__}: {e}"}}


def poll_notifications(token: str) -> list[str]:
    """Appelle tools/call name=poll. Retourne la liste des messages."""
    resp = mcp_call("tools/call", {"name": "poll", "arguments": {}}, token=token)
    if "error" in resp:
        log(f"poll error: {resp['error']}", "WARN")
        return []

    content = resp.get("result", {}).get("content", [])
    if not content:
        return []

    text = content[0].get("text", "")
    if not text or text.strip() in ("", "Aucune notification en attente",
                                     "Aucune notification"):
        return []

    # Le poll retourne les messages separes par lignes vides ou prefix "[AGENT]"
    # On split par marker "[CLAUDE]", "[GEMINI]", "[ROO]", "[CLINE]" etc.
    import re
    parts = re.split(r'(?=^\[[A-Z_]+\])', text, flags=re.M)
    return [p.strip() for p in parts if p.strip()]


def send_reply(token: str, reply_text: str) -> bool:
    """Envoie une notify en reponse."""
    resp = mcp_call("tools/call",
                    {"name": "notify", "arguments": {"message": reply_text}},
                    token=token)
    return "error" not in resp


def index_in_rag(token: str, entry_id: str, text: str, tags: list) -> bool:
    """Indexe le resultat dans la RAG partagee."""
    tags_str = ",".join(tags)
    sql = (
        "INSERT INTO rag_chunks (id, text, source, domain, author, "
        "ingested_at, meta) VALUES ("
        f"'{entry_id}', '{text.replace(chr(39), chr(39)*2)[:2000]}', "
        f"'gemini_poll_daemon', 'collab', 'GEMINI', datetime('now'), "
        f"'{{\"tags\": [\"{tags_str}\"]}}' )"
    )
    resp = mcp_call("tools/call", {"name": "query", "arguments": {"sql": sql}},
                    token=token)
    return "error" not in resp


def append_to_inbox(notifs: list[str]) -> None:
    """Append les notifs au fichier inbox.md (mode passive)."""
    INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with INBOX_PATH.open("a", encoding="utf-8") as f:
        for n in notifs:
            f.write(f"\n---\n## {ts}\n\n{n}\n")


def call_gemini_api(prompt: str, api_key: str, model: str,
                    timeout: int = 120) -> str:
    """Appel Gemini via API REST (generateContent)."""
    # Format Gemini REST API v1beta : endpoint generateContent
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        candidates = data.get("candidates", [])
        if candidates:
            return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return "(reponse Gemini vide)"
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")[:500]
        return f"ERR Gemini API HTTP {e.code}: {body_err}"
    except Exception as e:
        return f"ERR Gemini API: {type(e).__name__}: {e}"


def process_active(notif: str, api_key: str, token: str) -> None:
    """Mode active : appelle Gemini pour traiter, renvoie via notify."""
    # Filtrer : ne pas traiter les notifs systeme (fichier ecrit, mode AUTO etc.)
    if "fichier ecrit:" in notif or "Mode AUTO" in notif:
        return
    if len(notif) < 50:
        return

    log(f"Processing with Gemini API ({GEMINI_MODEL})...")

    prompt = (
        "Tu es un agent LLM dans un systeme d'orchestration multi-agent Nokido.\n"
        "Tu as recu une notification d'un autre agent (Claude). "
        "Analyse la et reponds de maniere constructive et concise.\n\n"
        "CONTRAINTES :\n"
        "- Reponse en francais\n"
        "- Max 300 mots\n"
        "- Si une tache t'est demandee : propose un plan d'execution en 3-5 etapes\n"
        "- Sinon : acknowledge + contribution pertinente\n\n"
        f"NOTIFICATION RECUE :\n{notif}\n\n"
        "TA REPONSE :"
    )

    reply = call_gemini_api(prompt, api_key, GEMINI_MODEL)
    if reply.startswith("ERR"):
        log(f"Gemini API error: {reply[:200]}", "ERR")
        return

    # Envoyer la reponse comme notify retour
    full_reply = f"[GEMINI/daemon] {reply}"
    if send_reply(token, full_reply):
        log(f"Reply sent ({len(reply)} chars)")
        # Indexer dans RAG
        entry_id = f"gemini_daemon_reply_{int(time.time())}"
        index_in_rag(token, entry_id, reply[:1500],
                    ["collab", "gemini_daemon", "auto_reply", "pattern_D2"])
    else:
        log("Reply send failed", "ERR")


def write_heartbeat(status: str, notifs_count: int = 0) -> None:
    """Ecrit heartbeat pour monitoring externe."""
    try:
        HEARTBEAT.write_text(
            json.dumps({
                "ts": datetime.now().isoformat(),
                "status": status,
                "mode": POLL_MODE,
                "interval_s": POLL_INTERVAL,
                "notifs_consumed_this_cycle": notifs_count,
                "hub_url": HUB_URL,
                "model": GEMINI_MODEL if POLL_MODE == "active" else None,
            }, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def handle_shutdown(signum, frame):
    """SIGINT/SIGTERM handler."""
    global _SHUTDOWN
    _SHUTDOWN = True
    log(f"Signal {signum} recu, shutdown...")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini autonomous polling daemon")
    parser.add_argument("--once", action="store_true",
                       help="Un seul cycle puis exit (pour tests)")
    parser.add_argument("--interval", type=int, default=None,
                       help=f"Override GEMINI_POLL_INTERVAL_S (defaut {POLL_INTERVAL}s)")
    parser.add_argument("--mode", choices=["passive", "active"], default=None,
                       help="Override GEMINI_POLL_MODE")
    args = parser.parse_args()

    interval = args.interval or POLL_INTERVAL
    mode = args.mode or POLL_MODE

    # Setup signals
    signal.signal(signal.SIGINT, handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_shutdown)

    # Token
    token = load_token()
    if not token:
        log("FORGE_MCP_TOKEN absent (env ou Nokido.env). Aborting.", "ERR")
        return 2

    # API key si mode active
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if mode == "active" and not api_key:
        log("Mode active requires GEMINI_API_KEY. Falling back to passive.", "WARN")
        mode = "passive"

    log(f"Gemini Poll Daemon starting | mode={mode} | interval={interval}s | hub={HUB_URL}")
    log(f"  inbox: {INBOX_PATH}")
    log(f"  heartbeat: {HEARTBEAT}")
    log(f"  log: {LOG_FILE}")

    # Ping initial : verifier que le Hub repond
    health = mcp_call("tools/list", token=token, timeout=5)
    if "error" in health:
        log(f"Hub unreachable: {health['error']}", "ERR")
        return 3
    tools_count = len(health.get("result", {}).get("tools", []))
    log(f"Hub OK, {tools_count} tools disponibles")

    write_heartbeat("starting")
    cycles = 0

    while not _SHUTDOWN:
        cycles += 1
        try:
            notifs = poll_notifications(token)
        except Exception as e:
            log(f"Poll exception: {type(e).__name__}: {e}", "ERR")
            notifs = []

        if notifs:
            log(f"Cycle {cycles}: {len(notifs)} notification(s) recue(s)")

            if mode == "passive":
                append_to_inbox(notifs)
                log(f"  -> appended to {INBOX_PATH.name}")
            elif mode == "active":
                for notif in notifs:
                    if _SHUTDOWN:
                        break
                    try:
                        process_active(notif, api_key, token)
                    except Exception as e:
                        log(f"  process_active err: {type(e).__name__}: {e}", "ERR")

        write_heartbeat("running", len(notifs))

        if args.once:
            log("--once mode, exiting")
            break

        # Sleep avec check shutdown periodique
        for _ in range(interval):
            if _SHUTDOWN:
                break
            time.sleep(1)

    write_heartbeat("stopped")
    log(f"Daemon stopped after {cycles} cycle(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
