"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_mcp_bridge
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
mcp_bridge.py — Bridge MCP STDIO pour Cline (CLINE_PLAN / CLINE_ACT)
Utilise mcp.server.Server + stdio_server comme nokido_mcp_server.py
Logging vers sandbox/bridge.log
"""

import asyncio, json, logging, os, sys, time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _APP_DIR.parent
_LOCK_DIR = _ROOT_DIR / "sandbox" / "locks"
_LOG_FILE = _ROOT_DIR / "sandbox" / "bridge.log"
_STATE = _ROOT_DIR / "sandbox" / "bridge_state.json"
_TASKS = _ROOT_DIR / "sandbox" / "tasks.json"

_LOCK_DIR.mkdir(parents=True, exist_ok=True)
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Logging fichier UNIQUEMENT — stdout = MCP stdio
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[RotatingFileHandler(str(_LOG_FILE), encoding="utf-8", maxBytes=10485760, backupCount=5)],
)
logger = logging.getLogger("bridge")
logger.info(f"=== démarrage agent={os.environ.get('LAFORGE_AGENT', '?')} ===")

from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

logger.info("mcp imports OK")

server = Server("LaForge-Bridge")
_AGENT = os.environ.get("LAFORGE_AGENT", os.environ.get("LAFORGE_MODE", "UNKNOWN"))

_MODE_INSTRUCTIONS = {
    "CLINE_PLAN": "Tu es l'architecte Nokido. Analyse, propose, planifie. Ne modifie pas les fichiers.",
    "CLINE_ACT": "Tu es l'exécuteur Nokido. Applique les changements, teste, livre via task_result.",
    "CLAUDE": "Tu es Claude, orchestrateur Nokido. Supervise et coordonne.",
}

# ── BridgeBuffer — tampon d'orchestration ────────────────────────────────────
import threading as _threading


class _BridgeBuffer:
    """Tampon niveau bridge pour fluidifier l'orchestration.

    3 rôles :
    - StateCache  : évite les I/O JSON répétitifs (_rs/_ws) via cache 500ms
    - NotifDedup  : déduplique + cap les pending_notifications (max 20)
    - WriteThrottle: rate-limit par fichier (1 write/500ms max)
    """

    NOTIF_CAP = 20  # max notifs en file
    CACHE_TTL = 0.5  # secondes — durée validité cache state
    WRITE_MIN_MS = 0.5  # délai minimum entre 2 writes du même fichier

    def __init__(self) -> None:
        self._lock = _threading.Lock()
        self._state_cache: dict = {}
        self._cache_ts: float = 0.0
        self._write_ts: dict = {}  # {filename: last_write_time}

    # ── StateCache ────────────────────────────────────────────────────────────

    def read_state(self) -> dict:
        """Lecture avec cache TTL — évite les reads JSON en rafale."""
        with self._lock:
            now = time.monotonic()
            if self._state_cache and (now - self._cache_ts) < self.CACHE_TTL:
                return dict(self._state_cache)
        try:
            s = json.loads(_STATE.read_text(encoding="utf-8"))
        except Exception:
            s = {}
        with self._lock:
            self._state_cache = s
            self._cache_ts = time.monotonic()
        return dict(s)

    def write_state(self, s: dict) -> None:
        """Écriture + invalidation cache."""
        try:
            _STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        with self._lock:
            self._state_cache = dict(s)
            self._cache_ts = time.monotonic()

    # ── NotifDedup ────────────────────────────────────────────────────────────

    def push_notif(self, s: dict, msg: str) -> dict:
        """Ajoute une notification dédupliquée, capée à NOTIF_CAP."""
        notifs: list = s.setdefault("pending_notifications", [])
        # Déduplication : ne pas répéter 2× le même message consécutif
        if notifs and notifs[-1] == msg:
            return s
        notifs.append(msg)
        # Cap FIFO — retire les plus anciennes
        if len(notifs) > self.NOTIF_CAP:
            s["pending_notifications"] = notifs[-self.NOTIF_CAP :]
        return s

    # ── WriteThrottle ─────────────────────────────────────────────────────────

    def throttle_write(self, filename: str) -> bool:
        """Retourne True si l'écriture est autorisée, False si trop rapide."""
        with self._lock:
            now = time.monotonic()
            last = self._write_ts.get(filename, 0.0)
            if (now - last) < self.WRITE_MIN_MS:
                return False
            self._write_ts[filename] = now
        return True


_buf = _BridgeBuffer()  # instance singleton


