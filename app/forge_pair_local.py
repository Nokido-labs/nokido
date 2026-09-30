"""Qui, sur cette machine, est au bout d'une connexion loopback -- et a-t-il le droit ?

__FORGE_COLOR__ = "immunitaire/isolation-locale"

POURQUOI. Ecouter sur `127.0.0.1` protege du reseau, pas de la machine : tout
processus tournant sous le meme compte peut se connecter. Sur une machine qui
execute des agents, des jobs et du code tiers, « local » n'est pas « de
confiance ».

La recommandation classique est de passer a un named pipe ou une socket de
domaine avec ACL. Elle est INAPPLICABLE ici et il faut le dire : les clients de
la passerelle (Claude Desktop, Cline, Copilot...) parlent HTTP sur TCP parce
qu'ils implementent l'API OpenAI. Changer de transport ne durcirait rien -- ca
supprimerait le service.

Ce module atteint le meme OBJECTIF autrement : il identifie le PROCESSUS au
bout de la connexion et le confronte a une politique. C'est l'equivalent d'une
ACL, applique au-dessus du transport existant.

TROIS ETATS, jamais deux -- et c'est le coeur du dispositif :
    AUTORISE   : processus identifie ET permis par la politique ;
    REFUSE     : processus identifie ET interdit ;
    INDETERMINE: on n'a pas pu voir (socket fermee, autre compte, psutil absent).

`INDETERMINE` n'est PAS `REFUSE`. Un appelant legitime dont la socket s'est
fermee entre la requete et la mesure serait rejete a tort, et un garde qui crie
a faux se fait desarmer. C'est a l'APPELANT de decider ce qu'il fait d'un
indetermine -- ce module mesure, il ne tranche pas.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

__all__ = ["AUTORISE", "REFUSE", "INDETERMINE", "INAPPLICABLE", "identifier",
           "verdict", "politique_par_defaut", "portee"]

AUTORISE = "AUTORISE"
REFUSE = "REFUSE"
INDETERMINE = "INDETERMINE"
# Quatrieme etat, ajoute le 2026-09-02 pour la perspective EDGE : la question
# elle-meme n'a plus de sens. Identifier « le processus au bout de la
# connexion » suppose que le pair est sur CETTE machine. Des que le service est
# joignable de l'exterieur, l'appelant n'a plus de PID ici, et le module rendait
# alors INDETERMINE -- que l'appelant refuse silencieusement de traiter.
# Resultat : isolation armee + service expose = TOUT PASSE, sans un mot.
# C'est le fail-open le plus couteux possible : un garde qui s'eteint
# exactement au moment ou il devient necessaire.
INAPPLICABLE = "INAPPLICABLE"

_CACHE: Dict[str, Any] = {"ts": 0.0, "par_port": {}, "raison": ""}
_TTL = 2.0


def politique_par_defaut() -> Dict[str, List[str]]:
    """Politique VIDE : aucun nom autorise, aucun interdit.

    Volontairement vide. Une allowlist inventee ici serait pire qu'aucune : elle
    donnerait l'illusion d'un controle tout en laissant passer ce que l'auteur
    n'a pas devine, et elle refuserait des clients legitimes que personne n'a
    pense a lister. La politique se remplit d'appelants OBSERVES -- meme chemin
    que la matrice d'autorisation : observer, puis decider.
    """
    return {"autorises": [], "interdits": [], "chemins_autorises": []}


def portee(port_ecoute: Optional[int] = None) -> Dict[str, Any]:
    """L'isolation par processus est-elle APPLICABLE sur ce service ?

    Elle suppose que l'appelant vit sur cette machine. Sur un service joignable
    de l'exterieur, la question perd son sens : le pair n'a pas de PID ici, et
    ce module ne peut RIEN dire de lui.

    Rend `applicable` a `None` (et non `False`) quand l'exposition elle-meme
    est illisible -- trois etats, comme partout : on ne remplace pas une
    incertitude par un verdict.
    """
    if not port_ecoute:
        return {"applicable": True, "expose": "NON_MESURE",
                "motif": "port d'ecoute non fourni : portee presumee locale"}
    try:
        from nokido_agent.app.forge_bind_guard import verdict as _bind

        v = _bind(int(port_ecoute))
        etat = v.get("etat")
    except Exception as e:  # noqa: BLE001
        return {"applicable": None, "expose": "ILLISIBLE",
                "motif": "exposition du port %s illisible (%s) : ne pas conclure"
                         % (port_ecoute, type(e).__name__)}
    if etat == "EXPOSE":
        return {"applicable": False, "expose": etat,
                "motif": "service joignable hors de la machine : l'identification "
                         "du processus appelant ne s'applique plus, il faut une "
                         "garantie de TRANSPORT (TLS/mTLS) et une identite "
                         "prouvee, pas un PID"}
    if etat == "LOOPBACK":
        return {"applicable": True, "expose": etat,
                "motif": "service en loopback : le pair est sur cette machine"}
    return {"applicable": None, "expose": etat or "INCONNU",
            "motif": "exposition indeterminee : ne pas presumer la portee"}


def _table(psutil) -> tuple:
    """{port_source: pid}, et la RAISON quand elle est vide."""
    now = time.time()
    if now - _CACHE["ts"] < _TTL and _CACHE["par_port"]:
        return _CACHE["par_port"], _CACHE["raison"]
    par_port: Dict[int, int] = {}
    raison = ""
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.pid and c.laddr:
                par_port[c.laddr.port] = c.pid
    except Exception as e:  # noqa: BLE001
        # « Acces refuse » n'est pas « aucune connexion » : sans cette
        # distinction, un compte sans privilege rendrait tout INDETERMINE en
        # silence et la politique paraitrait inapplicable.
        raison = "net_connections refuse (%s)" % type(e).__name__
    _CACHE.update({"ts": now, "par_port": par_port, "raison": raison})
    return par_port, raison


def identifier(port_source: Optional[int]) -> Dict[str, Any]:
    """Processus au bout de la connexion. Ne LEVE jamais, ne tranche pas."""
    vide = {"pid": None, "process": None, "chemin": None, "raison": ""}
    if not port_source:
        return dict(vide, raison="port source absent")
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return dict(vide, raison="psutil_absent")

    par_port, raison = _table(psutil)
    if raison:
        return dict(vide, raison=raison)
    pid = par_port.get(int(port_source))
    if pid is None:
        return dict(vide, raison="aucune socket ne porte ce port source "
                                 "(connexion fermee, ou hors perimetre du compte)")
    out = dict(vide, pid=pid)
    try:
        p = psutil.Process(pid)
        try:
            out["process"] = p.name()
        except Exception:  # noqa: BLE001
            out["raison"] = "nom illisible (autre compte)"
        try:
            out["chemin"] = p.exe()
        except Exception:  # noqa: BLE001
            # Le CHEMIN est ce qui distingue un binaire legitime d'un homonyme
            # depose ailleurs. Ne pas l'avoir affaiblit la mesure, et doit se
            # voir plutot que de passer pour une identification complete.
            out["raison"] = (out["raison"] + " ; " if out["raison"] else "") + \
                "chemin illisible -- un homonyme ne serait pas distingue"
    except Exception as e:  # noqa: BLE001
        out["raison"] = "process %s illisible (%s)" % (pid, type(e).__name__)
    return out


def verdict(port_source: Optional[int], politique: Optional[dict] = None,
            port_ecoute: Optional[int] = None) -> Dict[str, Any]:
    """(etat, pid, process, raison). L'interdiction PRIME sur l'autorisation.

    Ordre voulu : un nom present dans les deux listes est REFUSE. Devant une
    contradiction de configuration, la lecture la plus stricte l'emporte.

    Un NOM de processus ne prouve rien -- `claude.exe` depose dans un dossier
    quelconque porte le meme nom que le vrai. La politique accepte donc aussi
    des CHEMINS (`chemins_autorises`), qui distinguent le binaire legitime de
    son homonyme. Recommandation de la revue M2M du 2026-09-02, et elle comble
    une limite que ce module signalait deja lui-meme.
    """
    pol = politique or politique_par_defaut()

    # PORTEE D'ABORD : sur un service expose, ce controle ne s'applique plus.
    # Le dire explicitement evite qu'un `INDETERMINE` muet soit lu comme « rien
    # a signaler » alors que le garde vient de s'eteindre.
    if port_ecoute is not None:
        p = portee(port_ecoute)
        if p["applicable"] is False:
            return {"pid": None, "process": None, "chemin": None,
                    "raison": p["motif"], "etat": INAPPLICABLE, "motif": p["motif"]}
        if p["applicable"] is None:
            return {"pid": None, "process": None, "chemin": None,
                    "raison": p["motif"], "etat": INDETERMINE, "motif": p["motif"]}

    ident = identifier(port_source)
    nom = (ident.get("process") or "").lower()

    if not nom:
        return dict(ident, etat=INDETERMINE,
                    motif=ident.get("raison") or "processus non identifie")

    interdits = {str(x).lower() for x in (pol.get("interdits") or [])}
    autorises = {str(x).lower() for x in (pol.get("autorises") or [])}
    chemins = [str(x).lower().replace("\\", "/") for x in (pol.get("chemins_autorises") or [])]

    if nom in interdits:
        return dict(ident, etat=REFUSE, motif="processus explicitement interdit")

    if chemins:
        # Exigence de CHEMIN : le nom seul ne suffit plus. Un chemin illisible
        # (autre compte) rend INDETERMINE et non AUTORISE -- ne pas pouvoir
        # verifier n'est pas verifier.
        exe = (ident.get("chemin") or "").lower().replace("\\", "/")
        if not exe:
            return dict(ident, etat=INDETERMINE,
                        motif="chemin du binaire illisible alors que la politique "
                              "l'exige : un homonyme ne serait pas distingue")
        if not any(exe == c or exe.startswith(c.rstrip("/") + "/") for c in chemins):
            return dict(ident, etat=REFUSE,
                        motif="binaire hors des chemins autorises (%s)" % exe[:80])

    if not autorises:
        if chemins:
            # Chemin verifie et conforme : c'est une preuve plus forte qu'un nom.
            return dict(ident, etat=AUTORISE,
                        motif="binaire dans un chemin autorise")
        # Politique vide = MESURE SEULE. Rendre AUTORISE ici ferait croire a un
        # controle ; rendre REFUSE couperait tout le monde. L'indetermine est le
        # seul etat honnete tant que personne n'a decide.
        return dict(ident, etat=INDETERMINE,
                    motif="aucune liste d'autorises : politique non encore decidee")
    if nom in autorises:
        return dict(ident, etat=AUTORISE, motif="processus autorise par la politique")
    return dict(ident, etat=REFUSE, motif="processus absent de la liste d'autorises")
