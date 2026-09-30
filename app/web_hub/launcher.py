"""
app/web_hub/launcher.py - Supervisor des modules Nokido.

Lance/arrete/monitore de maniere SECURISEE les modules declares dans
le registre MODULES. Pas de shell=True, pas d input utilisateur qui
entre dans la commande : whitelist stricte.

FICHIERS RUNTIME :
  sandbox/run/<module>.pid          PID + start_time + cmd + port
  sandbox/logs/<module>.log         stdout/stderr combine
  sandbox/audit/launcher.log        audit append-only (start/stop)

CONCURRENCE : asyncio.Lock par module (evite double-start simultane).

DECOUVERTE d un process deja lance :
  - Lecture pidfile + verif PID vivant via psutil.Process(pid).is_running()
  - Double-check start_time (evite PID reutilise)

TUER un process :
  - SIGTERM (gracieux)
  - Attend jusqu a stop_timeout_s
  - SIGKILL si encore vivant
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("nokido.hub.launcher")

ROOT = Path(__file__).resolve().parent.parent.parent
RUN_DIR = ROOT / "sandbox" / "run"
LOG_DIR = ROOT / "sandbox" / "logs"
AUDIT_DIR = ROOT / "sandbox" / "audit"
AUDIT_LOG = AUDIT_DIR / "launcher.log"


# --------------------------------------------------------------------
# Registre de modules (whitelist)
# --------------------------------------------------------------------
@dataclass(frozen=True)
class ModuleSpec:
    """Declaration d un module lancable."""

    key: str  # identifiant unique (slug)
    title: str  # affichage UI
    description: str
    script: str  # chemin relatif au ROOT (ex: tools/xxx.py)
    port_env: Optional[str] = None  # env var qui force le port (optionnel)
    default_port: Optional[int] = None
    # Args supplementaires fixes (pas d input utilisateur)
    extra_args: tuple = ()
    # Env supplementaires fixes (whitelist stricte)
    extra_env: dict = field(default_factory=dict)
    stop_timeout_s: float = 5.0
    # api_managed=False : start/stop via API refuse (CLI only).
    # Utilise pour le hub (chicken-egg : ne peut pas se self-stop via API).
    api_managed: bool = True
    # open_path : URL sous le hub pour acceder au module via proxy.
    # None = pas de bouton "Ouvrir" dans l UI (module headless/CLI only).
    open_path: Optional[str] = None
    # watch=True : surveille par le watcher auto-restart (opt-in strict).
    # Requiert api_managed=True (sinon ignore pour proteger le hub).
    watch: bool = False
    # health_url : endpoint HTTP(S) verifie en plus du PID par le watcher.
    # >= 500 ou timeout = module considere down -> restart.
    # None = check PID seulement.
    health_url: Optional[str] = None
    # python : interpreteur a utiliser. None = celui du portail (`sys.executable`).
    # MESURE 2026-08-26 : le portail tourne sous `${PYTHON}` (miniforge3 base), et tout
    # module lance en heritait. Or l'env base porte un `transformers` ancien qui exige
    # `huggingface-hub<1.0` alors que 1.4.1 y est installe : tout import de la chaine
    # torch_geometric -> transformers y echoue. Le module `graph` mourait donc au
    # demarrage, pendant que son JUMEAU service (NokidoGraphExplorer :7474) tournait
    # parfaitement sous `${PY314}` — meme code, interpreteur different.
    # Le chemin est verifie a l'usage : s'il n'existe pas, on retombe sur sys.executable
    # en le DISANT, plutot que d'echouer sur un interpreteur fantome.
    python: Optional[str] = None


MODULES: dict[str, ModuleSpec] = {
    "tui_bridge": ModuleSpec(
        key="tui_bridge",
        title="TUI Bridge (xterm.js)",
        description="textual-serve wrap app/Nokido.py sur port 7440",
        script="tools/nokido_tui_bridge.py",
        port_env="LAFORGE_TUI_PORT",
        default_port=7440,
        stop_timeout_s=4.0,
        open_path="/tui/",
        watch=True,
        health_url="http://127.0.0.1:7440/",
    ),
    # recon/ctf non cables ici : leurs serveurs UI (ctf/tools/laforge_recon_server
    # :8000, ctf/tools/laforge_ctf_server) vivent dans /ctf/ GITIGNORE (corpus de
    # solveurs, hors depot). Exegol EST present (nwodtuhs/exegol:free). Le tracke
    # est du MCP HEADLESS (app/ctf/browser_mcp.py:8771,
    # app/forge_exegol_mcp_server.py:8770), pas des tuiles UI proxifiables.
    # Cablage reel = decision owner sur le corpus /ctf/ (cf session 2026-08-15).
    "graph": ModuleSpec(
        key="graph",
        title="Graph Studio",
        description="forge_graph_explorer, Cytoscape.js, port 7420",
        script="tools/nokido_graph_server.py",
        port_env="LAFORGE_GRAPH_PORT",
        default_port=7420,
        open_path="/graph/",
        watch=True,
        health_url="http://127.0.0.1:7420/",
        # Meme interpreteur que son jumeau service NokidoGraphExplorer (`${PY314}` dans
        # services.toml). Sous l'env base du portail, la chaine forge_graph_explorer ->
        # torch_geometric -> transformers echoue (huggingface-hub 1.4.1 vs borne <1.0).
        python="%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe",
    ),
    # opencode (decision owner 2026-09-25, choix A) : lance a la demande par le bouton
    # Demarrer, au nom de l'owner (le portail tourne en runAs=interactive), sur
    # 127.0.0.1:4096 et FERME sans mot de passe -- le contrat vit dans le wrapper.
    # open_path ABSOLU : l'interface d'opencode charge ses ressources en chemins
    # absolus, un proxy a prefixe sous :7400 la casserait (mesure du 25/09).
    # Ni watch ni service de boot : un agent de code ne redemarre pas tout seul.
    "opencode": ModuleSpec(
        key="opencode",
        title="opencode (agent de code)",
        description="opencode serve sur 127.0.0.1:4096, mot de passe du gestionnaire "
                    "d'identification de l'owner (utilisateur opencode)",
        script="tools/nokido_opencode_web.py",
        default_port=4096,
        stop_timeout_s=6.0,
        open_path="http://127.0.0.1:4096/",
    ),
    "hub": ModuleSpec(
        key="hub",
        title="Hub Web (FastAPI)",
        description="Hub principal + dashboard + proxy (port 7400)",
        script="tools/nokido_web_hub.py",
        port_env="LAFORGE_HUB_PORT",
        default_port=7400,
        stop_timeout_s=5.0,
        # CHICKEN-EGG : le hub heberge l API launcher, il ne peut pas se
        # stopper lui-meme via cette API sans se suicider. Start via CLI only.
        api_managed=False,
        open_path="/",
        # watch=False implicite ; de toute facon api_managed=False bloque.
    ),
}


# --------------------------------------------------------------------
# Helpers fichiers
# --------------------------------------------------------------------
def _ensure_dirs() -> None:
    for d in (RUN_DIR, LOG_DIR, AUDIT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _pidfile(mod: str) -> Path:
    return RUN_DIR / f"{mod}.pid"


def _logfile(mod: str) -> Path:
    return LOG_DIR / f"{mod}.log"


def _read_pidfile(mod: str) -> Optional[dict]:
    p = _pidfile(mod)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_pidfile(mod: str, pid: int, start_time: float, cmd: list, port: Optional[int]) -> None:
    _ensure_dirs()
    data = {"pid": pid, "start_time": start_time, "cmd": cmd, "port": port, "ts": int(time.time())}
    _pidfile(mod).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_pidfile(mod: str) -> None:
    try:
        _pidfile(mod).unlink()
    except OSError:
        pass


def _audit(action: str, mod: str, subject: str, extra: Optional[dict] = None) -> None:
    try:
        _ensure_dirs()
        line = json.dumps(
            {
                "ts": int(time.time()),
                "action": action,
                "module": mod,
                "subject": subject,
                "extra": extra or {},
            },
            ensure_ascii=False,
        )
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("audit log failed: %s", e)


# --------------------------------------------------------------------
# Detection process vivant (PID + start_time)
# --------------------------------------------------------------------
def _is_alive(pid: int, start_time_marker: float) -> bool:
    """Verifie que le PID est vivant ET que c est bien le meme process.

    On compare start_time car un PID peut etre reutilise apres crash.
    """
    try:
        import psutil
    except ImportError:
        # Fallback : juste un kill -0
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
    try:
        p = psutil.Process(pid)
        if not p.is_running():
            return False
        # psutil create_time est en epoch seconds ; on tolere 2s de skew
        return abs(p.create_time() - start_time_marker) < 2.0
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return False


# --------------------------------------------------------------------
# Etat d un module
# --------------------------------------------------------------------
def status(mod: str) -> dict:
    """Status actuel d un module.

    Retourne : {status: "running"|"stopped"|"stale", pid, port, uptime_s, log, ...}
    "stale" = pidfile present mais PID mort -> on peut .clear() et restart.
    """
    if mod not in MODULES:
        return {"error": "unknown module", "status": "unknown"}
    spec = MODULES[mod]
    pf = _read_pidfile(mod)
    base = {
        "module": mod,
        "title": spec.title,
        "description": spec.description,
        "port": spec.default_port,
        "log": str(_logfile(mod)),
        "open_path": spec.open_path,
        "api_managed": spec.api_managed,
        "watch": spec.watch,
        "health_url": spec.health_url,
    }
    if not pf:
        return {**base, "status": "stopped", "pid": None}
    alive = _is_alive(pf["pid"], pf["start_time"])
    if not alive:
        return {**base, "status": "stale", "pid": pf["pid"], "pidfile": str(_pidfile(mod))}
    return {
        **base,
        "status": "running",
        "pid": pf["pid"],
        "uptime_s": int(time.time() - pf["start_time"]),
        "port": pf.get("port", spec.default_port),
    }


def list_all() -> list[dict]:
    return [status(k) for k in MODULES]


# --------------------------------------------------------------------
# Start / Stop
# --------------------------------------------------------------------
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(mod: str) -> asyncio.Lock:
    if mod not in _locks:
        _locks[mod] = asyncio.Lock()
    return _locks[mod]


# Env whitelist : seules ces vars sont passees aux enfants depuis os.environ
_ENV_WHITELIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "USERNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
    "PYTHONUTF8",  # force UTF-8 stdout Windows
    # Auth : on NE propage PAS ADMIN_TOKEN aux subprocess (isolation)
    # sauf TUI bridge qui peut en avoir besoin via --dev ? Non : le TUI
    # est lance par le bridge qui le fork, il va herit du PATH+basics.
)


def _build_env(spec: ModuleSpec) -> dict:
    env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
    # FIX WINDOWS : force UTF-8 pour stdout/stderr des sous-process.
    # Evite les UnicodeEncodeError sur cp1252 quand un module print()
    # des emojis/unicode (cas reel : forge_graph_explorer print ⬡).
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    # Variables port si definies
    if spec.port_env and spec.default_port:
        env[spec.port_env] = str(spec.default_port)
    # Env specifique module
    for k, v in spec.extra_env.items():
        env[k] = str(v)
    return env


async def start(mod: str, subject: str = "admin") -> dict:
    """Lance un module. Idempotent : si deja running -> no-op.

    Retour : status() + {action: "started"|"already_running"|"error"}
    """
    if mod not in MODULES:
        raise ValueError(f"module inconnu : {mod}")
    spec = MODULES[mod]
    async with _get_lock(mod):
        # Deja lance ?
        st = status(mod)
        if st["status"] == "running":
            _audit("start.noop", mod, subject, {"reason": "already_running"})
            return {**st, "action": "already_running"}
        if st["status"] == "stale":
            # Clean le pidfile obsolete
            _clear_pidfile(mod)
            log.info("cleared stale pidfile for %s", mod)

        _ensure_dirs()
        script_abs = ROOT / spec.script
        if not script_abs.exists():
            raise RuntimeError(f"script introuvable : {script_abs}")

        # TROIS etats, jamais deux : interpreteur declare et present / declare mais
        # INTROUVABLE (on retombe sur celui du portail en le DISANT — un chemin fantome
        # ferait echouer le demarrage sans qu'on sache pourquoi) / non declare.
        _py = sys.executable
        if spec.python:
            if Path(spec.python).exists():
                _py = spec.python
            else:
                log.warning("module %s : interpreteur declare INTROUVABLE (%s) — "
                            "repli sur %s", mod, spec.python, sys.executable)
        cmd = [_py, str(script_abs), *spec.extra_args]
        env = _build_env(spec)

        log_path = _logfile(mod)
        # Ouvre en append pour pouvoir relancer sans perdre l historique
        log_fh = open(log_path, "ab")
        try:
            # Windows : DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP pour
            # pouvoir envoyer CTRL_BREAK au process group.
            kwargs = {
                "cwd": str(ROOT),
                "env": env,
                "stdout": log_fh,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "close_fds": True,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, **kwargs)
        finally:
            # fermeture cote parent : l enfant garde son fd
            try:
                log_fh.close()
            except OSError:
                pass

        # Recup start_time du process (via psutil si dispo, sinon "now")
        start_time = time.time()
        try:
            import psutil

            pt = psutil.Process(proc.pid).create_time()
            start_time = pt
        except Exception:
            pass

        _write_pidfile(mod, proc.pid, start_time, cmd, spec.default_port)
        _audit("start", mod, subject, {"pid": proc.pid, "port": spec.default_port})
        log.info("started %s pid=%s port=%s", mod, proc.pid, spec.default_port)

        # Laisse 1.5s au process pour mourir si crash apres import.
        # Certains modules crashent APRES l import (ex: UnicodeEncodeError
        # sur un print() emoji sous Windows cp1252) -> il faut assez de
        # temps pour que le process echoue proprement.
        await asyncio.sleep(1.5)
        final = status(mod)
        if final["status"] != "running":
            _clear_pidfile(mod)
            _audit("start.failed", mod, subject, {"after_status": final["status"]})
            return {**final, "action": "error", "detail": "process died at startup, see log"}
        return {**final, "action": "started"}


async def stop(mod: str, subject: str = "admin") -> dict:
    """Arrete un module. Gracieux (SIGTERM) puis force (SIGKILL)."""
    if mod not in MODULES:
        raise ValueError(f"module inconnu : {mod}")
    spec = MODULES[mod]
    async with _get_lock(mod):
        st = status(mod)
        if st["status"] in ("stopped", "unknown"):
            return {**st, "action": "already_stopped"}
        pf = _read_pidfile(mod)
        if not pf:
            return {**st, "action": "no_pidfile"}
        pid = pf["pid"]
        if st["status"] == "stale":
            _clear_pidfile(mod)
            _audit("stop.stale", mod, subject, {"pid": pid})
            return {**status(mod), "action": "cleared_stale"}

        # Gracieux
        try:
            if sys.platform == "win32":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as e:
            log.warning("kill SIGTERM %s: %s", pid, e)

        # Poll jusqu au timeout
        deadline = time.time() + spec.stop_timeout_s
        while time.time() < deadline:
            if not _is_alive(pid, pf["start_time"]):
                break
            await asyncio.sleep(0.15)

        if _is_alive(pid, pf["start_time"]):
            # Force
            try:
                if sys.platform == "win32":
                    # SIGKILL n existe pas sous Windows; os.kill envoie TerminateProcess
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            await asyncio.sleep(0.3)

        force_used = _is_alive(pid, pf["start_time"])
        _clear_pidfile(mod)
        _audit("stop", mod, subject, {"pid": pid, "forced": force_used})
        log.info("stopped %s pid=%s forced=%s", mod, pid, force_used)
        return {**status(mod), "action": "stopped", "forced": force_used, "pid": pid}


# --------------------------------------------------------------------
# Logs : lecture des N dernieres lignes du log d un module
# --------------------------------------------------------------------
def tail_log(mod: str, n: int = 100, max_bytes: int = 64 * 1024) -> str:
    """Retourne les n dernieres lignes du log, plafonne a max_bytes."""
    if mod not in MODULES:
        raise ValueError(f"module inconnu : {mod}")
    p = _logfile(mod)
    if not p.exists():
        return ""
    # Lecture depuis la fin, en binaire, decodee en ignore-errors
    size = p.stat().st_size
    start = max(0, size - max_bytes)
    with open(p, "rb") as f:
        f.seek(start)
        blob = f.read()
    text = blob.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # Si on a tronque le debut, on drop la 1ere ligne (partielle)
    if start > 0 and lines:
        lines = lines[1:]
    return "\n".join(lines[-n:])


# --------------------------------------------------------------------
# Helpers NR
# --------------------------------------------------------------------
def _reset_for_tests(tmp: Optional[Path] = None) -> None:
    global RUN_DIR, LOG_DIR, AUDIT_DIR, AUDIT_LOG, _locks
    _locks = {}
    if tmp is not None:
        RUN_DIR = tmp / "run"
        LOG_DIR = tmp / "logs"
        AUDIT_DIR = tmp / "audit"
        AUDIT_LOG = AUDIT_DIR / "launcher.log"


# --------------------------------------------------------------------
# Tail live (SSE-friendly async generator)
# --------------------------------------------------------------------
# Cap global : max de streams concurrents cote serveur (DoS protection)
MAX_CONCURRENT_STREAMS = 8
# Duree max d un stream : ceinture anti-fuite (1h)
STREAM_MAX_DURATION_S = 3600
# Batching : max bytes par event SSE (anti-flood client)
STREAM_CHUNK_MAX_BYTES = 16 * 1024
# Poll interval (stat fichier) en secondes
STREAM_POLL_S = 0.5
# Heartbeat periode : envoi d un ":ping" pour keep-alive intermediaires
STREAM_HEARTBEAT_S = 30.0

_active_streams = 0
_active_streams_lock = asyncio.Lock()


async def _acquire_stream_slot() -> bool:
    """Reserve un slot SSE ; retourne False si cap atteint."""
    global _active_streams
    async with _active_streams_lock:
        if _active_streams >= MAX_CONCURRENT_STREAMS:
            return False
        _active_streams += 1
        return True


async def _release_stream_slot() -> None:
    global _active_streams
    async with _active_streams_lock:
        _active_streams = max(0, _active_streams - 1)


async def tail_log_stream(mod: str, start_from_end: bool = True):
    """Async generator : yield de chunks de log pour SSE.

    Comportement type `tail -f` :
      - Si start_from_end : commence a la position actuelle du fichier
        (pas de flood historique a la connexion).
      - Poll toutes STREAM_POLL_S ; si le fichier grandit, yield le nouveau.
      - Detecte truncate/rotate (taille chute) : reprend depuis 0.
      - Heartbeat : yield ":ping" toutes STREAM_HEARTBEAT_S.
      - Duree max STREAM_MAX_DURATION_S puis arret propre.

    Cap global _active_streams geré par les helpers.

    Yield convention :
      - bytes non prefixes -> donnees log brutes
      - None            -> signal fin (rare, utile pour unit test)
    """
    if mod not in MODULES:
        raise ValueError(f"module inconnu : {mod}")
    path = _logfile(mod)

    # Reserve slot (non-blocking - refus immediat si full)
    got_slot = await _acquire_stream_slot()
    if not got_slot:
        raise RuntimeError(f"max streams atteint ({MAX_CONCURRENT_STREAMS}), reessayer plus tard")

    started = time.time()
    last_heartbeat = started
    # Position courante dans le fichier
    try:
        last_size = path.stat().st_size if path.exists() else 0
    except OSError:
        last_size = 0
    pos = last_size if start_from_end else 0

    try:
        while True:
            # Duree max : ceinture
            if time.time() - started > STREAM_MAX_DURATION_S:
                return

            # Heartbeat periodique
            now = time.time()
            if now - last_heartbeat > STREAM_HEARTBEAT_S:
                yield b""  # signal heartbeat ; le caller le traduit en ":ping\n\n"
                last_heartbeat = now

            # Verif fichier
            if not path.exists():
                await asyncio.sleep(STREAM_POLL_S)
                continue

            try:
                cur_size = path.stat().st_size
            except OSError:
                await asyncio.sleep(STREAM_POLL_S)
                continue

            # Rotate/truncate : taille chute -> on repart du debut
            if cur_size < pos:
                pos = 0

            # Nouvelles donnees ?
            if cur_size > pos:
                with open(path, "rb") as f:
                    f.seek(pos)
                    remaining = cur_size - pos
                    to_read = min(remaining, STREAM_CHUNK_MAX_BYTES)
                    chunk = f.read(to_read)
                    pos += len(chunk)
                if chunk:
                    yield chunk
                    # On relit tout de suite si le reste > 0 (pas de sleep)
                    continue

            await asyncio.sleep(STREAM_POLL_S)
    finally:
        await _release_stream_slot()


__all__ = [
    "ModuleSpec",
    "MODULES",
    "status",
    "list_all",
    "start",
    "stop",
    "tail_log",
    "tail_log_stream",
    "RUN_DIR",
    "LOG_DIR",
    "AUDIT_LOG",
    "MAX_CONCURRENT_STREAMS",
    "STREAM_MAX_DURATION_S",
    "_reset_for_tests",
]
