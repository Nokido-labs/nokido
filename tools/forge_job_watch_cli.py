"""Surveille un job detache et EMET ses transitions sur stdout.

__FORGE_COLOR__ = "vegetatif/heartbeat : emet les transitions d'un job long vers la boucle du client"

Pourquoi ce module existe (2026-09-13). L'outil `Monitor` du client reveille sa
boucle en transformant chaque ligne de stdout en evenement -- une notification
deposee dans l'inbox ne le fait PAS (mesure du 2026-09-09). Mais `Monitor`
execute du shell NATIF : il echappait a `bash_guard`, donc a toute la politique
d'execution. C'etait un passe-droit, releve et ferme sur directive owner.

Ce CLI est la seule forme de surveillance que `bash_guard` accepte pour
`Monitor` : un script git-tracke, en LECTURE SEULE, dont le comportement est
revu. Le shell libre n'y a plus sa place.

Frere de `tools/forge_job_watch_notify.py`, qui vise l'INBOX (asynchrone, ne
reveille pas la boucle). Les deux coexistent a dessein : meme surveillance,
deux destinataires.

COUVERTURE. Le silence n'est pas un succes : un moniteur qui n'emet que sur le
chemin heureux reste muet sur un crash, et le mutisme ressemble a « ca tourne ».
Trois sorties sont donc emises -- fin (`.rc` present), GEL (le journal cesse de
grossir), DEPASSEMENT. Et jamais `kill -0` : sous Git Bash il interroge la table
de PID MSYS, pas Windows, et a deja declare morte une CI bien vivante.

  LAFORGE_PYTHON tools/forge_job_watch_cli.py --job job_xxx [--gel-s 900]

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `lire_bilan` — Etat GRADUE d'un job fini : ECHEC · ARRET_GARDE · VIDE · DECLARE · TERMINE_NON_VERIFIE · INCONNU. Jamais VERIFIED.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "sandbox" / "jobs"


def _mtime(p: Path):
    """mtime, ou None si illisible. None n'est PAS 'pas de progres'."""
    try:
        return p.stat().st_mtime
    except OSError:
        return None


TACHES = ROOT / "sandbox" / "tasks.db"
_TERMINAUX = ("done", "failed", "error", "cancelled", "timeout")


def _etat_tache(task_id: str, db=None):
    """(status, longueur_du_result) — `(None, 0)` si illisible ou inconnue.

    `None`, jamais une chaine : une base verrouillee ou une tache absente ne
    doivent pas se lire comme un statut. ILLISIBLE != PAS_LA != EN_COURS.
    """
    import sqlite3
    chemin = Path(db) if db else TACHES
    if not chemin.exists():
        return None, 0
    try:
        c = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=3)
        try:
            ligne = c.execute(
                "SELECT status, COALESCE(LENGTH(result), 0) FROM tasks WHERE id = ?",
                (task_id,)).fetchone()
        finally:
            c.close()
    except Exception:  # noqa: BLE001 — muet-ok : l'appelant recoit None et le DIT
        return None, 0
    return (ligne[0], ligne[1]) if ligne else (None, 0)


def surveiller_tache(task_id: str, gel_s: int, max_s: int, intervalle: int,
                     ecrire=print, db=None, horloge=time.time, dormir=time.sleep) -> int:
    """Surveille une TACHE M2M (`tasks.db`) comme `surveiller` suit un job.

    POURQUOI. Une reponse deposee dans l'inbox ne REVEILLE PAS la boucle du
    client. Le 2026-09-22, une tache confiee a ANTIGRAVITY a repondu en
    quelques minutes : vue au tour suivant, par hasard. Le meme jour, le
    verdict d'une CI distante est reste trois heures non lu.

    CE QU'ON N'ANNONCE JAMAIS. Le statut d'une tache dit ce que l'agent
    AFFIRME, pas ce qu'il a PRODUIT. Mesure du meme jour :

        status=done  intent=OK_DONE  status_code=SUCCESS
        detail="Je suis EN TRAIN d'executer... J'ATTENDS le premier lot."

    et l'artefact visé n'avait pas bouge depuis un mois. L'emission renvoie
    donc toujours a l'artefact, et ne dit jamais « reussi ».

        ACCEPTED DECLARE ACHIEVED — c'est le faux calme qu'on refuse de relayer.
    """
    debut = horloge()
    vu, _ = _etat_tache(task_id, db)
    dernier_changement = debut
    if vu is not None:
        ecrire("TACHE %s statut=%s — un statut dit ce que l'agent AFFIRME ; "
               "l'effet se lit sur l'ARTEFACT vise" % (task_id, vu))

    while True:
        statut, taille = _etat_tache(task_id, db)
        maintenant = horloge()

        if statut is not None and statut != vu:
            vu, dernier_changement = statut, maintenant
            ecrire("TACHE %s -> %s (result %d o) — statut AFFIRME, pas effet "
                   "constate : relire l'ARTEFACT vise par la tache"
                   % (task_id, statut, taille))

        if statut in _TERMINAUX:
            ecrire("TACHE %s TERMINALE statut=%s — ne pas conclure sur OK_DONE : "
                   "l'ARTEFACT tranche (mesure 2026-09-22 : un done/SUCCESS "
                   "n'avait rien produit)" % (task_id, statut))
            return 0

        if maintenant - dernier_changement > gel_s:
            ecrire("TACHE %s FIGEE — statut %s inchange depuis %d min"
                   % (task_id, vu if vu is not None else "ILLISIBLE",
                      int((maintenant - dernier_changement) / 60)))
            return 0

        if maintenant - debut > max_s:
            ecrire("TACHE %s TOUJOURS EN COURS apres %d min — ni fin ni gel"
                   % (task_id, int((maintenant - debut) / 60)))
            return 0

        dormir(intervalle)


