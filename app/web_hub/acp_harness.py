# -*- coding: utf-8 -*-
"""Adaptateur LECTURE SEULE : taches ANTIGRAVITY de sandbox/tasks.db -> sessions au format du journal ACP.

AGY ne parle pas ACP. forge_task_executor._delegate_to_agy lance `agy --print` hors harness ; la seule trace
durable est la ligne de la table tasks (agent ANTIGRAVITY). Session = "agy-<job_id ou id>", prompt =
description, reponse = result, fermee quand status in done/failed/completed.

Base ouverte en file:...?mode=ro ; 50 taches les plus recentes par SEARCH rowid (fenetre bornee, pas de
SCAN) ; description/result tronques a la source (substr) avec "tronque" dit ; base illisible -> entree
ILLISIBLE (jamais une liste vide). Payloads passes par le redacteur existant (forge_acp_client._journal_caviarde).
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

__FORGE_COLOR__ = "peau/front ACP : projection lecture seule des taches ANTIGRAVITY de sandbox/tasks.db"

log = logging.getLogger("nokido.hub.acp_harness")

ROOT = Path(__file__).resolve().parents[2]   # CODE (tools/) : suit le paquet


def _racine_donnees() -> Path:
    """Les DONNEES (tasks.db) suivent forge_db_path.racine_donnees(), jamais __file__ (cliquet racine_donnees)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        from forge_db_path import racine_donnees
    return racine_donnees()


DB_PATH = _racine_donnees() / "sandbox" / "tasks.db"
MAX_JOBS = 50
MAX_LECTURE = 2 * 1024 * 1024
FENETRE = 5000  # fenetre de rowid recents examinee : SEARCH par rowid, jamais de SCAN de table
TERMINAUX = ("done", "failed", "completed")
_COLS = ("rowid, id, job_id, status, created_at, updated_at, "
         "substr(description,1,{d}), length(description), substr(result,1,{r}), length(result)")
REQUETE_RECENTES = ("SELECT " + _COLS.format(d="?3", r="?4") + " FROM tasks "
                    "WHERE rowid > (SELECT max(rowid) FROM tasks) - ?1 AND agent = 'ANTIGRAVITY' "
                    "ORDER BY rowid DESC LIMIT ?2")
REQUETE_UNE = "SELECT " + _COLS.format(d="?2", r="?3") + " FROM tasks WHERE rowid = ?1"
AGENT = "agy"
ILLISIBLE = "ILLISIBLE"


def _caviarder(texte: str) -> str:
    """Redacteur EXISTANT, via l'enveloppe de forge_acp_client."""
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from forge_acp_client import _journal_caviarde

    sortie: list = []
    _journal_caviarde(sortie.append)(texte)
    return sortie[0]


def _caviarder_valeur(v):
    """Caviarde chaque chaine d'une charge imbriquee (parcours commun : forge_utils.mapper_chaines)."""
    from nokido_agent.app.forge_utils import mapper_chaines
    return mapper_chaines(v, _caviarder)


def _ouvrir(db) -> sqlite3.Connection:
    """Connexion LECTURE SEULE (file:...?mode=ro) : toute ecriture leve OperationalError."""
    con = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=2.0)
    con.execute("PRAGMA query_only=ON")
    return con


def _ts(v):
    """created_at/updated_at : epoch numerique, sinon ISO converti en epoch, sinon valeur brute."""
    try:
        return float(v)
    except (TypeError, ValueError):  # muet-ok : pas un epoch numerique, l'essai ISO qui suit decide
        pass
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return v


def _termine(status) -> bool:
    return str(status or "").strip().lower() in TERMINAUX


def _illisible(sid: str, e: Exception) -> dict:
    log.warning("tasks.db illisible pour la projection AGY : %s (%s)", type(e).__name__, e)
    return {"session": sid, "agent": AGENT, "etat": ILLISIBLE, "erreur": type(e).__name__, "lignes": []}


def _lignes(r, cap_aff: bool = True) -> dict:
    """Projette une ligne de REQUETE_RECENTES / REQUETE_UNE en session au format du journal."""
    (_rid, tid, job_id, status, created, updated, desc, ldesc, res, lres) = r
    sid = "agy-" + str(job_id or tid)
    lignes: list = []

    def ligne(ts, kind, payload):
        lignes.append({"ts": _ts(ts), "session": sid, "agent": AGENT, "kind": kind,
                       "payload": _caviarder_valeur(payload)})

    ligne(created, "ouverte", {"task": tid, "job_id": job_id, "status": status})
    ligne(created, "prompt", {"send": desc or "", "tronque": (ldesc or 0) > len(desc or "")})
    if res:
        ligne(updated or created, "reponse",
              {"output": res, "tronque": (lres or 0) > len(res), "status": status})
    fini = _termine(status)
    if fini:
        ligne(updated or created, "fermee", {})
    return {"session": sid, "agent": AGENT, "etat": "TERMINE" if fini else "EN_COURS", "lignes": lignes}


def sessions_agy() -> list:
    cap = MAX_LECTURE // MAX_JOBS
    try:
        con = _ouvrir(DB_PATH)
        try:
            rows = con.execute(REQUETE_RECENTES, (FENETRE, MAX_JOBS, cap, cap)).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError) as e:
        s = _illisible("agy-illisible", e)
        return [{"session": s["session"], "agent": AGENT, "etat": ILLISIBLE, "dernier_ts": None,
                 "lignes": 0, "erreur": s["erreur"]}]
    out = []
    for r in rows:
        s = _lignes(r)
        out.append({"session": s["session"], "agent": AGENT, "etat": s["etat"],
                    "dernier_ts": s["lignes"][-1]["ts"], "lignes": len(s["lignes"])})
    return out


def session_agy(sid: str, n: int = 200):
    """None si inconnue (ou hors des 50 plus recentes) ; session ILLISIBLE dite si la base l'est."""
    if not sid.startswith("agy-"):
        return None
    cap = MAX_LECTURE // MAX_JOBS
    try:
        con = _ouvrir(DB_PATH)
        try:
            rows = con.execute(REQUETE_RECENTES, (FENETRE, MAX_JOBS, cap, cap)).fetchall()
            trouve = next((r for r in rows if "agy-" + str(r[2] or r[1]) == sid), None)
            if trouve is None:
                return None
            r = con.execute(REQUETE_UNE, (trouve[0], MAX_LECTURE, MAX_LECTURE)).fetchone()
        finally:
            con.close()
    except (sqlite3.Error, OSError) as e:
        return _illisible(sid, e)
    s = _lignes(r)
    s["lignes"] = s["lignes"][-n:]
    s["permissions"] = "aucune : AGY n'emet pas de permission"
    return s
