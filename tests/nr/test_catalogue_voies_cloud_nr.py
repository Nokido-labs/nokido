"""NR -- combler trous de mesure catalogue fournisseurs (TÂCHE M).
Sans aucun appel réseau, faux interroger/sonder.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_provider_catalogue as C  # noqa: E402


def test_ollama_cloud_dans_fournisseurs_avec_cle_attendue():
    etiquettes = [e for e, _, _ in C.FOURNISSEURS]
    assert "ollama_cloud" in etiquettes
    for e, k, url in C.FOURNISSEURS:
        if e == "ollama_cloud":
            assert k == "OLLAMA_API_KEY"
            assert "/v1/models" in url
            break


def test_ollama_cloud_cle_absente_donne_non_mesure_pas_zero(monkeypatch):
    def faux_get_secret(nom):
        return ""

    def faux_interroger(url, cle):
        raise AssertionError("interroger ne doit pas etre appele si cle absente")

    m = C.construire_matrice(get_secret=faux_get_secret, interroger_fn=faux_interroger)
    assert m["fournisseurs"].get("ollama_cloud") == "CLE_ABSENTE"


def test_cloudflare_et_litellm_dans_hors_perimetre_avec_motif_precis():
    assert "CLOUDFLARE_AI_API_KEY" in C.HORS_PERIMETRE
    assert "LITELLM_API_KEY" in C.HORS_PERIMETRE or any("litellm" in str(v).lower() for v in C.HORS_PERIMETRE.values())
    # motifs precis
    motif_cf = C.HORS_PERIMETRE.get("CLOUDFLARE_AI_API_KEY", "")
    assert motif_cf
    assert len(motif_cf.strip()) > 5
    # litellm doit mentionner passerelle / relais / fournisseurs
    motif_ll = None
    for k, v in C.HORS_PERIMETRE.items():
        if "litellm" in k.lower() or "litellm" in str(v).lower():
            motif_ll = str(v)
            break
    assert motif_ll is not None
    ml = motif_ll.lower()
    assert "passerelle" in ml or "relais" in ml or "agrégat" in ml or "agregat" in ml
    assert "matrice" in ml
