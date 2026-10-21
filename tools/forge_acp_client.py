#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_acp_client.py — Nokido comme CLIENT/HOST ACP : pilote un agent-CLI
externe parlant Agent Client Protocol (ex: `gemini --experimental-acp`).

Dual de forge_acp_adapter (qui fait de Nokido un agent ACP SERVI). Ici Nokido
SPAWN l'agent, fait le handshake initialize -> session/new -> session/prompt et
agrege le stream session/update. But : exposer Gemini CLI comme membre/provider
SOUVERAIN sans cle API (reutilise l'OAuth deja loggé du CLI) -> evite
provider=gemini (429 API) et le scrape de stdout interactif (lent, >120s cap).

Transport : JSON-RPC 2.0 newline-delimited sur stdin/stdout du subprocess.
Spec ACP (origine Zed) : protocolVersion ENTIER ; session/update.update porte un
discriminant STRING `sessionUpdate` ; l'agent peut RE-questionner le client
(session/request_permission, fs/read_text_file, fs/write_text_file). Client
TOLERANT : accepte aussi la forme objet {type:...} (celle de forge_acp_adapter)
pour selftest loopback SANS gemini.

Usage :
  LAFORGE_PYTHON forge_acp_client.py --selftest        # loopback vs forge_acp_adapter (pas besoin de gemini)
  LAFORGE_PYTHON forge_acp_client.py --probe           # handshake gemini seul (initialize) — contexte user/trusted
  LAFORGE_PYTHON forge_acp_client.py --ask "explique X"# spawn gemini, 1 prompt complet
  GEMINI_ACP_CMD='["gemini","--experimental-acp"]'     # override commande (JSON liste)

NB : `gemini` vit sur le PATH user (npm), absent du sandbox -> --ask/--probe a
lancer en contexte trusted/user. --selftest tourne partout (subprocess python).
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from nokido_opencode_web import dossier_appdata, trouver_opencode
except ImportError:
    try:
        from tools.nokido_opencode_web import dossier_appdata, trouver_opencode
    except ImportError:
        _tools = Path(__file__).resolve().parent
        if str(_tools) not in sys.path:
            sys.path.insert(0, str(_tools))
        try:
            from nokido_opencode_web import dossier_appdata, trouver_opencode
        except ImportError:
            dossier_appdata = None
            trouver_opencode = None

# DRAPEAU ACP : `--acp`, et non plus `--experimental-acp` (mesure 2026-09-18).
#
# Le CLI gemini installe ici est en 0.51.0 et son aide est explicite :
#     --experimental-acp   Starts the agent in ACP mode (deprecated, use --acp instead)
#
# `deprecated` n'est pas `removed` : l'ancien drapeau fonctionne encore, d'ou l'absence
# de panne visible jusqu'ici. Mais un depot qui appelle une option depreciee tombe le
# jour ou elle disparait, et ce jour-la le symptome sera « l'agent ne parle plus ACP »,
# pas « le drapeau a ete retire ». On migre donc AVANT, et on garde l'ancien en repli
# explicite pour les versions anterieures.
ACP_FLAG = "--acp"
ACP_FLAG_LEGACY = "--experimental-acp"

DEFAULT_CMD = ["gemini", ACP_FLAG]
PROTOCOL_VERSION = 1          # ACP/Zed : ENTIER (pas "1.0")
DEFAULT_TIMEOUT = 180.0

ACP_AGENTS = {
    "gemini": ["gemini", ACP_FLAG],
    "claude": ["claude-agent-acp"],
    "codex": ["codex-acp"],
    "opencode": ["opencode", "acp"],
}


def _resolve_cmd(agent: str = "gemini") -> list:
    """Commande agent : env GEMINI_ACP_CMD / OPENCODE_ACP_CMD (JSON liste)
    sinon binaire resolu via PATH ou appdata npm (gere .cmd/.ps1 npm Windows)."""
    if agent == "claude":
        env = os.environ.get("CLAUDE_ACP_CMD")
    elif agent == "codex":
        env = os.environ.get("CODEX_ACP_CMD")
    elif agent == "opencode":
        env = os.environ.get("OPENCODE_ACP_CMD")
    else:
        env = os.environ.get("GEMINI_ACP_CMD")
    if env:
        try:
            c = json.loads(env)
            if isinstance(c, list) and c:
                return c
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_acp_client.py', 96, exc_info=True)
    cmd = list(ACP_AGENTS.get(agent, DEFAULT_CMD))
    if agent == "opencode":
        exe = None
        if trouver_opencode is not None:
            appdata = dossier_appdata() if dossier_appdata is not None else None
            exe = trouver_opencode(appdata)
        if exe:
            cmd[0] = exe
        return cmd
    exe = shutil.which(cmd[0]) or shutil.which(cmd[0] + ".cmd")
    if exe:
        cmd[0] = exe
        return cmd
    # PAS DE REPLI SUR `LAFORGE_AGY_BIN` — et c'est une MESURE, pas un oubli.
    #
    # J'ai ecrit ce repli le 2026-09-18, en raisonnant que `--probe` echouait sur
    # « gemini introuvable [WinError 2] » la ou `forge_task_executor._delegate_to_agy`
    # lance le meme programme avec succes par un chemin ABSOLU. La deduction etait
    # fausse, et agy l'a dit lui-meme quand on le lui a demande :
    #
    #     agy 1.2.6 — drapeau `--experimental-acp` : ABSENT de son aide.
    #     Ce qu'il a a la place : `--continue` / `--conversation` (session persistante),
    #     `remote-control` (mode demon), `--input-format/--output-format stream-json`.
    #
    # `agy.exe` est le CLI Antigravity, pas le `gemini` npm officiel : meme MODELE,
    # binaire different. Replier dessus donnerait un chemin VALIDE pour un drapeau
    # INVALIDE -- c'est-a-dire une erreur obscure en plein handshake au lieu d'un
    # « introuvable » franc, ce qui est strictement pire. Un mecanisme branche sur une
    # capacite qui n'existe pas est une dette de cablage, jamais une securite.
    #
    # Pour piloter agy, le canal est `forge_task_executor` (delegation en mode agent),
    # pas ACP. Ce client reste valable pour un vrai agent ACP -- `gemini` npm, Zed --
    # et son echec doit rester LISIBLE.
    return cmd


def _texts(content) -> list:
    """Extrait les .text de content : str | block | [blocks]. Tolerant aux 2
    formes (Zed = bloc unique, adapter = liste de blocs)."""
    if content is None:
        return []
    if isinstance(content, str):
        return [content]
    if isinstance(content, dict):
        content = [content]
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") in (None, "text"):
            out.append(b.get("text", ""))
        elif isinstance(b, str):
            out.append(b)
    return [t for t in out if t]


class SessionBusyError(RuntimeError):
    """Refus client : un seul prompt a la fois par session (garde protocole OpenCode ACP)."""
    pass


def _journal_caviarde(on_log):
    """Enveloppe `on_log` : le stderr d'un agent dont l'environnement porte FORGE_TOKEN_<INSTANCE> passe par le
    redacteur EXISTANT avant tout journal (RED7, 19/10)."""
    try:
        from nokido_agent.tools.forge_log_redact import redact
    except ImportError:
        try:
            from forge_log_redact import redact
        except ImportError:
            def redact(t):  # muet-ok : redacteur absent DIT sur stderr, le journal reste utile
                sys.stderr.write("[acp] redacteur INDISPONIBLE -- journaux ACP en clair\n")
                return t
    return lambda m: on_log(redact(str(m)))


class SilenceACP(TimeoutError):
    """Aucun signe de vie de l'agent (ni notification, ni requete, ni reponse) depuis `silence_max` s. TimeoutError :
    le repli de modele de l'executeur reste declenche ; nomme « silence » pour ne pas se confondre avec la borne
    totale (19/10 : 25 min d'attente sur des sessions muettes)."""


class ACPClient:
    """Pilote un agent ACP via subprocess stdio. Thread lecteur -> queue inbox.
    Classe les messages : reponses (id+result/error), notifications (method, pas
    d'id), requetes agent->client (id+method : permission, fs/*)."""

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.cmd = cmd or _resolve_cmd(agent)
        self.agent = agent
        self.cwd = cwd or os.getcwd()
        self.on_log = _journal_caviarde(on_log or (lambda m: None))
        self.env = dict(env) if env is not None else None
        self.proc = None
        self._rpc_id = 0
        self._lock = threading.Lock()
        self._inbox = queue.Queue()
        self._chunks = []         # texte agent accumule pour le prompt courant
        self._alive = True
        self._busy_sessions = set()
        self.derniere_session = {}     # derniere reponse session/new (modeles disponibles)
        self.silence_max = None        # veille de silence des prompts (s) ; None = borne totale seule

    # ---- transport ----
    def start(self):
        run_cmd = list(self.cmd)
        if sys.platform == "win32" and run_cmd and \
                run_cmd[0].lower().endswith((".cmd", ".bat")):
            run_cmd = ["cmd", "/c"] + run_cmd  # CreateProcess ne lance pas .cmd direct
        popen_kwargs = dict(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1, text=True, encoding="utf-8",
            errors="replace", cwd=self.cwd,
        )
        if self.env is not None:
            proc_env = dict(os.environ)
            proc_env.update(self.env)
            popen_kwargs["env"] = proc_env
        self.proc = subprocess.Popen(run_cmd, **popen_kwargs)
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self):
        try:
            for line in self.proc.stderr:
                if line.strip():
                    self.on_log("[stderr] " + line.rstrip())
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_acp_client.py', 223, exc_info=True)

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._inbox.put(json.loads(line))
                except json.JSONDecodeError:
                    self.on_log("[non-json] " + line[:200])
        except Exception as exc:  # noqa: BLE001
            self.on_log(f"[read_loop] {exc}")
        finally:
            self._alive = False
            self._inbox.put(None)  # sentinelle EOF

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _next_id(self):
        with self._lock:
            self._rpc_id += 1
            return self._rpc_id

    # ---- requetes agent -> client ----
    def _handle_agent_request(self, obj):
        """L'agent re-questionne le client. Politique SOUVERAINE par defaut :
        permission -> refuse ; fs/read -> lit borne ; fs/write -> refuse."""
        method = obj.get("method")
        rid = obj.get("id")
        params = obj.get("params") or {}
        if method in ("session/request_permission", "request_permission"):
            self._send({"jsonrpc": "2.0", "id": rid,
                        "result": {"outcome": {"outcome": "cancelled"}}})
        elif method in ("fs/read_text_file", "readTextFile"):
            try:
                with open(params.get("path", ""), "r", encoding="utf-8") as f:
                    self._send({"jsonrpc": "2.0", "id": rid,
                                "result": {"content": f.read(200000)}})
            except Exception as exc:  # noqa: BLE001
                self._send({"jsonrpc": "2.0", "id": rid,
                            "error": {"code": -32000, "message": str(exc)}})
        elif method in ("fs/write_text_file", "writeTextFile"):
            self._send({"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32001, "message": "write refuse (souverain)"}})
        else:
            self._send({"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": f"unsupported: {method}"}})

    # ---- notifications ----
    def _handle_note(self, obj):
        if obj.get("method") != "session/update":
            return
        params = obj.get("params") or {}
        upd = params.get("update") or params.get("sessionUpdate") or {}
        if not isinstance(upd, dict):
            return
        kind = upd.get("sessionUpdate") or upd.get("type")
        # Seul le message agent final compte. On ignore agent_thought_chunk
        # (raisonnement), available_commands_update, plan, tool_call, etc.
        # `None` accepte la forme adapter loopback (type implicite = texte).
        if kind in ("agent_message_chunk", "agent_message", None):
            self._chunks.extend(_texts(upd.get("content")))

    # ---- pompe synchrone ----
    def _pump_until(self, target_id, timeout, silence_max=None):
        deadline = time.monotonic() + timeout
        signe = time.monotonic()      # dernier signe de vie de l'agent (tout message recu)
        while True:
            maintenant = time.monotonic()
            remaining = deadline - maintenant
            if remaining <= 0:
                raise TimeoutError(f"timeout en attente id={target_id}")
            if silence_max is not None and maintenant - signe > silence_max:
                raise SilenceACP(f"silence de l'agent depuis {maintenant - signe:.0f} s (veille {silence_max} s, "
                                 f"attente id={target_id})")
            try:
                obj = self._inbox.get(timeout=min(remaining, 1.0, silence_max or 1.0))
            except queue.Empty:
                if not self._alive and self.proc.poll() is not None:
                    raise RuntimeError("agent ACP termine prematurement")
                continue
            signe = time.monotonic()
            if obj is None:
                raise RuntimeError("flux agent ferme")
            rid = obj.get("id")
            if "method" in obj and rid is None:
                self._handle_note(obj)
            elif "method" in obj and rid is not None:
                self._handle_agent_request(obj)
            elif rid == target_id:
                return obj
            # autre reponse (id different) : ignoree (PoC = sync, 1 inflight)

    def request(self, method, params, timeout=DEFAULT_TIMEOUT):
        rid = self._next_id()
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        veille = self.silence_max if method == "session/prompt" else None
        resp = self._pump_until(rid, timeout, silence_max=veille)
        if "error" in resp:
            raise RuntimeError(f"{method} -> {resp['error']}")
        return resp.get("result", {})

    # ---- ACP haut niveau ----
    def initialize(self):
        return self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}},
            "clientInfo": {"name": "Nokido", "version": "acp-client-poc1"},
        }, timeout=30)

    def session_new(self):
        res = self.request("session/new", {"cwd": self.cwd, "mcpServers": []}, timeout=30)
        if isinstance(res, dict):
            self.derniere_session = res    # conserve : models.availableModels sert au choix du modele
        sid = res.get("sessionId") or res.get("session_id")
        if not sid:
            raise RuntimeError(f"session/new sans sessionId: {res}")
        return sid

    def is_session_busy(self, sid: str) -> bool:
        with self._lock:
            return sid in self._busy_sessions

    def prompt(self, sid, text, timeout=DEFAULT_TIMEOUT):
        with self._lock:
            if sid in self._busy_sessions:
                raise SessionBusyError(
                    f"session occupee ({sid}) : un seul prompt a la fois par session"
                )
            self._busy_sessions.add(sid)
        try:
            self._chunks = []
            res = self.request("session/prompt", {
                "sessionId": sid,
                "prompt": [{"type": "text", "text": text}],
            }, timeout=timeout)
            return {"text": "".join(self._chunks).strip(),
                    "stopReason": res.get("stopReason")}
        finally:
            with self._lock:
                self._busy_sessions.discard(sid)

    def close(self):
        with self._lock:
            self._busy_sessions.clear()
        try:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.close()
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_acp_client.py', 377, exc_info=True)
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_acp_client.py', 384, exc_info=True)


