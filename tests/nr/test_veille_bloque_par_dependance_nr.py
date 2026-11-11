# -*- coding: utf-8 -*-
"""NR -- une veille dont la recherche web n'a pas eu lieu ne finit JAMAIS `completed` (P1, 10/11).

MESURE QUI L'A DECLENCHE. 5 veilles du 10/11 portaient `error="recherche degradee : SearXNG muet (repli sans
recherche web)"` et finissaient pourtant `completed` (n_stored 1 a 4, abstracts arxiv hors sujet rendus par le repli
academique) ou `completed_empty` (lu « le sujet n'existe pas »). Le motif etait CONNU de l'executeur
(`_motifs_arret`, `_noter_degradation`) mais `verdict_chaine` ne le lisait pas : faux vert, UNKNOWN != NO.
Decision owner 10/11 (lot 1 veille, debat AGY docs/veille/debat_veille_web_tour2_agy_20261110.md §A).

Contrat :
  1. sans motif de degradation, le verdict est INCHANGE (aucune regression des appelants existants) ;
  2. degradation + rien retenu -> `bloque_par_dependance` (jamais `completed_empty`) ;
  3. degradation + contenu retenu -> `completed_partial` (jamais `completed`) ;
  4. une etape encore en cours reste `en_cours`, une lecture illisible reste `indetermine` ;
  5. par le CHEMIN REEL : `ChainExecutor._clore_job_si_chaine_terminee` transmet le motif connu au verdict
     et l'ecrit dans watch_jobs.error.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

W = importlib.import_module("nokido_agent.app.forge_watch_agent")
MOTIF = "recherche degradee : SearXNG muet (repli sans recherche web)"
ETAPES_FINIES = [("keywords", "completed"), ("verify_kw", "completed"), ("search", "completed"),
                 ("refine", "completed"), ("crawl", "completed"), ("ingest", "completed"), ("store", "completed")]


def test_sans_degradation_verdict_inchange():
    assert W.verdict_chaine(ETAPES_FINIES, 3) == "completed"
    assert W.verdict_chaine(ETAPES_FINIES, 0) == "completed_empty"
    assert W.verdict_chaine(ETAPES_FINIES, 0, dedup=True) == "completed_dedup"
    assert W.verdict_chaine(ETAPES_FINIES, 0, degrade=None) == "completed_empty"


def test_degradation_sans_retention_est_bloque_par_dependance():
    assert W.verdict_chaine(ETAPES_FINIES, 0, degrade=MOTIF) == "bloque_par_dependance"
    assert W.verdict_chaine(ETAPES_FINIES, 0, dedup=True, degrade=MOTIF) == "bloque_par_dependance"


def test_degradation_avec_retention_est_partielle_jamais_completed():
    assert W.verdict_chaine(ETAPES_FINIES, 4, degrade=MOTIF) == "completed_partial"


def test_en_cours_et_illisible_priment():
    assert W.verdict_chaine([("search", "running")], 0, degrade=MOTIF) == "en_cours"
    assert W.verdict_chaine(None, 0, degrade=MOTIF) == "indetermine"


@pytest.fixture()
def executeur(tmp_path, monkeypatch):
    E = importlib.import_module("nokido_agent.app.forge_chain_executor")
    db = tmp_path / "veille.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE agent_chain_nodes (chain_id TEXT, step_name TEXT, status TEXT)")
    c.execute("CREATE TABLE watch_jobs (id TEXT PRIMARY KEY, n_stored INTEGER, status TEXT, step TEXT, "
              "error TEXT, updated_at TEXT)")
    c.commit()
    c.close()
    ex = object.__new__(E.ChainExecutor)

    def _conn():
        k = sqlite3.connect(str(db))
        return k
    ex._get_conn = _conn
    ex._relaches = set()
    monkeypatch.setattr(W, "_relacher_docker", lambda cid: None)
    return ex, db


def _job(db, cid, n_stored, statut="running"):
    c = sqlite3.connect(str(db))
    for s, st in ETAPES_FINIES:
        c.execute("INSERT INTO agent_chain_nodes VALUES (?,?,?)", (cid, s, st))
    c.execute("INSERT INTO watch_jobs VALUES (?,?,?,?,?,?)", (cid, n_stored, statut, "store", None, None))
    c.commit()
    c.close()


def _lire(db, cid):
    c = sqlite3.connect(str(db))
    r = c.execute("SELECT status, error FROM watch_jobs WHERE id=?", (cid,)).fetchone()
    c.close()
    return r


def test_chemin_reel_cloture_transmet_le_motif(executeur):
    ex, db = executeur
    _job(db, "wj_vide", 0)
    _job(db, "wj_partiel", 2)
    _job(db, "wj_sain", 2)
    ex._motifs_arret = {"wj_vide": MOTIF, "wj_partiel": MOTIF}
    ex._degradations = {"wj_vide": MOTIF, "wj_partiel": MOTIF}
    assert ex._clore_job_si_chaine_terminee("wj_vide") == "bloque_par_dependance"
    assert _lire(db, "wj_vide") == ("bloque_par_dependance", MOTIF)
    assert ex._clore_job_si_chaine_terminee("wj_partiel") == "completed_partial"
    assert _lire(db, "wj_partiel") == ("completed_partial", MOTIF)
    assert ex._clore_job_si_chaine_terminee("wj_sain") == "completed"
    assert _lire(db, "wj_sain") == ("completed", None)
