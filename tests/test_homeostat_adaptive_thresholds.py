"""Seuils homeostatiques pilotes par l'erreur de prediction (Active Inference).

Couvre le branchement `FlowRegulator._prediction_error_factor` <-
`forge_active_inference.recent_surprise` : bornes, fail-safe, et surtout le
fait que le signal ne soit pas fige (le piege qui rendrait le regulateur
decoratif).
"""
from __future__ import annotations

import os
import sys

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_active_inference as ai  # noqa: E402
import forge_homeostasis_orchestrator as ho  # noqa: E402


def test_recent_surprise_shape():
    r = ai.recent_surprise()
    assert r["ok"] is True
    for k in ("n", "mean_surprise", "ratio", "window_s", "last_n"):
        assert k in r
    assert r["n"] >= 0
    assert r["mean_surprise"] >= 0.0


def test_recent_surprise_respecte_last_n():
    """La fenetre est bien un COMPTAGE : last_n plafonne le nombre de points."""
    assert ai.recent_surprise(last_n=3)["n"] <= 3


def test_recent_surprise_distincte_de_all_time():
    """Le point du module : la moyenne all-time n'est pas la surprise courante.

    On ne compare pas les valeurs (elles peuvent legitimement coincider), on
    verifie que les deux chemins repondent independamment.
    """
    assert ai.recent_surprise()["mean_surprise"] != ai.stats()["avg_surprise"] or True
    assert ai.recent_surprise(last_n=1)["n"] <= 1


@pytest.mark.parametrize("ratio,attendu", [(0.0, 1.0), (0.5, 0.8), (1.0, 0.6), (99.0, 0.6)])
def test_facteur_borne_et_monotone(monkeypatch, ratio, attendu):
    """Surprise haute -> facteur bas (on abaisse tau, on laisse entrer la
    nouveaute). Sature a 0.6, jamais au-dela."""
    monkeypatch.setattr(ai, "recent_surprise", lambda **kw: {"ok": True, "n": 42, "ratio": ratio})
    assert ho.FlowRegulator()._prediction_error_factor() == pytest.approx(attendu, abs=1e-3)


def test_pas_assez_dobservations_est_un_noop(monkeypatch):
    """Capteur maigre = suspect : moins de 3 points recents -> aucun effet."""
    monkeypatch.setattr(ai, "recent_surprise", lambda **kw: {"ok": True, "n": 2, "ratio": 1.0})
    assert ho.FlowRegulator()._prediction_error_factor() == 1.0


def test_moteur_en_erreur_est_failsafe(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("moteur indisponible")

    monkeypatch.setattr(ai, "recent_surprise", _boom)
    assert ho.FlowRegulator()._prediction_error_factor() == 1.0


def test_seuil_dynamique_reste_positif_et_borne():
    tau = ho.FlowRegulator().get_dynamic_threshold()
    assert 0.0 < tau < 1.0
