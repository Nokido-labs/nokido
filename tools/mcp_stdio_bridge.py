"""
mcp_stdio_bridge.py — Bridge stdio → HTTP Nokido Hub v3.0
===========================================================
Permet à Claude Desktop de parler en stdio pendant que le vrai
serveur MCP Nokido tourne en service Windows permanent (nssm).

DESIGN :
  - Proxy STDIO → HTTP/8766 transparent (zéro logique métier)
  - Fallback automatique → nokido_mcp_server.py si hub DOWN
  - Conformité JSON-RPC 2.0 complète (notifications, batch, error codes)
  - Sécurité : rate limiting, max payload, sanitisation erreurs
  - Zéro dépendance lourde (stdlib uniquement)

INDEPENDANCE nssm :
  Claude Desktop peut tuer ce process à tout moment.
  Le hub reste UP via nssm NokidoMCP.
  Au prochain lancement Claude Desktop recrée le bridge.

Config claude_desktop_config.json :
  {
    "mcpServers": {
      "Nokido": {
        "command": __import__("os").path.expanduser("~/miniforge3/python.exe"),
        "args": [__import__("os").path.expanduser("~/Script python IA/LaForge/tools/mcp_stdio_bridge.py")],
        "env": {
          "PYTHONIOENCODING": "utf-8",
          "PYTHONUTF8": "1"
        }
      }
    }
  }

Refs conformité :
  https://www.jsonrpc.org/specification#extensions
  https://datatracker.ietf.org/doc/html/draft-yang-json-rpc-02
  https://www.stackhawk.com/blog/json-rpc-security-best-practices
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ───────────────────────────────────────────────────────────────────────────────
# CONFIG — lu depuis env ou Nokido.env (pas de secrets hardcodés)
# ───────────────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_ENV = _ROOT / "Nokido.env"

# Ecriture stdout SERIALISEE via QUEUE + writer thread UNIQUE.
# Avant : _STDOUT_LOCK tenu PENDANT write+flush -> si le client lit lentement, le pipe
# stdout se remplit, le flush bloque, le lock reste pris et TOUS les writers (boucle +
# watcher capabilities + workers concurrents) se figent = deadlock collaboratif.
# Maintenant : les producteurs enqueue (non bloquant) ; UN seul thread draine et ecrit
# -> zero entrelacement, zero deadlock (pipe plein => seul le writer attend). File
# bornee = contre-pression douce sous burst multi-CLI/swarm.
_DISPATCH_WORKERS = int(os.environ.get("LAFORGE_BRIDGE_WORKERS", "8"))
_OUT_Q: "queue.Queue" = queue.Queue(maxsize=10000)
_WRITER_STARTED = threading.Event()


def _writer_loop(out=None) -> None:
    out = out if out is not None else sys.stdout.buffer
    while True:
        data = _OUT_Q.get()
        if data is None:  # sentinelle d'arret
            break
        try:
            out.write(data + b"\n")
            out.flush()
        except (BrokenPipeError, ValueError, OSError):
            break  # client parti / stdout ferme -> stop propre


def _start_writer() -> None:
    """Demarre le writer thread une seule fois (idempotent)."""
    if not _WRITER_STARTED.is_set():
        _WRITER_STARTED.set()
        threading.Thread(target=_writer_loop, daemon=True, name="stdout-writer").start()


def _write_out(data: bytes) -> None:
    """Enqueue non bloquant ; le writer thread unique serialise l'ecriture reelle."""
    _start_writer()  # garantit le writer meme sur les chemins d'ecriture precoces
    try:
        _OUT_Q.put_nowait(data)
    except queue.Full:
        _OUT_Q.put(data, timeout=30)  # backpressure extreme : attendre plutot que perdre

