# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_batch_services_launcher
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: lanceur unifie pour brain_worker + LM Studio + ClawHub smoke test, auto-skip si deja UP
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
tools/forge_services_launcher.py — Launcher unifie des services Nokido
========================================================================

Demarre (ou verifie l etat de) les services optionnels :
  - brain_worker      : embeddings + ONNX, port 5557 ZMQ REP
  - LM Studio server  : OpenAI-compat GUI, port 1234
  - llama.cpp native  : OpenAI-compat Python natif, port 8080 (le plus rapide)
  - gemini_poll_daemon: poll MCP Hub pour Gemini (pattern D2 autonomous)
  - ClawHub smoke     : test API reachability

Chaque service :
  1. Check si deja UP -> skip
  2. Sinon: spawn detached via subprocess, log dans sandbox/<service>.log
  3. Attend jusqu a N secondes que le port reponde
  4. Retourne status : up | started | failed | skipped

Usage:
  python tools/forge_services_launcher.py            # tout demarrer
  python tools/forge_services_launcher.py --status   # juste status
  python tools/forge_services_launcher.py --only brain_worker
  python tools/forge_services_launcher.py --stop-all

Variables env supportees :
  LAFORGE_BRAIN_PYTHON            : python pour brain_worker (defaut ryzen-ai-final, fallback sys.executable)
  LAFORGE_BRAIN_PORT              : port ZMQ brain_worker (defaut 5557)
  LAFORGE_LMSTUDIO_PORT           : port LM Studio server (defaut 1234)
  LAFORGE_LLAMACPP_NATIVE_PORT    : port llama.cpp natif Python (defaut 8080)
  LAFORGE_LLAMACPP_NATIVE_MODEL   : path GGUF ou blob Ollama (auto-detect qwen2.5-coder:7b)
  LAFORGE_LLAMACPP_NATIVE_CTX     : context size (defaut 4096)
  LAFORGE_LLAMACPP_NATIVE_GPU     : n_gpu_layers (defaut 0, CPU pur)
  LAFORGE_LLAMACPP_NATIVE_CHAT    : chat_format (defaut qwen)
  LAFORGE_LMSTUDIO_BIN            : path vers lms.exe (defaut auto-detect)
  LAFORGE_SKIP_LMSTUDIO           : 1 pour ne pas demarrer LM Studio
  LAFORGE_SKIP_LLAMACPP_NATIVE    : 1 pour ne pas demarrer llama.cpp natif
  LAFORGE_ENABLE_GEMINI_POLL      : 1 pour lancer gemini_poll_daemon (opt-in)
  GEMINI_POLL_INTERVAL_S          : intervalle poll (defaut 30)
  GEMINI_POLL_MODE                : passive | active (defaut passive)
  GEMINI_API_KEY                  : requis en mode active
"""

import argparse
import json
import os
import socket
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
SANDBOX.mkdir(exist_ok=True)
APP_DIR = ROOT / "app"
sys.path.insert(0, str(APP_DIR))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

SERVICES_TOKEN = get_secret("FORGE_TOKEN_SERVICES") or ""


def _load_env_file() -> None:
    """Reglages de Nokido.env et SECRETS du coffre dans os.environ, sans ecraser l'existant.

    Decision owner 2026-10-01 : ce chargeur recopiait tout le .env, secrets compris, en clair.
    """
    # forge_secrets est deja importe sans garde en tete de module (get_secret) : pas de try ici.
    from nokido_agent.app.forge_secrets import injecter_env_ou_dire

    injecter_env_ou_dire(ROOT / "Nokido.env", "launcher")


_load_env_file()

# Detection Windows pour flags Popen
_WIN = sys.platform == "win32"
_DETACHED = 0x00000008 if _WIN else 0  # DETACHED_PROCESS


# ============================================================================
# UTILS
# ============================================================================


def port_is_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """True si quelqu un ecoute sur host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def http_ok(url: str, timeout: float = 2.0) -> bool:
    """True si l URL repond (quelconque statut 2xx)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def log(msg: str, level: str = "INFO") -> None:
    """Log sur stderr pour ne jamais polluer stdout."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level:>5}] {msg}", file=sys.stderr, flush=True)


