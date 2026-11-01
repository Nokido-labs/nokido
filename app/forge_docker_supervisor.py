# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [GREEN]
DATE:2026-05-02 | VER:v_forge_docker_supervisor_v1
#FORGE:[score:88|agent:claude-opus-4.7|temp:0.00|risk:0.30|color:GREEN|attempt:1]
CONTRAINTE: Docker MCP gateway supervisor (cold-start + stdio bridge + JSON-RPC)

ORGANE (CLAUDE.md §10) :
  - SN peripherique (cousin de forge_mcp_registry).
  - Vascularisation : flux Hub :8766 -> stdio Popen('docker mcp gateway run')
    -> retour string, namespace docker_*.
  - Hemorragie : si daemon Docker down ou subprocess crash, on retourne
    'ERR: ...' propre (jamais d'exception non capturee dans le hub).

POURQUOI UN NOUVEAU MODULE (anti-duplication CLAUDE.md §3) :
  - forge_mcp_registry._handle_netcfg_proxy fait du HTTP -> netcfg-mcp :8767.
    Docker MCP n'expose PAS de HTTP, uniquement stdio JSON-RPC.
  - forge_runner.py fait du fire-forget mmap, pas du JSON-RPC bidirectionnel
    avec request id matching.
  - forge_handler_advanced.py / forge_handler_build.py utilisent run_python
    pour subprocess one-shot, pas un daemon long-lived a stdin partage.
  - Donc : module dedie minimal, pattern singleton lazy, request_id +
    asyncio.Future map pour multiplexer plusieurs in-flight calls.

USAGE :
  >>> from forge_docker_supervisor import DockerSupervisor
  >>> sup = DockerSupervisor.instance()
  >>> await sup.ensure_daemon()                 # cold-start si besoin
  >>> tools = await sup.list_tools()            # ['docker', 'compose', ...]
  >>> out = await sup.call_tool('docker', {'cmd': 'ps'}, timeout=15)
"""

from __future__ import annotations

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:88|agent:claude-opus-4.7|temp:0.00|risk:0.30|color:GREEN|attempt:1]"

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Nokido.DockerSupervisor")

# Source de verite pour le binaire Python (CLAUDE.md §11)
try:
    from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON  # noqa: F401  (futur usage)
except Exception:
    LAFORGE_PYTHON = sys.executable

DOCKER_DESKTOP_PATH = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
DAEMON_BOOT_TIMEOUT = 90.0  # s
DAEMON_POLL_INTERVAL = 2.0  # s
GATEWAY_CMD = ["docker", "mcp", "gateway", "run"]
# Meme profil que les clients (~/.claude.json : `docker mcp gateway run --profile laforge`, 28/10) : sans lui,
# le gateway du hub chargeait une configuration VIDE, un autre inventaire que celui des clients.
DOCKER_MCP_PROFIL_DEFAUT = "laforge"


# MODE SERVICE (28/10, accord owner) : le hub ne lance plus le gateway sous son compte (il y meurt, base dans le
# profil owner) ; il reveille le service NokidoDockerMcpGateway (runAs=interactive, tools/forge_docker_mcp_gateway.py)
# et lui parle en HTTP streaming authentifie. LAFORGE_DOCKER_MCP_TRANSPORT=stdio rend l'ancien comportement.
SERVICE_GATEWAY = "NokidoDockerMcpGateway"
PORT_GATEWAY_DEFAUT = 8811
NOM_JETON_GATEWAY = "MCP_GATEWAY_AUTH_TOKEN"
DELAI_PORT_GATEWAY_S = 90.0


def _mode_service() -> bool:
    return os.environ.get("LAFORGE_DOCKER_MCP_TRANSPORT", "service").strip().lower() != "stdio"


def _port_gateway() -> int:
    return int(os.environ.get("LAFORGE_DOCKER_MCP_PORT") or PORT_GATEWAY_DEFAUT)


def _url_gateway() -> str:
    return f"http://127.0.0.1:{_port_gateway()}/mcp"


def _importer_app(nom: str):
    import importlib
    try:
        return importlib.import_module("nokido_agent.app." + nom)
    except ImportError as e:
        logger.debug("nokido_agent.app.%s introuvable (%s) : racine du depot ajoutee au chemin", nom, e)
        racine = str(Path(__file__).resolve().parent.parent)
        if racine not in sys.path:
            sys.path.insert(0, racine)
        return importlib.import_module("nokido_agent.app." + nom)


def _jeton_gateway() -> Optional[str]:
    return _importer_app("forge_secrets").get_secret(NOM_JETON_GATEWAY, required=False)


def _demarrer_service_gateway() -> None:
    """Reveil du service par le superviseur (meme route et memes en-tetes que la regulation)."""
    import urllib.request as _ur
    rm = _importer_app("forge_resource_manager")
    req = _ur.Request(rm._url_reveil(SERVICE_GATEWAY), method="POST",
                      headers=rm._supervisor_auth_headers("DOCKER_SUPERVISOR"))
    with _ur.urlopen(req, timeout=5):
        pass


def _port_ouvert(port: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        s.close()


def _lire_reponse(brut: str, ctype: str) -> Optional[dict]:
    """Reponse JSON-RPC du transport streaming : JSON direct ou flux SSE (`data: {...}`)."""
    if not brut or not brut.strip():
        return None
    if "text/event-stream" in (ctype or ""):
        for ligne in brut.splitlines():
            if ligne.startswith("data:"):
                try:
                    obj = json.loads(ligne[5:].strip())
                except ValueError:  # muet-ok : ligne SSE non JSON (ping, fragment) -- on lit la suivante
                    continue
                if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                    return obj
        return None
    return json.loads(brut)


def _post_http(url: str, corps: dict, jeton: str, session: Optional[str] = None, timeout: float = 15.0):
    import urllib.request as _ur
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "Authorization": f"Bearer {jeton}"}
    if session:
        h["Mcp-Session-Id"] = session
    req = _ur.Request(url, data=json.dumps(corps).encode("utf-8"), headers=h, method="POST")
    with _ur.urlopen(req, timeout=timeout) as r:
        sid = r.headers.get("Mcp-Session-Id") or session
        return _lire_reponse(r.read().decode("utf-8", errors="replace"), r.headers.get("Content-Type", "")), sid


def _gateway_cmd() -> List[str]:
    """Commande du gateway, profil inclus (LAFORGE_DOCKER_MCP_PROFILE ; vide = pas de profil)."""
    profil = os.environ.get("LAFORGE_DOCKER_MCP_PROFILE", DOCKER_MCP_PROFIL_DEFAUT).strip()
    return list(GATEWAY_CMD) + (["--profile", profil] if profil else [])
DOCKER_MCP_CATALOG_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "docker_mcp_catalog.json"
CATALOG_MAX_AGE_HOURS = 24


# PROCEDE REACTIF (owner 28/10) : le hub RECLAME Docker en son nom et le RELACHE apres RELACHE_APRES_S sans appel
# docker_* (la derniere reclamation relachee arrete Docker sans attendre le TTL de 900 s de docker.wanted).
PROPRIETAIRE_DOCKER = "HUB_DOCKER_MCP"
RELACHE_APRES_S = 120.0


def _keeper():
    """Module du keeper, quel que soit le chemin d'import (28/10 : lance en SCRIPT, le module n'a que app/ sur
    sys.path et `from tools.forge_docker_keeper` echouait -- le reveil de Docker etait impossible)."""
    import importlib
    for nom in ("nokido_agent.tools.forge_docker_keeper", "tools.forge_docker_keeper", "forge_docker_keeper"):
        try:
            return importlib.import_module(nom)
        except ImportError as e:
            logger.debug("keeper introuvable sous %s (%s) : chemin suivant", nom, e)
            continue
    racine = str(Path(__file__).resolve().parent.parent)
    if racine not in sys.path:
        sys.path.insert(0, racine)
    return importlib.import_module("nokido_agent.tools.forge_docker_keeper")


def _importer_ensure_docker():
    return _keeper().ensure_docker


def _sous_test_sans_keeper_simule() -> bool:
    """Sous pytest, le VRAI keeper n'est jamais touche (28/10 : une relache reelle arrete Docker sur la machine)
    sauf si le test a remplace `_keeper` -- meme classe que le registre des evinces ecrit par un test."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and getattr(_keeper, "__name__", "") == "_keeper"


