# -*- coding: utf-8 -*-
"""NR -- Plafond d'effort par modele (Tache S4 de l'enquete omniroute_free_tier_quota_effort_20261030).

Contrat :
1. Un modele qui ne supporte que low/medium, si appele avec effort='high', est borne a 'medium' avec un motif explicite.
2. Un modele inconnu de la matrice de support (aucun plafond connu) conserve son effort inchange, sans motif.
3. Un niveau supporte par le modele reste inchange, sans motif.
4. Dans forge_palier_effort.resoudre(), la sortie borne effectivement l'effort retenu.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_palier_effort as pe  # noqa: E402

pytestmark = pytest.mark.timeout(30)


def test_modele_support_borne_au_plus_haut_inferieur():
    """Modele qui supporte low/medium + demande high -> borne a medium + motif explicite."""
    # ("test_surface", "test_model_low_med") supporte ("low", "medium")
    pe.EFFORTS_SUPPORTES[("test_surface", "test_model_low_med")] = ("low", "medium")
    try:
        effort_res, motif = pe.borner_effort("test_surface", "test_model_low_med", "high")
        assert effort_res == "medium"
        assert motif is not None
        assert "high" in motif and "medium" in motif
    finally:
        pe.EFFORTS_SUPPORTES.pop(("test_surface", "test_model_low_med"), None)


def test_modele_inconnu_conserve_effort_sans_motif():
    """Modele inconnu -> effort inchange, aucun bridage."""
    effort_res, motif = pe.borner_effort("surface_inconnue", "modele_inconnu_xyz", "high")
    assert effort_res == "high"
    assert motif is None


def test_niveau_supporte_inchange_sans_motif():
    """Niveau supporte -> inchange, aucun motif."""
    pe.EFFORTS_SUPPORTES[("test_surface", "test_model_supporte")] = ("low", "medium", "high")
    try:
        effort_res, motif = pe.borner_effort("test_surface", "test_model_supporte", "medium")
        assert effort_res == "medium"
        assert motif is None

        effort_res_low, motif_low = pe.borner_effort("test_surface", "test_model_supporte", "low")
        assert effort_res_low == "low"
        assert motif_low is None
    finally:
        pe.EFFORTS_SUPPORTES.pop(("test_surface", "test_model_supporte"), None)


def test_resoudre_branchement_borner_effort(monkeypatch):
    """Verifie que resoudre() applique borner_effort a la sortie."""
    # claude_api supporte low, medium, high pour claude-opus-5-5 mais pas xhigh/max
    # Simuler un modele dont le plafond est depasse
    pe.EFFORTS_SUPPORTES[("claude_api", "claude-haiku-5-5")] = ("low", "medium")
    try:
        # escalade='nr_rouge' avec effort haut -> resoudre retient EFFORT_ESCALADE='high',
        # qui doit etre borne a 'medium' par borner_effort
        res = pe.resoudre("claude_api", taille="S", escalade="nr_rouge")
        assert res["effort"] == "medium"
        assert "motif_borne" in res
        assert "medium" in res["motif_borne"]
    finally:
        pe.EFFORTS_SUPPORTES[("claude_api", "claude-haiku-5-5")] = ("low", "medium", "high")
