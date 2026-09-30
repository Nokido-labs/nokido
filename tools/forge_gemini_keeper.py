#!/usr/bin/env python3
"""forge_gemini_keeper.py — tient le Gemini CLI WARM + endpoint local rapide.

Design : docs/gemini_keeper_design.md (panel groq/cerebras/mistral, convergence ACP).
Probleme : `gemini_cli` cold-start ~120s par appel > cap hub -> inutilisable inline. Solution :
warm 1x (init session), puis appels rapides via :7901. Mecanisme = ACP (`gemini --experimental-acp`,
JSON-RPC stdio) si dispo, REPL fallback sinon. SERIEL (1 session = lock FIFO).

Modes : --selftest (structurel, sans gemini) | --ask "<prompt>" (one-shot live) | (nu) = daemon :7901.
P1 PoC : ACP/REPL + /ask + /health + selftest. P2 (design) : SSE + OAuth-watch + warm-ping + service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
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
HEARTBEAT = ROOT / "sandbox" / "gemini_keeper.heartbeat"
PORT = 7901
_lock = threading.Lock()  # 1 session ACP = serialisation

# Invocation ALIGNEE sur forge_agent_proxy.GeminiCLI (hub) : BIN SYSTEM-profile npm + env OAuth clean-home.
# (bare `gemini` ne marche pas : service SYSTEM sans PATH + OAuth dans un HOME specifique.)
_BIN = os.environ.get("LAFORGE_GEMINI_BIN",
                      r"C:\WINDOWS\system32\config\systemprofile\AppData\Roaming\npm\gemini.cmd")
_CWD = r"C:\tmp"  # hors Nokido -> pas d'auto-load GEMINI.md (sinon mode agent au lieu de repondre)
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _gemini_env() -> dict:
    """env Gemini CLI (cf forge_agent_proxy) : HOME OAuth clean + trust workspace + SANS API key (force OAuth)."""
    clean = r"C:\tmp\gemini_home"
    home = clean if os.path.isdir(clean + r"\.gemini") else os.environ.get("LAFORGE_GEMINI_HOME", __import__("os").path.expanduser(r"~"))
    env = {**os.environ, "USERPROFILE": home, "HOME": home, "GEMINI_CLI_TRUST_WORKSPACE": "true"}
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "GEMINI_API_KEY_FREE"):
        env.pop(k, None)
    return env


# ── Helpers JSON-RPC PURS (testables sans subprocess) ───────────────────────
def _rpc(method: str, params: dict | None = None, rpc_id: int | None = None) -> dict:
    m = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        m["params"] = params
    if rpc_id is not None:
        m["id"] = rpc_id
    return m


def _build_init_rpc(rpc_id: int = 1) -> dict:
    return _rpc("initialize", {"protocolVersion": "1.0",
                               "clientCapabilities": {}}, rpc_id)


def _build_session_new_rpc(rpc_id: int = 2) -> dict:
    return _rpc("session/new", {"cwd": str(ROOT), "mcpServers": []}, rpc_id)


def _build_prompt_rpc(session_id: str, text: str, rpc_id: int) -> dict:
    return _rpc("session/prompt", {"sessionId": session_id,
                                   "prompt": [{"type": "text", "text": text}]}, rpc_id)


def _assemble_updates(updates: list[dict]) -> str:
    """Concatene le texte des notifications session/update (agent_message_chunk)."""
    out = []
    for u in updates:
        su = (u.get("params") or {}).get("sessionUpdate") or {}
        if su.get("type") in ("agent_message_chunk", "agent_message"):
            for c in su.get("content") or []:
                if isinstance(c, dict) and c.get("type") in (None, "text"):
                    out.append(c.get("text", ""))
    return "".join(out)


def _acp_available() -> bool:
    """Detecte si le CLI supporte ACP (--help liste experimental-acp). Best-effort (False si BIN inaccessible).
    NB : doit tourner en contexte ayant acces au BIN SYSTEM-profile (hub/SYSTEM ; sandbox = Acces refuse)."""
    if not os.path.exists(_BIN):
        return False
    try:
        r = subprocess.run([_BIN, "--help"], capture_output=True, text=True, timeout=30,
                           env=_gemini_env(), cwd=_CWD, creationflags=_NOWIN, encoding="utf-8", errors="replace")
        h = (r.stdout + r.stderr).lower()
        return "experimental-acp" in h or "--acp" in h
    except Exception:
        return False


def _acp_flag() -> str:
    """Le drapeau ACP que CE CLI comprend, lu dans SON aide — jamais suppose.

    Mesure 2026-09-18 sur gemini 0.51.0, ligne exacte de l'aide :
        --experimental-acp   Starts the agent in ACP mode (deprecated, use --acp instead)

    `deprecated` n'est pas `removed` : l'ancien drapeau marche encore, et c'est
    precisement pourquoi la dette est restee invisible. Le jour ou il disparait, le
    symptome sera « l'agent ne parle plus ACP » et non « une option a ete retiree » —
    on cherchera la panne du mauvais cote.

    On ne fige donc aucun des deux : on demande au binaire present. Repli sur l'ancien
    si l'aide est illisible, parce qu'il couvre les versions anterieures et qu'un repli
    qui se tait vaut mieux qu'un refus sur une version qu'on n'a pas su lire.
    """
    try:
        r = subprocess.run([_BIN, "--help"], capture_output=True, text=True, timeout=30,
                           env=_gemini_env(), cwd=_CWD, creationflags=_NOWIN,
                           encoding="utf-8", errors="replace")
        h = (r.stdout + r.stderr).lower()
        if "--acp" in h:
            return "--acp"
    except Exception:  # noqa: BLE001 — muet-ok : aide illisible -> repli documente
        pass
    return "--experimental-acp"


# ── Backend ACP (warm) ───────────────────────────────────────────────────────
class GeminiACP:
    """Session ACP persistante vers `gemini <drapeau ACP>` (stdio JSON-RPC). Warm 1x.

    Le drapeau est RESOLU depuis l'aide du binaire (`_acp_flag`), pas code en dur :
    `--experimental-acp` est deprecie depuis gemini 0.51.0 au profit de `--acp`.
    """

    def __init__(self):
        self.proc = subprocess.Popen(
            [_BIN, _acp_flag()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            env=_gemini_env(), cwd=_CWD, creationflags=_NOWIN, errors="replace")
        self.sid = None
        self._id = 0
        self._warm()

    def _send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _recv_result(self, rpc_id: int, timeout: float = 130.0):
        """Lit jusqu'au result de rpc_id ; accumule les notifications (session/update)."""
        updates, t0 = [], time.time()
        while time.time() - t0 < timeout:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("ACP stdout closed (CLI mort)")
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == rpc_id and ("result" in msg or "error" in msg):
                return msg, updates
            if msg.get("method") == "session/update":
                updates.append(msg)
        raise TimeoutError("ACP timeout")

    def _warm(self) -> None:
        i = self._next_id()
        self._send(_build_init_rpc(i))
        self._recv_result(i)
        i = self._next_id()
        self._send(_build_session_new_rpc(i))
        res, _ = self._recv_result(i)
        self.sid = (res.get("result") or {}).get("sessionId", "default")

    def prompt(self, text: str) -> str:
        i = self._next_id()
        self._send(_build_prompt_rpc(self.sid, text, i))
        _res, updates = self._recv_result(i)
        return _assemble_updates(updates)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


