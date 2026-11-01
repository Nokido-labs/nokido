"""NR du 27/10 : la soif remesure une lacune avec l'instrument QUI L'A OUVERTE.

Avant : le demon remesurait TOUT par coverage_dense ; `remesurer_lacune` refuse un instrument different,
donc une lacune ouverte par un autre instrument ne pouvait JAMAIS fermer. Decision owner : brancher la soif
sur les lacunes reelles du take-home, fermees par le banc (cycles) ou par z3 (fenetre tranchee).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N))
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402


def test_banc_takehome_gap_tant_que_le_seuil_n_est_pas_battu(tmp_path, monkeypatch):
    reg = tmp_path / "registre_preuves.jsonl"
    reg.write_text(json.dumps({"statut": "VALEUR", "correct": True, "cycles": 1017, "empreinte": "e1"}) + "\n"
                   + json.dumps({"statut": "ECHEC_METIER", "correct": False, "cycles": 700}) + "\n",
                   encoding="utf-8")
    monkeypatch.setattr(ev, "_DEFI_TAKEHOME", tmp_path)
    c = ev.mesurer_selon_instrument({"instrument": "banc_takehome", "critere": {"seuil_cycles": 1000}})
    assert c["ok"] and c["instrument"] == "banc_takehome" and c["gap"] is True and c["score"] == 1017
    c = ev.mesurer_selon_instrument({"instrument": "banc_takehome", "critere": {"seuil_cycles": 1100}})
    assert c["gap"] is False  # un score FAUX (700) ne ferme jamais rien : seul 1017 exact compte


def test_z3_superopt_ferme_sur_trouve_ou_impossible(tmp_path, monkeypatch):
    (tmp_path / "superopt_enum.json").write_text(json.dumps([
        {"fenetre": "etages2_3", "verdict": "IMPOSSIBLE"}, {"fenetre": "x", "verdict": "INCONNU"}]), encoding="utf-8")
    monkeypatch.setattr(ev, "_DEFI_TAKEHOME", tmp_path)
    c = ev.mesurer_selon_instrument({"instrument": "z3_superopt", "critere": {"fenetre": "etages2_3"}})
    assert c["ok"] and c["gap"] is False
    c = ev.mesurer_selon_instrument({"instrument": "z3_superopt", "critere": {"fenetre": "x"}})
    assert c["gap"] is True
    c = ev.mesurer_selon_instrument({"instrument": "z3_superopt", "critere": {"fenetre": "absente"}})
    assert c["ok"] is False  # source muette = remesure impossible, jamais « fermee »


def test_une_preuve_complementaire_tranche_une_fenetre_inconnue_de_z3(tmp_path, monkeypatch):
    # 27/10 : (madd, madd) hors de portee de z3 a 600 s, prouve IMPOSSIBLE par differences finies
    (tmp_path / "superopt_enum.json").write_text(json.dumps([{"fenetre": "etages2_3", "verdict": "INCONNU"}]),
                                                 encoding="utf-8")
    (tmp_path / "preuve_madd_madd_etages2_3.json").write_text(
        json.dumps({"fenetre": "etages2_3", "verdict": "IMPOSSIBLE", "methode": "differences finies"}), encoding="utf-8")
    monkeypatch.setattr(ev, "_DEFI_TAKEHOME", tmp_path)
    c = ev.mesurer_selon_instrument({"instrument": "z3_superopt", "critere": {"fenetre": "etages2_3"}})
    assert c["ok"] and c["gap"] is False and c["score"] == "IMPOSSIBLE"


def test_instrument_inconnu_garde_le_comportement_historique(monkeypatch):
    vu = []
    monkeypatch.setattr(ev, "coverage_dense", lambda q: vu.append(q) or {"ok": True, "instrument": "cov"})
    ev.mesurer_selon_instrument({"question": "q?", "instrument": "cov"})
    assert vu == ["q?"]