# BILAN GRADUE (fiche de veille V2, 2026-09-23). Ce CLI rappelait que le rc n'est
# qu'un signal... puis s'arretait la. Payes le meme jour : vague 5 finie rc=0 sans
# bilan, un rc=0 a 0 chunk, un arret de garde disque (rc=5) a relire a la main.
# Il lit donc le BILAN que le producteur ecrit. `DECLARE` = l'affirmation du
# producteur, JAMAIS `VERIFIED` : la preuve independante (compte en base par
# source) est hors de portee d'un notifieur en lecture seule. NR :
# tests/nr/test_job_watch_bilan_gradue_nr.py
import re as _re

_QUEUE_OCTETS = 256 * 1024
# Un arret de garde TERMINE le job : il est en QUEUE de journal. Un « ARRET » suivi de travail est
# la sortie d'autre chose -- mesure 2026-09-26 : une CI verte (12 462 tests, 0 echec) annoncee
# ARRET_GARDE sur une ligne imprimee par un NR de ci-attente qui simule des admissions.
_QUEUE_ARRET = 30
_BILANS = (_re.compile(r"TOTAL\s+(\d+)\s+chunks"),
           _re.compile(r"=== RAG : \+(\d+) chunks"))
# Le bilan d'une CI (`tools/ci_local.py`) est sa ligne `[preuve]`, calculee sur le JUnit. Mesure
# 2026-09-26 : la CI de reference job_e073b2edba52 (12 496 executes, 0 echec, SUITE_COMPLETE)
# annoncee ECHEC -- 13 Traceback IMPRIMES par des tests qui passent, et faute de bilan
# d'ingestion le premier suffisait. Meme famille que ARRET_GARDE : la sortie d'un test n'est
# pas la fin du job.
_DEFAILLANCES_CI = ("echecs", "erreurs", "timeouts")
_ANSI = _re.compile(r"\x1b\[[0-9;]*m")


def _preuve_ci(lignes: list) -> tuple:
    """(index, champs, ligne) de la DERNIERE ligne `[preuve]`, ou (-1, None, "")."""
    for i in range(len(lignes) - 1, -1, -1):
        if "[preuve]" in lignes[i]:
            ligne = _ANSI.sub("", lignes[i]).strip()
            return i, dict(_re.findall(r"(\w+)=(\S+)", ligne)), ligne
    return -1, None, ""


def lire_bilan(texte: str, rc: str) -> dict:
    """Etat GRADUE d'un job fini : ECHEC · ARRET_GARDE · VIDE · DECLARE ·
    TERMINE_NON_VERIFIE · INCONNU. Jamais VERIFIED (voir plus haut)."""
    rc = (rc or "").strip()
    if not rc.lstrip("-").isdigit():
        return {"etat": "INCONNU", "motif": "rc illisible : %s" % rc[:80]}
    lignes = (texte or "").splitlines()
    dernier_bilan, n_chunks = -1, None
    for i, l in enumerate(lignes):
        for motif in _BILANS:
            m = motif.search(l)
            if m:
                dernier_bilan, n_chunks = i, int(m.group(1))
    i_preuve, preuve, ligne_preuve = _preuve_ci(lignes)
    non_vides = [l.strip() for l in lignes if l.strip()]
    arret = [l for l in non_vides[-_QUEUE_ARRET:] if "ARRET" in l]
    if arret:
        return {"etat": "ARRET_GARDE", "motif": arret[-1][:240]}
    tb = [i for i, l in enumerate(lignes) if l.startswith("Traceback")]
    if tb and tb[-1] > max(dernier_bilan, i_preuve):
        fin = [l.strip() for l in lignes[tb[-1]:] if l.strip()]
        return {"etat": "ECHEC", "motif": (fin[-1] if fin else "Traceback")[:240]}
    if rc != "0":
        return {"etat": "ECHEC", "motif": "rc=%s %s" % (
            rc, ligne_preuve[:200] if preuve is not None else "sans motif lisible dans le journal")}
    if preuve is not None:
        if any(preuve.get(k, "0") != "0" for k in _DEFAILLANCES_CI):
            return {"etat": "ECHEC", "motif": ligne_preuve[:240]}
        if preuve.get("etat") != "SUITE_COMPLETE":
            return {"etat": "TERMINE_NON_VERIFIE", "motif": "suite incomplete : " + ligne_preuve[:200]}
        return {"etat": "DECLARE",
                "motif": "preuve CI du producteur, NON verifiee (JUnit) : " + ligne_preuve[:200]}
    if n_chunks is None:
        return {"etat": "TERMINE_NON_VERIFIE", "motif": "rc=0 sans ligne de bilan : le silence n'est pas un succes"}
    if n_chunks == 0:
        return {"etat": "VIDE", "chunks": 0, "motif": "bilan a 0 chunk"}
    return {"etat": "DECLARE", "chunks": n_chunks,
            "motif": "bilan du producteur, NON verifie en base"}