def _sonde_http(port: int, chemin: str, timeout: float = 3.0):
    """Rend (code, corps) — DELEGUE au contrat de capacite, source de verite.

    `forge_capability_contracts._http` porte la semantique du niveau APPLICATIF
    ecrite le 2026-08-18 : un endpoint qui repond < 500 prouve que le service est
    VIVANT, un 401/403/404 compris. C'est exactement ce que `http_ok` ci-dessus ne
    sait pas faire (il exige un 2xx, donc il lit un service protege par cle comme
    MORT et le relance inutilement — mesure du 2026-09-04 sur LM Studio).

    On ne recopie pas cette regle : on appelle le contrat. Il n'avait jusqu'ici que
    deux consommateurs et `forge_introspect` le rangeait parmi les organes « non
    consultes » — la brique la plus juste du depot sur la preuve de service etait
    la moins utilisee. Repli local si elle est indisponible, et l'echec rend
    (None, b"") : une sonde qui ne peut pas voir ne conclut pas.
    """
    try:
        from nokido_agent.tools.forge_capability_contracts import _http as _contrat_http  # noqa: PLC0415

        return _contrat_http(port, chemin, timeout=timeout)
    except Exception:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (port, chemin), timeout=timeout) as r:
                return r.status, r.read(4000)
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception:
            return None, b""


def wait_for_port(port: int, max_s: int = 15, host: str = "127.0.0.1") -> bool:
    """Attend max_s secondes que le port ecoute."""
    for i in range(max_s):
        if port_is_listening(host, port):
            return True
        time.sleep(1)
    return False


def spawn_detached(cmd: list[str], cwd: Path, log_file: Path, env: dict | None = None) -> int:
    """Spawn un process detache, log redirige. Retourne PID."""
    extra_env = {
        **os.environ,
        **(env or {}),
        "FORGE_TOKEN_SERVICES": SERVICES_TOKEN,
        "X_AGENT_NAME": "SERVICES",
    }
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=open(log_file, "ab"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=extra_env,
        creationflags=_DETACHED,
    )
    return proc.pid


