"""Demande d'organe et etat d'organe — deux signaux qu'on avait confondus.

__FORGE_COLOR__ = "vegetatif/heartbeat : demande d'organe et etat d'organe, deux signaux distincts"

LE DEFAUT QUE CE MODULE EXISTE POUR LEVER (mesure 2026-09-02). Le drapeau
`llama.wanted` signifiait a la fois « quelqu'un a besoin de cognition » et,
indirectement, « le service est encore la ». Il etait repose par
`forge_llm_ondemand._poser_drapeau`, appele depuis `llama_up()` -- c'est-a-dire
depuis la fonction qui VERIFIE que llama tourne. 957 emissions, une toutes les
~300 s pour un TTL de 900 s : le drapeau ne perimait jamais, donc le veto qui
protege llama de l'eviction ne retombait jamais.

    Le surveillant declarait le besoin. L'organe se rendait necessaire en
    restant vivant.

Symetriquement, en juillet, PERSONNE ne posait ce drapeau : 73 arrets en 7,6
jours et 312,94 Go rechargees. Le meme signal a donc produit les deux pannes
opposees, parce qu'il portait deux sens.

TROIS SIGNAUX DISTINCTS, et c'est tout l'objet :

    ETAT     ce que le corps CONSTATE   -- OFF/STARTING/READY/SERVING/IDLE/SLEEPING
    DEMANDE  ce que quelqu'un VEUT      -- un bail, avec un demandeur et une fin
    (wanted) la decision historique     -- inchangee, toujours seule aux commandes

CE MODULE NE DECIDE RIEN. Aucun regulateur ne le consulte encore : c'est une
phase de COEXISTENCE, destinee a repondre par la mesure a « qui demande llama,
pour quoi, combien de temps, et que fait llama ensuite ? ». Retirer le faux
emetteur AVANT d'avoir cette reponse rejouerait juillet.

LE GARDE QUI COMPTE. `acquerir()` REFUSE un demandeur issu de la couche de
surveillance. Constater qu'un organe vit n'est pas le demander. Ce refus est
structurel plutot que documentaire : une regle ecrite dans un commentaire ne
survit pas a la prochaine boucle de keeper qui aura « juste besoin » de poser
la demande.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

__all__ = [
    "ETATS", "EVENEMENTS", "LIVENESS_INTERDITE", "DemandeRefusee",
    "poser_etat", "etat_courant", "acquerir", "renouveler", "liberer",
    "demandes_actives", "resume", "journal",
]

# Etats d'organe. `UNKNOWN` n'est pas un etat de l'organe, c'est un etat de
# NOTRE connaissance : rien n'a ete pose, ou la trace est trop vieille.
ETATS = ("OFF", "STARTING", "READY", "SERVING", "IDLE", "SLEEPING", "UNKNOWN")
EVENEMENTS = ("DEMAND_ACQUIRED", "DEMAND_RENEWED", "DEMAND_RELEASED",
              "DEMAND_EXPIRED", "DEMAND_REFUSED")

# Modules et fonctions de la couche LIVENESS : ils constatent, ils ne demandent
# pas. La liste nomme ce qui a REELLEMENT produit le defaut, pas une categorie
# abstraite -- `forge_llm_ondemand._poser_drapeau` appele par `llama_up()`, et
# le keeper qui epargne l'organe sur la foi du drapeau.
LIVENESS_INTERDITE = (
    "forge_llm_ondemand",
    "forge_llama_keeper",
    "forge_service_watchdog",
    "forge_port_reconcile",
)
# Fonctions nommement responsables du defaut, en plus des modules ci-dessus.
# Volontairement PRECISES : `tick`, `_sert` ou `_attendre` ont ete essayes puis
# RETIRES -- trop generiques, ils auraient refuse des demandes legitimes venant
# de n'importe quelle boucle. Et ils etaient redondants : `forge_llama_keeper.py:tick`
# est deja attrape par le nom du module. Un garde qui crie a faux se fait
# desarmer, ce qui coute plus cher que la couverture qu'il pretend ajouter.
_FONCTIONS_LIVENESS = ("_poser_drapeau", "poser_intention", "llama_up")

_AGE_ETAT_MAX_S = 900.0     # au-dela, on ne sait plus : UNKNOWN, pas le dernier connu


class DemandeRefusee(RuntimeError):
    """Un demandeur de la couche liveness a tente d'acquerir un bail."""


