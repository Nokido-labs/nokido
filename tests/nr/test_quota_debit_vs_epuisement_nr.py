"""NR -- distinction entre 429 de debit (sans echeance de 4h) et vrai epuisement / retry-after.

Prouve que :
1. Un 429 de debit simple ou erreur sans motif d'epuisement ne consigne pas d'echeance de 4 h (echeance_quota -> None).
2. "usage limit reached" ou "quota exceeded" consigne un blocage (defaut 4 h ou mensuel).
3. "retry-after=60s" consigne 60 s et donne l'echeance reelle.
4. Le veilleur forge_opencode_journal ne forge "quota exceeded" que sur un vrai epuisement.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_free_tier_census as ftc
import forge_opencode_journal as foj


def test_debit_simple_ne_consigne_pas_decheance_4h(tmp_path):
    t0 = 1000000.0
    census_file = tmp_path / "free_tier_census.json"
    census_file.write_text(json.dumps({"verdicts": {}}), encoding="utf-8")

    # Message de debit ou stream error sans mention d'epuisement
    msg_debit = "Rate limit exceeded"
    fin = ftc.echeance_quota(msg_debit, maintenant=t0)
    assert fin is None, "Un debit simple ne doit pas generer d'echeance"

    res = ftc.consigner_quota_epuise("mistral", "codestral-latest", msg_debit, maintenant=t0, chemin=census_file)
    assert res is None, "Aucun quota epuise ne doit etre consigne sur debit simple"

    # Vérification que le fichier n'a pas été pollué
    doc = json.loads(census_file.read_text(encoding="utf-8"))
    assert "mistral:codestral-latest" not in doc.get("verdicts", {})


def test_usage_limit_reached_consigne_blocage(tmp_path):
    t0 = 1000000.0
    census_file = tmp_path / "free_tier_census.json"
    census_file.write_text(json.dumps({"verdicts": {}}), encoding="utf-8")

    msg_epuise = "Free usage limit reached"
    fin = ftc.echeance_quota(msg_epuise, maintenant=t0)
    assert fin == t0 + ftc.QUOTA_REPOS_DEFAUT_S, "Doit appliquer le repos defaut (4h)"

    res = ftc.consigner_quota_epuise("mistral", "codestral-latest", msg_epuise, maintenant=t0, chemin=census_file)
    assert res == t0 + ftc.QUOTA_REPOS_DEFAUT_S

    doc = json.loads(census_file.read_text(encoding="utf-8"))
    v = doc["verdicts"]["mistral:codestral-latest"]
    assert v["quota_epuise_jusqu_a"] == t0 + ftc.QUOTA_REPOS_DEFAUT_S
    assert "Free usage limit reached" in v["quota_motif"]


def test_retry_after_consigne_duree_reelle(tmp_path):
    t0 = 1000000.0
    census_file = tmp_path / "free_tier_census.json"
    census_file.write_text(json.dumps({"verdicts": {}}), encoding="utf-8")

    # Formats variés retry-after
    msg_retry = "Rate limit exceeded. retry-after=60s"
    fin = ftc.echeance_quota(msg_retry, maintenant=t0)
    assert fin == t0 + 60.0

    res = ftc.consigner_quota_epuise("mistral", "codestral-latest", msg_retry, maintenant=t0, chemin=census_file)
    assert res == t0 + 60.0

    doc = json.loads(census_file.read_text(encoding="utf-8"))
    v = doc["verdicts"]["mistral:codestral-latest"]
    assert v["quota_epuise_jusqu_a"] == t0 + 60.0


def test_veilleur_opencode_distingue_panne_flux_et_epuisement(tmp_path):
    log_file = tmp_path / "opencode.log"
    # Ligne 1 : stream error / Rate limit sans epuisement
    quota_re = re.compile(r"rate limit|usage limit", re.I)
    futur = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    ligne_rate = f'timestamp={futur} level=ERROR run=2efc9c81 message="stream error" providerID=mistral modelID=codestral-latest session.id=ses_test error.error="AI_APICallError: Rate limit exceeded"\n'
    log_file.write_text(ligne_rate, encoding="utf-8")

    class DummyClient:
        def prompt(self, sid, text, timeout):
            import time
            time.sleep(0.5)
            return "ok"

    debut = datetime(2026, 11, 6, 11, 0, 0, tzinfo=timezone.utc)
    # Chercher la panne directement
    panne = foj.chercher_panne(log_file, debut, "ses_test", quota_re)
    assert panne is not None

    # Doit lever QuotaJournalOpenCode avec le libellé adapté
    with pytest.raises(foj.QuotaJournalOpenCode) as exc_info:
        foj.prompt_avec_veilleur(DummyClient(), "ses_test", "hello", timeout=5, chemin=log_file, quota_re=quota_re, intervalle_s=0.1)

    assert "panne flux fournisseur (journal OpenCode)" in str(exc_info.value)
    assert "quota exceeded" not in str(exc_info.value)

    # Ligne 2 : vrai épuisement
    ligne_epuise = f'timestamp={futur} level=ERROR run=2efc9c81 message="stream error" providerID=mistral modelID=codestral-latest session.id=ses_test2 error.error="AI_APICallError: Free usage limit reached"\n'
    log_file.write_text(ligne_epuise, encoding="utf-8")

    with pytest.raises(foj.QuotaJournalOpenCode) as exc_info2:
        foj.prompt_avec_veilleur(DummyClient(), "ses_test2", "hello", timeout=5, chemin=log_file, quota_re=quota_re, intervalle_s=0.1)

    assert "quota exceeded (journal OpenCode)" in str(exc_info2.value)