# ── Helpers ───────────────────────────────────────────────────────────────────


def _rs() -> dict:
    """Read state — via BridgeBuffer (cache 500ms)."""
    return _buf.read_state()


def _ws(s) -> None:
    """Write state — via BridgeBuffer (invalide cache)."""
    _buf.write_state(s)


def _rt() -> object:
    """Rt."""
    try:
        return json.loads(_TASKS.read_text(encoding="utf-8"))
    except Exception:
        return {"pending": []}


def _wt(t) -> None:
    """Wt.

    Args:
        t: Description.
    """
    try:
        _TASKS.write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _get_db() -> object:
    """Get db."""
    import sqlite3

    for db in [_ROOT_DIR / "RAG" / "embeddings.db"] + list((_ROOT_DIR / "RAG").glob("*.db")):
        if not db.exists():
            continue
        try:
            c = sqlite3.connect(str(db), timeout=10, check_same_thread=False)
            c.execute("SELECT 1 FROM rag_chunks LIMIT 1")
            c.row_factory = sqlite3.Row
            return c
        except Exception:
            pass
    return None


# ── Tools list ────────────────────────────────────────────────────────────────


@server.list_tools()
async def handle_list_tools() -> list:
    """Handle list tools."""
    logger.info("list_tools appelé")
    return [
        Tool(
            name="get_instructions",
            description="Retourne le rôle et les instructions pour cet agent",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="task_claim",
            description="Réclame la prochaine tâche en attente",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="task_result",
            description="Livre le résultat d'une tâche",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "result": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["task_id", "result"],
            },
        ),
        Tool(
            name="read_file",
            description="Lit un fichier du projet Nokido",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
        Tool(
            name="write_file",
            description="Écrit un fichier (Commit Guard auto sur forge_*.py)",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="auto_test",
            description="py_compile sur un fichier",
            inputSchema={"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]},
        ),
        Tool(
            name="notify",
            description="Envoie une notification à Nokido",
            inputSchema={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        ),
        Tool(
            name="poll_notifications",
            description="Lit les notifications en attente",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_mode",
            description="Mode actif et statuts agents",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="query_rag",
            description="Interroge le RAG Nokido",
            inputSchema={
                "type": "object",
                "properties": {"question": {"type": "string"}, "k": {"type": "integer"}},
                "required": ["question"],
            },
        ),
        Tool(
            name="index_result",
            description="Indexe un résultat dans le RAG",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "result": {"type": "string"}},
                "required": ["task_id", "result"],
            },
        ),
        Tool(name="get_status", description="État du bridge", inputSchema={"type": "object", "properties": {}}),
        Tool(
            name="heartbeat",
            description="Ping heartbeat + synchronisation inter-agents",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "progress": {"type": "integer"},
                    "task": {"type": "string"},
                },
            },
        ),
        Tool(
            name="heartbeat_read",
            description="Lit le heartbeat complet sans modifier",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="heartbeat_token",
            description="Acquiert ou libère le token d écriture exclusif",
            inputSchema={"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]},
        ),
        Tool(
            name="agy_run",
            description="Exécute une commande terminal via AGY",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["command", "explanation"],
            },
        ),
        Tool(
            name="agy_config",
            description="Lis/écris dans ~/.gemini/settings.json",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {},
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="agy_add_dir",
            description="Autorise un répertoire dans trustedWorkspaces",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    ]


# ── Tool dispatch ─────────────────────────────────────────────────────────────