def _conn() -> sqlite3.Connection:
    """Meme base dediee que les signaux, mêmes reglages anti-contention.

    Reutilisee plutot que recopiee : dupliquer `isolation_level=None` + WAL +
    `busy_timeout` ferait une seconde verite a maintenir, et le cliquet de
    clones aurait raison de le signaler.
    """
    from nokido_agent.app.forge_signal_coupling import _conn as _base

    cx = _base()
    cx.execute(
        "CREATE TABLE IF NOT EXISTS organ_etats ("
        " organe TEXT PRIMARY KEY,"
        " etat TEXT NOT NULL,"
        " emetteur TEXT NOT NULL,"
        " ts REAL NOT NULL)"
    )
    cx.execute(
        "CREATE TABLE IF NOT EXISTS organ_demandes ("
        " id TEXT PRIMARY KEY,"
        " organe TEXT NOT NULL,"
        " issuer TEXT NOT NULL,"
        " reason TEXT NOT NULL,"
        " priority INTEGER NOT NULL DEFAULT 50,"
        " ref TEXT NOT NULL DEFAULT '',"
        " created_at REAL NOT NULL,"
        " expires_at REAL NOT NULL,"
        " released_at REAL)"
    )
    cx.execute(
        "CREATE TABLE IF NOT EXISTS organ_demandes_journal ("
        " ts REAL NOT NULL,"
        " organe TEXT NOT NULL,"
        " evenement TEXT NOT NULL,"
        " id TEXT NOT NULL DEFAULT '',"
        " issuer TEXT NOT NULL DEFAULT '',"
        " detail TEXT NOT NULL DEFAULT '')"
    )
    return cx


def _appelant(profondeur: int = 2) -> str:
    """Qui appelle, vu de la pile. Meme methode que `emit_signal` : on veut
    savoir QUI, pas seulement que quelqu'un."""
    try:
        f = sys._getframe(profondeur)
        return "%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name)
    except Exception:  # muet-ok : l'instrumentation ne casse jamais l'appelant
        return "inconnu"


def _est_liveness(issuer: str, pile: str) -> bool:
    """Le demandeur appartient-il a la couche qui CONSTATE ?

    On regarde le nom declare ET la pile reelle : un module de surveillance qui
    passerait un `issuer` d'emprunt serait sinon indetectable.
    """
    sonde = ("%s %s" % (issuer or "", pile or "")).lower()
    if any(m in sonde for m in LIVENESS_INTERDITE):
        return True
    return any(f.lower() in sonde for f in _FONCTIONS_LIVENESS)


def _journaliser(cx, organe: str, evenement: str, ident: str = "",
                 issuer: str = "", detail: str = "") -> None:
    cx.execute(
        "INSERT INTO organ_demandes_journal (ts, organe, evenement, id, issuer, detail)"
        " VALUES (?,?,?,?,?,?)",
        (time.time(), organe, evenement, ident, issuer, detail[:400]))


# ------------------------------------------------------------------ ETAT

def poser_etat(organe: str, etat: str, emetteur: Optional[str] = None) -> bool:
    """CONSTAT du corps. C'est ici que le keeper a le droit d'ecrire.

    Poser un etat n'a AUCUN effet protecteur : c'est precisement la separation
    que ce module installe. Un organe `READY` n'est pas un organe demande.
    """
    if etat not in ETATS:
        raise ValueError("etat inconnu : %r (attendus %s)" % (etat, ", ".join(ETATS)))
    emetteur = emetteur or _appelant()
    try:
        cx = _conn()
    except Exception:
        return False  # muet-ok : la telemetrie ne casse pas l'organe qu'elle observe
    try:
        cx.execute(
            "INSERT INTO organ_etats (organe, etat, emetteur, ts) VALUES (?,?,?,?)"
            " ON CONFLICT(organe) DO UPDATE SET etat=?, emetteur=?, ts=?",
            (organe, etat, emetteur, time.time(), etat, emetteur, time.time()))
        return True
    except Exception:
        return False
    finally:
        cx.close()


