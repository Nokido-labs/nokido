"""
forge_cli_harness.py — generic unattended harness for arbitrary CLI processes.

Mined from relaydeck/relaydeck ("run vendor CLIs unattended in PTYs" as fleet
workers). Spawns ANY CLI, drives its stdin, reads its stdout headless, with a
lifecycle (start/send/read/read_until/alive/stop). Turns a non-protocol CLI into
a managed worker — complements forge_acp_server (which covers protocol/stdio-JSON
agents) and the supervisor (which manages long-lived services).

Backends (api-identical):
  - pipe   : subprocess pipes. Reliable, line-oriented CLIs. Default + tested.
  - pty    : pywinpty ConPTY (true terminal) for interactive TUIs (Claude Code,
             Codex, ...). Best-effort; selected with backend="pty" if pywinpty is
             present. Hardening (non-blocking reads, pyte screen render) = follow-up.

Anti-dup: app/forge_pty.py exposes a Textual TUI widget (PTYTerminal, needs
textual+pyte) for the *interactive* TUI — NOT a headless driver. This module is
the headless harness Nokido lacked.
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/runner : harness generique pour CLI non assistes"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

try:
    import winpty as _winpty  # pywinpty (ConPTY)
except Exception:  # noqa: BLE001
    _winpty = None


def kill_tree(pid):
    """Kill a process AND its children (Windows taskkill /T). terminate() kills
    only the parent -> CLI agents that spawn node/electron children orphan and
    wedge the caller. Best-effort."""
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_cli_harness.py', 46, exc_info=True)


class _PipeBackend:
    """subprocess pipes — line-oriented CLIs (no full TUI). stderr merged in."""

    def __init__(self, cmd, cwd=None, env=None, devnull=False):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.devnull = devnull
        self.proc = None
        self._q = queue.Queue()

    def start(self):
        _stdin = subprocess.DEVNULL if self.devnull else subprocess.PIPE
        self.proc = subprocess.Popen(
            self.cmd, cwd=self.cwd,
            env={**os.environ, **(self.env or {})},
            stdin=_stdin, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0)
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        try:
            while True:
                b = self.proc.stdout.read(1)
                if not b:
                    break
                self._q.put(b)
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_cli_harness.py', 77, exc_info=True)
        finally:
            self._q.put(None)

    def write(self, data):
        if not self.proc.stdin:
            return
        self.proc.stdin.write(data.encode("utf-8", "replace"))
        self.proc.stdin.flush()

    def close_stdin(self):
        try:
            if self.proc and self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_cli_harness.py', 92, exc_info=True)

    def read(self, timeout=0.5):
        out = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            try:
                b = self._q.get(timeout=max(0.0, end - time.time()))
            except queue.Empty:
                break
            if b is None:
                break
            out.extend(b)
        return out.decode("utf-8", "replace")

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                kill_tree(self.proc.pid)
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_cli_harness.py', 115, exc_info=True)


class _WinPtyBackend:
    """pywinpty ConPTY — true PTY for interactive TUIs. A reader thread -> queue
    turns pywinpty's blocking read() into a non-blocking read(timeout) for the
    caller (same model as the pipe backend)."""

    def __init__(self, cmd, cwd=None, env=None):
        self.cmdline = cmd if isinstance(cmd, str) else subprocess.list2cmdline(cmd)
        self.cwd = cwd
        self.env = env
        self.proc = None
        self._q = queue.Queue()

    def start(self):
        self.proc = _winpty.PtyProcess.spawn(
            self.cmdline, cwd=self.cwd, env={**os.environ, **(self.env or {})})
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        try:
            while self.proc.isalive():
                try:
                    chunk = self.proc.read(1024)
                except (EOFError, OSError):
                    break
                except Exception:  # noqa: BLE001
                    break
                if chunk:
                    self._q.put(chunk)
                else:
                    time.sleep(0.02)
        finally:
            self._q.put(None)

    def write(self, data):
        self.proc.write(data)

    def close_stdin(self):
        # ConPTY has no separable stdin EOF; no-op (interactive TUIs stay open).
        pass

    def read(self, timeout=0.5):
        out = []
        end = time.time() + timeout
        while time.time() < end:
            try:
                item = self._q.get(timeout=max(0.0, end - time.time()))
            except queue.Empty:
                break
            if item is None:
                break
            out.append(item)
        return "".join(out)

    def alive(self):
        return self.proc is not None and self.proc.isalive()

    def stop(self):
        try:
            if self.proc and self.proc.isalive():
                kill_tree(getattr(self.proc, "pid", None))
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_cli_harness.py', 180, exc_info=True)


class CliHarness:
    """Headless worker around an arbitrary CLI. backend='auto' (pipe) | 'pty'."""

    def __init__(self, cmd, cwd=None, env=None, backend="auto", stdin_devnull=False):
        self.cmd = cmd
        if backend == "pty" and _winpty is not None:
            self._b = _WinPtyBackend(cmd, cwd, env)
        else:
            self._b = _PipeBackend(cmd, cwd, env, devnull=stdin_devnull)
        self.backend = type(self._b).__name__
        self._raw = ""

    def start(self):
        self._b.start()
        return self

    def send(self, data, newline=True):
        if newline and not data.endswith("\n"):
            data += "\n"
        self._b.write(data)

    def send_eof(self):
        """Close stdin (EOF) — drives headless stdin-until-EOF tools (e.g.
        `codex exec -`). No-op on the PTY backend."""
        fn = getattr(self._b, "close_stdin", None)
        if fn:
            fn()

    def read(self, timeout=0.5):
        out = self._b.read(timeout)
        if out:
            self._raw += out
            if len(self._raw) > 200000:
                self._raw = self._raw[-200000:]
        return out

    def screen(self, cols=120, rows=40):
        """Render accumulated output as a clean terminal screen via pyte (strips
        ANSI/control codes) — for scraping TUI state. Falls back to raw tail if
        pyte is unavailable."""
        try:
            import pyte

            scr = pyte.Screen(cols, rows)
            st = pyte.Stream(scr)
            st.feed(self._raw)
            return "\n".join(line.rstrip() for line in scr.display).rstrip()
        except Exception:  # noqa: BLE001
            return self._raw[-(cols * rows):]

    def read_until(self, needle, timeout=10.0):
        buf = ""
        end = time.time() + timeout
        while time.time() < end:
            buf += self.read(0.3)  # via self.read() -> accumulates _raw for screen()
            if needle in buf:
                break
        return buf

    def alive(self):
        return self._b.alive()

    def stop(self):
        self._b.stop()


# `claude_api` = `claude -p` headless : le MEME binaire que `claude` -- ce n'est pas un autre programme, c'est une
# AUTRE IDENTITE (celle qui porte la cle API, voir _SECRETS_PAR_AGENT).
_BIN_REEL = {"claude_api": "claude"}


def agent_bin(name):
    """Resolve a known agent CLI binary by name (full path), mirroring how the
    forge providers locate them. Honors LAFORGE_<AGENT>_BIN overrides."""
    import glob
    import shutil
    name = (name or "").lower()
    reel = _BIN_REEL.get(name, name)   # `claude_api` parle au MEME binaire que `claude`
    envk = {"codex": "LAFORGE_CODEX_BIN", "claude": "LAFORGE_CLAUDE_BIN",
            "claude_api": "LAFORGE_CLAUDE_BIN",
            "gemini": "LAFORGE_GEMINI_BIN", "copilot": "LAFORGE_COPILOT_BIN",
            "vibe": "LAFORGE_VIBE_BIN"}.get(name)
    if envk and os.environ.get(envk):
        return os.environ[envk]
    if name == "vibe":
        home = os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~"))
        return os.path.abspath(os.path.join(home, ".local", "bin", "vibe.exe"))
    if name == "codex":
        local = os.environ.get("LOCALAPPDATA", "")
        pats = [os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe"),
                os.path.join(os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~")),
                             "AppData", "Local", "OpenAI", "Codex", "bin", "*", "codex.exe")]
        for pat in pats:
            for c in glob.glob(pat):
                return c
    return shutil.which(reel) or reel


# Identite MCP par agent (owner 16/10 : « il faut que vibe soit authentifie au mcp »). TABLE FIGEE : un job JSON
# (fichier de sandbox/, forgeable par tout processus local) ne nomme AUCUN secret ; c'est le harness qui associe un
# agent a SON jeton, lu au coffre au lancement et injecte au seul enfant -- jamais ecrit sur disque.
# `vibe` = l'executeur (VIBE_HEADLESS) ; `vibe_cli` = l'owner a la main par tools/nokido_vibe.py (VIBE_CLI) --
# deux identites distinctes au journal du hub, decision owner du 16/10. Table : variable d'environnement de l'enfant
# -> cle du coffre. L'executeur recoit aussi NOTRE cle Mistral (forme b, owner 16/10 : Codestral mesure 125 req/min),
# sous un nom DEDIE pour ne pas ecraser la cle propre de Vibe.
_SECRETS_PAR_AGENT = {
    # 9/11 (owner) : cle de PORTEE Vibe (« Nokido ») ; la cle Studio (MISTRAL_API_KEY) renvoie 402 pour Vibe.
    "vibe": {"FORGE_TOKEN_VIBE_HEADLESS": "FORGE_TOKEN_VIBE_HEADLESS", "NOKIDO_MISTRAL_API_KEY": "MISTRAL_VIBE_API_KEY"},
    "vibe_cli": {"FORGE_TOKEN_VIBE_CLI": "FORGE_TOKEN_VIBE_CLI"},
    # `claude_api` = `claude -p` headless, facture sur les CREDITS API de l'owner (owner 22/10). `claude` (pilotage
    # interactif, connexion Max) n'est PAS dans cette table : il ne recoit jamais de cle API.
    "claude_api": {"ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY_ORG",
                   "FORGE_TOKEN_CLAUDE_HEADLESS": "FORGE_TOKEN_CLAUDE_HEADLESS"},
}


# ---------------------------------------------------------------------------------------------------------------
# CLAUDE HEADLESS (`claude -p`) -- politique de facturation (owner 22/10)
# ---------------------------------------------------------------------------------------------------------------
# Sans cle API, `claude -p` retombe EN SILENCE sur la connexion Max de l'owner : un couloir de facturation non voulu.
# Le harness REFUSE alors de demarrer -- un DISABLED_BY_POLICY nomme, pas une panne -- SAUF repli EXPLICITE de
# l'owner (interrupteur versionne, reversible par un commit).
class SecretObligatoireAbsent(RuntimeError):
    """Un secret OBLIGATOIRE manque : le lancement est REFUSE, pas degrade."""


# Interrupteur OWNER versionne (config/ -- jamais sandbox/, que l'executeur peut ecrire) : `repli_connexion_max`
# autorise `claude -p` SANS cle, en repli sur la connexion Max. Absent, illisible ou faux = REFUS.
_CONFIG_CLAUDE_HEADLESS = Path(__file__).resolve().parent.parent / "config" / "claude_headless.json"


def jeton_mcp(agent) -> dict:
    """{variable: valeur} des secrets propres a `agent` (identite MCP, cle fournisseur), lus au coffre au moment de
    l'appel ; un secret absent n'est pas injecte -- jamais une valeur vide, jamais une valeur au journal."""
    table = _SECRETS_PAR_AGENT.get((agent or "").strip().lower()) or {}
    if not table:
        return {}
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("Nokido.Harness").warning(
            "[harness] coffre indisponible pour %s (%s) : lance SANS ses secrets (401 attendu)", agent, type(e).__name__)
        return {}
    env = {}
    for variable, cle in table.items():
        try:
            valeur = get_secret(cle)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("Nokido.Harness").warning(
                "[harness] secret %s illisible pour %s (%s) : non injecte", cle, agent, type(e).__name__)
            continue
        if valeur:
            env[variable] = valeur
    return env


def _agent_env(agent=None):
    """OAuth context: the agent CLIs read their login from the owner profile ; plus the agent's own MCP token."""
    home = os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~"))
    env = {"USERPROFILE": home, "HOME": home}
    env.update(jeton_mcp(agent))
    return env