_HOST = "127.0.0.1"
_PORT = 8766  # hub v18 (nssm NokidoMCP)
_TOKEN = ""
# Ce script EST le bridge stdio→HTTP : son identité est BRIDGE, figée.
# Le token résolu par _load_env() est FORGE_TOKEN_BRIDGE. Un override
# LAFORGE_AGENT=CLAUDE (ex: env injecté par claude_desktop_config.json)
# crée un mismatch agent/token côté hub (_resolve_ring) -> 401 "Hub auth
# error". L'identité est donc HARDCODÉE — aucun env ne peut la casser.
# cross-OS, aucun launcher (.bat/.sh) requis, pas de régression possible.
# LAFORGE_AGENT HONORÉE (2026-07-29) : le commentaire ci-dessus l'annonçait depuis
# toujours, le code ne l'a JAMAIS lue — tout client passant par le bridge s'annonçait
# donc « BRIDGE », sans identité propre, sans ring distinct, sans traçabilité. C'est
# ce qui empêchait de brancher un nouveau CLI en stdio SANS lui coller un Bearer en
# clair dans un fichier de config. DÉFAUT INCHANGÉ : sans la variable, comportement
# identique (Claude chat/cowork restent BRIDGE) — l'identité doit exister dans
# config/agent_identities.json, sinon le videur la traitera en ring par défaut.
_AGENT = (os.environ.get("LAFORGE_AGENT") or "BRIDGE").strip().upper() or "BRIDGE"

# ParamÃ¨tres configurables via env
# Timeout 30s : aucun tool MCP legitime ne devrait prendre plus. Fail fast
# au lieu de bloquer Claude Desktop 2 minutes par requete.
_TIMEOUT = int(os.environ.get("LAFORGE_BRIDGE_TIMEOUT", "30"))
_MAX_RETRY = int(os.environ.get("LAFORGE_BRIDGE_RETRIES", "3"))
_RETRY_DLY = float(os.environ.get("LAFORGE_BRIDGE_RETRY_DLY", "0.5"))
_MAX_BYTES = int(os.environ.get("LAFORGE_BRIDGE_MAX_BYTES", str(512 * 1024)))
_RATE_LIMIT = int(os.environ.get("LAFORGE_BRIDGE_RATE_LIMIT", "120"))  # req/min
_WAIT_HUB = float(os.environ.get("LAFORGE_BRIDGE_WAIT_HUB", "30.0"))
# SSE : _TIMEOUT (30s) borne un POST JSON classique. Pour un stream SSE, le hub
# émet un heartbeat ': ping' toutes les 15s pendant une tâche longue : on tolère
# donc _SSE_IDLE entre deux events (45s = 3× la marge du heartbeat) et un cap dur
# global _SSE_MAX. Une inférence locale de plusieurs minutes survit ainsi.
_SSE_IDLE = float(os.environ.get("LAFORGE_BRIDGE_SSE_IDLE", "45"))
_SSE_MAX = float(os.environ.get("LAFORGE_BRIDGE_SSE_MAX", "600"))

# Tools sensibles qui necessitent une validation sentinel (execution code,
# mutation state, ecriture). Les autres tools (read, get_mode, poll, notify,
# search_recent, etc.) skip sentinel â€” leurs args ne contiennent pas
# d'injection candidates et sentinel ajoutait juste de la latence.
_SENTINEL_TOOLS = frozenset(
    {
        "run",
        "write",
        "query",
        "mutation:start",
        "trigger_autonomous_evolution",
        "set_mode",
        "task_assign",
        "task_result",
        "event_publish",
        "agy_run",
        "agy_config",
        "agy_add_dir",
        # Sentinelle du fail-closed : rendue par `_nom_canonique` quand la table
        # d'alias est illisible. Sa presence ICI est ce qui rend le repli REEL —
        # sans elle, le nom sentinelle ne serait dans aucune liste et le doute se
        # traduirait par un bypass, soit l'inverse de l'intention.
        "__alias_illisible__",
    }
)