def etat_courant(organe: str, age_max_s: float = _AGE_ETAT_MAX_S) -> Dict[str, Any]:
    """Etat CONSTATE, avec son age. Trop vieux -> UNKNOWN, jamais le dernier connu.

    Presenter un etat perime comme actuel serait la meme faute que presenter un
    backlog d'hier comme frais.
    """
    try:
        cx = _conn()
    except Exception as exc:  # noqa: BLE001
        return {"organe": organe, "etat": "UNKNOWN", "age_s": None,
                "raison": "base illisible (%s)" % type(exc).__name__}
    try:
        r = cx.execute("SELECT etat, emetteur, ts FROM organ_etats WHERE organe=?",
                       (organe,)).fetchone()
    finally:
        cx.close()
    if not r:
        return {"organe": organe, "etat": "UNKNOWN", "age_s": None,
                "raison": "aucun etat pose"}
    age = time.time() - float(r[2])
    if age > age_max_s:
        return {"organe": organe, "etat": "UNKNOWN", "age_s": age,
                "dernier_connu": r[0], "emetteur": r[1],
                "raison": "etat perime (%.0f s > %.0f s)" % (age, age_max_s)}
    return {"organe": organe, "etat": r[0], "emetteur": r[1], "age_s": age, "raison": ""}


# --------------------------------------------------------------- DEMANDE

def acquerir(organe: str, issuer: str, reason: str, duree_s: float = 300.0,
             priority: int = 50, ref: str = "") -> str:
    """Ouvre un bail de demande. Rend son identifiant.

    REFUSE un demandeur de la couche liveness (`DemandeRefusee`). C'est LE
    garde de ce module : constater qu'un organe vit ne le demande pas. Le refus
    est journalise -- une tentative doit se voir, sinon on ne saura pas qu'un
    keeper a essaye.
    """
    pile = _appelant()
    if _est_liveness(issuer, pile):
        try:
            cx = _conn()
            _journaliser(cx, organe, "DEMAND_REFUSED", issuer=issuer,
                         detail="liveness interdite (pile=%s)" % pile)
            cx.close()
        except Exception:  # muet-ok : le refus prime sur sa trace
            pass
        raise DemandeRefusee(
            "%s appartient a la couche qui CONSTATE (pile=%s) : un organe vivant "
            "n'est pas un organe demande. Poser `poser_etat(%r, 'READY')` a la "
            "place." % (issuer, pile, organe))
    if not reason:
        raise ValueError("une demande sans raison n'est pas instruisible")
    ident = "dem_" + secrets.token_hex(6)
    maintenant = time.time()
    cx = _conn()
    try:
        cx.execute(
            "INSERT INTO organ_demandes (id, organe, issuer, reason, priority, ref,"
            " created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (ident, organe, issuer, reason, int(priority), ref, maintenant,
             maintenant + float(duree_s)))
        _journaliser(cx, organe, "DEMAND_ACQUIRED", ident, issuer,
                     "%s (%.0fs, prio=%d)" % (reason, duree_s, priority))
    finally:
        cx.close()
    return ident