def find_lms_binary() -> Path | None:
    """Trouve le binaire lms.exe de LM Studio."""
    override = os.environ.get("LAFORGE_LMSTUDIO_BIN", "")
    if override and Path(override).exists():
        return Path(override)

    candidates = [
        Path.home() / ".lmstudio" / "bin" / "lms.exe",
        Path.home() / ".lmstudio" / "bin" / "lms",
        Path(__import__("os").path.expanduser("~/.lmstudio/bin/lms.exe")),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ============================================================================
# SERVICE HANDLERS
# ============================================================================


def status_brain_worker() -> dict:
    """Check status brain_worker (port ZMQ 5557)."""
    port = int(os.environ.get("LAFORGE_BRAIN_PORT", "5557"))
    up = port_is_listening("127.0.0.1", port)
    return {"name": "brain_worker", "port": port, "up": up, "url": f"zmq://127.0.0.1:{port}"}


def start_brain_worker() -> dict:
    """Demarre brain_worker.py en detached. Skip si deja UP."""
    st = status_brain_worker()
    if st["up"]:
        log(f"brain_worker deja UP sur :{st['port']}")
        return {**st, "status": "skipped"}

    bw = APP_DIR / "brain_worker.py"
    if not bw.exists():
        return {**st, "status": "failed", "error": f"File missing: {bw}"}

    log_file = SANDBOX / "brain_worker.log"
    log(f"Spawning brain_worker (log: {log_file.name})")

    _RYZEN_PY = __import__("os").path.expanduser(r"~\miniforge3\envs\ryzen-ai-final\python.exe")
    brain_py = os.environ.get(
        "LAFORGE_BRAIN_PYTHON", _RYZEN_PY if Path(_RYZEN_PY).exists() else sys.executable
    )
    pid = spawn_detached(
        [brain_py, str(bw), "--port", str(st["port"])],
        cwd=APP_DIR,
        log_file=log_file,
    )
    log(f"brain_worker PID={pid}, waiting port {st['port']}...")

    # `preuve="transport"` : brain_worker parle ZMQ, il n'expose AUCUN endpoint HTTP.
    # Le port ouvert est donc le niveau de preuve MAXIMAL atteignable ici — et le
    # contrat de `forge_capability_contracts` (2026-08-18) rappelle qu'il « ne prouve
    # RIEN sur le service : un process fige tient son port ». On ne peut pas monter
    # d'un niveau, alors on DIT lequel on a atteint plutot que d'annoncer un succes
    # qui prétend davantage.
    if wait_for_port(st["port"], max_s=60):  # brain_worker charge torch, ~30s
        return {**st, "up": True, "pid": pid, "status": "started",
                "preuve": "transport", "preuve_note": "ZMQ — aucun endpoint HTTP a sonder"}
    else:
        return {
            **st,
            "pid": pid,
            "status": "failed",
            "error": f"Port {st['port']} ne repond pas apres 60s. Check {log_file}",
        }


def status_lmstudio() -> dict:
    """Check status LM Studio server (port 1234 par defaut).

    Lit LAFORGE_LMSTUDIO_PORT, PAS LAFORGE_LLAMACPP_PORT : les deux services
    sont distincts (LM Studio 1234, llama.cpp natif 8091). La collision faisait
    sonder LM Studio sur le port de llama.cpp -> faux 'LM Studio ne repond pas'.
    """
    port = int(os.environ.get("LAFORGE_LMSTUDIO_PORT", "1234"))
    up = http_ok(f"http://127.0.0.1:{port}/v1/models")
    return {"name": "lmstudio", "port": port, "up": up, "url": f"http://127.0.0.1:{port}"}


def start_lmstudio() -> dict:
    """Demarre LM Studio server via lms.exe. Skip si deja UP ou disable."""
    if os.environ.get("LAFORGE_SKIP_LMSTUDIO", "0") == "1":
        return {"name": "lmstudio", "status": "skipped", "reason": "LAFORGE_SKIP_LMSTUDIO=1"}

    st = status_lmstudio()
    if st["up"]:
        log(f"LM Studio deja UP sur :{st['port']}")
        return {**st, "status": "skipped"}

    lms = find_lms_binary()
    if not lms:
        return {
            **st,
            "status": "failed",
            "error": "lms.exe introuvable (installe LM Studio ou set LAFORGE_LMSTUDIO_BIN)",
        }

    log_file = SANDBOX / "lmstudio_server.log"
    log(f"Spawning LM Studio via {lms.name} (log: {log_file.name})")

    # lms server start est non-bloquant et retourne rapidement
    # On capture le retour pour voir si erreur
    try:
        r = subprocess.run(
            [str(lms), "server", "start"],
            capture_output=True,
            timeout=15,
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            err = (
                r.stderr.decode("cp1252", errors="replace")
                if r.stderr
                else r.stdout.decode("cp1252", errors="replace")
            )
            return {
                **st,
                "status": "failed",
                "error": f"lms server start rc={r.returncode}: {err[:400]}",
            }
    except subprocess.TimeoutExpired:
        return {**st, "status": "failed", "error": "lms server start timeout 15s"}

    # NIVEAU APPLICATIF EXIGE. Mesure 2026-09-04 : conclure « started » sur le seul
    # socket TCP declarait LM Studio demarre avant que son API ne reponde. Or
    # `/v1/models` existe : le niveau applicatif est atteignable, donc il est requis.
    # Un 401/403 compte comme VIVANT — le service a compris la requete et l'a refusee
    # (contrat du 2026-08-18) : c'est `auth_required`, pas `down`, et surtout pas une
    # raison de relancer un serveur qui tourne deja.
    if wait_for_port(st["port"], max_s=10):
        code, _ = _sonde_http(st["port"], "/v1/models")
        if code is None:
            return {**st, "status": "failed", "preuve": "transport",
                    "error": f"LM Studio :{st['port']} ecoute mais /v1/models ne repond pas"}
        if code in (401, 403):
            return {**st, "up": True, "status": "started", "preuve": "applicatif",
                    "auth_required": True,
                    "note": "API protegee par cle — service VIVANT, non exploitable sans token"}
        return {**st, "up": True, "status": "started", "preuve": "applicatif"}
    else:
        return {
            **st,
            "status": "failed",
            "preuve": "aucune",
            "error": f"LM Studio port {st['port']} ne repond pas apres 10s",
        }


def _find_default_gguf() -> Path | None:
    """Auto-detect un modele GGUF via les blobs Ollama.
    Priorite: qwen2.5-coder:7b-instruct-q4_K_M (par manifest), sinon plus gros blob GGUF."""
    override = os.environ.get("LAFORGE_LLAMACPP_NATIVE_MODEL", "")
    if override and Path(override).exists():
        return Path(override)

    ollama_home = Path(os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama" / "models")))
    if not ollama_home.exists():
        return None

    # 1. Essayer via manifest Qwen 7B Coder (le plus adapte pour agent coding)
    manifest = (
        ollama_home
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen2.5-coder"
        / "7b-instruct-q4_K_M"
    )
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text())
            for layer in m.get("layers", []):
                if layer.get("mediaType", "").endswith(".model"):
                    sha = layer.get("digest", "").replace("sha256:", "")
                    blob = ollama_home / "blobs" / f"sha256-{sha}"
                    if blob.exists():
                        return blob
        except Exception as ex:  # noqa: BLE001
            # PAS muet : un manifeste illisible fait basculer sur l'heuristique
            # "plus gros blob GGUF" ci-dessous, et change donc le MODELE servi
            # sans que personne ne le sache. Tracer le basculement.
            log(f"manifeste ollama illisible ({manifest.name}: {ex}) -> fallback plus gros blob GGUF")

    # 2. Fallback : plus gros blob avec magic GGUF
    blobs = ollama_home / "blobs"
    if blobs.exists():
        candidates = sorted(blobs.iterdir(), key=lambda p: -p.stat().st_size)
        for b in candidates[:10]:
            try:
                with b.open("rb") as f:
                    if f.read(4) == b"GGUF":
                        return b
            except Exception:  # muet-ok : scan de candidats, un blob illisible se saute
                continue

    return None


def status_llamacpp_native() -> dict:
    """Check status llama.cpp natif Python (port 8080 par defaut)."""
    port = int(os.environ.get("LAFORGE_LLAMACPP_NATIVE_PORT", "8080"))
    up = http_ok(f"http://127.0.0.1:{port}/v1/models")
    return {"name": "llamacpp_native", "port": port, "up": up, "url": f"http://127.0.0.1:{port}"}


def start_llamacpp_native() -> dict:
    """Demarre llama.cpp natif via python -m llama_cpp.server.
    Skip si deja UP ou disable. Model auto-detecte depuis blobs Ollama si absent."""
    if os.environ.get("LAFORGE_SKIP_LLAMACPP_NATIVE", "0") == "1":
        return {
            "name": "llamacpp_native",
            "status": "skipped",
            "reason": "LAFORGE_SKIP_LLAMACPP_NATIVE=1",
        }

    st = status_llamacpp_native()
    if st["up"]:
        log(f"llama.cpp natif deja UP sur :{st['port']}")
        return {**st, "status": "skipped"}

    # Verifier que llama_cpp.server est disponible
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return {
            **st,
            "status": "failed",
            "error": "llama-cpp-python non installe (pip install llama-cpp-python[server])",
        }

    # Auto-detect model
    model = _find_default_gguf()
    if not model:
        return {
            **st,
            "status": "failed",
            "error": "Aucun GGUF trouve. Set LAFORGE_LLAMACPP_NATIVE_MODEL=<path>",
        }

    ctx = os.environ.get("LAFORGE_LLAMACPP_NATIVE_CTX", "4096")
    gpu = os.environ.get("LAFORGE_LLAMACPP_NATIVE_GPU", "0")
    chat = os.environ.get("LAFORGE_LLAMACPP_NATIVE_CHAT", "qwen")

    log_file = SANDBOX / "llamacpp_server.log"
    log(f"Spawning llama.cpp natif (model: {model.name[:20]}..., log: {log_file.name})")

    cmd = [
        sys.executable,
        "-m",
        "llama_cpp.server",
        "--model",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(st["port"]),
        "--n_ctx",
        ctx,
        "--n_gpu_layers",
        gpu,
        "--chat_format",
        chat,
        "--verbose",
        "false",
    ]

    pid = spawn_detached(cmd, cwd=ROOT, log_file=log_file)
    log(f"llama.cpp natif PID={pid}, waiting port {st['port']} (model load ~5-30s)...")

    if wait_for_port(st["port"], max_s=60):
        # Double-check API OpenAI
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/v1/models", timeout=3) as r:
                data = json.loads(r.read())
                models = [m["id"] for m in data.get("data", [])]
                log(f"llama.cpp natif API OK: {len(models)} model(s)")
        except Exception as e:
            log(f"port UP mais API KO: {e}", "WARN")

        return {**st, "up": True, "pid": pid, "status": "started", "model": model.name[:40]}
    else:
        return {
            **st,
            "pid": pid,
            "status": "failed",
            "error": f"Port {st['port']} ne repond pas apres 60s. Check {log_file}",
        }


def status_gemini_poll() -> dict:
    """Check status gemini_poll_daemon via heartbeat file.
    Le daemon n'expose pas de port, on regarde son heartbeat."""
    hb = SANDBOX / "gemini_poll_daemon.heartbeat"
    if not hb.exists():
        return {"name": "gemini_poll", "port": None, "up": False, "reason": "no heartbeat file"}
    try:
        data = json.loads(hb.read_text(encoding="utf-8"))
        # Heartbeat valide si < 2 x interval
        from datetime import datetime

        ts = datetime.fromisoformat(data["ts"])
        age = (datetime.now() - ts).total_seconds()
        interval = int(data.get("interval_s", 30))
        is_alive = age < (interval * 2 + 10) and data.get("status") != "stopped"
        return {
            "name": "gemini_poll",
            "port": None,
            "up": is_alive,
            "mode": data.get("mode", "?"),
            "age_s": int(age),
            "url": "daemon (no port)",
        }
    except Exception as e:
        return {"name": "gemini_poll", "port": None, "up": False, "error": f"heartbeat parse: {e}"}


def start_gemini_poll() -> dict:
    """Demarre gemini_poll_daemon.py en detached. Opt-in via LAFORGE_ENABLE_GEMINI_POLL=1."""
    if os.environ.get("LAFORGE_ENABLE_GEMINI_POLL", "0") != "1":
        return {
            "name": "gemini_poll",
            "status": "skipped",
            "reason": "LAFORGE_ENABLE_GEMINI_POLL!=1 (opt-in)",
        }

    st = status_gemini_poll()
    if st["up"]:
        log(f"gemini_poll_daemon deja UP (mode={st.get('mode', '?')}, age={st.get('age_s', '?')}s)")
        return {**st, "status": "skipped"}

    daemon = ROOT / "tools" / "gemini_poll_daemon.py"
    if not daemon.exists():
        return {**st, "status": "failed", "error": f"File missing: {daemon}"}

    log_file = SANDBOX / "gemini_poll_daemon.log"
    log(f"Spawning gemini_poll_daemon (mode={os.environ.get('GEMINI_POLL_MODE', 'passive')})")

    pid = spawn_detached(
        [sys.executable, str(daemon)],
        cwd=ROOT,
        log_file=log_file,
    )

    # Attendre que le heartbeat apparaisse (signal que daemon boot OK)
    hb = SANDBOX / "gemini_poll_daemon.heartbeat"
    for _ in range(10):
        time.sleep(1)
        if hb.exists():
            break

    if hb.exists():
        return {**st, "up": True, "pid": pid, "status": "started"}
    return {
        **st,
        "pid": pid,
        "status": "failed",
        "error": f"No heartbeat after 10s. Check {log_file}",
    }


def status_multi_llm() -> dict:
    """Check status multi_llm_daemon via heartbeat."""
    hb = SANDBOX / "multi_llm_daemon.heartbeat"
    if not hb.exists():
        return {"name": "multi_llm", "port": None, "up": False, "reason": "no heartbeat file"}
    try:
        from datetime import datetime

        data = json.loads(hb.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["ts"])
        age = (datetime.now() - ts).total_seconds()
        interval = int(data.get("interval_s", 15))
        is_alive = age < (interval * 3 + 10) and data.get("status") != "stopped"
        return {
            "name": "multi_llm",
            "port": None,
            "up": is_alive,
            "age_s": int(age),
            "mode": data.get("status", "?"),
        }
    except Exception as e:
        return {"name": "multi_llm", "port": None, "up": False, "error": f"heartbeat parse: {e}"}


def start_multi_llm() -> dict:
    """Démarre multi_llm_daemon.py en detached. Opt-in via LAFORGE_ENABLE_MULTI_LLM=1."""
    if os.environ.get("LAFORGE_ENABLE_MULTI_LLM", "0") != "1":
        return {
            "name": "multi_llm",
            "status": "skipped",
            "reason": "LAFORGE_ENABLE_MULTI_LLM!=1 (opt-in)",
        }

    st = status_multi_llm()
    if st["up"]:
        log(f"multi_llm_daemon deja UP (age={st.get('age_s', '?')}s)")
        return {**st, "status": "skipped"}

    daemon = ROOT / "tools" / "multi_llm_daemon.py"
    if not daemon.exists():
        return {**st, "status": "failed", "error": f"File missing: {daemon}"}

    log_file = SANDBOX / "multi_llm_daemon.log"
    log("Spawning multi_llm_daemon")

    pid = spawn_detached([sys.executable, str(daemon)], cwd=ROOT, log_file=log_file)

    hb = SANDBOX / "multi_llm_daemon.heartbeat"
    for _ in range(10):
        time.sleep(1)
        if hb.exists():
            break

    if hb.exists():
        return {**st, "up": True, "pid": pid, "status": "started"}
    return {
        **st,
        "pid": pid,
        "status": "failed",
        "error": f"No heartbeat after 10s. Check {log_file}",
    }


def status_biblio_worker() -> dict:
    """Check status forge_biblio_worker via heartbeat (sandbox/biblio_worker.heartbeat)."""
    hb = SANDBOX / "biblio_worker.heartbeat"
    if not hb.exists():
        return {"name": "biblio_worker", "port": None, "up": False, "reason": "no heartbeat file"}
    try:
        from datetime import datetime

        data = json.loads(hb.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["ts"])
        age = (datetime.now() - ts).total_seconds()
        interval = int(data.get("interval_s", 30))
        is_alive = age < (interval * 3 + 10)
        return {
            "name": "biblio_worker",
            "port": None,
            "up": is_alive,
            "age_s": int(age),
            "searxng": data.get("searxng_url", "?"),
            "url": "daemon (no port)",
        }
    except Exception as e:
        return {
            "name": "biblio_worker",
            "port": None,
            "up": False,
            "error": f"heartbeat parse: {e}",
        }


def start_biblio_worker() -> dict:
    """Demarre forge_biblio_worker.py en detached. Opt-out via LAFORGE_SKIP_BIBLIO_WORKER=1."""
    if os.environ.get("LAFORGE_SKIP_BIBLIO_WORKER", "0") == "1":
        return {
            "name": "biblio_worker",
            "status": "skipped",
            "reason": "LAFORGE_SKIP_BIBLIO_WORKER=1",
        }

    st = status_biblio_worker()
    if st["up"]:
        log(f"biblio_worker deja UP (age={st.get('age_s', '?')}s)")
        return {**st, "status": "skipped"}

    daemon = ROOT / "app" / "forge_biblio_worker.py"
    if not daemon.exists():
        return {**st, "status": "failed", "error": f"File missing: {daemon}"}

    log_file = SANDBOX / "biblio_worker.log"
    log("Spawning forge_biblio_worker (poll SearXNG → reviewed)")
    pid = spawn_detached(
        [sys.executable, str(daemon)],
        cwd=ROOT,
        log_file=log_file,
    )

    hb = SANDBOX / "biblio_worker.heartbeat"
    for _ in range(10):
        time.sleep(1)
        if hb.exists():
            break

    if hb.exists():
        return {**st, "up": True, "pid": pid, "status": "started"}
    return {
        **st,
        "pid": pid,
        "status": "failed",
        "error": f"No heartbeat after 10s. Check {log_file}",
    }


def status_clawhub() -> dict:
    """Smoke test ClawHub API publique."""
    url = "https://clawhub.ai/api/v1/search?q=test&limit=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
            n_results = len(body.get("results", []))
            return {
                "name": "clawhub",
                "up": True,
                "url": "https://clawhub.ai/api/v1",
                "results": n_results,
            }
    except urllib.error.HTTPError as e:
        return {"name": "clawhub", "up": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"name": "clawhub", "up": False, "error": f"{type(e).__name__}: {e}"}


def status_ollama() -> dict:
    up = http_ok("http://127.0.0.1:11434/api/tags")
    if up:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
                d = json.loads(r.read())
                return {
                    "name": "ollama",
                    "port": 11434,
                    "up": True,
                    "models": len(d.get("models", [])),
                }
        except Exception as ex:  # noqa: BLE001
            # PAS muet : ce timeout de 2 s tombe sous pression RAM alors qu'ollama
            # sert parfaitement. Sans trace, le rapport montre un ollama sans compte
            # de modeles et on conclut a tort qu'il est degrade (faux diagnostic du
            # 2026-08-11 : 16 modeles servis, declare "backend non pret").
            log(f"ollama /api/tags injoignable en 2s ({ex}) -> compte de modeles absent du rapport")
    return {"name": "ollama", "port": 11434, "up": up}


def status_hub() -> dict:
    up = http_ok("http://127.0.0.1:8766/health")
    return {"name": "hub", "port": 8766, "up": up, "url": "http://127.0.0.1:8766"}


def status_netcfg_ui() -> dict:
    up = http_ok("http://127.0.0.1:7500/api/network")
    return {"name": "netcfg_ui", "port": 7500, "up": up, "url": "http://127.0.0.1:7500"}


def status_netcfg_mcp() -> dict:
    up = http_ok("http://127.0.0.1:8767/health")
    return {"name": "netcfg_mcp", "port": 8767, "up": up, "url": "http://127.0.0.1:8767"}


_CERVELET_WSL_IP = os.environ.get("LAFORGE_CERVELET_WSL_IP", "localhost")
_CERVELET_WSL_PORT = int(os.environ.get("LAFORGE_CERVELET_WSL_PORT", "55555"))
_CERVELET_SCRIPT = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "start_wasmedge_cervelet.sh")


def status_wasmedge_cervelet() -> dict:
    """Check wasmedge cervelet (WSL Debian, nomic-embed :55555)."""
    up = http_ok(f"http://{_CERVELET_WSL_IP}:{_CERVELET_WSL_PORT}/v1/models")
    return {
        "name": "wasmedge_cervelet",
        "port": _CERVELET_WSL_PORT,
        "up": up,
        "url": f"http://{_CERVELET_WSL_IP}:{_CERVELET_WSL_PORT}",
    }


def start_wasmedge_cervelet() -> dict:
    """Lance wasmedge cervelet dans WSL Debian. Skip si deja UP."""
    if os.environ.get("LAFORGE_SKIP_WASMEDGE", "0") == "1":
        return {
            "name": "wasmedge_cervelet",
            "status": "skipped",
            "reason": "LAFORGE_SKIP_WASMEDGE=1",
        }

    st = status_wasmedge_cervelet()
    if st["up"]:
        log(f"wasmedge_cervelet deja UP sur {_CERVELET_WSL_IP}:{_CERVELET_WSL_PORT}")
        return {**st, "status": "skipped"}

    script_win = Path(_CERVELET_SCRIPT)
    if not script_win.exists():
        return {**st, "status": "failed", "error": f"Script manquant: {_CERVELET_SCRIPT}"}

    # Convert Windows path to WSL /mnt/c/... path
    wsl_path = "/mnt/c" + str(script_win).replace("C:", "").replace("\\", "/")
    log_file = SANDBOX / "wasmedge_cervelet.log"
    log(f"Spawning wasmedge via WSL Debian (log: {log_file.name})")

    # subprocess list — spaces in path handled correctly without shell=True
    pid = spawn_detached(
        ["wsl", "-d", "Debian", "--", "bash", wsl_path],
        cwd=ROOT,
        log_file=log_file,
    )
    log(f"wasmedge WSL PID={pid}, waiting {_CERVELET_WSL_IP}:{_CERVELET_WSL_PORT}...")

    # `preuve="transport"` : on ne sonde ici que l'ouverture du port cote WSL. Tant
    # qu'un endpoint de sante n'est pas declare pour ce cervelet, le niveau
    # applicatif n'est pas atteignable — on le DIT au lieu de le sous-entendre.
    if wait_for_port(_CERVELET_WSL_PORT, max_s=30, host=_CERVELET_WSL_IP):
        return {**st, "up": True, "pid": pid, "status": "started",
                "preuve": "transport",
                "preuve_note": "aucun endpoint de sante declare pour le cervelet WSL"}
    return {
        **st,
        "pid": pid,
        "status": "failed",
        "error": f"Port {_CERVELET_WSL_PORT} ne repond pas apres 30s. Check {log_file}",
    }


# ============================================================================
# COMMANDS
# ============================================================================


def cmd_status() -> int:
    """Affiche le statut de tous les services."""
    statuses = [
        status_hub(),
        status_netcfg_ui(),
        status_netcfg_mcp(),
        status_ollama(),
        status_brain_worker(),
        status_lmstudio(),
        status_llamacpp_native(),
        status_wasmedge_cervelet(),
        status_gemini_poll(),
        status_multi_llm(),
        status_biblio_worker(),
        status_clawhub(),
    ]

    print(f"\n{'=' * 60}")
    print(f"  STATUS Nokido services @ {time.strftime('%H:%M:%S')}")
    print(f"{'=' * 60}")
    for s in statuses:
        icon = "UP " if s.get("up") else "DN "
        name = s["name"]
        port = s.get("port", "")
        port_s = f":{port:<5}" if port else "       "
        extra = ""
        if s.get("models"):
            extra = f" ({s['models']} models)"
        elif s.get("results"):
            extra = f" ({s['results']} API results)"
        elif s.get("mode"):
            extra = f" (mode={s['mode']}, age={s.get('age_s', '?')}s)"
        elif s.get("error"):
            extra = f"  ← {s['error'][:60]}"
        elif s.get("reason"):
            extra = f"  ({s['reason'][:40]})"
        print(f"  {icon} {port_s} {name:<16} {'UP' if s.get('up') else 'DOWN'}{extra}")
    print()
    return 0 if all(s.get("up") for s in statuses) else 1


def cmd_start(only: str | None = None) -> int:
    """Demarre les services optionnels manquants."""
    log("=== Launching Nokido services ===")

    targets = {
        "brain_worker": start_brain_worker,
        "lmstudio": start_lmstudio,
        "llamacpp_native": start_llamacpp_native,
        "wasmedge_cervelet": start_wasmedge_cervelet,
        "gemini_poll": start_gemini_poll,
        "multi_llm": start_multi_llm,
        "biblio_worker": start_biblio_worker,
    }

    # Filtrer si --only
    if only:
        if only not in targets:
            log(f"Service inconnu: {only}. Disponibles: {list(targets.keys())}", "ERR")
            return 2
        targets = {only: targets[only]}

    results = []
    for name, starter in targets.items():
        log(f"--- {name} ---")
        try:
            r = starter()
        except Exception as e:
            r = {"name": name, "status": "failed", "error": f"{type(e).__name__}: {e}"}
        results.append(r)
        icon = {"started": "OK ", "skipped": "-- ", "failed": "ERR"}.get(r.get("status", ""), "?")
        log(
            f"  {icon} {name}: {r.get('status', '?')}"
            + (f" - {r.get('error', '')}" if r.get("error") else "")
        )

    # ClawHub smoke test
    log("--- clawhub smoke ---")
    ch = status_clawhub()
    results.append({**ch, "status": "up" if ch.get("up") else "failed"})
    if ch.get("up"):
        log(f"  OK  clawhub: API reachable ({ch.get('results', 0)} results test query)")
    else:
        log(f"  ERR clawhub: {ch.get('error', 'down')}")

    # Final status
    cmd_status()

    fails = [r for r in results if r.get("status") == "failed"]
    return 0 if not fails else 1


def cmd_stop_all() -> int:
    """Stop les services demarres par ce launcher."""
    log("=== Stopping Nokido services ===")

    # brain_worker
    try:
        # Trouver PID via connexions
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-NetTCPConnection -LocalPort 5557 -State Listen -ErrorAction SilentlyContinue).OwningProcess",
            ],
            capture_output=True,
            timeout=3,
            creationflags=_NO_WINDOW,
        )
        pid = r.stdout.decode("cp1252", errors="replace").strip() if r.stdout else ""
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
            log(f"  brain_worker PID={pid} killed")
    except Exception as e:
        log(f"  brain_worker stop failed: {e}", "ERR")

    # gemini_poll_daemon (par heartbeat age + pid inspection via cmdline)
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*gemini_poll_daemon*' } | "
                "ForEach-Object { $_.ProcessId }",
            ],
            capture_output=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        if r.stdout:
            for pid in r.stdout.decode("cp1252", errors="replace").split():
                if pid.strip().isdigit():
                    subprocess.run(
                        ["taskkill", "/PID", pid.strip(), "/F"],
                        capture_output=True,
                        timeout=5,
                        creationflags=_NO_WINDOW,
                    )
                    log(f"  gemini_poll_daemon PID={pid.strip()} killed")
    except Exception as e:
        log(f"  gemini_poll stop failed: {e}", "ERR")

    # multi_llm_daemon
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*multi_llm_daemon*' } | "
                "ForEach-Object { $_.ProcessId }",
            ],
            capture_output=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        if r.stdout:
            for pid in r.stdout.decode("cp1252", errors="replace").split():
                if pid.strip().isdigit():
                    subprocess.run(
                        ["taskkill", "/PID", pid.strip(), "/F"],
                        capture_output=True,
                        timeout=5,
                        creationflags=_NO_WINDOW,
                    )
                    log(f"  multi_llm_daemon PID={pid.strip()} killed")
    except Exception as e:
        log(f"  multi_llm stop failed: {e}", "ERR")

    # llama.cpp natif (port 8080)
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue).OwningProcess",
            ],
            capture_output=True,
            timeout=3,
            creationflags=_NO_WINDOW,
        )
        pid = r.stdout.decode("cp1252", errors="replace").strip() if r.stdout else ""
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
            log(f"  llamacpp_native PID={pid} killed")
    except Exception as e:
        log(f"  llamacpp_native stop failed: {e}", "ERR")

    # LM Studio
    lms = find_lms_binary()
    if lms:
        try:
            r = subprocess.run([str(lms), "server", "stop"], capture_output=True, timeout=10)
            log(f"  lms server stop rc={r.returncode}")
        except Exception as e:
            log(f"  lms server stop failed: {e}", "ERR")

    return cmd_status()


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Nokido services launcher")
    parser.add_argument(
        "--status", action="store_true", help="Affiche juste le statut sans demarrer"
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Demarre un seul service (brain_worker|lmstudio|llamacpp_native|gemini_poll|biblio_worker)",
    )
    parser.add_argument(
        "--stop-all", action="store_true", help="Arrete tous les services lances par ce launcher"
    )
    args = parser.parse_args()

    if args.stop_all:
        return cmd_stop_all()
    if args.status:
        return cmd_status()
    return cmd_start(only=args.only)


if __name__ == "__main__":
    sys.exit(main())
