# -*- coding: utf-8 -*-
"""NR -- relecture 1/11 de la livraison AGY (coupe-circuit 3 etats) : `_reaffecter` appelait
`autoriser_essai_half_open(a)` DANS le filtre des candidats ; chaque candidat HALF_OPEN evalue voyait son unique essai
verrouille, choisi ou non. L'essai se consomme sur le SEUL candidat retenu."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def test_le_filtre_des_candidats_ne_consomme_aucun_essai():
    src = inspect.getsource(T._reaffecter)
    debut = src.index("vivants = [")
    filtre = src[debut:src.index("]", src.index('!= "OPEN"', debut)) + 1]
    assert "autoriser_essai_half_open" not in filtre


def test_l_essai_est_consomme_sur_le_candidat_retenu(tmp_path, monkeypatch):
    etat = {}
    monkeypatch.setattr(T, "_lire_coupe_circuit", lambda: etat)
    monkeypatch.setattr(T, "_ecrire_coupe_circuit", lambda e: etat.update(e))
    for nom in ("A", "B"):
        etat[nom] = {"etat": "HALF_OPEN", "trial_active": False}
    vivants = ["A", "B"]
    vers = next((a for a in vivants if T.autoriser_essai_half_open(a)[0]), None)
    assert vers == "A" and etat["A"]["trial_active"] is True and etat["B"]["trial_active"] is False
    assert "next((a for a in vivants if autoriser_essai_half_open(a)[0]), None)" in inspect.getsource(T._reaffecter)