@server.call_tool()
async def handle_call_tool(name, arguments) -> list:
    """Handle call tool.

    Args:
        name: Description.
        arguments: Description.
    """
    args = arguments or {}
    logger.info(f"call_tool: {name} args={str(args)[:80]}")

    try:
        if name == "get_instructions":
            s = _rs()
            mode = s.get("active_mode", "AUTO")
            instr = _MODE_INSTRUCTIONS.get(_AGENT, "Agent Nokido.")
            res = f"**Mode:** {_AGENT}\n\n{instr}\n\n**Mode actif:** {mode}"

        elif name == "task_claim":
            tks = _rt()
            pending = [t for t in tks.get("pending", []) if t.get("status") == "pending"]
            if not pending:
                res = "Aucune tâche en attente."
            else:
                t = pending[0]
                t["status"] = "in_progress"
                t["claimed_by"] = _AGENT
                t["claimed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                _wt(tks)
                res = f"**TACHE:** `{t['task_id']}`\n\n**Description:** {t['description']}\n\n**Fichiers:** `{t.get('files', '')}`"

        elif name == "task_result":
            tks = _rt()
            for t in tks.get("pending", []):
                if t["task_id"] == args.get("task_id", ""):
                    t["status"] = args.get("status", "done")
                    t["result"] = args.get("result", "")
                    t["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    break
            _wt(tks)
            s = _rs()
            s.setdefault("pending_notifications", []).append(
                f"[{_AGENT}] terminé: {args.get('task_id', '')} — {args.get('result', '')[:80]}"
            )
            _ws(s)
            res = f"✅ Résultat livré: `{args.get('task_id', '')}`"

        elif name == "read_file":
            p = _ROOT_DIR / args["path"]
            if not p.exists():
                res = f"Non trouvé: {args['path']}"
            else:
                res = p.read_text(encoding="utf-8", errors="replace")[:8000]

        elif name == "write_file":
            import py_compile, tempfile

            path = args["path"]
            content = args["content"]
            p = _ROOT_DIR / path
            is_forge = p.suffix == ".py" and (p.name.startswith("forge_") or p.name == "Nokido.py")
            if is_forge:
                with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as tf:
                    tf.write(content)
                    tfp = tf.name
                try:
                    py_compile.compile(tfp, doraise=True)
                    os.unlink(tfp)
                except py_compile.PyCompileError as e:
                    os.unlink(tfp)
                    res = f"❌ **COMMIT GUARD FAIL:** `{p.name}` L{e.lineno}: {e.msg}"
                    return [TextContent(type="text", text=res)]
            p.parent.mkdir(parents=True, exist_ok=True)
            # WriteThrottle — évite les écritures en rafale sur le même fichier
            if not _buf.throttle_write(p.name):
                res = f"⚡ `{path}` throttled (trop rapide) — réessaie dans 500ms"
            else:
                p.write_text(content, encoding="utf-8")
                s = _rs()
                s = _buf.push_notif(s, f"[{_AGENT}] fichier ecrit: {p.name} ({len(content)} chars)")
                _ws(s)
                res = f"✅ `{path}` écrit" + (" [Commit Guard OK]" if is_forge else "")

        elif name == "auto_test":
            import py_compile

            p = _ROOT_DIR / args["filepath"]
            if not p.exists():
                res = f"Non trouvé: {args['filepath']}"
            else:
                try:
                    py_compile.compile(str(p), doraise=True)
                    res = f"✅ `{args['filepath']}` — py_compile OK"
                except py_compile.PyCompileError as e:
                    res = f"❌ `{args['filepath']}` L{e.lineno}: {e.msg}"

        elif name == "notify":
            s = _rs()
            s = _buf.push_notif(s, f"[{_AGENT}] {args['message']}")
            _ws(s)
            res = "✅ Notification envoyée"

        elif name == "poll_notifications":
            s = _rs()
            notifs = s.pop("pending_notifications", [])
            if notifs:
                _ws(s)
            res = "\n".join(f"- {n}" for n in notifs) if notifs else "Aucune notification."

        elif name == "get_mode":
            s = _rs()
            lines = [f"**mode:** {s.get('active_mode', 'AUTO')}  **agent:** {_AGENT}"]
            for ag, info in s.get("agents", {}).items():
                lines.append(f"- {ag}: {info.get('status', '?')} {info.get('progress', 0)}%")
            res = "\n".join(lines)

        elif name == "query_rag":
            db = _get_db()
            if not db:
                res = "DB non disponible."
            else:
                words = [w for w in args["question"].split() if len(w) > 3][:5]
                if not words:
                    res = "Question trop courte."
                else:
                    like = " OR ".join(f"text LIKE '%{w}%'" for w in words)
                    rows = db.execute(
                        f"SELECT source,text FROM rag_chunks WHERE {like} LIMIT ?", (int(args.get("k", 5)),)
                    ).fetchall()
                    db.close()
                    res = "\n\n".join(f"**[{r['source']}]**\n{r['text'][:400]}" for r in rows) or "Aucun résultat."

        elif name == "index_result":
            db = _get_db()
            if not db:
                res = "DB non disponible."
            else:
                src = f"mcp_result:{_AGENT}:{args['task_id']}:{int(time.time())}"
                txt = f"[AGENT:{_AGENT}] [TASK:{args['task_id']}]\n{args['result']}"
                # 2026-09-12 : `INSERT OR REPLACE` SANS `id` ne remplace rien —
                # la clef primaire restant nulle, chaque appel ajoutait une ligne.
                # Et `txt[:4000]` coupait le resultat d'agent en silence.
                from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

                ecrire_chunk(db, src, "mcp_result", txt)
                db.commit()
                db.close()
                s = _rs()
                s = _buf.push_notif(s, f"[{_AGENT}] indexé: {args['task_id']}")
                _ws(s)
                res = f"✅ Indexé: `{src}`"

        elif name == "get_status":
            db = _get_db()
            db_ok = db is not None
            if db:
                db.close()
            s = _rs()
            res = f"**agent:** {_AGENT}\n**mode:** {s.get('active_mode', '?')}\n**db:** {'✅' if db_ok else '❌'}\n**log:** {_LOG_FILE}"

        elif name == "heartbeat":
            sys.path.insert(0, str(_APP_DIR))
            from nokido_agent.app.forge_heartbeat import beat as _hb_beat, collab_summary

            _hb_beat(
                agent=_AGENT,
                status=args.get("status", "idle"),
                progress=int(args.get("progress", 0)),
                task=args.get("task", ""),
            )
            res = collab_summary()

        elif name == "heartbeat_read":
            from nokido_agent.app.forge_heartbeat import collab_summary

            res = collab_summary()

        elif name == "heartbeat_token":
            from nokido_agent.app.forge_heartbeat import acquire_token, release_token

            action = args.get("action", "read")
            if action == "acquire":
                ok = acquire_token(_AGENT)
                res = f"✅ Token acquis par {_AGENT}" if ok else "❌ Token non disponible (timeout)"
            elif action == "release":
                release_token(_AGENT)
                res = f"✅ Token libéré par {_AGENT}"
            else:
                from nokido_agent.app.forge_heartbeat import read_heartbeat

                hb = read_heartbeat()
                res = f"Token holder: {hb.get('token_holder') or 'libre'}"

        elif name in ("agy_run", "agy_config", "agy_add_dir"):
            sys.path.insert(0, str(_APP_DIR))
            from nokido_agent.app.forge_mcp_registry import _reg

            res = await _reg.dispatch(name, args, _AGENT, 2)

        else:
            res = f"Outil inconnu: {name}"

        logger.info(f"call_tool {name} OK -> {str(res)[:60]}")
        return [TextContent(type="text", text=str(res))]

    except Exception as e:
        logger.error(f"call_tool {name} ERROR: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Erreur: {e}")]


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    # Idle watchdog — arrêt auto si inactif (Cline fermé)
    """Main."""
    try:
        from nokido_agent.app.forge_idle_watchdog import IdleWatchdog

        IdleWatchdog(os.environ.get("LAFORGE_AGENT", "NokidoMCP")).start()
    except Exception:
        pass

    logger.info("stdio_server démarrage")
    async with stdio_server() as (r, w):
        caps = server.get_capabilities(NotificationOptions(), {})
        await server.run(
            r, w, InitializationOptions(server_name="LaForge-Bridge", server_version="1.0.0", capabilities=caps)
        )


if __name__ == "__main__":
    import threading as _th, sys as _sys, os as _os, time as _tm

    # ── Au boot : tuer les anciens process Cline orphelins ───────────────
    try:
        import sys as _s2

        _s2.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        from nokido_agent.app.forge_heartbeat import kill_stale_agents as _ksa

        _killed = _ksa(stale_seconds=30)
        if _killed:
            import logging as _lg
            from logging.handlers import RotatingFileHandler

            _lg.getLogger("mcp_bridge").warning(f"[boot] Orphelins tués: {_killed}")
    except Exception:
        pass

    # ── Stdin watchdog — suicide si stdin fermé (VSCode/Cline fermé) ─────
    def _stdin_watch() -> None:
        """Détecte la fermeture de stdin par le parent (Cline/VSCode)."""
        try:
            while True:
                _tm.sleep(2)
                if _sys.stdin.closed:
                    break
                # Test EOF non-bloquant
                try:
                    chunk = _sys.stdin.buffer.read1(1) if hasattr(_sys.stdin, "buffer") else None
                    if chunk == b"":  # EOF
                        break
                except Exception:
                    break
        except Exception:
            pass
        logger.info("[mcp_bridge] stdin fermé — arrêt (parent Cline/VSCode disparu)")
        _os.kill(_os.getpid(), 15)  # SIGTERM

    _th.Thread(target=_stdin_watch, daemon=True, name="StdinWatch").start()

    logger.info("asyncio.run(main())")
    asyncio.run(main())