# ── Backend REPL (fallback) ──────────────────────────────────────────────────
class GeminiREPL:
    """Fallback : `gemini -p` one-shot par appel (PAS warm — degrade ; le vrai warm exige ACP).
    Conserve l'interface .prompt() pour que le keeper marche meme sans ACP."""

    def __init__(self):
        self.sid = "repl"

    def prompt(self, text: str) -> str:  # = invocation prouvee du hub (cold one-shot ; PAS de warm-gain)
        r = subprocess.run([_BIN, "-p", text[:30000]], capture_output=True, text=True, timeout=130,
                           env=_gemini_env(), cwd=_CWD, creationflags=_NOWIN, encoding="utf-8", errors="replace")
        return (r.stdout or r.stderr).strip()

    def alive(self) -> bool:
        return True

    def close(self) -> None:
        pass


# ── Keeper ────────────────────────────────────────────────────────────────────
class Keeper:
    def __init__(self):
        self.mode = "acp" if _acp_available() else "repl"
        self.backend = None
        self._spawn()

    def _spawn(self) -> None:
        try:
            self.backend = GeminiACP() if self.mode == "acp" else GeminiREPL()
        except Exception as e:
            print(f"[gemini_keeper] spawn {self.mode} KO ({e}) -> REPL", file=sys.stderr)
            self.mode, self.backend = "repl", GeminiREPL()

    def ask(self, text: str) -> dict:
        with _lock:  # serialisation (1 session)
            if self.backend is None or not self.backend.alive():
                self._spawn()
            try:
                return {"ok": True, "mode": self.mode, "text": self.backend.prompt(text)}
            except Exception as e:
                self._spawn()  # respawn sur erreur
                return {"ok": False, "mode": self.mode, "error": str(e)}


