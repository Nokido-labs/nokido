"""forge_bind_guard.py -- l'ecoute reelle est-elle bornee au loopback ?

Le hub verifie deja `HUB_HOST` avant de servir et retombe sur `127.0.0.1` si la
valeur n'est pas loopback (garde Phase 18). C'est un controle de l'INTENTION.

Ce module controle l'EFFET : ce que le systeme d'exploitation expose vraiment.
La difference n'est pas theorique -- une variable juste ne garantit pas un socket
sain. Trois chemins exposent un port sans jamais toucher `HUB_HOST` :

  * un mapping de conteneur (`-p 0.0.0.0:8766->8766`),
  * un proxy ou un tunnel place devant,
  * un socket herite d'un processus parent.

La posture « local-only » de Nokido est un ARBITRAGE, pas une morale : sur
loopback, le Bearer sans OAuth est defendable (la spec MCP 2026-07-28 rend
d'ailleurs l'autorisation OPTIONNELLE). Mais elle ne tient que si l'hypothese
reste VRAIE dans le temps. Le risque n'est pas le choix d'aujourd'hui, c'est
qu'il devienne faux sans que personne ne le sache. Ce module est ce qui le fait
savoir.

TROIS ETATS, jamais deux : `LOOPBACK` / `EXPOSE` / `INCONNU`. Une sonde qui n'a
pas pu regarder ne doit pas rendre « sain » -- c'est ainsi qu'on fabrique une
securite imaginaire.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/garde-exposition-reseau"

import os
from typing import Any, Dict, List

LOOPBACK = {"127.0.0.1", "::1", "localhost", "127.0.0.0/8"}
# Adresses qui signifient « toutes les interfaces ».
TOUTES = {"0.0.0.0", "::", "*", ""}

OK = "LOOPBACK"
EXPOSE = "EXPOSE"
INCONNU = "INCONNU"


def _override_actif() -> bool:
    return os.environ.get("LAFORGE_HUB_BIND_EXTERNAL", "0") == "1"


def inspecter(port: int) -> Dict[str, Any]:
    """Que le systeme expose-t-il REELLEMENT sur ce port ?

    Rend {etat, adresses, raison}. `INCONNU` si l'enumeration est refusee : sous
    Windows, `psutil.net_connections` demande des droits que le compte de service
    n'a pas toujours, et un refus d'acces ressemble a « aucune ecoute ».
    """
    try:
        import psutil
    except ImportError:
        return {"etat": INCONNU, "adresses": [], "raison": "psutil absent"}

    adresses: List[str] = []
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status == "LISTEN" and c.laddr and c.laddr.port == port:
                adresses.append(str(c.laddr.ip))
    except (psutil.AccessDenied, PermissionError) as e:
        # NE PAS rendre LOOPBACK ici : « je n'ai pas pu voir » n'est pas
        # « rien n'est expose ». C'est exactement le faux negatif que ce
        # module existe pour eviter.
        return {"etat": INCONNU, "adresses": [],
                "raison": "enumeration refusee: %s" % str(e)[:80]}
    except Exception as e:  # noqa: BLE001
        return {"etat": INCONNU, "adresses": [],
                "raison": "%s: %s" % (type(e).__name__, str(e)[:80])}

    if not adresses:
        return {"etat": INCONNU, "adresses": [],
                "raison": "aucun listener vu sur le port %d (pas encore bind ?)" % port}

    exposees = [a for a in adresses if a in TOUTES or a not in LOOPBACK]
    if exposees:
        return {"etat": EXPOSE, "adresses": sorted(set(adresses)),
                "raison": "ecoute hors loopback: %s" % sorted(set(exposees))}
    return {"etat": OK, "adresses": sorted(set(adresses)), "raison": ""}


def verdict(port: int) -> Dict[str, Any]:
    """Ajoute la POLITIQUE au constat : l'exposition est-elle AUTORISEE ?

    Une exposition declaree (`LAFORGE_HUB_BIND_EXTERNAL=1`) reste une exposition ;
    elle est simplement ASSUMEE. La distinction doit rester visible, sinon
    l'override devient un angle mort permanent.
    """
    v = inspecter(port)
    autorise = _override_actif()
    v["override_declare"] = autorise
    if v["etat"] == EXPOSE:
        v["conforme"] = autorise
        v["message"] = (
            "EXPOSITION ASSUMEE (LAFORGE_HUB_BIND_EXTERNAL=1) sur %s" % v["adresses"]
            if autorise else
            "EXPOSITION NON DECLAREE sur %s -- le hub sert hors loopback sans que "
            "l'override soit pose. Un Bearer sans OAuth n'est defendable QUE sur "
            "loopback." % v["adresses"])
    elif v["etat"] == INCONNU:
        # Ne pas transformer une cecite en conformite.
        v["conforme"] = None
        v["message"] = "ETAT D'EXPOSITION INCONNU : %s" % v["raison"]
    else:
        v["conforme"] = True
        v["message"] = "loopback seul (%s)" % ", ".join(v["adresses"])
    return v


def controler(port: int, logger=None) -> Dict[str, Any]:
    """Point d'appel du hub. N'ARRETE JAMAIS le processus.

    Un garde qui tue le control-plane au demarrage transforme une exposition
    possible en indisponibilite CERTAINE. Il crie ; l'arret reste une decision
    owner. Le corps a deja paye un service sain arrete sur un faux positif.
    """
    v = verdict(port)
    if logger is not None:
        try:
            if v["conforme"] is False:
                logger.critical("[bind_guard] %s", v["message"])
            elif v["conforme"] is None:
                logger.warning("[bind_guard] %s", v["message"])
            else:
                logger.info("[bind_guard] %s", v["message"])
        except Exception:  # noqa: BLE001  # muet-ok : un garde ne casse pas le boot
            pass
    return v


if __name__ == "__main__":
    import json
    import sys

    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print(json.dumps(verdict(p), ensure_ascii=False, indent=1))
