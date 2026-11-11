"""NR -- l'effort AGY suit le niveau porte par le nom d'un modele FORCE (8/11).

Mesure : journal agy_job_94f34e7a_1794131954 « --model gemini-4-argon-medium conflicts with --effort=low » ; deux
taches rendues RIEN_PRODUIT. L'executeur posait --effort depuis la table (taille M -> low) sans voir le niveau du
modele force par LAFORGE_AGY_MODEL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import forge_task_executor as te  # noqa: E402


@pytest.mark.parametrize("modele,attendu", [("gemini-4-argon-medium", "medium"), ("gemini-4-argon-low", "low"),
                                            ("gemini-4-argon-high", "high")])
def test_modele_force_impose_son_niveau(monkeypatch, modele, attendu):
    monkeypatch.setenv("LAFORGE_AGY_MODEL", modele)
    monkeypatch.delenv("LAFORGE_AGY_EFFORT", raising=False)
    assert te._effort_agy("taille: M") == attendu


def test_le_niveau_du_modele_prime_sur_le_forcage_d_effort(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_MODEL", "gemini-4-argon-medium")
    monkeypatch.setenv("LAFORGE_AGY_EFFORT", "low")
    assert te._effort_agy("taille: M") == "medium"


def test_sans_modele_force_la_table_decide(monkeypatch):
    monkeypatch.delenv("LAFORGE_AGY_MODEL", raising=False)
    monkeypatch.delenv("LAFORGE_AGY_EFFORT", raising=False)
    assert te._effort_agy("taille: M") == "low"


def test_modele_force_sans_niveau_laisse_la_table(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_MODEL", "gemini-4-argon")
    monkeypatch.delenv("LAFORGE_AGY_EFFORT", raising=False)
    assert te._effort_agy("taille: M") == "low"
