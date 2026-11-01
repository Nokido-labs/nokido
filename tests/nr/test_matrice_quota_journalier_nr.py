"""NR : classement des refus fournisseurs de la matrice des voies (24/10).

402 = SANS_SOLDE, 404 = MODELE_ABSENT, quota journalier = QUOTA_EPUISE (avec echeance), jamais « 0.0 »,
jamais retire definitivement (voie gelee, a re-sonder). Un 429 de debit simple reste DEBIT.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_provider_catalogue as cat  # noqa: E402

QUOTA = '{"error":{"message":"Rate limit exceeded: free-models-per-day","code":429}}'


def test_402_sans_solde_404_modele_absent():
    assert cat.classer_reponse(402, '{"error":"payment_required"}') == "SANS_SOLDE"
    assert cat.classer_reponse(404, '{"error":{"code":"model_not_found"}}') == "MODELE_ABSENT"


def test_quota_journalier_est_quota_epuise_et_non_debit():
    assert cat.classer_reponse(429, QUOTA) == "QUOTA_EPUISE"
    assert cat.classer_reponse(429, "tokens per day (TPD) limit reached") == "QUOTA_EPUISE"
    assert cat.classer_reponse(429, "rate limit, retry later") == "DEBIT"


def test_echeance_quota_prochain_minuit_utc():
    now = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
    assert cat.echeance_quota(now) == "2026-10-25T00:00:00+00:00"


def test_voie_gelee_jamais_zero_ni_retiree():
    voie = cat.geler_voie({"fournisseur": "openrouter_free", "modele": "m"}, 429, QUOTA,
                          now=datetime(2026, 10, 24, 15, tzinfo=timezone.utc))
    assert voie["etat"] == "QUOTA_EPUISE" and voie["echeance"] == "2026-10-25T00:00:00+00:00"
    assert voie["gelee"] is True and voie.get("retiree") is not True
    assert voie.get("score") is None  # jamais « 0.0 »
    v402 = cat.geler_voie({"fournisseur": "cerebras", "modele": "m"}, 402, "payment_required")
    assert v402["etat"] == "SANS_SOLDE" and v402["gelee"] is True and v402.get("score") is None
    assert "echeance" not in v402
