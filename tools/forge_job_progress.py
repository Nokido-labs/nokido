#!/usr/bin/env python3
"""forge_job_progress — l'avancement d'un job detache, partage par tous les clients.

__FORGE_COLOR__ = "sn-vegetatif/interoception-jobs"

POURQUOI CE MODULE EXISTE (enfin)
=================================
`forge_job_runner.read_job()` joint une cle `progress` depuis `forge_job_progress`
et `forge_vitals_tools` appelle `all_active(900)`. DEUX consommateurs — et le module
n'avait JAMAIS ete ecrit : `git log` sur son chemin est vide. Les deux imports
tombaient dans un `except` best-effort, donc `job_status` rendait `progress: null`
**par construction**, sans que rien ne le signale. Mesure 2026-09-03 : un run de CI
locale a ete suivi a l'aveugle, par polling du `log_tail`, alors qu'un champ prevu
pour ca existait dans la reponse.

C'est le motif deja consigne — un mecanisme presume actif qui n'a pas d'emetteur —
applique ici a l'observabilite : un lecteur, une cle dans le contrat de sortie, et
personne pour ecrire. **L'existence d'un mecanisme n'est pas son effet.**

CONTRAT
=======
- `emit(...)`  : appele PAR LE SCRIPT DU JOB. L'id vient de `LAFORGE_JOB_ID`, que
                 le wrapper de `forge_job_runner` injecte dans l'environnement.
- `read(id)`   : l'etat courant, ou None. Jamais d'exception : un lecteur
                 d'observabilite ne casse pas l'appel qu'il enrichit.
- `all_active` : les jobs ayant emis recemment.

L'etat vit a cote des autres fichiers du job (`sandbox/jobs/<id>.progress.json`),
donc meme repertoire partage entre le compte du job et celui du hub, et il survit
au restart comme le reste de l'etat des jobs. Ecriture ATOMIQUE (fichier temporaire
puis remplacement) : sans cela un lecteur tombe un jour sur un JSON tronque, et
cette panne-la n'arrive que sous charge.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

JOBS_DIR = Path(os.environ.get(
    "LAFORGE_JOBS_DIR",
    str(Path(__file__).resolve().parent.parent / "sandbox" / "jobs")))

_LOG = logging.getLogger("Nokido.JobProgress")


def _fichier(job_id: str) -> Path:
    return JOBS_DIR / ("%s.progress.json" % job_id)


def _id_courant(job_id: str | None = None) -> str:
    return (job_id or os.environ.get("LAFORGE_JOB_ID") or "").strip()


def emit(etape: str = "", *, index: int | None = None, total: int | None = None,
         message: str = "", job_id: str | None = None) -> bool:
    """Publie l'avancement du job courant. -> True si ecrit.

    Rend False (et le journalise en debug) quand il n'y a pas d'id : appele hors
    d'un job, il n'y a rien a publier — mais le silence total ferait croire a une
    emission reussie, et c'est precisement ce genre de faux positif qui a laisse
    ce module manquant pendant si longtemps.
    """
    jid = _id_courant(job_id)
    if not jid:
        _LOG.debug("emit ignore : aucun LAFORGE_JOB_ID (hors job ?)")
        return False
    etat = {
        "job_id": jid,
        "etape": str(etape)[:200],
        "index": index,
        "total": total,
        "pct": (round(100.0 * index / total, 1)
                if isinstance(index, int) and isinstance(total, int) and total > 0
                else None),
        "message": str(message)[:400],
        "ts": time.time(),
    }
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        cible = _fichier(jid)
        tmp = cible.with_suffix(".tmp")
        tmp.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, cible)   # atomique : jamais de JSON tronque cote lecteur
        return True
    except OSError as e:
        _LOG.debug("emit %s impossible : %s", jid, type(e).__name__)
        return False


def read(job_id: str) -> dict | None:
    """Avancement d'un job, ou None. Ne leve JAMAIS.

    None couvre trois cas distincts qu'on ne peut pas separer ici sans mentir :
    le job n'a rien emis, le fichier est illisible, ou il est corrompu. Le champ
    `age_s` permet au lecteur de distinguer un job muet d'un job fige.
    """
    jid = (job_id or "").strip()
    if not jid or "/" in jid or "\\" in jid:
        return None
    try:
        f = _fichier(jid)
        if not f.is_file():
            return None
        etat = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _LOG.debug("read %s illisible : %s", jid, type(e).__name__)
        return None
    try:
        etat["age_s"] = round(time.time() - float(etat.get("ts") or 0), 1)
    except (TypeError, ValueError):
        etat["age_s"] = None
    return etat


def all_active(max_age_s: float = 900.0) -> list[dict]:
    """Jobs ayant emis dans la fenetre. Trie du plus recent au plus ancien."""
    vus: list[dict] = []
    try:
        fichiers = sorted(JOBS_DIR.glob("*.progress.json"))
    except OSError as e:
        _LOG.debug("all_active : repertoire illisible (%s)", type(e).__name__)
        return []
    for f in fichiers:
        etat = read(f.name[:-len(".progress.json")])
        if etat and etat.get("age_s") is not None and etat["age_s"] <= max_age_s:
            vus.append(etat)
    return sorted(vus, key=lambda e: e.get("ts") or 0, reverse=True)


def clear(job_id: str) -> bool:
    """Retire l'etat d'avancement (fin de job). Best-effort."""
    jid = _id_courant(job_id)
    if not jid:
        return False
    try:
        _fichier(jid).unlink(missing_ok=True)
        return True
    except OSError as e:
        _LOG.debug("clear %s impossible : %s", jid, type(e).__name__)
        return False
