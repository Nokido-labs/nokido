"""forge_bell.py - La sonnette Nokido.

Surveille en boucle :
  1. Task queue hub (task_claim) -> dispatche vers worker python ou gemini
  2. COMMUNICATIONS.md (mtime) -> notifie les agents si nouveau message
  3. EventBus topics task.*.start -> log + heartbeat

Complement du gemini_poll_daemon :
  - daemon   = facteur (lit/écrit les lettres)
  - bell     = sonnette (réveille les exécutants quand courrier arrive)

Usage:
  python tools/forge_bell.py
  python tools/forge_bell.py --interval 15
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
SANDBOX.mkdir(exist_ok=True)
LOG = SANDBOX / "forge_bell.log"
HB = SANDBOX / "forge_bell.heartbeat"
COMMS = ROOT / "COMMUNICATIONS.md"

HUB = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766")


def _load_directory() -> dict:
    """Charge DIRECTORY.json -- annuaire des correspondants."""
    d = ROOT / "DIRECTORY.json"
    if d.exists():
        try:
            return json.loads(d.read_text(encoding="utf-8"))["correspondents"]
        except:
            pass
    return {}


DIRECTORY = _load_directory()
INTERVAL = int(os.environ.get("FORGE_BELL_INTERVAL", "20"))

_shutdown = False


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:>5}] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


def _token() -> str:
    for line in (ROOT / "Nokido.env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("FORGE_TOKEN_SERVICES="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("FORGE_MCP_TOKEN", "")


def _mcp(name, args, token, timeout=15):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 99999,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(
        f"{HUB}/mcp",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Agent-Name": "SERVICES",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def _heartbeat(status, task_id=None):
    try:
        HB.write_text(
            json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "status": status,
                    "last_task": task_id,
                    "interval": INTERVAL,
                }
            ),
            encoding="utf-8",
        )
    except:
        pass


def _send_ack(token: str, msg_hash: str, agent: str):
    """Accusé de réception léger — EventBus topic comms.ack, zéro token."""
    _mcp(
        "event",
        {
            "action": "publish",
            "topic": "comms.ack",
            "kind": "ack",
            "data": {"hash": msg_hash[:8], "agent": agent, "ok": True},
        },
        token,
    )


def _dispatch_task(task: dict, token: str):
    """Dispatche une tâche vers le bon exécutant selon son type."""
    tid = task.get("task_id", "?")
    desc = task.get("description", "")
    agent = task.get("agent", "")

    log(f"Task claimed: {tid} agent={agent} desc={desc[:60]}")

    # Routing par agent assigné
    if agent in ("GEMINI", "gemini"):
        # Déléguer au daemon Gemini via notify
        _mcp("notify", {"message": f"BELL→GEMINI: task_id={tid} | {desc}"}, token)
        log("  → dispatched to gemini_daemon")

    elif agent in ("WORKER", "worker", "python", "PYTHON") or not agent:
        # description = code Python à exécuter
        res = _mcp("run", {"action": "python", "code": desc}, token, timeout=60)
        content = res.get("result", {}).get("content", [])
        result = content[0].get("text", "ERR") if content else str(res)[:200]
        _mcp("task", {"action": "result", "task_id": tid, "result": result}, token)
        log(f"  → WORKER result: {result[:80]}")

    elif agent in ("CLAUDE", "claude"):
        # Écrire dans COMMUNICATIONS.md pour Claude
        entry = f"\n### [BELL → CLAUDE @ {datetime.now().isoformat()}]\n"
        entry += f"**Task {tid}** : {desc}\n\n---\n"
        with COMMS.open("a", encoding="utf-8") as f:
            f.write(entry)
        log("  → written to COMMUNICATIONS.md for Claude")

    elif agent.upper() in ("MCP_DOCKER", "DOCKER_MCP"):
        _mcp("notify", {"message": f"MCP_DOCKER task_id={tid}: {desc[:300]}"}, token)
        log("  -> MCP_DOCKER notify")

    elif agent.upper() in ("VIDEO_GEN_MCP", "VIDEO"):
        _mcp("notify", {"message": f"VIDEO_GEN task_id={tid}: {desc[:200]}"}, token)
        log("  -> VIDEO_GEN_MCP notify")

    elif agent.upper() in ("SEARXNG", "SEARXNG_MCP"):
        import json as _jj
        import urllib.parse as _up
        import urllib.request as _ur

        try:
            q = _up.quote(desc[:150])
            r = _ur.urlopen(f"http://127.0.0.1:8080/search?q={q}&format=json", timeout=10)
            data = _jj.loads(r.read())
            result = " | ".join(x.get("title", "") for x in data.get("results", [])[:3])
            _mcp("task", {"action": "result", "task_id": tid, "result": result}, token)
        except Exception as e:
            log(f"  -> SEARXNG err: {e}", "WARN")

    else:
        log(f"  -> agent inconnu {agent}, notify fallback")
        _mcp("notify", {"message": f"BELL: task {tid} non route (agent={agent})"}, token)
    _send_ack(token, tid, agent)


def _sync_comms(content: str, token: str, last_hash: str) -> str:
    """Synchronise COMMUNICATIONS.md : RAG + notify agents si nouveau bloc."""
    import hashlib
    import re
    import sqlite3

    cur_hash = hashlib.md5(content.encode()).hexdigest()
    if cur_hash == last_hash:
        return last_hash

    # Extraire les nouveaux blocs [AGENT @ timestamp]
    blocks = re.findall(r"### \[([A-Z]+) @ ([^\]]+)\]\n(.*?)(?=\n###|\Z)", content, re.DOTALL)
    new_blocks = [(a, ts, body.strip()) for a, ts, body in blocks if body.strip()]
    log(f"COMMUNICATIONS.md synchro: {len(new_blocks)} blocs detectes")

    # 1. Indexer en RAG
    try:
        db_path = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(db_path))
        now = datetime.now(UTC).isoformat()
        for agent, ts, body in new_blocks:
            uid = "comm_" + hashlib.md5(f"{agent}{ts}".encode()).hexdigest()[:10]
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks "
                "(id,text,source,domain,role_hint,author,ingested_at) VALUES (?,?,?,?,?,?,?)",
                (
                    uid,
                    # 2026-09-12 : `[:3000]` — meme borne que celle qui avait
                    # detruit le corps de 377 documents de veille (gate
                    # `borne_trop_serree`). 562 chunks coupes pile a 3000.
                    f"[{agent} @ {ts}]\n{body}",
                    "COMMUNICATIONS.md",
                    "nokido_collab",
                    f"comm_{agent.lower()}",
                    agent,
                    now,
                ),
            )
        conn.commit()
        conn.close()
        log(f"  RAG: {len(new_blocks)} blocs indexes")
    except Exception as e:
        log(f"  RAG error: {e}", "WARN")

    # 2. Sonnette legere : EventBus topic comms.updated (zero token, zero LLM)
    agents_in_blocks = set(a for a, _, _ in new_blocks)
    _mcp(
        "event",
        {
            "action": "publish",
            "topic": "comms.updated",
            "kind": "bell",
            "data": {
                "hash": cur_hash[:8],
                "agents": list(agents_in_blocks),
                "blocks": len(new_blocks),
            },
        },
        token,
    )

    # 3. Ecrire snapshot horodaté dans sandbox/
    try:
        snap = SANDBOX / f"comms_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        snap.write_text(content, encoding="utf-8")
        # Garder seulement les 5 derniers snapshots
        snaps = sorted(SANDBOX.glob("comms_snapshot_*.md"))
        for old in snaps[:-5]:
            old.unlink(missing_ok=True)
    except:
        pass

    return cur_hash


def _has_ack(token: str, msg_hash: str) -> bool:
    """Vérifie si un ack existe pour ce hash dans l EventBus (zéro token)."""
    res = _mcp("event", {"action": "history", "topics": ["comms.ack"], "limit": 20}, token)
    events = res.get("result", {}).get("content", [{}])[0].get("text", "")
    return msg_hash[:8] in events


def _watch_comms(last_mtime: float, last_hash: str, token: str):
    """Surveille COMMUNICATIONS.md — synchro seulement si hash change et pas encore acké."""
    if not COMMS.exists():
        return last_mtime, last_hash
    mtime = COMMS.stat().st_mtime
    if mtime <= last_mtime:
        return last_mtime, last_hash
    content = COMMS.read_text(encoding="utf-8", errors="replace")
    import hashlib

    cur_hash = hashlib.md5(content.encode()).hexdigest()
    if cur_hash == last_hash:
        return mtime, last_hash  # contenu identique
    if _has_ack(token, cur_hash):
        log(f"COMMUNICATIONS.md: hash={cur_hash[:8]} déjà acké -- skip")
        return mtime, cur_hash
    new_hash = _sync_comms(content, token, last_hash)
    return mtime, new_hash


def main():
    import argparse
    import signal

    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=INTERVAL)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    def _stop(*_):
        global _shutdown
        _shutdown = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    token = _token()
    comms_mtime = COMMS.stat().st_mtime if COMMS.exists() else 0
    comms_hash = ""
    cycles = 0

    log(f"forge_bell starting | interval={args.interval}s | hub={HUB}")
    _heartbeat("starting")

    while not _shutdown:
        cycles += 1
        try:
            # 1. Claim une tâche en attente
            res = _mcp("task", {"action": "claim"}, token)
            content = res.get("result", {}).get("content", [{}])[0].get("text", "")
            if content and "task_id" in content:
                try:
                    task = json.loads(content) if content.startswith("{") else {}
                    if task.get("task_id"):
                        _dispatch_task(task, token)
                except:
                    log(f"task parse error: {content[:80]}", "WARN")

            # 2. Surveiller COMMUNICATIONS.md
            comms_mtime, comms_hash = _watch_comms(comms_mtime, comms_hash, token)

            _heartbeat("running", cycles)

        except Exception as e:
            log(f"cycle error: {e}", "ERR")

        if args.once:
            break
        for _ in range(args.interval):
            if _shutdown:
                break
            time.sleep(1)

    _heartbeat("stopped")
    log(f"forge_bell stopped after {cycles} cycles")


if __name__ == "__main__":
    main()
