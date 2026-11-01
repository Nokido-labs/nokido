"""Gardien du gateway Docker MCP sous la SESSION OWNER (service NokidoDockerMcpGateway, runAs=interactive).

Pourquoi un service a part (accord owner 28/10) : lance par le hub ou un job (comptes LaForgeSbx*/service),
`docker mcp gateway run` meurt au demarrage -- `unable to open database file (14)` : sa base
~/.docker/mcp/mcp-toolkit.db vit dans le profil owner. Sous la session owner, il demarre.

Le gardien :
- lance le gateway en transport HTTP `streaming` sur 127.0.0.1, protege par MCP_GATEWAY_AUTH_TOKEN, lu au
  coffre (cree au premier usage, valeur jamais journalisee). Jamais `--allow-unauthenticated` : le gateway
  expose mcp-add et code-mode, un port sans jeton donnerait ces pouvoirs a tout processus local ;
- attend Docker SANS le reveiller : Docker eteint est un etat VOULU (dynamique, a la demande), pas une panne ;
  seul le hub, quand on lui demande un outil docker_*, pose la demande au keeper ;
- relance le gateway s'il meurt pendant que Docker est leve, l'arrete si Docker s'endort ;
- ne sort pas sur Docker eteint (pas de boucle de relance du superviseur) et bat par beat_daemon.
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/passerelle Docker MCP sous la session owner (le hub lui parle en HTTP authentifie)"

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

NOM_JETON = "MCP_GATEWAY_AUTH_TOKEN"
PORT_DEFAUT = 8811
HOTE = "127.0.0.1"
TOUR_S = 5.0
JOURNAL = _RACINE_DONNEES / "logs" / "docker_mcp_gateway.log"
_STOP = False


def _log(msg: str) -> None:
    print("[docker_mcp_gateway] %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def argv_gateway() -> list:
    """Meme profil que les clients (~/.claude.json : --profile laforge), HTTP local authentifie."""
    profil = os.environ.get("LAFORGE_DOCKER_MCP_PROFILE", "laforge").strip()
    port = int(os.environ.get("LAFORGE_DOCKER_MCP_PORT") or PORT_DEFAUT)
    a = ["docker", "mcp", "gateway", "run"]
    if profil:
        a += ["--profile", profil]
    return a + ["--transport", "streaming", "--host", HOTE, "--port", str(port)]


def jeton() -> str:
    """Jeton du gateway au coffre machine (lisible par le hub) ; cree une fois s'il manque."""
    from nokido_agent.app import forge_secrets as fs
    v = fs.get_secret(NOM_JETON, required=False)
    if v:
        return v
    v = secrets.token_urlsafe(32)
    if not fs.set_secret(NOM_JETON, v):
        raise RuntimeError("jeton du gateway non pose au coffre")
    _log("jeton du gateway cree au coffre (valeur jamais journalisee)")
    return v


def env_gateway() -> dict:
    e = dict(os.environ)
    e[NOM_JETON] = jeton()
    return e


def _docker_up() -> bool:
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True,
                           errors="replace", timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:  # noqa: BLE001 - CLI absente ou bloquee : Docker non joignable, on attend
        return False


def _lancer(argv: list, env: dict):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    sortie = open(JOURNAL, "a", encoding="utf-8")  # noqa: SIM115 (vit avec l'enfant)
    _log("gateway lance : %s" % " ".join(argv))
    return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=sortie, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _arreter(proc) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception as e:  # noqa: BLE001
            _log("gateway non arrete (%s)" % type(e).__name__)


def tour(etat: dict, docker_up=None, lancer=None) -> str:
    """Un tour : EN_ATTENTE_DOCKER (Docker eteint, gateway arrete) | LANCE | VIVANT."""
    proc = etat.get("proc")
    vivant = proc is not None and proc.poll() is None
    if not (docker_up or _docker_up)():
        if vivant:
            _arreter(proc)
        etat["proc"] = None
        return "EN_ATTENTE_DOCKER"
    if not vivant:
        if proc is not None:
            etat["morts"] = etat.get("morts", 0) + 1
            _log("gateway mort (rc=%s), relance -- voir %s" % (proc.poll(), JOURNAL))
        etat["proc"] = (lancer or _lancer)(argv_gateway(), env_gateway())
        return "LANCE"
    return "VIVANT"


def _heartbeat(**champs) -> None:
    from nokido_agent.app.forge_heartbeat import beat_daemon
    beat_daemon("docker_mcp_gateway", **champs)


def _signal(signum, _frame) -> None:
    global _STOP
    _STOP = True


def main() -> int:
    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGINT, _signal)
    etat: dict = {}
    _log("gardien UP pid=%d, port=%s" % (os.getpid(), argv_gateway()[-1]))
    while not _STOP:
        try:
            s = tour(etat)
        except Exception as e:  # noqa: BLE001 - jamais mourir sur un tour : le dire et rebattre
            s = "ERREUR"
            _log("tour en echec : %s" % (repr(e)[:300]))
        try:
            _heartbeat(etat_gateway=s, port=int(argv_gateway()[-1]), morts=etat.get("morts", 0))
        except Exception as e:  # noqa: BLE001
            _log("pouls non ecrit (%s)" % type(e).__name__)
        fin = time.time() + TOUR_S
        while not _STOP and time.time() < fin:
            time.sleep(0.5)
    if etat.get("proc") is not None:
        _arreter(etat["proc"])
    _log("gardien arrete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