def ask(prompt_text, cmd=None, timeout=DEFAULT_TIMEOUT, on_log=None, agent="gemini", env=None):
    """One-shot : spawn agent ACP, initialize -> session -> prompt, renvoie
    {text, stopReason}. Reutilisable comme back-end provider `gemini_acp`."""
    cli = ACPClient(cmd=cmd, on_log=on_log, agent=agent, env=env)
    cli.start()
    try:
        cli.initialize()
        sid = cli.session_new()
        return cli.prompt(sid, prompt_text, timeout=timeout)
    finally:
        cli.close()


def _selftest() -> int:
    """Pilote forge_acp_adapter.py (serveur ACP Nokido) en loopback subprocess
    -> teste le handshake + prompt + routing cowork SANS gemini. Le texte de
    reponse depend du hub (peut etre une erreur si hub down) : on valide le
    PROTOCOLE (stopReason, sessionId, cowork), pas la qualite de la reponse."""
    here = os.path.dirname(os.path.abspath(__file__))
    adapter = os.path.join(here, "forge_acp_adapter.py")
    if not os.path.exists(adapter):
        print(json.dumps({"ok": False, "err": f"adapter introuvable: {adapter}"}))
        return 1
    logs = []
    cli = ACPClient(cmd=[sys.executable, adapter], on_log=logs.append)
    cli.start()
    try:
        init = cli.initialize()
        assert init.get("agentInfo", {}).get("name") == "Nokido", f"initialize KO: {init}"
        sid = cli.session_new()
        assert sid, "session/new KO"
        # r1 : round-trip protocole (stopReason). Le TEXTE depend du hub/ollama
        # (peut etre vide) -> ne pas l'asserter ici.
        r1 = cli.prompt(sid, "explique en une phrase ce qu'est Nokido", timeout=90)
        assert r1["stopReason"] == "end_turn", f"prompt stopReason KO: {r1}"
        # r2 : cowork = reponse LOCALE deterministe non-vide -> prouve que
        # l'accumulation du texte streamé (session/update) fonctionne.
        r2 = cli.prompt(sid, "cowork list", timeout=30)
        assert "[cowork]" in r2["text"], f"cowork routing/streaming KO: {r2}"
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "err": str(exc), "logs": logs[-6:]},
                         ensure_ascii=False, indent=2))
        return 1
    finally:
        cli.close()
    print(json.dumps({
        "ok": True, "agent": init.get("agentInfo"), "sessionId": sid,
        "ask_text": r1["text"][:160], "ask_stop": r1["stopReason"],
        "cowork": r2["text"][:120], "logs": logs[-4:],
    }, ensure_ascii=False, indent=2))
    return 0


