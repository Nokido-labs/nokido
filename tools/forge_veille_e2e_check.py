# -*- coding: utf-8 -*-
"""E2E de la chaine de veille : prothese Docker -> SearXNG -> Crawl4AI -> bail.

POURQUOI CE SCRIPT EXISTE
=========================
La chaine de veille traverse une PROTHESE (Docker, avec `searxng-laforge` et
`laforge-crawl4ai`) et non un organe. Sa panne ne se lit donc pas comme une maladie :
elle se lit comme une degradation SILENCIEUSE. Mesure du 2026-08-24 deja consignee
dans `forge_crawl_tool` — sans Crawl4AI, le repli `urllib` rend le chrome d'une page
rendue en JavaScript (88 caracteres pour un README entier) et « les veilles tournent
aveugles en ayant l'air de tourner ».

Ce controle refuse la lecture binaire up/down. Il rend CINQ etages, parce qu'un port
ouvert ne prouve pas qu'un service repond, et qu'un service qui repond ne prouve pas
qu'il sert encore quelque chose :

    PROTHESE   le moteur Docker est-il debout (vu par son keeper, pas par nous)
    TRANSPORT  le port accepte-t-il une connexion
    APPLICATIF le service rend-il 200
    CAPACITE   rend-il un RESULTAT utile (des resultats de recherche, du markdown)
    CHAINE     `forge_crawl_tool` passe-t-il vraiment par le tier 1, ou en repli
    BAIL       l'usage a-t-il prolonge `docker.wanted` (sinon relache en pleine veille)

Chaque etage vaut OK / KO / INDETERMINE, avec sa RAISON. Jamais un vide lu comme un
succes : un compte sans acces au loopback rend « injoignable » exactement comme un
service mort, et cette confusion a deja coute (cf. RULES_SHARED, timeout muet a 120 s).

Usage : run action=shell network=true — le compte doit voir le loopback.
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/controle-chaine-veille"

import json
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEARXNG = os.environ.get("LAFORGE_SEARXNG_URL", "http://127.0.0.1:8080")
CRAWL4AI = os.environ.get("CRAWL4AI_URL", "http://127.0.0.1:11235")
TEMOIN = os.environ.get("E2E_URL_TEMOIN", "https://example.com")
WANT = ROOT / "sandbox" / "docker.wanted"
HB_KEEPER = ROOT / "sandbox" / "docker_keeper.heartbeat"


def _port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Sonde de port. Delegue a `forge_ports.probe`, qui fait deja exactement ca.

    La premiere version reecrivait le `socket.create_connection` : le cliquet de
    duplication l'a signale (`forge_ports.py | forge_veille_e2e_check.py`) et il
    avait raison — une primitive qui existe se cable, elle ne se reecrit pas.
    Le repli local ne sert que si le module est introuvable, et il le DIT.
    """
    try:
        from nokido_agent.tools.forge_ports import probe
    except Exception:  # noqa: BLE001 - repli assume, jamais silencieux
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
    return bool(probe(port, host=host, timeout=timeout))