def _demander_docker() -> None:
    """Reclamation NOMMEE (compteur du keeper + docker.wanted)."""
    if _sous_test_sans_keeper_simule():
        return
    _keeper().claim_docker(PROPRIETAIRE_DOCKER)


def _relacher_docker() -> None:
    if _sous_test_sans_keeper_simule():
        return
    try:
        _keeper().release_claim(PROPRIETAIRE_DOCKER)
    except Exception as e:  # noqa: BLE001 - non delivree : le TTL de docker.wanted reste le filet
        logger.warning("relache de Docker non delivree (%s)", type(e).__name__)


class DockerSupervisorError(RuntimeError):
    """Erreur niveau supervisor (daemon down, gateway crash, RPC timeout)."""


class DockerSupervisor:
    """
    Singleton lazy : garde un Popen('docker mcp gateway run') en vie,
    multiplexe les JSON-RPC requests via id counter + asyncio.Future map.

    Concurrency model :
      - Une seule instance hub-wide (DockerSupervisor.instance()).
      - Un reader thread daemon lit stdout en continu et route les
        responses vers les Future via _pending[id].
      - call_tool est async : pose un Future, ecrit la requete sur stdin,
        attend le Future avec timeout.
    """

    _instance: Optional["DockerSupervisor"] = None
    _instance_lock = threading.Lock()

    # ----- singleton -------------------------------------------------------

    @classmethod
    def instance(cls) -> "DockerSupervisor":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._req_id: int = 0
        self._pending: Dict[int, "asyncio.Future[dict]"] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._daemon_up: bool = False

    # ----- daemon health ---------------------------------------------------

    @staticmethod
    def _docker_info_ok() -> bool:
        try:
            r = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    async def ensure_daemon(self) -> None:
        """
        Garantit que `docker info` repond. Sinon lance Docker Desktop et
        attend jusqu a DAEMON_BOOT_TIMEOUT.
        Raise DockerSupervisorError si timeout.
        """
        if self._daemon_up and self._docker_info_ok():
            return

        if self._docker_info_ok():
            self._daemon_up = True
            return

        # Reveil dynamique : pose docker.wanted, le keeper lance Docker.
        try:
            _demander_docker()
        except Exception as e:
            raise DockerSupervisorError(
                f"BLOQUE_PAR_DEPENDANCE : demande docker.wanted impossible ({e})")

        # Poll
        deadline = time.monotonic() + DAEMON_BOOT_TIMEOUT
        while time.monotonic() < deadline:
            if self._docker_info_ok():
                self._daemon_up = True
                logger.info("Docker daemon ready")
                return
            await asyncio.sleep(DAEMON_POLL_INTERVAL)
        raise DockerSupervisorError(
            f"BLOQUE_PAR_DEPENDANCE : docker non réveillé par le keeper "
            f"(apres {DAEMON_BOOT_TIMEOUT}s)")

    # ----- gateway lifecycle ----------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def spawn_gateway_stdio(self) -> None:
        """
        Lance `docker mcp gateway run` en subprocess long-lived.
        Idempotent : si deja en vie, ne fait rien.
        """
        if self._alive():
            return

        await self.ensure_daemon()

        # Capture la loop courante pour le reader thread (call_soon_threadsafe)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                _gateway_cmd(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # unbuffered binary
                creationflags=creationflags,
            )
        except FileNotFoundError as e:
            raise DockerSupervisorError(f"`docker mcp gateway run` introuvable (CLI Docker MCP plugin manquant): {e}")

        # Reset id counter et pending map a chaque spawn
        self._req_id = 0
        self._pending.clear()
        self._tools_cache = None

        # Demarre le reader thread (daemon=True : meurt avec le hub)
        self._reader_thread = threading.Thread(target=self._reader_loop, name="DockerSupervisorReader", daemon=True)
        self._reader_thread.start()
        logger.info("docker mcp gateway spawned pid=%s", self._proc.pid)

        # Initialize handshake (MCP requirement)
        try:
            await self._jsonrpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "laforge-hub", "version": "1.0"},
                },
                timeout=10,
            )
            # notification initialized
            self._send_raw({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception as e:
            proc = self._proc
            rc = proc.poll() if proc is not None else None
            if rc is None and proc is not None and "closed" in str(e):
                # stdout deja ferme mais processus pas encore sorti (cas reel 28/10 11:53) : attendre sa sortie.
                try:
                    rc = proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    rc = None
            if rc is not None:
                # Gateway MORT au demarrage (28/10) : sa sortie d'erreur, capturee en PIPE, n'etait jamais lue ;
                # on continuait, et l'erreur suivante (« stdin write failed ») masquait la cause.
                try:
                    tail = (proc.stderr.read() or b"")[-1500:].decode("utf-8", errors="replace").strip()
                except Exception as lecture:  # noqa: BLE001
                    tail = "stderr illisible (%s)" % type(lecture).__name__
                self._proc = None
                logger.warning("Docker MCP gateway ferme au demarrage (rc=%s) : %s", rc, tail)
                raise DockerSupervisorError(f"gateway ferme au demarrage (rc={rc}) : {tail or 'stderr vide'}") from e
            logger.warning("Docker MCP handshake echoue: %s", e)

    def _reader_loop(self) -> None:
        """Thread bloquant : lit stdout ligne par ligne (NDJSON)."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                try:
                    msg = json.loads(raw.decode("utf-8", errors="replace").strip())
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_docker_supervisor.py', 233, exc_info=True)
                    continue
                rid = msg.get("id")
                if rid is None:
                    # notification, ignore
                    continue
                fut = self._pending.pop(rid, None)
                if fut is None or self._loop is None:
                    continue
                # Marshal back to the asyncio loop
                self._loop.call_soon_threadsafe(lambda f=fut, m=msg: f.set_result(m) if not f.done() else None)
        except Exception as e:
            logger.error("Docker reader loop crashed: %s", e)
        finally:
            # Reveiller tous les pending pour ne pas leaker
            if self._loop is not None:
                for fid, fut in list(self._pending.items()):
                    self._loop.call_soon_threadsafe(
                        lambda f=fut: f.set_exception(DockerSupervisorError("gateway closed")) if not f.done() else None
                    )
                self._pending.clear()

    def _send_raw(self, obj: dict) -> None:
        if not self._alive() or self._proc is None or self._proc.stdin is None:
            raise DockerSupervisorError("gateway not running")
        line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except Exception as e:
            raise DockerSupervisorError(f"stdin write failed: {e}")

    async def _jsonrpc(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        """
        JSON-RPC 2.0 request/response avec id matching.
        Lazy spawn du gateway si pas encore demarre.
        """
        if _mode_service():
            return await self._jsonrpc_http(method, params, timeout)
        if not self._alive():
            await self.spawn_gateway_stdio()

        async with self._lock:
            self._req_id += 1
            rid = self._req_id

        loop = asyncio.get_running_loop()
        fut: "asyncio.Future[dict]" = loop.create_future()
        self._pending[rid] = fut

        self._send_raw(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params,
            }
        )

        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise DockerSupervisorError(f"timeout {timeout}s on {method}")

        if "error" in resp:
            err = resp["error"]
            raise DockerSupervisorError(f"{method} error: {err}")
        return resp.get("result", {})

    # ----- public API ------------------------------------------------------

    async def list_tools(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        Retourne la liste des tools exposes par le gateway.
        Cache lazy : invalide si force=True.
        """
        if self._tools_cache is not None and not force:
            return self._tools_cache
        result = await self._jsonrpc("tools/list", {}, timeout=15)
        tools = result.get("tools", [])
        self._tools_cache = tools
        try:
            self._write_catalogue(tools)
        except Exception as e:
            logger.debug("docker catalogue write failed: %s", e)
        return tools

    def _write_catalogue(self, tools: List[Dict[str, Any]]) -> None:
        try:
            path = DOCKER_MCP_CATALOG_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "horodatage": datetime.now(timezone.utc).isoformat(),
                "outils": [
                    {
                        "name": t.get("name"),
                        "description": t.get("description"),
                        "inputSchema": t.get("inputSchema"),
                    }
                    for t in (tools or [])
                    if isinstance(t, dict)
                ],
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("docker catalogue serialize failed: %s", e)
            raise

    async def call_tool(self, name: str, args: dict, timeout: float = 15.0) -> str:
        """
        Appelle un tool du gateway. `name` est le nom NATIF (sans prefixe
        docker_). Retourne content[0].text si dispo, sinon str(result).
        """
        # docker.wanted expire (TTL 900 s) et ensure_daemon ne le repose pas quand le demon est leve :
        # chaque appel le renouvelle, sinon le keeper eteint Docker sous un gateway en service.
        try:
            _demander_docker()
        except Exception as e:
            logger.debug("docker.wanted non renouvele: %s", e)
        self._armer_relache()
        result = await self._jsonrpc(
            "tools/call",
            {"name": name, "arguments": args or {}},
            timeout=timeout,
        )
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                return str(first["text"])
        return json.dumps(result, ensure_ascii=False)

    # ----- shutdown --------------------------------------------------------

    def _armer_relache(self) -> None:
        """(Re)arme la relache de Docker apres RELACHE_APRES_S sans appel. Hors boucle asyncio : rien."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        t = getattr(self, "_timer_relache", None)
        if t is not None:
            t.cancel()
        self._timer_relache = loop.call_later(RELACHE_APRES_S, self._relacher_inactif)

    def _relacher_inactif(self) -> None:
        self._timer_relache = None
        self._session_http = None
        logger.info("Docker relache par le hub apres %.0f s sans appel docker_*", RELACHE_APRES_S)
        _relacher_docker()

    async def _assurer_service_http(self) -> None:
        """Docker (docker.wanted) -> service NokidoDockerMcpGateway -> port -> initialize. Echecs NOMMES."""
        if getattr(self, "_session_http", None):
            return
        await self.ensure_daemon()
        try:
            _demarrer_service_gateway()
        except Exception as e:  # noqa: BLE001
            raise DockerSupervisorError(
                f"BLOQUE_PAR_DEPENDANCE : reveil de {SERVICE_GATEWAY} non delivre ({type(e).__name__}: {e})") from e
        fin = time.monotonic() + DELAI_PORT_GATEWAY_S
        while not _port_ouvert(_port_gateway()):
            if time.monotonic() > fin:
                raise DockerSupervisorError(
                    f"BLOQUE_PAR_DEPENDANCE : {SERVICE_GATEWAY} sans port {_port_gateway()} apres "
                    f"{DELAI_PORT_GATEWAY_S:.0f} s (voir logs/docker_mcp_gateway.log)")
            await asyncio.sleep(1.0)
        jeton = _jeton_gateway()
        if not jeton:
            raise DockerSupervisorError(
                f"BLOQUE_PAR_DEPENDANCE : jeton {NOM_JETON_GATEWAY} absent du coffre (le gardien le cree au lancement)")
        rep, sid = await asyncio.to_thread(
            _post_http, _url_gateway(),
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "laforge-hub", "version": "1.0"}}},
            jeton, None, 15.0)
        if rep is None or "error" in rep:
            raise DockerSupervisorError(f"gateway HTTP : initialize refuse ({rep})")
        self._jeton_http, self._session_http = jeton, sid or "sans-session"
        await asyncio.to_thread(_post_http, _url_gateway(),
                                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                jeton, self._session_http, 10.0)

    async def _jsonrpc_http(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        await self._assurer_service_http()
        async with self._lock:
            self._req_id += 1
            rid = self._req_id
        try:
            rep, sid = await asyncio.to_thread(
                _post_http, _url_gateway(), {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                self._jeton_http, self._session_http, timeout)
        except Exception as e:  # noqa: BLE001 - session perdue (gateway relance, Docker endormi) : la refaire
            self._session_http = None
            raise DockerSupervisorError(f"gateway HTTP injoignable sur {method} ({type(e).__name__}: {e})") from e
        if sid:
            self._session_http = sid
        if rep is None:
            raise DockerSupervisorError(f"gateway HTTP : reponse vide a {method}")
        if "error" in rep:
            raise DockerSupervisorError(f"{method} error: {rep['error']}")
        return rep.get("result", {})

    def shutdown(self) -> None:
        """Termine le gateway proprement. A appeler au shutdown du hub."""
        self._session_http = None
        if not self._alive() or self._proc is None:
            self._proc = None
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        except Exception as e:
            logger.warning("Shutdown gateway: %s", e)
        finally:
            self._proc = None
            self._tools_cache = None
            self._daemon_up = False


def get_supervisor() -> DockerSupervisor:
    """Helper pour symetrie avec get_registry / get_state_manager."""
    return DockerSupervisor.instance()


def catalogue_en_cache(path: Optional[Path] = None) -> Dict[str, Any]:
    """Lit le catalogue Docker MCP depuis le cache SANS spawn/ensure_daemon."""
    cat_path = path or DOCKER_MCP_CATALOG_PATH
    try:
        if not cat_path.exists():
            return {"etat": "ABSENT", "outils": []}
        try:
            raw = cat_path.read_text(encoding="utf-8")
        except Exception:
            return {"etat": "ABSENT", "outils": []}
        try:
            data = json.loads(raw)
        except Exception:
            return {"etat": "PERIME", "outils": []}
        outils = data.get("outils") if isinstance(data, dict) else None
        if not isinstance(outils, list):
            return {"etat": "PERIME", "outils": []}
        horo = data.get("horodatage") if isinstance(data, dict) else None
        if not horo:
            return {"etat": "PERIME", "outils": outils}
        try:
            ts = datetime.fromisoformat(str(horo).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now - ts > timedelta(hours=CATALOG_MAX_AGE_HOURS):
                return {"etat": "PERIME", "outils": outils}
        except Exception:
            return {"etat": "PERIME", "outils": outils}
        return {"etat": "FRAIS", "outils": outils}
    except Exception:
        return {"etat": "ABSENT", "outils": []}


__all__ = [
    "DockerSupervisor",
    "DockerSupervisorError",
    "get_supervisor",
    "catalogue_en_cache",
    "DOCKER_MCP_CATALOG_PATH",
    "main",
]


def main(argv: Optional[List[str]] = None) -> int:
    """`--rafraichir-catalogue` : seule voie de REMPLISSAGE du cache lu par tools/list (28/10). Reveille Docker
    par la voie dynamique (ensure_daemon -> docker.wanted), liste les outils, ecrit le cache, rend la main au
    gateway. Une ligne JSON : RAFRAICHI (noms) ou ECHEC (motif) -- jamais un vide muet. rc 0 / 2."""
    import argparse
    ap = argparse.ArgumentParser(prog="forge_docker_supervisor")
    ap.add_argument("--rafraichir-catalogue", action="store_true")
    ap.add_argument("--timeout", type=float, default=DAEMON_BOOT_TIMEOUT + 60.0)
    a = ap.parse_args(argv)
    if not a.rafraichir_catalogue:
        ap.print_help()
        return 0
    sup = get_supervisor()
    try:
        outils = asyncio.run(asyncio.wait_for(sup.list_tools(force=True), a.timeout))
        noms = [t.get("name") for t in outils if isinstance(t, dict) and t.get("name")]
        print(json.dumps({"etat": "RAFRAICHI", "outils": noms, "catalogue": str(DOCKER_MCP_CATALOG_PATH)},
                         ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"etat": "ECHEC", "motif": f"{type(e).__name__}: {e}"[:400]}, ensure_ascii=False))
        return 2
    finally:
        sup.shutdown()
        _relacher_docker()  # procede reactif : le rafraichissement fini, Docker n'est plus reclame par le hub


if __name__ == "__main__":
    sys.exit(main())