def _probe(agent: str = "gemini") -> int:
    """Handshake reel contre `gemini --experimental-acp` : initialize seul ->
    montre protocolVersion/authMethods. Detecte gemini absent du PATH."""
    cli = ACPClient(on_log=lambda m: print(m, file=sys.stderr), agent=agent)
    print("cmd:", cli.cmd, file=sys.stderr)
    try:
        cli.start()
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "err": f"gemini introuvable: {exc}"}))
        return 1
    try:
        init = cli.initialize()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "err": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        cli.close()
    print(json.dumps({"ok": True, "initialize": init}, ensure_ascii=False, indent=2))
    return 0


def _raw() -> int:
    """Diagnostic : spawn l'agent, envoie un initialize minimal, et DUMP tout le
    trafic brut (JSON recu + lignes non-JSON + stderr) pendant 20s. Revele le
    format reel de l'agent (gemini) sans rien interpreter."""
    cli = ACPClient(on_log=lambda m: print("LOG ", m, file=sys.stderr, flush=True))
    print("cmd:", cli.cmd, file=sys.stderr, flush=True)
    try:
        cli.start()
    except Exception as exc:  # noqa: BLE001
        print("SPAWN-FAIL", exc, file=sys.stderr, flush=True)
        return 1
    cli._send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": 1,
        "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}},
        "clientInfo": {"name": "Nokido", "version": "raw"}}})
    print("SENT initialize", file=sys.stderr, flush=True)
    sent_new = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            obj = cli._inbox.get(timeout=1.0)
        except queue.Empty:
            if not cli._alive and cli.proc.poll() is not None:
                print("AGENT-EXITED rc=", cli.proc.poll(), file=sys.stderr, flush=True)
                break
            continue
        if obj is None:
            print("EOF (flux ferme) rc=", cli.proc.poll() if cli.proc else "?",
                  file=sys.stderr, flush=True)
            break
        print("RECV", json.dumps(obj, ensure_ascii=False), flush=True)
        # des reception de l'initialize -> tenter session/new (voir si deja loggé)
        if obj.get("id") == 1 and not sent_new:
            sent_new = True
            cli._send({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                       "params": {"cwd": cli.cwd, "mcpServers": []}})
            print("SENT session/new", file=sys.stderr, flush=True)
    cli.close()
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_acp_client.py', 506, exc_info=True)
    argv = sys.argv[1:]
    agent = "gemini"
    if "--agent" in argv:
        ai = argv.index("--agent")
        if ai + 1 < len(argv):
            agent = argv[ai + 1]
    if "--selftest" in argv:
        return _selftest()
    if "--probe" in argv:
        return _probe(agent)
    if "--raw" in argv:
        return _raw()
    if "--ask" in argv:
        i = argv.index("--ask")
        text = " ".join(argv[i + 1:]).strip()
        if not text:
            print("usage: --ask <prompt>", file=sys.stderr)
            return 2
        res = ask(text, on_log=lambda m: print(m, file=sys.stderr), agent=agent)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
