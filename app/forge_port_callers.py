# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/qui-appelle-quoi"
QUI APPELLE QUOI -- attribution des connexions locales a leur service appelant.

POURQUOI
========
Mesure du 2026-08-05 : `NokidoLlamaEmbed` (:8099) est passe de 2,73 a 6,07 Go en
69 minutes. Le corps savait dire QUE l'embedder grossissait (capteur de derive RSS,
04/08) mais pas POURQUOI -- or la reponse tenait dans une grandeur que personne ne
mesurait : ~118 connexions en TIME_WAIT vers :8099, soit **~50 requetes par minute
en continu**. L'embedder ne fuyait pas, il TRAVAILLAIT. Sans ce compteur, la seule
lecture disponible etait « il grossit », et la conclusion naturelle « il fuit » --
celle que j'avais deja tiree a tort le 04/08 sur une lecture unique.

Corollaire encore ouvert au 03/08 : « un AUTRE chemin vectorise en fond, a
instruire ». Ce module est l'instrument de cette instruction.

CE QU'IL MESURE, ET CE QU'IL REFUSE DE DIRE
===========================================
- `etablies` : connexions VIVANTES vers le port, attribuables a un PID.
- `recentes` : connexions en TIME_WAIT. Elles n'ont PLUS de PID (Windows le libere)
  -- c'est du trafic REEL non attribuable, jamais « personne ». Leur nombre divise
  par la duree du TIME_WAIT donne le DEBIT ; c'est la seule facon d'observer une
  rafale de requetes courtes, qu'un instantane des connexions etablies rate.
- `non_attribuees` : un PID existe mais le compte n'a pas le droit de le lire.
  Trois etats, jamais deux.

PIEGE DU LAUNCHER (mesure, pas suppose)
=======================================
Un service `runAs=interactive` passe par un LANCEUR : le registre du superviseur
note le PID du lanceur, et c'est son ENFANT qui ouvre les connexions. Chercher le
PID tel quel dans le registre rend donc « non declare » pour un service pourtant
supervise. On remonte la chaine des parents jusqu'a trouver un ancetre connu, et on
DIT quand on a du remonter -- sinon l'attribution aurait l'air directe.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_APP = os.path.dirname(os.path.abspath(__file__))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

_ROOT = Path(_APP).parent
ETAT = _ROOT / "sandbox" / "port_callers_state.json"

# Ports surveilles -> role lisible. Un port qu'on n'ecoute pas ne coute rien.
PORTS = {
    8099: "embedder bge-m3",
    8100: "reranker bge-m3",
    8091: "llama natif (on-demand)",
    11434: "ollama",
    8766: "hub souverain",
}
# Duree du TIME_WAIT sous Windows. Sert a convertir un STOCK de sockets fermees en
# DEBIT. Valeur par defaut de Windows ; si elle est modifiee dans le registre, le
# debit est proportionnellement faux -- d'ou la mention explicite dans la sortie.
TIME_WAIT_S = 120.0
_PROFONDEUR_PARENTS = 4


