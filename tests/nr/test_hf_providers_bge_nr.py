"""NR — recenser les fournisseurs d'un modèle : une absence se DIT, elle ne s'invente pas.

Mesure 2026-09-06 : `BAAI/bge-m3` n'est servi que par `hf-inference` derrière le routeur
Hugging Face — aucun tiers (Together, Scaleway, DeepInfra) ne le relaie. Sans cet
inventaire, on aurait ouvert un compte tiers en croyant contourner les 0,10 $/mois du
tier gratuit HF.

Ce que le test verrouille, sur des réponses simulées (aucun réseau) :
  1. la forme historique `{provider: {...}}` est lue comme la forme liste ;
  2. « aucun fournisseur » est DIT, pas transformé en liste vide silencieuse ;
  3. un refus HTTP rend INDÉTERMINÉ (rc=2) et jamais « absent » — c'est la règle du
     corps : ne jamais conclure d'une source qui se tait.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_hf_providers_bge as P  # noqa: E402


def test_forme_liste(monkeypatch):
    monkeypatch.setattr(P, "_lire", lambda url, timeout=25.0: {
        "inferenceProviderMapping": [
            {"provider": "hf-inference", "task": "sentence-similarity",
             "status": "live", "providerId": "BAAI/bge-m3"}]})
    fs = P._fournisseurs("BAAI/bge-m3")
    assert [f["provider"] for f in fs] == ["hf-inference"]


def test_forme_historique_dictionnaire(monkeypatch):
    monkeypatch.setattr(P, "_lire", lambda url, timeout=25.0: {
        "inferenceProviderMapping": {
            "together": {"task": "feature-extraction", "status": "live"},
            "nebius": {"task": "feature-extraction", "status": "staging"}}})
    fs = P._fournisseurs("X/y")
    assert sorted(f["provider"] for f in fs) == ["nebius", "together"]
    assert all("task" in f for f in fs)


def test_aucun_fournisseur_rend_une_liste_vide_explicite(monkeypatch):
    monkeypatch.setattr(P, "_lire", lambda url, timeout=25.0: {"id": "X/y"})
    assert P._fournisseurs("X/y") == []


def test_un_refus_http_est_indetermine_pas_une_absence(monkeypatch, capsys):
    def _boum(url, timeout=25.0):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(P, "_lire", _boum)
    monkeypatch.setattr(sys, "argv", ["x", "--modele", "BAAI/bge-m3"])
    rc = P.main()
    sortie = capsys.readouterr().out
    assert rc == 2, rc
    assert "INDETERMINE" in sortie and "429" in sortie
    assert "AUCUN" not in sortie, "un refus ne doit jamais se lire comme une absence"


def test_le_chemin_nominal_liste_les_fournisseurs(monkeypatch, capsys):
    monkeypatch.setattr(P, "_lire", lambda url, timeout=25.0: {
        "inferenceProviderMapping": [
            {"provider": "hf-inference", "task": "sentence-similarity",
             "status": "live", "providerId": "BAAI/bge-m3"}]})
    monkeypatch.setattr(sys, "argv", ["x"])
    assert P.main() == 0
    assert "hf-inference" in capsys.readouterr().out
