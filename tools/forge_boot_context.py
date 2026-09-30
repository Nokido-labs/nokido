#!/usr/bin/env python3
"""
forge_boot_context.py - Generateur de contexte de reprise pour agents Nokido.

Genere un snapshot de l etat Nokido par agent :
  - Messages non lus dans sa boite
  - Jobs interrompus qui lui appartiennent
  - Derniere session CLI (avec commande --resume)
  - Biblio a reviewer

Transposable a tous les agents : Gemini CLI, Claude, Cline, workers.
Usage :
    python tools/forge_boot_context.py
    python tools/forge_boot_context.py --inject   # injecte dans GEMINI.md
    python tools/forge_boot_context.py --agent GEMINI
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

AGENT_CONFIGS = {
    "agt_gemini": {
        "name": "GEMINI",
        "display": "Gemini CLI OAuth",
        "session_base": Path.home() / ".gemini" / "tmp",
        "project_map": {
            str(ROOT): "laforge",
            str(ROOT.parent): "script-python-ia",
            str(Path.home()): "user",
        },
        "resume_cmd": "gemini --resume '{session_id}'",
        "fallback_cmd": "python tools/gemini_resume.py",
        "context_file": Path.home() / ".gemini" / "GEMINI.md",
        "inject_section": "## CONTEXTE DE REPRISE",
    },
    "agt_claude": {
        "name": "CLAUDE",
        "display": "Claude Desktop (bridge STDIO)",
        "session_base": None,
        "project_map": {},
        "resume_cmd": None,
        "fallback_cmd": None,
        "context_file": ROOT / "docs" / "CLAUDE_BOOT_CONTEXT.md",
        "inject_section": None,
    },
    "agt_cline": {
        "name": "CLINE",
        "display": "Cline VS Code",
        "session_base": None,
        "project_map": {},
        "resume_cmd": None,
        "fallback_cmd": None,
        "context_file": ROOT / "docs" / "CLINE_BOOT_CONTEXT.md",
        "inject_section": None,
    },
    "agt_daemon": {
        "name": "DAEMON",
        "display": "gemini_poll_daemon",
        "session_base": None,
        "project_map": {},
        "resume_cmd": None,
        "fallback_cmd": "python tools/gemini_poll_daemon.py --interval 20",
        "context_file": ROOT / "sandbox" / "daemon_boot_context.md",
        "inject_section": None,
    },
}


def db_conn():
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def last_session(cfg: dict) -> dict | None:
    base = cfg.get("session_base")
    if not base or not Path(base).exists():
        return None
    cwd = str(ROOT)
    project = None
    for path, name in sorted(cfg["project_map"].items(), key=lambda x: -len(x[0])):
        if cwd.startswith(path):
            project = name
            break
    if not project:
        return None
    chats = Path(base) / project / "chats"
    if not chats.exists():
        return None
    for f in sorted(chats.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            if not lines:
                continue
            d = json.loads(lines[0])
            sid = d.get("sessionId")
            if sid:
                return {
                    "sessionId": sid,
                    "file": f.name,
                    "size_kb": f.stat().st_size // 1024,
                    "mtime": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M"),
                    "project": project,
                }
        except Exception:
            pass
    return None


def build_context(agent_id: str) -> str:
    cfg = AGENT_CONFIGS.get(agent_id, {})
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db_conn()

    # Messages non lus
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : la boite vit dans la base M2M, pas avec biblio_raw/watch_jobs
    _m2m = sqlite3.connect(m2m_path())
    unread = _m2m.execute(
        "SELECT id, from_agent, created_at, payload FROM agent_messages "
        "WHERE to_agent=? AND status='unread' ORDER BY created_at DESC LIMIT 5",
        (agent_id,),
    ).fetchall()

    # Jobs interrompus
    jobs = conn.execute(
        "SELECT id, theme, step, status FROM watch_jobs "
        "WHERE status IN ('pending','running','error') "
        "ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    # Biblio en attente
    biblio = conn.execute(
        "SELECT id, title FROM biblio_raw WHERE status='unverified' LIMIT 4"
    ).fetchall()

    conn.close()

    # Session CLI
    session = last_session(cfg)
    resume_cmd = ""
    if session and cfg.get("resume_cmd"):
        resume_cmd = cfg["resume_cmd"].format(session_id=session["sessionId"])

    out = []
    out.append(f"## CONTEXTE DE REPRISE — {cfg.get('display', agent_id)}")
    out.append(f"*Nokido boot snapshot {now}*")
    out.append("")

    if resume_cmd:
        out.append("### Session CLI a reprendre")
        out.append(f"    {resume_cmd}")
        out.append(f"    # {session['file']} ({session['size_kb']}kb) @ {session['mtime']}")
        out.append(f"    # Ou : {cfg.get('fallback_cmd', '')}")
        out.append("")

    if unread:
        out.append(f"### Messages non lus ({len(unread)})")
        for r in unread:
            try:
                txt = json.loads(r["payload"]).get("text", "")[:120]
            except Exception:
                txt = str(r["payload"])[:120]
            out.append(f"- [{r['created_at'][-8:]}] {r['from_agent']}: {txt}")
        out.append("")
        out.append("Marquer lus apres traitement :")
        out.append(
            f'    UPDATE agent_messages SET status="read" WHERE to_agent="{agent_id}" AND status="unread"'
        )
        out.append("")
    else:
        out.append("### Messagerie : rien a traiter")
        out.append("")

    if jobs:
        out.append(f"### Jobs interrompus ({len(jobs)})")
        for j in jobs:
            out.append(f"- [{j['status']:8}] step={j['step']} | {j['theme'][:55]}")
            out.append(f"  -> run_watch_job('{j['id']}')")
        out.append("")

    if biblio:
        out.append(f"### Biblio a reviewer ({len(biblio)})")
        for b in biblio:
            out.append(f"- {b['id'][:12]} : {b['title'][:60]}")
        out.append("    biblio action=list")
        out.append("")

    out.append("### Lire sa boite")
    out.append("    SELECT id,from_agent,created_at,substr(payload,1,200)")
    out.append(f'    FROM agent_messages WHERE to_agent="{agent_id}" AND status="unread"')
    out.append("    ORDER BY created_at DESC LIMIT 10")

    return "\n".join(out)


def inject_gemini_md(context: str) -> None:
    md = Path.home() / ".gemini" / "GEMINI.md"
    txt = md.read_text(encoding="utf-8")
    marker = "## CONTEXTE DE REPRISE"
    if marker in txt:
        start = txt.find(marker)
        end = txt.find("\n## ", start + 1)
        end = end if end != -1 else len(txt)
        txt = txt[:start] + context + "\n\n" + txt[end:].lstrip("\n")
    else:
        txt = txt.rstrip() + "\n\n" + context
    md.write_text(txt, encoding="utf-8")
    print(f"[inject] GEMINI.md: {md.stat().st_size}b")


def main():
    args = sys.argv[1:]
    inject = "--inject" in args
    target = None
    if "--agent" in args:
        idx = args.index("--agent")
        if idx + 1 < len(args):
            target = "agt_" + args[idx + 1].lower()

    agents = [target] if target else list(AGENT_CONFIGS.keys())

    for agent_id in agents:
        cfg = AGENT_CONFIGS.get(agent_id, {})
        ctx = build_context(agent_id)
        print(f"\n{'=' * 56}")
        print(f"Agent: {cfg.get('display', agent_id)}")
        print(ctx[:600])
        ctx_file = cfg.get("context_file")
        if ctx_file:
            Path(ctx_file).parent.mkdir(parents=True, exist_ok=True)
            Path(ctx_file).write_text(ctx, encoding="utf-8")
            print(f"[saved] {ctx_file}")

    if inject:
        ctx_g = build_context("agt_gemini")
        inject_gemini_md(ctx_g)


if __name__ == "__main__":
    main()