def _serve(keeper: "Keeper") -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencieux
            pass

        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"ok": True, "mode": keeper.mode,
                                 "alive": keeper.backend.alive() if keeper.backend else False})
            else:
                self._json(404, {"error": "use POST /ask or GET /health"})

        def do_POST(self):
            if self.path != "/ask":
                return self._json(404, {"error": "POST /ask"})
            n = int(self.headers.get("Content-Length", 0))
            try:
                prompt = json.loads(self.rfile.read(n) or b"{}").get("prompt", "")
            except Exception:
                return self._json(400, {"error": "bad json"})
            self._json(200, keeper.ask(prompt))

    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


def _code_identity() -> dict:
    """Identité du code RÉELLEMENT CHARGÉ (cf tools/forge_code_identity.py) — un keeper
    qui exécute un fichier périmé doit se voir dans son propre battement (mesuré 02/08)."""
    try:
        from nokido_agent.tools.forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le keeper
        return {}


def _beat(mode: str) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                         "pid": os.getpid(), "mode": mode, "port": PORT,
                                         **_code_identity()}))
    except Exception:
        pass


def _selftest() -> int:
    # helpers JSON-RPC PURS (sans gemini)
    r = _build_prompt_rpc("sess1", "hello", 5)
    assert r["method"] == "session/prompt" and r["params"]["sessionId"] == "sess1" and r["id"] == 5, r
    assert _build_init_rpc()["method"] == "initialize"
    ups = [
        {"method": "session/update", "params": {"sessionUpdate": {"type": "agent_message_chunk",
         "content": [{"type": "text", "text": "Hello "}]}}},
        {"method": "session/update", "params": {"sessionUpdate": {"type": "agent_message_chunk",
         "content": [{"type": "text", "text": "world"}]}}},
        {"method": "other", "params": {}},  # ignore
    ]
    assert _assemble_updates(ups) == "Hello world", _assemble_updates(ups)
    acp = _acp_available()
    print(f"GEMINI-KEEPER-P1 OK | JSON-RPC framing + session/update assembly OK | "
          f"acp_available={acp} -> mode={'acp' if acp else 'repl'} | (warm->fast = test live runtime hub)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--probe-acp" in sys.argv:  # gate du warm : a lancer en contexte SYSTEM (acces au BIN)
        print(json.dumps({"bin": _BIN, "bin_exists": os.path.exists(_BIN), "acp_available": _acp_available()}))
        raise SystemExit(0)
    if "--ask" in sys.argv:
        i = sys.argv.index("--ask")
        q = sys.argv[i + 1] if i + 1 < len(sys.argv) else "ping"
        k = Keeper()
        t0 = time.time()
        out = k.ask(q)
        out["latency_s"] = round(time.time() - t0, 1)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        k.backend.close()
        raise SystemExit(0)
    # daemon : warm + serve :7901 + heartbeat
    keeper = Keeper()
    threading.Thread(target=_serve, args=(keeper,), daemon=True).start()
    print(f"[gemini_keeper] warm ({keeper.mode}) + serving :{PORT}", file=sys.stderr)
    while True:
        _beat(keeper.mode)
        time.sleep(30)