def _queue_du_journal(log: Path) -> tuple[str, str]:
    """Les derniers octets du journal, et DIT s'il a ete tronque (borne annoncee)."""
    try:
        taille = log.stat().st_size
        with log.open("rb") as f:
            if taille > _QUEUE_OCTETS:
                f.seek(taille - _QUEUE_OCTETS)
            brut = f.read()
    except OSError as e:
        return "", "journal illisible (%s)" % type(e).__name__
    note = "" if taille <= _QUEUE_OCTETS else "lu sur les %d Ko de fin" % (_QUEUE_OCTETS // 1024)
    return brut.decode("utf-8", errors="replace"), note


def surveiller(job: str, gel_s: int, max_s: int, intervalle: int, ecrire=print,
               jobs_dir=None, horloge=time.time, dormir=time.sleep) -> int:
    """Surveille un job. `jobs_dir`/`horloge`/`dormir` existent pour le NR.

    Une constante figee a l'import ne se redirige pas : sans ce parametre, le
    test ne pourrait pas fabriquer un job temoin, et le module resterait
    verifie seulement « par lecture ». Defaut paye ailleurs le meme jour --
    une redirection qui court-circuite le point d'injection casse d'abord la
    testabilite.
    """
    base = Path(jobs_dir) if jobs_dir else JOBS
    rc = base / ("%s.rc" % job)
    log = base / ("%s.log" % job)
    debut = horloge()
    dernier_vu = None
    dernier_progres = debut

    while True:
        if rc.exists():
            try:
                code = rc.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as e:
                code = "ILLISIBLE (%s)" % type(e).__name__
            # Les Traceback partent sur STDERR (`.err`), pas dans le `.log` : sans lui,
            # un echec etait note ECHEC mais SANS son motif (controle du 2026-09-23).
            texte, note = _queue_du_journal(log)
            texte_err, _ = _queue_du_journal(base / ("%s.err" % job))
            b = lire_bilan(texte + "\n" + texte_err, code)
            ecrire("JOB %s TERMINE rc=%s — le rc est un SIGNAL, le verdict se lit "
                   "sur l'artefact (JUnit, rapport), jamais sur lui | bilan %s%s : %s%s"
                   % (job, code, b["etat"],
                      "(%d)" % b["chunks"] if b.get("chunks") is not None else "",
                      b["motif"], (" [%s]" % note) if note else ""))
            return 0

        m = _mtime(log)
        maintenant = horloge()
        if m is None:
            # Journal pas encore cree, ou illisible : on ne conclut pas.
            dernier_progres = maintenant if dernier_vu is None else dernier_progres
        elif m != dernier_vu:
            dernier_vu = m
            dernier_progres = maintenant

        if maintenant - dernier_progres > gel_s:
            ecrire("JOB %s FIGE — journal sans ecriture depuis %d min, et aucun .rc"
                   % (job, int((maintenant - dernier_progres) / 60)))
            return 0

        if maintenant - debut > max_s:
            ecrire("JOB %s TOUJOURS EN COURS apres %d min — ni fin ni gel detecte"
                   % (job, int((maintenant - debut) / 60)))
            return 0

        dormir(intervalle)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # `--job` et `--task` s'excluent : un seul sujet par surveillance. Sans
    # `required`, oublier les deux rendrait un usage, pas un plantage.
    cible = ap.add_mutually_exclusive_group(required=True)
    cible.add_argument("--job", help="job_id rendu par run_job")
    cible.add_argument("--task", help="task_id d'une tache M2M (tasks.db)")
    ap.add_argument("--gel-s", type=int, default=900,
                    help="silence du journal au-dela duquel on declare un GEL")
    ap.add_argument("--max-s", type=int, default=4800, help="borne dure")
    ap.add_argument("--intervalle", type=int, default=20)
    a = ap.parse_args(argv)
    sujet = a.job or a.task
    if "/" in sujet or "\\" in sujet or ".." in sujet:
        print("REFUS : --job/--task est un identifiant, pas un chemin")
        return 2
    if a.task:
        return surveiller_tache(a.task, a.gel_s, a.max_s, a.intervalle)
    return surveiller(a.job, a.gel_s, a.max_s, a.intervalle)


if __name__ == "__main__":
    raise SystemExit(main())
