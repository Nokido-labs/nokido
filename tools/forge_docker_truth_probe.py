"""forge_docker_truth_probe.py — vérité terrain sur la vie de Docker, en continu.

Question (2026-07-22) : `NokidoDockerKeeper` déclare `docker info DOWN` puis exécute
`wsl --shutdown` + relance. Docker est-il REELLEMENT mort a cet instant, ou la sonde
du keeper (pipe `dockerDesktopLinuxEngine`, propriete de la session owner) rend-elle
un faux negatif depuis un compte de service ?

L'affirmation est TEMPORELLE et intermittente : elle ne peut pas se refuter par une
commande lancee a la demande — quand on regarde, la boucle s'est arretee. D'ou cette
sonde CONTINUE, qui echantillonne trois signaux INDEPENDANTS du pipe prive :

  - port_8080   : SearXNG est publie par com.docker.backend.exe -> si le port repond,
                  le moteur Docker SERT, quoi qu'en dise le pipe. (Identifier par
                  CAPACITE SERVIE, pas par nom ni par handle prive.)
  - backend_proc: presence de com.docker.backend.exe / vmmem (le corps est la ou non).
  - pipe        : existence du named pipe, c'est-a-dire ce que le keeper croit voir.

Croiser ensuite avec les lignes `docker info DOWN` du log du keeper :
  - port OK + proc OK au moment du DOWN  -> FAUX POSITIF du keeper (il tue un sain).
  - tout KO                              -> Docker meurt vraiment, chercher ailleurs.

Sortie : sandbox/docker_truth.jsonl (une ligne par echantillon, append-only).
Aucun subprocess, aucune ecriture hors sandbox, lecture seule sur le systeme.

Usage : run action=run_job script=tools/forge_docker_truth_probe.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sandbox" / "docker_truth.jsonl"
PIPE = r"\\.\pipe\dockerDesktopLinuxEngine"
TICK_S = 10.0
DURATION_S = float(os.environ.get("DOCKER_TRUTH_DURATION_S", "10800"))  # 3 h par defaut


def _port_ok(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _pipe_present() -> bool:
    try:
        return os.path.exists(PIPE)
    except OSError:
        return False


def _procs() -> dict:
    """Presence des process Docker. psutil si dispo, sinon champ absent (jamais fatal)."""
    try:
        import psutil
    except ImportError:
        return {}
    found = {"backend": False, "desktop": False, "vmmem": False}
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info.get("name") or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if "com.docker.backend" in n:
            found["backend"] = True
        elif n == "docker desktop.exe":
            found["desktop"] = True
        elif n.startswith("vmmem"):
            found["vmmem"] = True
    return found


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + DURATION_S
    prev_key = None
    n = 0
    while time.time() < deadline:
        rec = {
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "port_8080": _port_ok(8080),
            "pipe": _pipe_present(),
            "procs": _procs(),
        }
        # N'ecrire que les CHANGEMENTS d'etat + un battement par minute : le fichier
        # reste lisible et la transition (le seul moment interessant) saute aux yeux.
        key = (rec["port_8080"], rec["pipe"], tuple(sorted(rec["procs"].items())))
        if key != prev_key or n % 6 == 0:
            rec["transition"] = key != prev_key
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            prev_key = key
        n += 1
        time.sleep(TICK_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