def _registre() -> dict:
    """{pid: nom} des services supervises. {} si injoignable, et l'appelant le DIT."""
    try:
        from nokido_agent.app import forge_service_rss_watch as W  # anti-dup : le registre existe deja

        return {v: k for k, v in (W._registre() or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def _attribuer(pid: int, reg: dict, psutil) -> tuple[str, str]:
    """(nom, comment). Remonte la chaine des parents : un service interactif passe
    par un lanceur, donc le PID qui ouvre la connexion n'est PAS celui du registre."""
    if pid in reg:
        return reg[pid], "direct"
    try:
        p = psutil.Process(pid)
    except Exception as e:  # noqa: BLE001
        return "illisible", type(e).__name__
    nom_proc = "?"
    try:
        nom_proc = p.name()
    except Exception:  # noqa: BLE001
        pass
    cur = p
    for saut in range(1, _PROFONDEUR_PARENTS + 1):
        try:
            cur = cur.parent()
        except Exception:  # noqa: BLE001
            break
        if cur is None:
            break
        if cur.pid in reg:
            return reg[cur.pid], "via lanceur (+%d)" % saut
    return nom_proc, "hors superviseur"


def echantillon() -> dict:
    """Un tour de mesure, cumule dans l'etat. Ne leve JAMAIS."""
    try:
        import psutil
    except Exception:
        return {"raison": "psutil_absent"}
    reg = _registre()
    etat = _charger()
    now = time.time()
    try:
        conns = psutil.net_connections(kind="tcp")
    except Exception as e:  # noqa: BLE001
        # Un refus de lecture n'est pas « aucune connexion » : on le consigne dans
        # l'etat pour qu'un lecteur ne prenne pas le silence pour du calme.
        etat["_derniere_panne"] = "net_connections refuse (%s)" % type(e).__name__
        _ecrire(etat)
        return {"raison": etat["_derniere_panne"]}
    etat.pop("_derniere_panne", None)
    vus: dict = {}
    # DEFAUT CORRIGE dans le tour meme de l'ecriture : la premiere version ne creait
    # une entree que pour les ports ayant du trafic. Un port surveille SANS trafic
    # disparaissait donc du rapport, indistinguable d'un port jamais mesure -- le
    # defaut que ce module existe pour eviter. On distingue desormais trois etats :
    # ecoute + trafic / ecoute + silence / personne n'ecoute.
    ecoutes = {c.laddr.port for c in conns
               if c.status == "LISTEN" and c.laddr and c.laddr.port in PORTS}
    for p in PORTS:
        vus[p] = {"etablies": {}, "recentes": 0, "non_attribuees": 0,
                  "ecoute": p in ecoutes}
    for c in conns:
        port = c.raddr.port if c.raddr else None
        # TIME_WAIT n'a plus de raddr exploitable cote client : on compte alors la
        # socket cote SERVEUR (laddr = le port surveille).
        if c.status == "TIME_WAIT" and c.laddr and c.laddr.port in PORTS:
            d = vus.setdefault(c.laddr.port, {"etablies": {}, "recentes": 0, "non_attribuees": 0})
            d["recentes"] += 1
            continue
        if port not in PORTS or c.status != "ESTABLISHED":
            continue
        d = vus.setdefault(port, {"etablies": {}, "recentes": 0, "non_attribuees": 0})
        if not c.pid:
            d["non_attribuees"] += 1
            continue
        nom, comment = _attribuer(c.pid, reg, psutil)
        cle = nom if comment in ("direct",) else "%s [%s]" % (nom, comment)
        d["etablies"][cle] = d["etablies"].get(cle, 0) + 1
    for port, d in vus.items():
        e = etat.setdefault(str(port), {"role": PORTS[port], "appelants": {}, "tours": 0})
        e["tours"] = int(e.get("tours") or 0) + 1
        e["dernier_ts"] = round(now, 1)
        e["recentes"] = d["recentes"]
        # Un port que PERSONNE n'ecoute n'a pas un debit de zero : il n'a pas de
        # debit du tout. Confondre les deux ferait lire « service au repos » sur un
        # service ARRETE.
        e["ecoute"] = d.get("ecoute", False)
        e["debit_req_min"] = (round(60.0 * d["recentes"] / TIME_WAIT_S, 1)
                              if d.get("ecoute") else None)
        e["non_attribuees"] = d["non_attribuees"]
        for nom, n in d["etablies"].items():
            e["appelants"][nom] = int(e["appelants"].get(nom) or 0) + n
    _ecrire(etat)
    return {"ports_vus": len(vus), "registre": len(reg)}


def _charger() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _ecrire(etat: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def canaux() -> dict:
    """Canaux compacts pour la serie vitals : debit par port surveille.

    On ne journalise QUE le debit (un scalaire par port) : la liste des appelants
    vit dans l'etat, elle n'a pas sa place 4 fois par minute dans la serie."""
    out = {}
    for port, e in _charger().items():
        if not isinstance(e, dict) or "debit_req_min" not in e:
            continue
        # None (personne n'ecoute) est journalise TEL QUEL : la serie porte alors un
        # trou, qui se lit « service arrete », pas « service inactif ».
        out["q%s" % port] = e.get("debit_req_min")
    return out


def rapport(ratio_min: int = 0) -> dict:
    """Vue humaine : qui appelle quoi, a quel debit, et ce qu'on n'a pas pu voir."""
    etat = _charger()
    out = {"panne": etat.get("_derniere_panne"), "time_wait_s": TIME_WAIT_S, "ports": []}
    for port, e in sorted(etat.items()):
        if not isinstance(e, dict) or "role" not in e:
            continue
        app = sorted(e.get("appelants", {}).items(), key=lambda kv: -kv[1])
        out["ports"].append({
            "port": int(port),
            "role": e.get("role"),
            "ecoute": e.get("ecoute"),
            "debit_req_min": e.get("debit_req_min"),
            "tours": e.get("tours"),
            "appelants": [{"qui": k, "vu": v} for k, v in app if v >= ratio_min],
            "non_attribuees": e.get("non_attribuees"),
            "age_s": round(time.time() - float(e.get("dernier_ts") or 0), 1),
        })
    return out


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Qui appelle les ports locaux surveilles")
    ap.add_argument("--once", action="store_true", help="un echantillon")
    ap.add_argument("--report", action="store_true", help="etat cumule")
    ap.add_argument("--tours", type=int, default=0, help="N echantillons espaces de 5 s")
    a = ap.parse_args(argv)
    if a.tours:
        for i in range(a.tours):
            print(json.dumps(echantillon(), ensure_ascii=False))
            if i < a.tours - 1:
                time.sleep(5)
    elif a.once or not a.report:
        print(json.dumps(echantillon(), ensure_ascii=False))
    if a.report:
        print(json.dumps(rapport(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
