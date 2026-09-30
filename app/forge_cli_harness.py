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
        pass


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
            pass
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
            pass

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
            pass


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
            pass


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


def agent_bin(name):
    """Resolve a known agent CLI binary by name (full path), mirroring how the
    forge providers locate them. Honors LAFORGE_<AGENT>_BIN overrides."""
    import glob
    import shutil
    name = (name or "").lower()
    envk = {"codex": "LAFORGE_CODEX_BIN", "claude": "LAFORGE_CLAUDE_BIN",
            "gemini": "LAFORGE_GEMINI_BIN", "copilot": "LAFORGE_COPILOT_BIN"}.get(name)
    if envk and os.environ.get(envk):
        return os.environ[envk]
    if name == "codex":
        local = os.environ.get("LOCALAPPDATA", "")
        pats = [os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe"),
                os.path.join(os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~")),
                             "AppData", "Local", "OpenAI", "Codex", "bin", "*", "codex.exe")]
        for pat in pats:
            for c in glob.glob(pat):
                return c
    return shutil.which(name) or name


def _agent_env():
    """OAuth context: the agent CLIs read their login from the owner profile."""
    home = os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~"))
    return {"USERPROFILE": home, "HOME": home}


def harness_for(agent, args=None, interactive=False, cwd=None, stdin_devnull=False):
    """A CliHarness wired to launch a known agent CLI as a managed worker.
    interactive=True -> spawn the agent's TUI on a real ConPTY (drive via
    send/read/screen) -- this MUST run in the owner's interactive session for
    OAuth/console. Else spawn headless with `args` (caller drives)."""
    cmd = [agent_bin(agent)] + list(args or [])
    backend = "pty" if interactive else "auto"
    return CliHarness(cmd, cwd=cwd or r"C:\tmp", env=_agent_env(), backend=backend,
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