def _http(url: str, timeout: float = 20.0) -> tuple:
    """(code, corps, erreur). Un echec rend la CAUSE, jamais un simple False."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), None
    except Exception as exc:  # noqa: BLE001
        return None, "", "%s: %s" % (type(exc).__name__, str(exc)[:120])


def etage_prothese() -> dict:
    """Etat du moteur DEMANDE A SON KEEPER, pas deduit d'une sonde a nous.

    La propriete se demande a l'organe : le keeper sait s'il a lance, echoue, ou
    s'il est en cooldown. Un `docker ps` depuis un compte hors `docker-users`
    rendrait « injoignable » sans que cela dise quoi que ce soit du moteur.
    """
    if not HB_KEEPER.exists():
        return {"etat": "INDETERMINE", "raison": "pouls du keeper absent"}
    try:
        d = json.loads(HB_KEEPER.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"etat": "INDETERMINE", "raison": "pouls illisible (%s)" % type(exc).__name__}
    age = time.time() - HB_KEEPER.stat().st_mtime
    if age > 600:
        return {"etat": "INDETERMINE", "age_s": int(age),
                "raison": "pouls PERIME (%d s) : le keeper ne parle plus, son "
                          "dernier avis ne dit rien du present" % age}
    stats = d.get("stats") or {}
    if stats.get("daemon_up") is True:
        return {"etat": "OK", "age_s": int(age), "health": d.get("health")}
    return {"etat": "KO", "age_s": int(age), "health": d.get("health"),
            "echecs": stats.get("consecutive_failures"),
            "raison": str(stats.get("error"))[:160]}


def etage_service(nom: str, base: str, port: int, chemin: str) -> dict:
    if not _port("127.0.0.1", port):
        return {"etat": "KO", "raison": "port %d ferme (service eteint OU compte sans "
                                        "acces loopback — voir 'loopback' plus bas)" % port}
    code, corps, err = _http(base + chemin)
    if code is None:
        return {"etat": "KO", "raison": "port ouvert mais pas de reponse : %s" % err}
    if code != 200:
        return {"etat": "KO", "raison": "HTTP %s" % code}
    # `corps` ENTIER : l'etage CAPACITE le parse. Le tronquer ici a 400 caracteres
    # faisait echouer `json.loads` sur du JSON coupe, et le controle rendait
    # « reponse non JSON » alors que SearXNG servait un JSON parfaitement valide
    # (mesure 2026-09-05, `ctype=application/json`). L'instrument accusait le
    # service de son propre defaut ; l'abreger reste l'affaire de l'AFFICHAGE.
    return {"etat": "OK", "octets": len(corps), "corps": corps,
            "extrait": corps[:400]}


def etage_capacite_searxng(corps: str) -> dict:
    try:
        d = json.loads(corps)
    except Exception:  # noqa: BLE001
        return {"etat": "INDETERMINE", "raison": "reponse non JSON"}
    res = d.get("results") or []
    ko = d.get("unresponsive_engines") or []
    if not res:
        return {"etat": "KO", "resultats": 0, "moteurs_ko": len(ko),
                "raison": "le service repond mais ne SERT rien"}
    return {"etat": "OK" if not ko else "DEGRADE", "resultats": len(res),
            "moteurs_ko": len(ko),
            "raison": "%d moteur(s) muet(s)" % len(ko) if ko else ""}


def etage_chaine() -> dict:
    """Le crawl passe-t-il par le tier 1, ou tombe-t-il en repli aveugle ?"""
    try:
        from nokido_agent.app.forge_crawl_tool import crawl_url_detail
    except Exception as exc:  # noqa: BLE001
        return {"etat": "INDETERMINE",
                "raison": "forge_crawl_tool inimportable (%s)" % type(exc).__name__}
    avant = WANT.stat().st_mtime if WANT.exists() else 0.0
    try:
        det = crawl_url_detail(TEMOIN, timeout=25)
    except Exception as exc:  # noqa: BLE001
        return {"etat": "KO", "raison": "crawl leve %s" % type(exc).__name__}
    backend = det.get("backend") or det.get("source") or "?"
    apres = WANT.stat().st_mtime if WANT.exists() else 0.0
    return {"etat": "OK" if backend == "crawl4ai" else "DEGRADE",
            "backend": backend, "octets": len(det.get("text") or ""),
            "bail_avant": avant, "bail_apres": apres,
            "bail_prolonge": apres > avant,
            "raison": "" if backend == "crawl4ai"
                      else "repli sans navigateur : contenu JavaScript reduit au chrome"}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
        pass
    r: dict = {"ts": time.time(), "compte": os.environ.get("USERNAME", "?")}
    r["prothese"] = etage_prothese()
    r["searxng"] = etage_service("searxng", SEARXNG, 8080, "/search?q=python&format=json")
    r["crawl4ai"] = etage_service("crawl4ai", CRAWL4AI, 11235, "/health")
    if r["searxng"]["etat"] == "OK":
        r["searxng_capacite"] = etage_capacite_searxng(r["searxng"].get("corps", ""))
    r["searxng"].pop("corps", None)
    r["crawl4ai"].pop("corps", None)
    # Un port ferme PARTOUT alors que le keeper voit le moteur debout designe le
    # compte, pas les services : ne pas accuser un service qu'on ne peut pas voir.
    if (r["prothese"]["etat"] == "OK"
            and r["searxng"]["etat"] == "KO" and r["crawl4ai"]["etat"] == "KO"):
        r["loopback"] = {"etat": "SUSPECT",
                         "raison": "moteur debout mais AUCUN port joignable : "
                                   "probable compte sans acces loopback, relancer "
                                   "sous network=true avant de conclure"}
    if r["crawl4ai"]["etat"] == "OK":
        r["chaine"] = etage_chaine()
    dur = [v.get("etat") for k, v in r.items() if isinstance(v, dict) and "etat" in v]
    r["verdict"] = ("OK" if all(e == "OK" for e in dur)
                    else "DEGRADE" if "KO" not in dur else "KO")
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["verdict"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
