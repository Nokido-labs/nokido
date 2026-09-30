"""Deploie un binaire Go compile vers son emplacement de service, sous compte privilegie.

POURQUOI CET OUTIL EXISTE (2026-09-19). Le correctif du 2026-09-18 sur
`go_services/forge_dispatcher/main.go` — passer l'adresse d'ecoute de `:8779`
(toutes interfaces) a `127.0.0.1:8779` — etait COMMITE et pourtant SANS EFFET :
le service executait toujours l'ancien binaire. `netstat` le montrait, le code
disait l'inverse. `CODE DECLARE != RUNTIME OBSERVE`, sur le seul port du systeme
qui ecoutait hors loopback.

Ce qui manquait n'etait pas le correctif mais le GESTE DE DEPLOIEMENT, et il
n'etait pas faisable a la main : le compte du bac a sable n'a pas le droit
d'ecrire dans `go_services/` (`go build -o` y rend « Access is denied », que le
service tourne ou non — c'est l'ACL du dossier, pas un verrou de fichier). Le
compte prive n'est donc pas le probleme a contourner, c'est la raison d'etre de
`trusted_script` : un script GIT-TRACKE, revu, execute sous `LaForgeTrusted`.

CE QU'IL NE FAIT PAS, ET C'EST VOULU : il n'arrete ni ne relance le service.
Arreter un service est une decision de disponibilite qui appartient au
superviseur (`forge_supervisor_ctl`) et, au-dessus, a l'owner. Cet outil REFUSE
de deployer tant que le port est occupe, plutot que de liberer lui-meme ce qu'il
ne sait pas remettre en marche.

Usage :
    forge_go_service_deploy.py --service forge_dispatcher            (dry-run)
    forge_go_service_deploy.py --service forge_dispatcher --apply
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploiement"

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GO_DIR = ROOT / "go_services"

# Port declare par chaque service, pour refuser un deploiement a chaud.
# Il ne s'agit PAS de piloter le service : seulement de constater qu'il tourne
# encore, auquel cas ecraser son binaire est au mieux inutile, au pire un
# remplacement partiel.
PORTS_CONNUS = {"forge_dispatcher": 8779}


def _port_occupe(port: int) -> bool:
    """Vrai si QUELQU'UN ecoute — on teste le loopback ET l'interface generique.

    Un service qui ecoute sur `0.0.0.0` accepte aussi le loopback, donc un seul
    test suffit en pratique ; on garde les deux parce que c'est exactement la
    propriete qu'on est en train de corriger et qu'on ne veut pas dependre d'elle.
    """
    for hote in ("127.0.0.1", "localhost"):
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex((hote, port)) == 0:
                return True
        finally:
            s.close()
    return False


def _empreinte(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def deployer(service: str, apply: bool) -> int:
    src = GO_DIR / service
    if not (src / "main.go").is_file():
        print(f"[deploy] {service} : pas de main.go sous {src} — rien a construire")
        return 2
    cible = src / f"{service}.exe"
    port = PORTS_CONNUS.get(service)

    if port and _port_occupe(port):
        # REFUS PLUTOT QUE DEGRADATION : ecraser le binaire d'un service vivant
        # laisse un etat qu'on ne sait pas decrire — l'ancien tourne encore, le
        # nouveau est sur le disque, et rien ne dit lequel repartira.
        print(f"[deploy] REFUS : le port {port} ecoute encore. Arreter le service "
              f"d'abord (forge_supervisor_ctl stop <service>), puis relancer ce "
              f"deploiement, puis le redemarrer.")
        return 3

    # On construit TOUJOURS hors du depot : si la construction echoue, le binaire
    # en place reste intact. Un `go build -o <cible>` ecraserait avant de savoir.
    tmp = Path(os.environ.get("TEMP", "/tmp")) / f"{service}.{int(time.time())}.exe"
    env = dict(os.environ, GOFLAGS="-buildvcs=false",
               GOCACHE=os.environ.get("GOCACHE", str(Path(os.environ.get("TEMP", "/tmp")) / "gocache")))
    # `errors="replace"` : en mode texte sans lui, un octet non-UTF8 dans la
    # sortie du compilateur fait planter le fil de lecture de subprocess — et on
    # perdrait le message d'erreur au moment precis ou on en a besoin. Signale
    # par le gate anti-regression au commit de cet outil.
    r = subprocess.run(["go", "build", "-o", str(tmp), "."], cwd=str(src),
                       capture_output=True, text=True, errors="replace",
                       env=env, timeout=600)
    if r.returncode != 0 or not tmp.is_file():
        print(f"[deploy] BUILD ECHOUE ({r.returncode}) :\n{(r.stderr or r.stdout)[:800]}")
        return 1

    neuf = _empreinte(tmp)
    ancien = _empreinte(cible) if cible.is_file() else "(absent)"
    print(f"[deploy] {service} : construit={neuf} en_place={ancien} "
          f"taille={tmp.stat().st_size}")
    if ancien == neuf:
        print("[deploy] IDENTIQUE — rien a deployer (le binaire en place est deja "
              "celui que la source produit)")
        tmp.unlink(missing_ok=True)
        return 0

    if not apply:
        print("[deploy] dry-run : --apply pour remplacer")
        tmp.unlink(missing_ok=True)
        return 0

    if cible.is_file():
        # GELER, JAMAIS SUPPRIMER : la sauvegarde horodatee permet de revenir sans
        # reconstruire, y compris si la source a bouge entre-temps.
        sauve = cible.with_suffix(f".exe.avant_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(cible, sauve)
        print(f"[deploy] sauvegarde : {sauve.name}")

    shutil.copy2(tmp, cible)
    tmp.unlink(missing_ok=True)
    # RELIRE plutot que croire la copie : `shutil` ne leve pas toujours sur une
    # ecriture partielle, et c'est exactement le genre de succes silencieux qui
    # ferait redemarrer un service sur un binaire tronque.
    relu = _empreinte(cible)
    if relu != neuf:
        print(f"[deploy] ECHEC : relecture {relu} != construit {neuf}")
        return 1
    print(f"[deploy] DEPLOYE et RELU ({relu}) — redemarrer le service pour que "
          f"l'effet existe : un binaire sur le disque n'est pas un processus.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--service", required=True, help="nom du dossier sous go_services/")
    p.add_argument("--apply", action="store_true", help="remplacer reellement")
    a = p.parse_args()
    return deployer(a.service, a.apply)


if __name__ == "__main__":
    sys.exit(main())
