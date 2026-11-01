# -*- coding: utf-8 -*-
"""NR : une lacune d'INTENTION d'origine INTERNE depose UNE tache « enquete de code » (executeur gratuit).

Avant : le daemon journalisait « traitement = enquete de code » puis ne faisait rien.
Mode OBSERVATION par defaut (LAFORGE_EPISTEMIC_ENQUETE_CODE absent) : journalise « SERAIT deposee ».
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

daemon = importlib.import_module("forge_epistemic_daemon")

Q = "brancher la soif interne sur une enquete de code"
PREUVES = ["tools/forge_epistemic_daemon.py"]


def _arme(monkeypatch, tmp_path, actif):
    monkeypatch.setattr(daemon, "_ENQUETE_CODE_ETAT", tmp_path / "etat.json")
    if actif:
        monkeypatch.setenv("LAFORGE_EPISTEMIC_ENQUETE_CODE", "1")
    else:
        monkeypatch.delenv("LAFORGE_EPISTEMIC_ENQUETE_CODE", raising=False)
    appels, debuts, journal = [], [], []
    monkeypatch.setattr(daemon, "_deposer_enquete_code",
                        lambda d: appels.append(d) or {"task_id": "T%d" % len(appels)})
    monkeypatch.setattr(daemon.ev, "debuter_enquete", lambda c, k: debuts.append((c, k)), raising=False)
    monkeypatch.setattr(daemon, "_journal", journal.append)
    return appels, debuts, journal


def test_observation_ne_depose_pas(monkeypatch, tmp_path):
    appels, debuts, journal = _arme(monkeypatch, tmp_path, actif=False)
    r = daemon._enquete_code_interne("cle1", Q, PREUVES, 0)
    assert appels == [] and debuts == []
    assert r["statut"] == "A_BLANC"
    assert any("SERAIT" in j for j in journal)


def test_actif_depose_une_fois_avec_consigne(monkeypatch, tmp_path):
    appels, debuts, journal = _arme(monkeypatch, tmp_path, actif=True)
    r = daemon._enquete_code_interne("cle1", Q, PREUVES, 0)
    assert r["statut"] == "DEPOSEE" and len(appels) == 1
    assert Q in appels[0] and PREUVES[0] in appels[0]
    assert "docs/enquetes/cle1.md" in appels[0] and "file:line" in appels[0]
    assert debuts == [("cle1", "enquete_code")]
    assert any("deposee" in j for j in journal)


def test_doublon_refuse_avec_motif(monkeypatch, tmp_path):
    appels, debuts, journal = _arme(monkeypatch, tmp_path, actif=True)
    daemon._enquete_code_interne("cle1", Q, PREUVES, 0)
    r = daemon._enquete_code_interne("cle1", Q, PREUVES, 0)
    assert r["statut"] == "REFUSEE" and r["motif"] == "doublon"
    assert len(appels) == 1
    assert any("doublon" in j for j in journal)


def test_budget_cycle_refuse(monkeypatch, tmp_path):
    appels, _d, journal = _arme(monkeypatch, tmp_path, actif=True)
    r = daemon._enquete_code_interne("cle2", Q, PREUVES, daemon.MAX_ENQUETES_CYCLE)
    assert r["statut"] == "REFUSEE" and r["motif"] == "budget_cycle"
    assert appels == [] and any("budget_cycle" in j for j in journal)


def test_budget_jour_refuse(monkeypatch, tmp_path):
    appels, _d, journal = _arme(monkeypatch, tmp_path, actif=True)
    for i in range(daemon.MAX_ENQUETES_JOUR):
        assert daemon._enquete_code_interne("k%d" % i, Q, PREUVES, 0)["statut"] == "DEPOSEE"
    r = daemon._enquete_code_interne("autre", Q, PREUVES, 0)
    assert r["statut"] == "REFUSEE" and r["motif"] == "budget_jour"
    assert len(appels) == daemon.MAX_ENQUETES_JOUR
    assert any("budget_jour" in j for j in journal)


def test_depot_refuse_journalise_et_pas_de_debut(monkeypatch, tmp_path):
    appels, debuts, journal = _arme(monkeypatch, tmp_path, actif=True)
    monkeypatch.setattr(daemon, "_deposer_enquete_code", lambda d: {"error": "hub muet"})
    r = daemon._enquete_code_interne("cle3", Q, PREUVES, 0)
    assert r["statut"] == "REFUSEE" and r["motif"] == "depot_refuse"
    assert debuts == [] and any("hub muet" in j for j in journal)