def renouveler(ident: str, duree_s: float = 300.0) -> bool:
    """Prolonge un bail EXISTANT. Ne ressuscite pas un bail libere ou expire :
    un renouvellement n'est pas une acquisition deguisee."""
    cx = _conn()
    try:
        r = cx.execute("SELECT organe, issuer, expires_at, released_at FROM"
                       " organ_demandes WHERE id=?", (ident,)).fetchone()
        if not r or r[3] is not None or float(r[2]) < time.time():
            return False
        cx.execute("UPDATE organ_demandes SET expires_at=? WHERE id=?",
                   (time.time() + float(duree_s), ident))
        _journaliser(cx, r[0], "DEMAND_RENEWED", ident, r[1], "+%.0fs" % duree_s)
        return True
    finally:
        cx.close()


def liberer(ident: str) -> bool:
    """Ferme un bail. Idempotent : liberer deux fois n'est pas une erreur."""
    cx = _conn()
    try:
        r = cx.execute("SELECT organe, issuer, released_at FROM organ_demandes"
                       " WHERE id=?", (ident,)).fetchone()
        if not r or r[2] is not None:
            return False
        cx.execute("UPDATE organ_demandes SET released_at=? WHERE id=?",
                   (time.time(), ident))
        _journaliser(cx, r[0], "DEMAND_RELEASED", ident, r[1])
        return True
    finally:
        cx.close()


def demandes_actives(organe: str) -> List[Dict[str, Any]]:
    """Baux vivants : ni liberes, ni expires. Journalise les expirations au
    passage -- un bail qui s'eteint doit laisser une trace, sinon on ne pourra
    pas mesurer la duree reelle des demandes."""
    maintenant = time.time()
    cx = _conn()
    try:
        expires = cx.execute(
            "SELECT id, organe, issuer FROM organ_demandes WHERE organe=?"
            " AND released_at IS NULL AND expires_at < ?", (organe, maintenant)
        ).fetchall()
        for ident, org, issuer in expires:
            deja = cx.execute(
                "SELECT 1 FROM organ_demandes_journal WHERE id=? AND evenement=?",
                (ident, "DEMAND_EXPIRED")).fetchone()
            if not deja:
                _journaliser(cx, org, "DEMAND_EXPIRED", ident, issuer)
        lignes = cx.execute(
            "SELECT id, issuer, reason, priority, ref, created_at, expires_at"
            " FROM organ_demandes WHERE organe=? AND released_at IS NULL"
            " AND expires_at >= ? ORDER BY priority DESC", (organe, maintenant)
        ).fetchall()
    finally:
        cx.close()
    return [{"id": l[0], "issuer": l[1], "reason": l[2], "priority": l[3],
             "ref": l[4], "created_at": l[5], "expires_at": l[6],
             "reste_s": l[6] - maintenant} for l in lignes]


def resume(organe: str) -> Dict[str, Any]:
    """Ce qu'on sait de l'organe : son etat CONSTATE et ses demandes REELLES.

    Les deux sont volontairement cote a cote et non fusionnes : c'est en les
    voyant diverger qu'on saura si le nouveau signal couvre les cas que
    `llama.wanted` couvrait par accident.
    """
    act = demandes_actives(organe)
    return {
        "organe": organe,
        "etat": etat_courant(organe),
        "demandes": act,
        "demande_active": bool(act),
        "priorite_max": max([d["priority"] for d in act], default=None),
        "note": "TELEMETRIE SEULE — aucun regulateur ne consomme encore ceci.",
    }


def journal(organe: Optional[str] = None, limite: int = 50) -> List[Dict[str, Any]]:
    cx = _conn()
    try:
        if organe:
            lignes = cx.execute(
                "SELECT ts, organe, evenement, id, issuer, detail FROM"
                " organ_demandes_journal WHERE organe=? ORDER BY ts DESC LIMIT ?",
                (organe, limite)).fetchall()
        else:
            lignes = cx.execute(
                "SELECT ts, organe, evenement, id, issuer, detail FROM"
                " organ_demandes_journal ORDER BY ts DESC LIMIT ?", (limite,)).fetchall()
    finally:
        cx.close()
    return [{"ts": l[0], "organe": l[1], "evenement": l[2], "id": l[3],
             "issuer": l[4], "detail": l[5]} for l in lignes]
