# -*- coding: utf-8 -*-
"""NR 7/11 (job_bce6a446, job_52e89513) : 0 commit, 0 fichier, « je n'ai rien fait » -> done/SUCCESS sur le panneau
de la veille. Aucun effet observe, ou JSON final ERR_*, ne donne jamais SUCCESS ; la cause est NON_LIVRE."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402
import forge_job_watch_cli as W  # noqa: E402

VIDE = "[effet observe] commits produits : 0 (aucun) ; fichiers non commites : 0"
RIEN = VIDE + " | je n'ai rien fait"
FICHIER = "[effet observe] commits produits : 0 (aucun) ; fichiers non commites : 1 | rapport ecrit"


def _cloture(monkeypatch, ok, detail, intent=None):
    vus, marques = [], []
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(":memory:"))
    # 7/11 (7aa64ee12) : `_mark_done` recoit aussi `workdir=` (juge sur le worktree de la tache) ; la doublure l'accepte.
    monkeypatch.setattr(T, "_mark_done", lambda conn, tid, res, o, workdir=None: marques.append(o))
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_noter_cause_echec", lambda conn, tid, cause: vus.append(cause))
    T._clore_delegation("t1", "jeton", ok, detail, intent)
    return vus, marques


def test_aucun_effet_n_est_pas_success(monkeypatch):
    assert T._statut_livraison(True, RIEN) != "SUCCESS"
    vus, marques = _cloture(monkeypatch, True, RIEN)
    assert vus == ["NON_LIVRE"] and marques == [False]


def test_json_final_err_internal_n_est_pas_success(monkeypatch):
    assert T._statut_livraison(True, FICHIER, "ERR_INTERNAL") != "SUCCESS"
    vus, marques = _cloture(monkeypatch, True, FICHIER, "ERR_INTERNAL")
    assert vus == ["NON_LIVRE"] and marques == [False]


def test_la_veille_suit_la_cause():
    assert W._livraison(RIEN, "done") != "SUCCESS"


def test_fichier_rendu_reste_success(monkeypatch):
    assert T._statut_livraison(True, FICHIER) == "SUCCESS"
    vus, marques = _cloture(monkeypatch, True, FICHIER)
    assert vus == [None] and marques == [True]
    assert W._livraison(FICHIER, "done") == "SUCCESS"


def test_pointeur_vers_artefact_reste_success():
    d = VIDE + ' | {"intent":"OK_DONE","pointer_ref":"sandbox/rapport.md"}'
    assert T._statut_livraison(True, d) == "SUCCESS"


def test_annulation_par_l_emetteur_n_est_pas_un_echec_agent(monkeypatch):
    vus, marques = _cloture(monkeypatch, True, VIDE + " | ANNULEE_SANS_EXECUTEUR")
    assert vus == [None] and marques == [True]


def test_prose_qui_cite_l_annulation_ne_s_exempte_pas():
    # 7/11 : l'exemption vaut quand le marqueur OUVRE le rendu ; citee au milieu d'une prose, elle ne juge pas.
    assert T._statut_livraison(True, VIDE + " | je n'ai rien fait (pas ANNULEE_SANS_EXECUTEUR)") != "SUCCESS"