def get_secret(key: str) -> str:
    """Lit un secret via le coffre DPAPI (app.forge_secrets) si disponible,
    sinon retombe sur os.environ. Import PARESSEUX + garde totale : le bridge
    reste stdlib-only et ne doit JAMAIS crasher ni ecrire sur stdout (le flux
    stdio est reserve au JSON-RPC MCP). Corrige le NameError qui empechait
    Claude Desktop de charger le MCP."""
    try:
        root = str(Path(__file__).resolve().parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from app.forge_secrets import get_secret as _vault_get
        return _vault_get(key) or ""
    except Exception:
        return os.environ.get(key, "") or ""


def _load_env():
    """Charge les variables depuis Nokido.env (token, host, port)."""
    global _HOST, _PORT, _TOKEN
    # PrioritÃ© : variables d'environnement dÃ©jÃ  prÃ©sentes (injectÃ©es par nssm)
    # 2b-5 (2026-09-28) : le JETON n'est plus lu ici (maitre au guichet, puis jeton du
    # pont EN CLAIR dans Nokido.env) -- c'est `_choisir_jeton`, au guichet, plus bas.
    try:
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.split("#")[0].strip().strip('"').strip("'")
            if k == "MCP_HTTP_HOST":
                _HOST = v or _HOST
            if k == "LAFORGE_HUB_PORT":
                _PORT = int(v) if v.isdigit() else _PORT
    except OSError as _e:
        logging.getLogger("mcp_stdio_bridge").debug(f"Nokido.env illisible: {_e}")


def _token_de_l_agent(agent: str) -> str:
    """Jeton PROPRE a l'agent, lu dans le coffre DPAPI. Jamais en clair sur disque.

    Le commentaire de `_AGENT` decrivait le blocage depuis toujours : porter
    LAFORGE_AGENT=X tout en presentant le Bearer de BRIDGE cree un mismatch
    agent/token cote hub (`_resolve_ring`) -> 401. C'est ce qui obligeait a coller
    un Bearer en clair dans le fichier de config de chaque client stdio.

    En resolvant `FORGE_TOKEN_<AGENT>` ici, la config du client ne porte plus AUCUN
    secret, et une rotation de cle est prise en compte au prochain lancement sans
    resynchroniser quoi que ce soit.
    """
    try:
        sys.path.insert(0, str(_ROOT))
        from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

        return (get_secret(f"FORGE_TOKEN_{agent}") or "").strip()
    except Exception as _e:  # noqa: BLE001
        logging.getLogger("mcp_stdio_bridge").warning(
            f"coffre injoignable pour FORGE_TOKEN_{agent}: {type(_e).__name__}")
        return ""


def _choisir_jeton(agent: str, lire) -> tuple:
    """(jeton, provenance) pour l'identite `agent`, lu au guichet par `lire(nom)`.

    2b-5 (2026-09-28). Mesure : pour tout client autre que BRIDGE, le « jeton propre »
    etait `get_secret("FORGE_MCP_TOKEN") or ... or _token_de_l_agent(...)` -- le MAITRE
    d'abord, contre la regle ecrite juste au-dessus. Chaque identite prend desormais SON
    jeton EN PREMIER ; sans jeton propre, le maitre reste servi en TRANSITION jusqu'a la
    fermeture 2b-6 (les modes dev et les clients de debug en vivent encore), et la
    provenance le dit.
    """
    propre = (lire(f"FORGE_TOKEN_{agent}") or "").strip()
    if propre:
        return propre, "propre"
    maitre = (lire("FORGE_MCP_TOKEN") or "").strip()
    if maitre:
        return maitre, "maitre_transition"
    return "", "absent"


_load_env()
# Identite : SON jeton, au guichet. On ne retombe JAMAIS sur celui d'un autre -- ce serait
# usurper une identite et fausser le ring, donc la tracabilite. Sans jeton propre, on part
# sans Authorization : le hub repondra 401, refus LISIBLE la ou un emprunt serait une
# reussite trompeuse.
_TOKEN, _PROVENANCE_JETON = _choisir_jeton(_AGENT, get_secret)
if _PROVENANCE_JETON == "maitre_transition":
    sys.stderr.write(
        f"[bridge] FORGE_TOKEN_{_AGENT} absent du coffre : jeton MAITRE en TRANSITION "
        f"(2b-5) -- provisionner l'identite propre.\n")
elif _PROVENANCE_JETON == "absent":
    sys.stderr.write(
        f"[bridge] AUCUN jeton propre pour {_AGENT} (FORGE_TOKEN_{_AGENT} absent du "
        f"coffre) -- pas d'emprunt, le hub repondra 401.\n")
# PLUS d'override du jeton par variable d'environnement (retire le 2026-09-28). La
# variable persistante posee cote Claude Desktop pour ce pont est celle qui l'a tenu en
# 401 des heures avec un jeton REVOQUE (incident du 2026-09-03) : l'environnement est la
# seule couche qu'aucune rotation ne met a jour. La session owner lit son propre
# FORGE_TOKEN_<AGENT> au coffre (`_choisir_jeton`, au guichet, ci-dessus) ; le cliquet
# « secrets hors coffre » de ci_local refuse le retour d'une telle lecture.

_HUB_URL = f"http://{_HOST}:{_PORT}/mcp"
_HEALTH_URL = f"http://{_HOST}:{_PORT}/health"

# Logs en stderr uniquement (stdout = protocole MCP)
_LOGS = _ROOT / "logs"
_LOGS.mkdir(parents=True, exist_ok=True)
try:
    _log_handler = RotatingFileHandler(
        _LOGS / "mcp_bridge.log", encoding="utf-8", maxBytes=10485760, backupCount=5
    )
except OSError:
    # logs/ non inscriptible (ex: user sandboxé) -> stderr-only.
    # stdout reste RÉSERVÉ au protocole MCP ; StreamHandler() = sys.stderr.
    _log_handler = logging.StreamHandler()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bridge] %(message)s",
    handlers=[_log_handler],
)
logger = logging.getLogger("mcp_stdio_bridge")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# RATE LIMITER â€” fenÃªtre glissante
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class _RateLimiter:
    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._times: deque = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] > 60:
                self._times.popleft()
            if len(self._times) >= self._max:
                return False
            self._times.append(now)
            return True


