"""forge_acp_server.py — ACP agent-side adapter: exposes the Nokido hub as an
Agent Client Protocol (ACP) agent over stdio (NDJSON, JSON-RPC 2.0).

Symmetric counterpart of tools/forge_acp_client.py (which drives external ACP
agents). This serves the inverse role: any ACP client (Zed, or Nokido's own
forge_acp_client in loopback) connects, runs initialize -> session/new ->
session/prompt, and the turn is answered by the Nokido brain. Missing ingress
side -> any ACP editor becomes a native Nokido client.

Stabilization goals (veille ACP 2026-06-21): #1 streaming chunks, #2 cancel +
bounded turn timeout always returns a StopReason, #3 in-band permission
handshake (works even for hook-less clients), #4 capability negotiation.

Wire = NDJSON, identical framing to forge_acp_client.py (loopback interop).
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

PROTOCOL_VERSION = 1

STOP_END_TURN = "end_turn"
STOP_MAX_TOKENS = "max_tokens"
STOP_MAX_TURN_REQUESTS = "max_turn_requests"
STOP_REFUSAL = "refusal"
STOP_CANCELLED = "cancelled"

TURN_TIMEOUT_S = 120
_HUB = os.environ.get("LAFORGE_HUB_URL") or (
    "http://127.0.0.1:" + os.environ.get("LAFORGE_HUB_PORT", "8766"))


def _texts(content):
    """Extract plain-text fragments from an ACP content value (str, content
    block dict, or list of such). Mirrors forge_acp_client._texts."""
    out = []
    if content is None:
        return out
    if isinstance(content, str):
        return [content]
    if isinstance(content, dict):
        t = content.get("text")
        if isinstance(t, str):
            out.append(t)
        return out
    if isinstance(content, list):
        for item in content:
            out.extend(_texts(item))
    return out


class TurnContext:
    """Handed to the brain for one prompt turn. The brain expresses output and
    side-effects ONLY through these callbacks; it never writes the wire."""

    def __init__(self, server, session_id, prompt_text):
        self.server = server
        self.session_id = session_id
        self.prompt_text = prompt_text

    def emit_chunk(self, text):
        self.server.emit_message_chunk(self.session_id, text)

    def emit_thought(self, text):
        self.server.emit_update(
            self.session_id,
            {"sessionUpdate": "agent_thought_chunk",
             "content": {"type": "text", "text": text}},
        )

    def cancelled(self):
        return self.server.is_cancelled(self.session_id)

    def request_permission(self, title, tool_kind="other", tool_call_id=None):
        """In-band permission handshake (#3). Returns True if allowed.

        `tool_call_id` : l'identifiant DEJA annonce par `tool_call()`. Le passer
        est ce qui garde la chaine `annonce -> permission -> effet` sur une seule
        identite (cf. NR test_acp_toolcallid_canonique_nr).
        """
        return self.server.request_permission(self.session_id, title, tool_kind,
                                              tool_call_id=tool_call_id)

    def tool_call(self, title, kind="other"):
        """Announce a tool call (status pending). Returns the toolCallId so the
        brain can report progress via tool_update()."""
        tcid = self.server._next_rid()
        self.server.emit_tool_call(self.session_id, tcid, title, kind)
        return tcid

    def tool_update(self, tool_call_id, status, content=None):
        """Report tool progress: in_progress | completed | cancelled | failed."""
        self.server.emit_tool_call_update(self.session_id, tool_call_id, status, content)


class EchoBrain:
    """No-hub brain: streams the prompt back, demonstrates cancel + permission.
    A prompt beginning with '!' simulates a gated action and triggers a
    session/request_permission round-trip before echoing."""

    def respond(self, ctx):
        text = ctx.prompt_text
        if text.startswith("!"):
            action = text[1:]
            # full ACP tool lifecycle wired to the permission handshake (#2+#3):
            # pending -> request_permission -> in_progress -> completed/cancelled.
            tcid = ctx.tool_call(f"gated action: {action!r}", kind="execute")
            allowed = ctx.request_permission(f"gated action: {action!r}",
                                             tool_kind="execute",
                                             tool_call_id=tcid)
            if not allowed:
                ctx.tool_update(tcid, "cancelled")
                ctx.emit_chunk("[permission refused -- action skipped]")
                return STOP_END_TURN
            ctx.tool_update(tcid, "in_progress")
            # a real brain would run the action here via a governed road
            # (forge run / governed_edit) and feed the result back to the model.
            ctx.tool_update(tcid, "completed",
                            content=[{"type": "content",
                                      "content": {"type": "text",
                                                  "text": f"ran: {action}"}}])
            text = action
        for word in text.split(" "):
            if ctx.cancelled():
                return STOP_CANCELLED
            ctx.emit_chunk(word + " ")
            time.sleep(0.01)
        return STOP_END_TURN


class HubBrain:
    """Routes the turn to the governed in-process ask pipeline
    (forge_agent_proxy.ask: firewall pre/post + thread + tracked usage).
    Sovereign-by-default provider (ollama); override via ACP_BRAIN_PROVIDER
    (e.g. router_local / router_cascade / groq). Requires app/ on PYTHONPATH
    (set by the launch wrapper). Streaming is approximated by chunking the full
    reply; true SSE streaming is a follow-up."""

    PROVIDER = os.environ.get("ACP_BRAIN_PROVIDER", "ollama")

    def respond(self, ctx):
        try:
            import asyncio
            from nokido_agent.app import forge_agent_proxy as proxy
            res = asyncio.run(proxy.ask(
                self.PROVIDER, ctx.prompt_text, rag_context=True,
                timeout=int(float(os.environ.get("ACP_BRAIN_TIMEOUT", "120")))))
        except Exception as exc:  # noqa: BLE001
            ctx.emit_chunk(f"[hub ask error: {exc}]")
            return STOP_REFUSAL
        if not res or not res.get("ok"):
            ctx.emit_chunk("[hub ask: " + str((res or {}).get("error", "no response")) + "]")
            return STOP_REFUSAL
        txt = res.get("text") or ""
        if ctx.cancelled():
            return STOP_CANCELLED
        buf = ""
        for ch in txt:
            if ctx.cancelled():
                return STOP_CANCELLED
            buf += ch
            if ch in ".\n!?" and len(buf) > 40:
                ctx.emit_chunk(buf)
                buf = ""
        if buf:
            ctx.emit_chunk(buf)
        return STOP_END_TURN


class StreamingBrain:
    """Governed progressive delivery: routes through forge_agent_proxy.ask
    (post_flight firewall applied to the COMPLETE response) then emits it
    word-by-word for a streamy feel. NOTE: true per-token SSE is intentionally
    NOT supported -- Nokido governance forbids un-scanned streaming egress (the
    governed_edit tripwire blocks the streaming flag; post_flight needs the full
    text). See docs/ACP_INGRESS.md."""

    PROVIDER = os.environ.get("ACP_BRAIN_PROVIDER", "ollama")

    def respond(self, ctx):
        try:
            import asyncio
            from nokido_agent.app import forge_agent_proxy as proxy
            res = asyncio.run(proxy.ask(
                self.PROVIDER, ctx.prompt_text, rag_context=True,
                timeout=int(float(os.environ.get("ACP_BRAIN_TIMEOUT", "120")))))
        except Exception as exc:  # noqa: BLE001
            ctx.emit_chunk(f"[stream error: {exc}]")
            return STOP_REFUSAL
        if not res or not res.get("ok"):
            ctx.emit_chunk("[hub ask: " + str((res or {}).get("error", "no response")) + "]")
            return STOP_REFUSAL
        for word in (res.get("text") or "").split(" "):
            if ctx.cancelled():
                return STOP_CANCELLED
            ctx.emit_chunk(word + " ")
        return STOP_END_TURN


def _default_brain():
    """Echo by default; opt into the hub-backed brain with ACP_BRAIN=hub
    (the launch wrapper sets it + PYTHONPATH)."""
    if os.environ.get("ACP_BRAIN", "echo").lower() == "hub":
        return HubBrain()
    return EchoBrain()


def _stdout_writer(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


class _Session:
    def __init__(self, sid, cwd):
        self.id = sid
        self.cwd = cwd
        self.cancel = threading.Event()


class ACPServer:
    """ACP agent over stdio."""

    def __init__(self, brain=None, writer=None):
        self.brain = brain or _default_brain()
        self._writer = writer or _stdout_writer
        self._sessions = {}
        self._wlock = threading.Lock()
        self._sid_seq = 0
        self._rid_seq = 0
        self._pending = {}
        self._turns = []

    def _log(self, msg):
        sys.stderr.write(f"[acp_server] {msg}\n")
        sys.stderr.flush()

    def _send(self, obj):
        with self._wlock:
            self._writer(json.dumps(obj, ensure_ascii=False))

    def _reply(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result if result is not None else {}
        self._send(msg)

    def _notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _next_rid(self):
        self._rid_seq += 1
        return f"s{self._rid_seq}"

    def emit_update(self, sid, update):
        self._notify("session/update", {"sessionId": sid, "update": update})

    def emit_message_chunk(self, sid, text):
        self.emit_update(sid, {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        })

    def emit_tool_call(self, sid, tool_call_id, title, kind, status="pending"):
        self.emit_update(sid, {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_call_id,
            "title": title,
            "kind": kind,
            "status": status,
        })

    def emit_tool_call_update(self, sid, tool_call_id, status, content=None):
        upd = {"sessionUpdate": "tool_call_update",
               "toolCallId": tool_call_id, "status": status}
        if content is not None:
            upd["content"] = content
        self.emit_update(sid, upd)

    def is_cancelled(self, sid):
        s = self._sessions.get(sid)
        return bool(s and s.cancel.is_set())

    def request_permission(self, sid, title, tool_kind="other", tool_call_id=None):
        """Demande l'autorisation d'un appel d'outil DEJA annonce.

        DEUX IDENTITES DISTINCTES, et c'est tout l'objet du correctif du
        2026-09-12 : `rid` identifie la REQUETE JSON-RPC (correlation de la
        reponse), `tool_call_id` identifie l'APPEL D'OUTIL. Avant, le meme
        compteur servait aux deux : l'outil annonce `s1` etait autorise sous
        `s2`, et les mises a jour repartaient sur `s1`. Cote client, la demande
        ne se rattachait a aucun appel affiche, et l'appel autorise n'etait
        jamais mis a jour — on pouvait autoriser A et rapporter B.

        `tool_call_id=None` retombe sur `rid` pour ne pas casser un appelant qui
        demanderait une permission sans annonce prealable.
        """
        rid = self._next_rid()
        box = queue.Queue(maxsize=1)
        self._pending[rid] = box
        self._send({
            "jsonrpc": "2.0", "id": rid, "method": "session/request_permission",
            "params": {
                "sessionId": sid,
                "toolCall": {"toolCallId": tool_call_id or rid, "title": title,
                             "kind": tool_kind},
                "options": [
                    {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
                ],
            },
        })
        try:
            resp = box.get(timeout=TURN_TIMEOUT_S)
        except queue.Empty:
            return False
        finally:
            self._pending.pop(rid, None)
        if "error" in resp:
            return False
        outcome = ((resp.get("result") or {}).get("outcome") or {})
        kind = outcome.get("outcome") or outcome.get("kind")
        return kind in ("selected", "allow", "allow_once", "allow_always")

    def _handle_request(self, obj):
        method = obj.get("method")
        rid = obj.get("id")
        params = obj.get("params") or {}
        if method == "initialize":
            client_pv = params.get("protocolVersion", PROTOCOL_VERSION)
            negotiated = min(int(client_pv or PROTOCOL_VERSION), PROTOCOL_VERSION)
            self._reply(rid, {
                "protocolVersion": negotiated,
                "agentCapabilities": {
                    "loadSession": False,
                    "promptCapabilities": {"image": False, "audio": False,
                                           "embeddedContext": True},
                },
                "agentInfo": {"name": "Nokido", "version": "acp-server-poc1"},
            })
        elif method == "authenticate":
            # REFUS EXPLICITE depuis le 2026-09-12 (audit adversarial).
            # Avant : `self._reply(rid, {})` — un `result` vide, que tout client
            # ACP peut lire comme « authentifie », alors qu'AUCUNE identite n'est
            # etablie et qu'`initialize` ne declare AUCUNE `authMethods`.
            # C'est une ceremonie de securite sans enforcement, et la confusion
            # exacte entre DECLARED et VERIFIED.
            #
            # L'asymetrie sautait aux yeux : `session/load` refuse deja en -32601
            # parce que `loadSession: false`. Meme raison ici, meme reponse.
            #
            # Ou vit la VRAIE authentification : au HANDSHAKE du transport WS
            # (jeton du coffre, `hmac.compare_digest`, 401 + WWW-Authenticate,
            # journal). En stdio, le client lance lui-meme le processus : il n'y
            # a rien a authentifier. Dans les deux cas, un succes ici serait faux.
            #
            # Le jour ou des `authMethods` seront declarees dans `initialize`,
            # cette branche doit les VERIFIER — pas revenir a `{}`.
            # Fige par tests/nr/test_acp_authenticate_sans_ceremonie_nr.py
            self._reply(rid, error={
                "code": -32601,
                "message": ("authenticate not supported: no authMethods declared "
                            "(stdio needs none; ws authenticates at handshake)"),
            })
        elif method == "session/new":
            self._sid_seq += 1
            sid = f"nokido-{self._sid_seq}"
            self._sessions[sid] = _Session(sid, params.get("cwd", ""))
            self._reply(rid, {"sessionId": sid})
        elif method == "session/load":
            self._reply(rid, error={"code": -32601,
                                    "message": "loadSession not supported"})
        elif method == "session/set_mode":
            self._reply(rid, {})
        elif method == "session/prompt":
            self._start_turn(rid, params)
        else:
            self._reply(rid, error={"code": -32601,
                                    "message": f"unsupported method: {method}"})

    def _handle_notification(self, obj):
        method = obj.get("method")
        params = obj.get("params") or {}
        if method == "session/cancel":
            s = self._sessions.get(params.get("sessionId"))
            if s:
                s.cancel.set()

    def _start_turn(self, rid, params):
        sid = params.get("sessionId")
        s = self._sessions.get(sid)
        if not s:
            self._reply(rid, error={"code": -32602,
                                    "message": f"unknown session: {sid}"})
            return
        s.cancel.clear()
        text = "".join(_texts(params.get("prompt")))

        def _run():
            ctx = TurnContext(self, sid, text)
            stop = STOP_END_TURN
            deadline = time.time() + TURN_TIMEOUT_S
            try:
                holder = {}

                def _call():
                    holder["r"] = self.brain.respond(ctx)

                worker = threading.Thread(target=_call, daemon=True)
                worker.start()
                while worker.is_alive():
                    if time.time() > deadline:
                        s.cancel.set()
                        stop = STOP_MAX_TURN_REQUESTS
                        break
                    worker.join(timeout=0.1)
                if "r" in holder:
                    stop = holder["r"] or STOP_END_TURN
                elif s.cancel.is_set():
                    stop = STOP_CANCELLED
            except Exception as exc:  # noqa: BLE001
                self._log(f"turn error: {exc}")
                stop = STOP_REFUSAL
            self._reply(rid, {"stopReason": stop})

        t = threading.Thread(target=_run, daemon=True)
        self._turns.append(t)
        t.start()

    def handle_obj(self, obj):
        if "method" in obj:
            if obj.get("id") is None:
                self._handle_notification(obj)
            else:
                self._handle_request(obj)
        elif "id" in obj and ("result" in obj or "error" in obj):
            box = self._pending.get(obj["id"])
            if box is not None:
                try:
                    box.put_nowait(obj)
                except queue.Full:
                    pass

    def handle_line(self, line):
        line = line.strip()
        if not line:
            return
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            self._log("non-json: " + line[:200])
            return
        self.handle_obj(obj)

    def serve(self):
        """stdio transport: one line of NDJSON per message on stdin/stdout."""
        for line in sys.stdin:
            self.handle_line(line)


def _bootstrap_syspath():
    """Make app/ importable so HubBrain can reach forge_agent_proxy without the
    caller having to set PYTHONPATH."""
    here = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(os.path.dirname(here), "app")
    if os.path.isdir(app_dir) and app_dir not in sys.path:
        sys.path.append(app_dir)


def _select_brain(argv):
    if "--echo" in argv:
        return EchoBrain()
    if "--brain" in argv:
        i = argv.index("--brain")
        if i + 1 < len(argv):
            choice = argv[i + 1]
            if choice == "hub":
                return HubBrain()
            if choice == "stream":
                return StreamingBrain()
    return _default_brain()


def _acp_journal(evenement: str, **champs) -> None:
    """Trace TOUTE decision d'admission. Sans elle, une session ouverte par un
    tiers ne laisse AUCUNE empreinte — mesure 2026-09-04 : `logger` x0 dans ce
    fichier, on n'aurait pas su qu'un acces avait eu lieu.

    Le jeton n'est JAMAIS journalise : seulement son empreinte courte.
    """
    import logging
    from pathlib import Path as _Path  # PAS importe au niveau module (verifie)
    _lg = logging.getLogger("acp.ws")
    if not _lg.handlers:
        try:
            _p = _Path(__file__).resolve().parent.parent / "logs" / "acp_ws.log"
            _p.parent.mkdir(parents=True, exist_ok=True)
            _h = logging.FileHandler(_p, encoding="utf-8")
            _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            _lg.addHandler(_h)
            _lg.setLevel(logging.INFO)
        except OSError:
            # Journal indisponible -> on le DIT sur stderr plutot que de se taire.
            print("[acp] journal indisponible", file=sys.stderr, flush=True)
    detail = " ".join("%s=%s" % (k, v) for k, v in champs.items())
    try:
        _lg.info("%s %s", evenement, detail)
    except Exception:  # noqa: BLE001  # muet-ok : journaliser ne doit rien casser
        pass
    print("[acp] %s %s" % (evenement, detail), file=sys.stderr, flush=True)


def _acp_secret_attendu():
    """(jeton, source) depuis le COFFRE. (None, raison) si illisible.

    FAIL-CLOSED : un coffre illisible rend None, et l'appelant REFUSE. Ouvrir
    l'acces parce qu'on n'a pas pu lire le secret serait exactement le defaut
    `sandbox=<inconnu>` du 2026-09-01, ou une entree invalide obtenait PLUS de
    droits qu'une valide.
    """
    from pathlib import Path as _Path  # idem : import LOCAL, verifie avant usage
    try:
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        return None, "coffre indisponible (%s)" % type(e).__name__
    for cle in ("FORGE_ACP_TOKEN", "FORGE_MCP_TOKEN"):
        try:
            v = get_secret(cle)
        except Exception:  # noqa: BLE001  # muet-ok : on essaie la clef suivante
            continue
        if v and v.strip():
            return v.strip(), cle
    return None, "aucun jeton au coffre (FORGE_ACP_TOKEN / FORGE_MCP_TOKEN)"


def _acp_admission(request):
    """(ok, agent, motif). L'identite vient du JETON, jamais de l'en-tete seul.

    Mesure 2026-08-10 : un `X-Agent-Name` non adosse a un jeton apparie DEGRADE
    l'identite au lieu de l'etablir. Ici le nom n'est retenu QUE si le jeton est
    valide ; sinon l'appelant reste anonyme et se voit refuser.
    """
    import hmac

    attendu, source = _acp_secret_attendu()
    if not attendu:
        return False, None, "FAIL-CLOSED: %s" % source
    brut = request.headers.get("Authorization", "")
    presente = brut[7:].strip() if brut[:7].lower() == "bearer " else ""
    if not presente:
        return False, None, "aucun Bearer presente"
    if not hmac.compare_digest(presente, attendu):
        return False, None, "jeton invalide"
    agent = (request.headers.get("X-Agent-Name") or "").strip()[:40] or "anonyme-authentifie"
    return True, agent, "jeton %s accepte" % source


def serve_ws(host=None, port=None):
    """Remote ACP transport over WebSocket (aiohttp), AUTHENTIFIE.

    Durci le 2026-09-04. Avant : le handshake rendait 101 sans aucun credential
    et `session/new` accordait un `sessionId` — n'importe quel process local
    ouvrait une session sur le hub, sans trace. Trois manques cumules : pas
    d'authentification, pas d'identite d'appelant, pas de journal.

    Desormais : jeton du COFFRE exige au handshake, refus en 401 avec
    `WWW-Authenticate` (RFC 6750 / RFC 9110), identite portee par le jeton, et
    toute decision d'admission journalisee. Le bind reste sur la boucle locale.
    """
    import asyncio
    import secrets as _secrets
    from aiohttp import web, WSMsgType
    host = host or os.environ.get("ACP_WS_HOST", "127.0.0.1")
    port = int(port or os.environ.get("ACP_WS_PORT", "7782"))
    if host not in ("127.0.0.1", "::1", "localhost"):
        _acp_journal("BIND_NON_LOOPBACK", host=host,
                     avertissement="surface elargie au reseau")

    async def _handler(request):
        pair = request.remote or "?"
        ok, agent, motif = _acp_admission(request)
        if not ok:
            _acp_journal("REFUS", pair=pair, motif=motif)
            # RFC 6750 : un endpoint protege repond 401 + WWW-Authenticate.
            return web.Response(status=401, text='{"error":"unauthorized"}',
                                content_type="application/json",
                                headers={"WWW-Authenticate":
                                         'Bearer realm="nokido-acp"'})
        # Identifiant de connexion NON PREDICTIBLE : `nokido-1` etait incremental.
        conn_id = _secrets.token_hex(8)
        _acp_journal("ADMIS", pair=pair, agent=agent, conn=conn_id, motif=motif)
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        loop = asyncio.get_event_loop()

        def _writer(line):
            asyncio.run_coroutine_threadsafe(ws.send_str(line + "\n"), loop)

        srv = ACPServer(brain=_select_brain(sys.argv), writer=_writer)
        n = 0
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    for ln in msg.data.splitlines():
                        n += 1
                        srv.handle_line(ln)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            _acp_journal("FERMETURE", agent=agent, conn=conn_id, lignes=n)
        return ws

    app = web.Application()
    app.router.add_get("/acp", _handler)
    web.run_app(app, host=host, port=port)


def main():
    """Serve ACP. Default = stdio (spawned as agent subprocess by an ACP client,
    Zed or forge_acp_client). `--ws` = WebSocket daemon (remote transport, WIP).
    `--brain hub|stream` selects the governed brain; default EchoBrain unless
    ACP_BRAIN is set."""
    _bootstrap_syspath()
    if "--ws" in sys.argv:
        serve_ws()
        return
    ACPServer(brain=_select_brain(sys.argv)).serve()


if __name__ == "__main__":
    main()