def _interrupteur_headless(cle: str) -> bool:
    """Vrai SEULEMENT si l'interrupteur versionne `cle` vaut vrai. Fichier absent, illisible ou faux -> faux :
    UNKNOWN n'est pas OUI. Lecteur unique des deux interrupteurs (cliquet clones 31/10)."""
    try:
        cfg = json.loads(Path(_CONFIG_CLAUDE_HEADLESS).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(cfg, dict) and cfg.get(cle) is True


def _repli_connexion_max_autorise() -> bool:
    """Repli sur la connexion Max quand la cle API est ABSENTE (interrupteur `repli_connexion_max`)."""
    return _interrupteur_headless("repli_connexion_max")


def _connexion_max_forcee() -> bool:
    """Owner 30/10 (« oui en attendant ») : credit de la cle API epuise (« Credit balance is too low », job_bc5c454e)
    -> `claude -p` sur la connexion Max jusqu'au quota API du 01/11. Le repli `repli_connexion_max` ne joue que cle
    ABSENTE ; ici elle est presente mais vide. Interrupteur versionne, defaut faux : fichier absent ou illisible -> faux
    (UNKNOWN n'est pas OUI)."""
    return _interrupteur_headless("forcer_connexion_max")


def _verifier_cle_api_obligatoire(agent, env) -> None:
    """`claude_api` SANS cle API ne demarre PAS : sans elle, `claude -p` retomberait sur la connexion Max de
    l'owner (facturation non voulue). Le refus nomme la politique et son interrupteur : DISABLED_BY_POLICY,
    pas une panne. Aucun autre agent n'est concerne (le `claude` interactif ne recoit jamais de cle)."""
    if (agent or "").strip().lower() != "claude_api":
        return
    if (env or {}).get("ANTHROPIC_API_KEY"):
        return
    if _repli_connexion_max_autorise() or _connexion_max_forcee():
        return
    nom = Path(_CONFIG_CLAUDE_HEADLESS).name
    raise SecretObligatoireAbsent(
        "[harness] politique owner (DISABLED_BY_POLICY) : sans cle API, `claude -p` consommerait le quota Max de "
        "l'owner ; pour l'autoriser, passer repli_connexion_max a true dans %s." % nom)


def harness_for(agent, args=None, interactive=False, cwd=None, stdin_devnull=False,
                binaire=None, env_extra=None):
    """A CliHarness wired to launch a known agent CLI as a managed worker.
    interactive=True -> spawn the agent's TUI on a real ConPTY (drive via
    send/read/screen) -- this MUST run in the owner's interactive session for
    OAuth/console. Else spawn headless with `args` (caller drives).

    `binaire` : chemin du programme, quand l'appelant l'a DEJA resolu -- l'executeur et la
    facade headless KNOWENT le resoudre (`LAFORGE_AGY_BIN` n'est pas dans le PATH du compte de
    service). Sans ce parametre, c'est `agent_bin(agent)` qui repond.
    `env_extra` : variables EN PLUS de l'agent (config d'instance OpenCode, jeton propre a
    l'instance). Elles vont au SEUL ENFANT -- jamais dans l'environnement du lanceur, jamais un
    argument de ligne de commande."""
    env = _agent_env(agent)
    if (agent or "").strip().lower() == "claude_api" and _connexion_max_forcee():
        # la cle est retiree du SEUL enfant claude_api : `claude -p` lit alors la connexion Max du profil owner
        env.pop("ANTHROPIC_API_KEY", None)
    _verifier_cle_api_obligatoire(agent, env)
    for k, v in (env_extra or {}).items():
        if v is None:
            continue
        env[str(k)] = str(v)
    cmd = [binaire or agent_bin(agent)] + list(args or [])
    backend = "pty" if interactive else "auto"
    return CliHarness(cmd, cwd=cwd or r"C:\tmp", env=env, backend=backend,
                      stdin_devnull=stdin_devnull)


def _selftest():
    """Drive a deterministic CLI (cmd.exe) headless, unattended."""
    h = CliHarness(["cmd", "/q", "/k"]).start()
    time.sleep(0.3)
    h.read(0.4)  # drain
    h.send("echo result_six_times_seven_42")
    out = h.read_until("_42", timeout=8)
    ok = "_42" in out
    h.send("exit")
    time.sleep(0.2)
    h.stop()
    print(json.dumps({"backend": h.backend, "ok": ok, "alive_after_stop": h.alive(),
                      "tail": out[-100:].replace("\r", " ").replace("\n", " ")},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