_rate = _RateLimiter(_RATE_LIMIT)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# VALIDATION JSON-RPC 2.0
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _err(code: int, msg: str, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": str(msg)[:200]}}


def _validate(obj: Any) -> dict | None:
    if not isinstance(obj, dict):
        return _err(-32600, "Invalid Request: not an object")
    if obj.get("jsonrpc") != "2.0":
        return _err(-32600, "Invalid Request: jsonrpc must be '2.0'")
    method = obj.get("method")
    if not isinstance(method, str) or not method:
        return _err(-32600, "Invalid Request: method must be string")
    if method.startswith("rpc.") and method != "rpc.discover":
        return _err(-32601, f"Method reserved: {method}")
    params = obj.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        return _err(-32602, "Invalid params: must be Object or Array")
    return None


def _is_notif(obj: dict) -> bool:
    """Spec 4.1 : Notification = Request sans champ id."""
    return "id" not in obj


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HTTP CLIENT
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_conn = None
_conn_lock = __import__("threading").Lock()


def _get_conn():
    global _conn
    if _conn is None:
        _conn = __import__("http.client", fromlist=["x"]).HTTPConnection(
            _HOST, _PORT, timeout=_TIMEOUT
        )
    return _conn


def _headers():
    h = {
        "Content-Type": "application/json",
        "X-Agent-Name": _AGENT,
        "X-Transport": "stdio-bridge/3.1",
        "Connection": "keep-alive",
        "Accept": "application/json, text/event-stream",
    }
    if _TOKEN:
        h["Authorization"] = "Bearer " + _TOKEN
    return h


def _post(body: bytes, req_id: Any = None, attempt: int = 0) -> bytes:
    req = urllib.request.Request(_HUB_URL, data=body, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            ct = r.headers.get("Content-Type", "")
            if "text/event-stream" in ct:
                # Stream SSE : le dernier event data:{...} = résultat. Idle timeout
                # = _SSE_IDLE entre deux events ; le heartbeat hub (15s) le reset,
                # donc une tâche longue ne casse plus la connexion. _SSE_MAX = cap
                # dur global anti-runaway.
                try:
                    r.fp.raw._sock.settimeout(_SSE_IDLE)
                except Exception:
                    pass
                last = None
                _deadline = time.monotonic() + _SSE_MAX
                for line in r:
                    if time.monotonic() > _deadline:
                        break
                    line = line.decode("utf-8", errors="replace").strip()
                    if line.startswith("data: ") and line[6:].startswith("{"):
                        last = line[6:].encode()
                return last if last else b"{}"
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # DIRE POURQUOI. Sans cela, 401 (aucun jeton / jeton inconnu) et 403
            # (identite refusee malgre un jeton valide) rendent le MEME message
            # cote client, et le diagnostic repart de zero a chaque fois --
            # mesure 2026-09-03, plusieurs heures perdues sur « Hub auth error »
            # alors que la requete rejouee a l'identique passait en 200.
            # Empreinte seulement, jamais la valeur.
            _emp = hashlib.sha256(_TOKEN.encode()).hexdigest()[:12] if _TOKEN else "AUCUN"
            try:
                _corps = e.read(200).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                _corps = "(corps illisible)"
            logger.error(
                "hub %d | agent=%s | jeton=%s | url=%s | %s"
                % (e.code, _AGENT, _emp, _HUB_URL, _corps)
            )
            return json.dumps(_err(-32001, "Hub auth error", req_id)).encode()
        if e.code >= 500 and attempt < _MAX_RETRY:
            time.sleep(_RETRY_DLY * (2**attempt))
            return _post(body, req_id, attempt + 1)
        return json.dumps(_err(-32002, f"Hub error {e.code}", req_id)).encode()
    except (urllib.error.URLError, ConnectionRefusedError, OSError):
        if attempt < _MAX_RETRY:
            time.sleep(_RETRY_DLY * (2**attempt))
            return _post(body, req_id, attempt + 1)
        return json.dumps(_err(-32003, "Hub unavailable", req_id)).encode()


def _hub_alive() -> bool:
    try:
        urllib.request.urlopen(_HEALTH_URL, timeout=2)
        return True
    except Exception:
        return False


def _wait_hub() -> bool:
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < _WAIT_HUB:
        if _hub_alive():
            if n:
                logger.info(f"Hub UP aprÃ¨s {n} tentatives")
            return True
        n += 1
        time.sleep(0.5)
    return False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# DISPATCH JSON-RPC 2.0 â€” single + batch + notifications
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Cache l'import sentinel UNE FOIS au load module au lieu de re-importer
# a chaque tools/call (sys.path.insert + import dict-lookup amortis sur N
# calls -> ~ 0 cout par call apres le premier).
_validate_action = None
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nokido_agent.app.forge_sentinel import validate_action as _validate_action  # noqa: E402
except Exception as _e:
    logger.debug(f"Sentinel module indisponible: {_e}")


# Sentinelle rendue quand la table d'alias est illisible : elle n'est dans
# aucune table, et elle est ajoutee a `_SENTINEL_TOOLS` plus bas pour que le
# doute se traduise par une VALIDATION et jamais par un bypass.
_FORCER_VALIDATION = "__alias_illisible__"
_ALIAS_CACHE: list = []


def _alias_canoniques():
    """Table d'alias du registry, lue par AST — ou None si illisible.

    Lue UNE fois, mise en cache : ce pont traite chaque message, et relire un
    fichier de 450 Ko par appel serait payer une analyse syntaxique a chaque
    tour d'outil.
    """
    if _ALIAS_CACHE:
        return _ALIAS_CACHE[0]
    table = None
    try:
        import ast as _ast
        from pathlib import Path as _P

        src = (_P(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py")
        arbre = _ast.parse(src.read_text(encoding="utf-8"))
        for n in arbre.body:
            cible = None
            if isinstance(n, _ast.Assign) and n.targets and hasattr(n.targets[0], "id"):
                cible = n.targets[0].id
            elif isinstance(n, _ast.AnnAssign) and hasattr(n.target, "id"):
                cible = n.target.id
            if cible == "_NAMESPACE_ALIASES":
                valeur = _ast.literal_eval(n.value)
                if isinstance(valeur, dict) and valeur:
                    table = valeur
                break
    except Exception as e:  # noqa: BLE001
        print(f"[sentinel] table d'alias ILLISIBLE ({type(e).__name__}) — tout "
              f"tools/call sera VALIDE, jamais bypasse", file=sys.stderr)
    _ALIAS_CACHE.append(table)
    return table


def _nom_canonique(nom: str) -> str:
    """Nom d'outil RESOLU, comme le hub le resoudra — jamais le nom brut.

    REVUE DEFENSIVE PROTOCOLS-RPC du 2026-09-19, confusion de protocole. Ce
    garde comparait le nom BRUT a `_SENTINEL_TOOLS` pendant que le hub, lui,
    applique `resolve_tool_name()` avant d'executer. Deux lectures du meme
    message, et le controle portait sur celle qui ne decide pas.

    Mesure, avec la vraie table d'alias et la vraie liste de garde :

        forge.run.run   non garde ici  ->  resolu « run »    -> AURAIT du l'etre
        forge_run       non garde ici  ->  resolu « run »    -> AURAIT du l'etre
        forge_write     non garde ici  ->  resolu « write »  -> AURAIT du l'etre

    Le garde se franchissait donc en RENOMMANT l'intention, ce que ce depot a
    deja paye ailleurs : « un garde qu'on franchit en renommant son intention
    ne garde rien ». On ne durcit pas la liste, on aligne la LECTURE — c'est la
    meme correction que pour le SQL, ou le verbe compte et non l'orthographe.

    18 alias pointent vers un outil sous garde, dont `agy_run` (owner-only),
    `set_mode`, `trigger_autonomous_evolution`, `write` et `query`.

    POURQUOI LA TABLE EST LUE PAR AST ET NON IMPORTEE. Premiere version de ce
    correctif : `from ... forge_mcp_registry import resolve_tool_name`. Elle
    ECHOUAIT en silence et le bypass restait ouvert — importer le registry tire
    `forge_spike_router`, donc `torch`, dont la chaine `dill` ouvre `os.devnull`
    et se fait refuser par le garde d'ecriture. Un pont stdio ne peut pas
    dependre de la pile ML ; ici la mesure a corrige la conception, pas
    l'inverse. La table reste donc definie UNE FOIS dans le registry, et on la
    LIT sans executer le module.

    FAIL-CLOSED, dans le bon sens : si la table est illisible, on rend un nom
    qui n'est dans AUCUNE table d'alias mais qui FORCE la validation. Au doute
    on valide — la latence est le bon prix ; le contraire laisserait passer
    exactement ce qu'on ferme ici.
    """
    if not isinstance(nom, str):
        return "?"
    table = _alias_canoniques()
    if table is None:
        return _FORCER_VALIDATION
    return table.get(nom, nom)


def _sentinel_check(obj: dict) -> dict | None:
    """
    Valide un tools/call via forge_sentinel avant envoi au hub.
    ProtÃ¨ge contre le tool poisoning (paper arxiv 2505.02279 s4.6).

    Bypass pour les tools READ-ONLY listes hors _SENTINEL_TOOLS â€” leurs
    args ne contiennent pas de patterns d'injection candidates et la
    validation ajoutait juste de la latence.

    Retourne None si OK, error dict si bloquÃ©.
    """
    if obj.get("method") != "tools/call":
        return None
    if _validate_action is None:
        return None  # sentinel indisponible -> fail-open

    params = obj.get("params", {})
    tool = _nom_canonique(params.get("name", "?"))
    if tool not in _SENTINEL_TOOLS:
        return None  # tool read-only / non-sensible -> bypass

    args = params.get("arguments", {})
    instruction = f"MCP tools/call: {tool}({json.dumps(args, ensure_ascii=False)[:200]})"
    try:
        result = _validate_action(instruction, tool, _AGENT)
        if not result.allowed:
            logger.warning(f"SENTINEL BLOCK: {tool} â€” {result.message}")
            return _err(-32003, f"Sentinel blocked: {result.message[:100]}", obj.get("id"))
    except Exception as e:
        logger.debug(f"Sentinel error (fail-open): {e}")
    return None


def _bridge_log(method: str, tool: str, latency_ms: float, response: bytes, req_id: Any):
    """Log l'appel dans network_log.db et met à jour le heartbeat du bridge."""
    try:
        import sqlite3

        db_path = _ROOT / "data" / "network_log.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            # 0. Schéma (ménage : ces tables n'étaient jamais créées -> "no such table:
            # bridge_logs" à CHAQUE appel). IF NOT EXISTS = idempotent.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bridge_logs "
                "(ts TEXT, method TEXT, tool TEXT, latency_ms REAL, status TEXT, req_id TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bridge_status (id TEXT PRIMARY KEY, last_seen TEXT)"
            )
            # 1. Insert log
            conn.execute(
                """
                INSERT INTO bridge_logs (ts, method, tool, latency_ms, status, req_id)
                VALUES (datetime('now'), ?, ?, ?, ?, ?)
            """,
                (method, tool, latency_ms, "OK" if response else "ERR", str(req_id)),
            )
            # 2. Heartbeat (last_seen)
            conn.execute("""
                INSERT INTO bridge_status (id, last_seen) VALUES ('stdio_bridge', datetime('now'))
                ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"bridge_log error: {e}")


def _handle_single(obj: dict) -> bytes | None:
    """Traite un Request unique. Retourne None si notification (pas de réponse)."""
    req_id = obj.get("id")

    err = _validate(obj)
    if err:
        if _is_notif(obj):
            return None
        err["id"] = req_id
        return json.dumps(err).encode()

    if not _rate.allow():
        if _is_notif(obj):
            return None
        return json.dumps(_err(-32029, "Rate limit exceeded", req_id)).encode()

    # Sentinel check — protection tool poisoning (arxiv 2505.02279 s4.6)
    sentinel_err = _sentinel_check(obj)
    if sentinel_err:
        if _is_notif(obj):
            return None
        return json.dumps(sentinel_err).encode()

    method = obj.get("method", "?")
    _tool_name = ""
    if method == "tools/call":
        _tool_name = " [" + str(obj.get("params", {}).get("name", "?")) + "]"
    logger.info(f"→ {method}{_tool_name} id={req_id}")
    # SPEC MCP §3.1 : tools/list_changed UNIQUEMENT apres notifications/initialized
    # Claude Desktop (Electron) ignore les notifs envoyees avant initialized.
    if method == "notifications/initialized":
        import threading as _th

        def _notify_changed():
            import time as _t

            _t.sleep(0.1)
            try:
                notif = json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
                    separators=(",", ":"),
                ).encode()
                _write_out(notif)
                logger.info("tools/list_changed envoyé post-initialized (spec §3.1)")
            except:
                pass

        _th.Thread(target=_notify_changed, daemon=True).start()

    if obj.get("method") == "tools/call":
        _pa = obj.get("params", {})
        if _pa.get("name") == "run":
            _ag = _pa.get("arguments", {})
            _c = _ag.get("code", "")
            if _c:
                import os as _os
                import tempfile

                _bridge_dir = str(__import__("pathlib").Path(__file__).resolve().parents[1] / ".bridge_tmp")
                _os.makedirs(_bridge_dir, exist_ok=True)
                _fd, _tmp = tempfile.mkstemp(suffix=".py", prefix="bri_", dir=_bridge_dir)
                _os.fdopen(_fd, "w", encoding="utf-8").write(_c)
                _ag["code_file"] = _tmp
                del _ag["code"]
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    t0 = time.monotonic()
    resp = _post(body, req_id)
    lat = round((time.monotonic() - t0) * 1000, 1)
    # ── Bridge → network_log SQLite + last_seen heartbeat ─────────────
    _bridge_log(method, _tool_name.strip("[] "), lat, resp, req_id)

    # Spec 4.1 : pas de réponse aux notifications
    if _is_notif(obj):
        logger.info(f"  notif {method} relayée (sans réponse)")
        return None

    logger.info(f"← {method}{_tool_name} id={req_id} {lat}ms")
    # Alerte si latence anormale
    if lat > 10000:
        logger.warning(
            f"[SLOW] {method}{_tool_name} id={req_id} lat={lat}ms — verifier timeout hub"
        )
    if lat == 0.0:
        logger.warning(
            f"[ZERO_LAT] {method}{_tool_name} id={req_id} — reponse cache ou court-circuit"
        )
    return resp


def _handle_batch(arr: list) -> bytes:
    """Spec 6 : batch concurrent, réponses en Array, notifications exclues."""
    if not arr:
        return json.dumps(_err(-32600, "Empty batch")).encode()
    results = []
    with ThreadPoolExecutor(max_workers=min(len(arr), 8)) as ex:
        futures = {ex.submit(_handle_single, item): item for item in arr if isinstance(item, dict)}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if r:
                    results.append(json.loads(r))
            except Exception as e:
                logger.error(f"Batch item: {e}")
    return json.dumps(results).encode() if results else b""


# ───────────────────────────────────────────────────────────────────────────────
# FALLBACK — si hub DOWN, bascule sur nokido_mcp_server.py direct
# ───────────────────────────────────────────────────────────────────────────────


def _fallback_stdio():
    """Hub indisponible - exécute le serveur MCP local directement (stdio)."""
    logger.warning("Hub DOWN - Bascule sur serveur local (stdio)")
    server_py = _ROOT / "tools" / "nokido_mcp_server.py"
    if not server_py.exists():
        logger.error(f"Serveur local non trouvé: {server_py}")
        sys.exit(1)

    # Windows : os.execv ne quote PAS les chemins avec espaces ("Script python IA")
    # -> python ouvrirait __import__("os").path.expanduser('~\Script') et crasherait le bridge (Claude
    # Desktop "Server disconnected"). subprocess (liste d'args) gère l'espace ; le
    # serveur local hérite stdin/stdout (MCP stdio), le bridge attend puis sort.
    import subprocess

    try:
        rc = subprocess.run([sys.executable, str(server_py)]).returncode
    except Exception as _e:
        logger.error(f"Fallback serveur local échoué: {_e}")
        rc = 1
    sys.exit(rc)


def _watch_capabilities() -> None:
    """Tail sandbox/reflexion.jsonl (miroir forge_swarm_bus). Sur capability.forged
    -> push notifications/tools/list_changed (Desktop re-fetch tools/list -> voit les
    outils forges). File-tail = robuste (pas de SSE), debounce 2s, gere rotation/trim."""
    mirror = _ROOT / "sandbox" / "reflexion.jsonl"
    last = 0.0
    try:
        pos = mirror.stat().st_size if mirror.exists() else 0
    except Exception:
        pos = 0
    while True:
        try:
            time.sleep(1.0)
            if not mirror.exists():
                pos = 0
                continue
            sz = mirror.stat().st_size
            if sz < pos:  # rotation / trim periodique du miroir
                pos = 0
            if sz == pos:
                continue
            with open(mirror, encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            if '"capability.forged"' in chunk and (time.time() - last) > 2.0:
                last = time.time()
                _write_out(json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
                    separators=(",", ":"),
                ).encode())
                logger.info("tools/list_changed push (capability.forged)")
        except Exception:
            time.sleep(2.0)


def _process_line(raw: bytes) -> None:
    """Traite UNE ligne JSON-RPC (parse + dispatch) et enqueue la reponse. Extrait de
    la boucle pour permettre le dispatch concurrent (fin du head-of-line blocking)."""
    if len(raw) > _MAX_BYTES:
        _write_out(json.dumps(_err(-32600, f"Payload too large: {len(raw)} bytes", None)).encode())
        return
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        _write_out(json.dumps(_err(-32700, f"Parse error: {e.msg}", None)).encode())
        return
    if isinstance(obj, list):
        resp = _handle_batch(obj)
    elif isinstance(obj, dict):
        resp = _handle_single(obj)
    else:
        resp = json.dumps(_err(-32600, "Must be Object or Array")).encode()
    if resp:
        _write_out(resp)


def run_bridge():
    logger.info(f"mcp_stdio_bridge v3.1 | agent={_AGENT} | hub={_HUB_URL}")
    sys.stderr.write(f"[bridge] Nokido MCP stdio->HTTP bridge v3.1\n[bridge] Hub: {_HUB_URL}\n")

    if not _wait_hub():
        _fallback_stdio()
        return  # jamais atteint si execv réussit

    # Watcher capabilities : push list_changed quand un outil est forge (tail bus).
    threading.Thread(target=_watch_capabilities, daemon=True, name="cap-watch").start()

    stdin = sys.stdin.buffer
    _start_writer()

    # Dispatch CONCURRENT borne : une requete lente (appel hub lourd) ne bloque plus les
    # suivantes (fin du head-of-line de la boucle serie). L'ordre de sortie n'a pas a etre
    # preserve : JSON-RPC correle par `id` (idem _handle_batch, deja concurrent). Le writer
    # thread unique serialise l'ecriture reelle.
    pool = ThreadPoolExecutor(max_workers=_DISPATCH_WORKERS, thread_name_prefix="rpc")
    try:
        for raw in stdin:
            raw = raw.strip()
            if raw:
                pool.submit(_process_line, raw)
    finally:
        pool.shutdown(wait=False)
        _OUT_Q.put(None)  # arret propre du writer


# ───────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ───────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run_bridge()
    except KeyboardInterrupt:
        logger.info("Arrêt (KeyboardInterrupt)")
    except BrokenPipeError:
        logger.info("Arrêt (BrokenPipeError — Claude Desktop a fermé le canal)")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
        sys.exit(1)
