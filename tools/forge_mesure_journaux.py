#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mesure AVANT / APRES du switch des journaux : la grosse base CESSE-T-ELLE de recevoir ?

__FORGE_COLOR__ = 'metabolisme/mesure : ecritures des journaux sur la base RAG, par fenetre'

Contrat owner du 2026-09-19 : « on ne deplace pas des tables, on RETIRE DES
ECRIVAINS DU VERROU RAG ». Le critere est NEGATIF : la base de 26 Go doit cesser
de recevoir. La fiche du chantier exige un comptage SUR FENETRE -- une moyenne
all-time ment sur les rafales -- et que rien d'autre ne bouge pendant la fenetre.

Ce qui est mesure, pour chaque journal (`token_usage`, `inspector_log`,
`conversation_log`), dans la base RAG ET dans sa base cible (`journal_path`) :
  * INSERTIONS  = ecart de MAX(rowid) entre deux instantanes ;
  * WAL         = taille et horodatage du `-wal` de la base RAG ;
  * LATENCE RAG = mediane de 5 executions d'une requete FTS fixe.

Trois etats, jamais deux : une table absente vaut ABSENTE, une base qu'on ne peut
ouvrir vaut ILLISIBLE -- jamais 0, qui se lirait « plus aucune ecriture ».
Lecture SEULE (`mode=ro`) : un instrument qui ecrit dans la base qu'il mesure
fausse sa propre mesure.

    run action=run_job script=tools/forge_mesure_journaux.py
        script_args="--label AVANT --fenetre 1800"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

JOURNAUX = ("token_usage", "inspector_log", "conversation_log")

# Ce que cette version NE mesure PAS -- dit dans chaque rapport, jamais tu.
NON_MESURE = [
    "suppressions du rotateur d'inspector_log (forge_log_retention) : MAX(rowid) "
    "ne compte que les insertions, le churn WAL reel est superieur",
    "erreurs `database is locked` : journal du hub non localise par cet instrument",
]


def _ouvrir(chemin: str):
    p = Path(chemin)
    if not p.exists():
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True, timeout=5)
    except sqlite3.Error:
        return None


def compter(chemin: str) -> dict:
    """{journal: MAX(rowid) | 'ABSENTE' | 'ILLISIBLE'} -- lecture seule."""
    c = _ouvrir(chemin)
    if c is None:
        return {j: "ILLISIBLE" for j in JOURNAUX}
    out = {}
    try:
        for j in JOURNAUX:
            try:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                 (j,)).fetchone():
                    out[j] = "ABSENTE"
                    continue
                out[j] = int(c.execute("SELECT COALESCE(MAX(rowid), 0) FROM %s" % j).fetchone()[0])
            except sqlite3.Error:
                out[j] = "ILLISIBLE"
    finally:
        c.close()
    return out


def ecarts(avant: dict, apres: dict) -> dict:
    """Insertions sur la fenetre ; un etat non numerique se PROPAGE, jamais 0."""
    d = {}
    for j in JOURNAUX:
        a, b = avant.get(j), apres.get(j)
        d[j] = (b - a) if isinstance(a, int) and isinstance(b, int) else (
            a if not isinstance(a, int) else b)
    return d


def _wal(chemin: str) -> dict:
    w = Path(chemin + "-wal")
    if not w.exists():
        return {"etat": "ABSENT"}
    try:
        s = w.stat()
        return {"octets": s.st_size, "mtime": s.st_mtime}
    except OSError:
        return {"etat": "ILLISIBLE"}


def _latence_rag(chemin: str) -> dict:
    c = _ouvrir(chemin)
    if c is None:
        return {"etat": "ILLISIBLE"}
    try:
        t = []
        for _ in range(5):
            t0 = time.perf_counter()
            c.execute("SELECT COUNT(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH 'nokido'").fetchone()
            t.append((time.perf_counter() - t0) * 1000)
        return {"mediane_ms": round(statistics.median(t), 2), "n": len(t)}
    except sqlite3.Error as exc:
        return {"etat": "ILLISIBLE", "raison": str(exc)[:120]}
    finally:
        c.close()


def _instantane(base_rag: str, cibles: dict) -> dict:
    return {"t": time.time(), "rag": compter(base_rag), "wal": _wal(base_rag),
            "latence": _latence_rag(base_rag),
            "cibles": {nom: compter(ch) for nom, ch in cibles.items()}}


def _chemins_reels():
    """Base RAG et cibles des journaux, DEMANDEES a l'accesseur -- jamais devinees."""
    import forge_db_path as D

    return D.db_path(), {j: D.journal_path(j) for j in JOURNAUX}, {
        "interrupteur_pose": D.journaux_bascules(),
        "retenus": sorted(getattr(D, "journaux_retenus", dict)()),
    }


def fenetre(fenetre_s: float, label: str, base_rag=None, cibles=None, sortie=None) -> dict:
    etat = {}
    if base_rag is None:
        base_rag, cibles, etat = _chemins_reels()
    cibles = cibles or {}
    t0 = _instantane(base_rag, cibles)
    time.sleep(max(0.0, fenetre_s))
    t1 = _instantane(base_rag, cibles)
    duree_min = max(1e-9, (t1["t"] - t0["t"]) / 60.0)
    rag = ecarts(t0["rag"], t1["rag"])
    rapport = {
        "label": label, "base_rag": base_rag, "cibles": cibles, "accesseur": etat,
        "debut": t0["t"], "fin": t1["t"], "duree_min": round(duree_min, 2),
        "insertions_base_rag": rag,
        "par_minute_base_rag": {j: (round(v / duree_min, 3) if isinstance(v, int) else v)
                                for j, v in rag.items()},
        "insertions_cibles": {n: ecarts(t0["cibles"][n], t1["cibles"][n]) for n in cibles},
        "wal": {"avant": t0["wal"], "apres": t1["wal"]},
        "latence_rag": {"avant": t0["latence"], "apres": t1["latence"]},
        "non_mesure": list(NON_MESURE),
    }
    sortie = Path(sortie or ROOT / "sandbox" / ("mesure_journaux_%s_%s.json"
                                                % (label, time.strftime("%Y%m%d_%H%M%S"))))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    rapport["sortie"] = str(sortie)
    return rapport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--fenetre", type=float, default=1800.0)
    a = ap.parse_args(argv)
    r = fenetre(a.fenetre, a.label)
    print("[mesure] %s %.1f min -> %s" % (a.label, r["duree_min"], r["sortie"]), flush=True)
    print("[mesure] insertions base RAG : %s" % r["insertions_base_rag"], flush=True)
    print("[mesure] NON MESURE : %s" % " | ".join(r["non_mesure"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
