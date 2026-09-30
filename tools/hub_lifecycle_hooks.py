"""
tools/hub_lifecycle_hooks.py — Server-side lifecycle hooks middleware
=====================================================================

Équivalent unifié des hooks SessionStart/AfterModel par-client (Gemini CLI,
Claude Code hooks, etc.) — agit côté hub :8766 selon `X-Agent-Name` header.

Avantage: code path unique, applicable à TOUS les clients MCP (Gemini, Codex,
Cline, Claude Desktop, TRAY, SERVICES…), même ceux sans système de hooks natif.

Fonctionnalités v1:
    - **inbox_preview**: si X-Agent a des messages unread ou jobs interrompus,
      append un bloc `[HOOK:INBOX]` au response text. Visible par le LLM
      appelant peu importe le client (les tool responses sont injectées dans
      le contexte LLM par tous les clients MCP).
    - **session_id**: propage X-Session-Id dans la telemetry et l'agent_messages
      log (correlation cross-request).
    - **telemetry**: enrichit `_log_network` avec session_id + outil + agent.

À étendre (v2):
    - Quota tracking serveur-side (au lieu du `after_model_hook.py` Gemini-only).
    - Rate limiting per-agent.
    - Boot context injection sur `initialize` (équivalent quota_hook.py).

Non-bloquant: toute erreur interne fait fallback silencieux (log warn, pas
de rejet de la requête).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("forge.lifecycle")

_ROOT = Path(os.environ.get("LAFORGE_ROOT", Path(__file__).resolve().parent.parent))
_DB = _ROOT / "RAG" / "embeddings.db"


def _m2m() -> str:
    """Base des agent_messages : suit l'interrupteur de la scission (sandbox/m2m.switch),
    lu a CHAQUE appel. Repli DIT sur la base historique si le point d'acces manque :
    un hook du hub ne casse jamais le hub."""
    try:
        import sys as _s
        _app = str(_ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_db_path import m2m_path
        return m2m_path()
    except Exception as _e:  # noqa: BLE001
        import sys as _s2
        print(f"[lifecycle_hooks] forge_db_path indisponible ({type(_e).__name__}) : base historique", file=_s2.stderr)
        return str(_DB)

# Tools/methods qu'on N'augmente PAS avec l'inbox preview pour éviter le bruit:
# - poll/notify/whoami: le client interroge déjà la mailbox, double-affichage inutile
# - initialize/tools/list: métadonnées protocole MCP
# - read/query: lourds, append diluerait l'output
_NO_INJECT_TOOLS = {
    "hub",  # hub.poll/whoami/notify handle inbox déjà
    "read",
    "query",
    "rag",
}

# Agents pour lesquels on injecte (clients LLM avec contexte conversationnel).
# Workers/daemons (SERVICES, BRIDGE, BELL...) reçoivent pas — ils consomment
# JSON, pas du texte LLM-visible.
_INJECT_AGENTS = {"CLAUDE", "CLAUDE_CLI", "GEMINI", "GEMINI_HEADLESS", "CODEX",
                  "COPILOT", "COPILOT_CLI", "CLINE", "TRAY"}


def _inject_agents() -> set:
    """CLI recevant l'INBOX : plancher fige UNION les cli_agent du registre LIVE.

    Le fige ci-dessus reste un PLANCHER (zero regression si le registre est
    illisible). La derivation ajoute AUTOMATIQUEMENT tout nouveau CLI declare
    kind=cli_agent dans config/agent_identities.json (mammouth, zcode, roo, vibe,
    sixth, vscode... + futurs) sans avoir a editer ce fichier.
    """
    base = set(_INJECT_AGENTS)
    try:
        import sys as _s
        from pathlib import Path as _P
        _s.path.insert(0, str(_P(__file__).resolve().parent.parent / "app"))
        from nokido_agent.app.forge_videur import cli_agents as _ca
        base |= _ca()
    except Exception:  # noqa: BLE001
        pass  # registre illisible -> on garde le plancher fige
    return base

# Limite : au-dessus on tronque (évite de surcharger les petits LLMs)
_MAX_PREVIEW_CHARS = 600
_MAX_MESSAGES = 3
_MAX_JOBS = 2

# ─── Un signal ne se repete pas tant qu'il n'a pas change (2026-09-24) ─────
# Mesure en session reelle : le MEME bloc de 3 messages etait reinjecte a CHAQUE
# reponse d'outil — 524 lignes [HOOK:INBOX] dans un seul transcript Claude Code,
# du contexte paye a chaque tour pour une information inchangee. La doc Claude Code
# le dit : un hook ne coute rien tant qu'il ne rend rien ; ce qu'il rend est injecte.
# Regle : pour (agent, session), on n'injecte que les elements NOUVEAUX. Tant que des
# elements restent non lus, un RAPPEL d'une ligne au plus toutes les _RAPPEL_S :
# une compaction du client peut avoir efface le premier affichage, et un silence
# total ferait lire la boite comme vide (UNKNOWN != NO). Etat EN MEMOIRE du process
# du hub : un redemarrage (ou un autre worker) re-montre une fois — borne dite.
_RAPPEL_S = int(os.environ.get("LAFORGE_INBOX_RAPPEL_S", "1800"))
_MAX_SESSIONS_SUIVIES = 512
_DEJA_MONTRES: dict = {}          # (agent, session) -> (frozenset de cles vues, t du dernier signal)
_VERROU_DEJA = threading.Lock()


def _cle_msg(m: dict) -> str:
    return "m:%s" % m.get("id")


def _cle_job(j: dict) -> str:
    return "j:%s:%s" % (j.get("id"), j.get("status"))


def _filtrer_nouveaux(agent: str, session_id: str, inbox: dict, maintenant: float | None = None):
    """-> (inbox restreinte aux elements NOUVEAUX | None, rappel d'une ligne | None)."""
    maintenant = time.time() if maintenant is None else maintenant
    msgs, jobs = inbox.get("messages", []), inbox.get("jobs", [])
    cles = frozenset([_cle_msg(m) for m in msgs] + [_cle_job(j) for j in jobs])
    k = (agent, session_id or "")
    with _VERROU_DEJA:
        if not cles:
            _DEJA_MONTRES.pop(k, None)
            return None, None
        vues, dernier = _DEJA_MONTRES.get(k, (frozenset(), 0.0))
        nouvelles = cles - vues
        if nouvelles:
            _DEJA_MONTRES[k] = (cles, maintenant)
            if len(_DEJA_MONTRES) > _MAX_SESSIONS_SUIVIES:
                for vieille in sorted(_DEJA_MONTRES, key=lambda c: _DEJA_MONTRES[c][1])[:len(_DEJA_MONTRES) - _MAX_SESSIONS_SUIVIES]:
                    _DEJA_MONTRES.pop(vieille, None)
            return ({"messages": [m for m in msgs if _cle_msg(m) in nouvelles],
                     "jobs": [j for j in jobs if _cle_job(j) in nouvelles]}, None)
        if maintenant - dernier >= _RAPPEL_S:
            _DEJA_MONTRES[k] = (cles, maintenant)
            return None, ("\n[HOOK:INBOX] %d element(s) toujours non lu(s), deja signale(s) — "
                          "detail : outil hub action=poll [/HOOK:INBOX]" % len(cles))
        _DEJA_MONTRES[k] = (cles, dernier)   # des elements lus ont pu sortir : on suit l'ensemble courant
        return None, None


def _query_inbox(agent: str) -> dict:
    """Lit la mailbox + jobs interrompus pour `agent`. Retourne dict {messages, jobs}.

    Schéma : table `agent_messages(id, from_agent, to_agent, status, payload, created_at)`
    + `watch_jobs(id, theme, step, status)`.
    """
    out: dict = {"messages": [], "jobs": []}
    if not _DB.exists():
        return out

    target_lower = agent.lower()
    target_full = f"agt_{target_lower}"

    try:
        with sqlite3.connect(f"file:{_m2m()}?mode=ro&immutable=0", uri=True, timeout=2.0) as conn:
            try:
                rows = conn.execute(
                    "SELECT id, from_agent, payload, created_at FROM agent_messages "
                    "WHERE (to_agent=? OR to_agent=?) AND status='unread' "
                    "ORDER BY rowid DESC LIMIT ?",
                    (target_full, target_lower, _MAX_MESSAGES),
                ).fetchall()
                for r in rows:
                    out["messages"].append(
                        {
                            "id": r[0],
                            "from": r[1],
                            "payload": (r[2] or "")[:200],
                            "ts": r[3],
                        }
                    )
            except sqlite3.OperationalError:
                pass  # table peut être absente sur installs fraîches

            try:
                rows = conn.execute(
                    "SELECT id, theme, step, status FROM watch_jobs "
                    "WHERE status IN ('pending','running','error') "
                    "ORDER BY rowid DESC LIMIT ?",
                    (_MAX_JOBS,),
                ).fetchall()
                for r in rows:
                    out["jobs"].append(
                        {
                            "id": r[0],
                            "theme": (r[1] or "")[:100],
                            "step": r[2],
                            "status": r[3],
                        }
                    )
            except sqlite3.OperationalError:
                pass
    except Exception as exc:  # pragma: no cover
        logger.debug(f"_query_inbox failed for {agent}: {exc}")

    return out


def _format_preview(inbox: dict) -> str | None:
    """Formate l'inbox en bloc texte injectable. None si rien d'urgent."""
    msgs = inbox.get("messages", [])
    jobs = inbox.get("jobs", [])
    if not msgs and not jobs:
        return None

    lines = ["", "[HOOK:INBOX]"]
    for m in msgs:
        snippet = (m.get("payload") or "").replace("\n", " ").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        lines.append(f"  * msg #{m['id']} from {m['from']}: {snippet}")
    for j in jobs:
        theme = (j.get("theme") or "").replace("\n", " ").strip()
        lines.append(f"  * job {j['id']} [{j['status']}] step={j['step']} : {theme[:80]}")
    lines.append("[/HOOK:INBOX]")
    block = "\n".join(lines)
    if len(block) > _MAX_PREVIEW_CHARS:
        block = block[:_MAX_PREVIEW_CHARS] + "...\n[/HOOK:INBOX]"
    return block


def pre_dispatch(agent: str, ring: int, tool: str, session_id: str) -> dict:
    """Hook pré-dispatch — capture contexte pour post_dispatch.

    Retour : dict de contexte (transmis à post_dispatch).
    Non-bloquant : ne raise jamais.
    """
    return {
        "agent": (agent or "").upper(),
        "ring": ring,
        "tool": tool or "",
        "session_id": session_id or "",
        "t_start": time.monotonic(),
    }


def post_dispatch(ctx: dict, response_text: str) -> str:
    """Hook post-dispatch — augmente la réponse avec [HOOK:INBOX] si nécessaire.

    Retourne le texte (possiblement augmenté). Idempotent + safe :
    si le bloc INBOX est déjà présent dans la réponse, ne réinjecte pas.
    """
    if not isinstance(response_text, str):
        return response_text

    agent = ctx.get("agent", "")
    tool = ctx.get("tool", "")

    # Filtres d'injection
    if agent not in _inject_agents():
        return response_text
    if tool in _NO_INJECT_TOOLS:
        return response_text
    if "[HOOK:INBOX]" in response_text:
        return response_text  # déjà présent (peut-être via hub.poll)

    try:
        inbox = _query_inbox(agent)
        a_montrer, rappel = _filtrer_nouveaux(agent, ctx.get("session_id", ""), inbox)
        preview = _format_preview(a_montrer) if a_montrer else rappel
        if preview:
            return response_text.rstrip() + "\n\n" + preview
    except Exception as exc:  # pragma: no cover
        logger.debug(f"post_dispatch inbox skipped for {agent}: {exc}")

    return response_text


# ─── Convenience API — wrappers utilisables direct côté nokido_hub.py ──────


def wrap_response(agent: str, ring: int, tool: str, session_id: str, response_text: str) -> str:
    """One-shot helper — équivalent pre_dispatch + post_dispatch.

    Utilisable depuis nokido_hub.mcp_post sans gérer le ctx explicitement.
    """
    ctx = pre_dispatch(agent, ring, tool, session_id)
    return post_dispatch(ctx, response_text)
