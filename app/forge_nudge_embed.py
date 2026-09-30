# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/reveil-embedding"
REVEIL du daemon d'embedding — et il DIT quand personne n'ecoute.

LE DEFAUT QU'IL CORRIGE (mesure 2026-08-05)
===========================================
Quatre organes de production reveillaient le `brain_worker` sur `:5557` par un
`zmq.PUSH` fire-and-forget : `forge_rag_engine._notify_brain_embed`,
`forge_self_correction._zmq_nudge_brain`, `nokido_hub._zmq_nudge` et
`forge_memory_consolidator`. Or ce port est FERME depuis juin — les trois services
qui l'ecoutaient sont desactives, chacun pour une raison differente.

Et voici le point qui rend le defaut invisible, **mesure et non suppose** :

    >>> s.connect("tcp://127.0.0.1:5557")   # port ferme
    >>> s.send(payload, zmq.NOBLOCK)
    ENVOI ACCEPTE -> aucune exception

**Un PUSH vers un port ferme est ACCEPTE.** Aucune erreur n'est levee, donc les
`except: pass` de ces fonctions ne se declenchent JAMAIS. Du point de vue de
l'appelant, le reveil a REUSSI. C'est plus grave qu'un echec silencieux : il n'y a
meme pas d'echec a taire.

Consequence mesuree : les chunks inseres avec `embedding IS NULL` attendaient un
reveil qui n'arrivait a personne, et aucun poller ne prenait le relais
(`NokidoEmbedTrigger` est `disabled`). Ils se sont accumules — 278 512 au
2026-08-05.

CE QUE FAIT CE MODULE
=====================
Il verifie qu'un ECOUTEUR existe avant de croire au reveil. Le succes d'un `send`
ne prouve rien ; la presence d'un pair, si. Trois etats rendus, jamais deux :
`delivre` / `aucun_ecouteur` / `impossible` (avec la raison).
"""
from __future__ import annotations

import logging
import socket
import time

PORT_DEFAUT = 5557
# Un connect_ex vers un port LOCAL ferme revient immediatement (ECONNREFUSED), donc
# la sonde est quasi gratuite. Le cache evite quand meme de la refaire a chaque
# chunk insere lors d'une ingestion en rafale.
_TTL_SONDE_S = 30.0
_SONDE: dict = {"ts": 0.0, "port": None, "ouvert": False}
_DERNIER_ETAT: dict = {}

logger = logging.getLogger(__name__)


def _ecouteur_present(port: int) -> bool:
    now = time.time()
    if _SONDE["port"] == port and (now - _SONDE["ts"]) < _TTL_SONDE_S:
        return bool(_SONDE["ouvert"])
    c = socket.socket()
    c.settimeout(0.3)
    try:
        ouvert = c.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        ouvert = False
    finally:
        try:
            c.close()
        except OSError:  # muet-ok : fermeture d'une socket de sonde, sans effet
            pass
    _SONDE.update({"ts": now, "port": port, "ouvert": ouvert})
    return ouvert


def _dire_une_fois(cle: str, etat: str, msg: str, *args) -> None:
    """Un etat qui DURE se dit une fois ; son changement se redit. Sans cela, une
    ingestion en rafale produirait une ligne par chunk et le remede finirait filtre."""
    if _DERNIER_ETAT.get(cle) == etat:
        return
    _DERNIER_ETAT[cle] = etat
    (logger.warning if etat != "ok" else logger.info)(msg, *args)


def nudge_embed(n: int = 1, port: int = PORT_DEFAUT, source: str = "?",
                payload: dict | None = None) -> dict:
    """Reveille le daemon d'embedding. Rend l'etat REEL de la livraison.

    Retourne {"delivre": bool, "etat": "ok"|"aucun_ecouteur"|"impossible", ...}.
    L'appelant peut donc agir — ce qu'un `except: pass` interdisait, faute d'avoir
    quoi que ce soit a observer.

    `payload` permet aux appelants qui envoient plus qu'un reveil (le moteur RAG
    soumet des ids ET des textes) de garder leur message : la VERIFICATION de
    l'ecouteur reste au meme endroit, ce qui evite que chaque appelant reinvente —
    et oublie — le controle qui manquait.
    """
    if not _ecouteur_present(port):
        _dire_une_fois(
            "ecouteur:%d" % port, "absent",
            "[nudge] personne n'ecoute :%d — reveil d'embedding NON delivre "
            "(appelant: %s) | consequence: les chunks inseres restent sans vecteur "
            "jusqu'a ce qu'un drain passe (NokidoDeportEmbed) ; un PUSH ZMQ vers un "
            "port ferme est ACCEPTE sans erreur, donc ce defaut ne pouvait pas etre "
            "vu par un try/except", port, source)
        return {"delivre": False, "etat": "aucun_ecouteur", "port": port}
    try:
        import msgpack
        import zmq
    except Exception as e:  # noqa: BLE001
        _dire_une_fois("lib", "absente",
                       "[nudge] zmq/msgpack indisponibles dans cet interpreteur (%s) — "
                       "reveil impossible (appelant: %s) | consequence: identique a un "
                       "port ferme, le drain seul rattrapera",
                       type(e).__name__, source)
        return {"delivre": False, "etat": "impossible", "raison": type(e).__name__}
    try:
        s = zmq.Context.instance().socket(zmq.PUSH)
        s.setsockopt(zmq.LINGER, 0)
        s.connect("tcp://127.0.0.1:%d" % port)
        s.send(msgpack.packb(payload or {"cmd": "nudge", "n": int(n)},
                             use_bin_type=True), zmq.NOBLOCK)
        s.close()
    except Exception as e:  # noqa: BLE001
        _dire_une_fois("envoi", "echec",
                       "[nudge] envoi vers :%d refuse (%s) — appelant: %s",
                       port, type(e).__name__, source)
        return {"delivre": False, "etat": "impossible", "raison": type(e).__name__}
    _dire_une_fois("ecouteur:%d" % port, "ok",
                   "[nudge] :%d de nouveau a l'ecoute — reveils d'embedding delivres",
                   port)
    return {"delivre": True, "etat": "ok", "port": port, "n": int(n)}
