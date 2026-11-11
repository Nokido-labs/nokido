"""NR -- modele AGY force (Argon) indisponible -> repli automatique sur gemini-3.8-flash au MEME niveau (8/11).

Owner : « le quota Argon est mort pour 162 h, tu te retrancheras automatiquement sur le 3.8 selon l'effort voulu ».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import forge_task_executor as te  # noqa: E402


def _env(monkeypatch, modele, indispo=None, quota="ok"):
    monkeypatch.setenv("LAFORGE_AGY_MODEL", modele)
    monkeypatch.delenv("LAFORGE_AGY_REPLI_FORCE", raising=False)
    monkeypatch.setattr(te, "surface_est_indisponible", lambda s, *a, **k: indispo if s == modele else None)
    monkeypatch.setattr(te, "_etat_quota_modele_agy", lambda m: quota)


def test_argon_disponible_reste_argon(monkeypatch):
    _env(monkeypatch, "gemini-4-argon-medium")
    assert te._modele_agy("taille: M") == "gemini-4-argon-medium"


def test_argon_marque_indisponible_replie_au_meme_niveau(monkeypatch):
    _env(monkeypatch, "gemini-4-argon-medium", indispo="quota owner 162 h")
    assert te._modele_agy("taille: M") == "gemini-3.8-flash-medium"


def test_argon_hors_quota_tracker_replie(monkeypatch):
    _env(monkeypatch, "gemini-4-argon-high", quota="quota_reached")
    assert te._modele_agy("taille: L") == "gemini-3.8-flash-high"


def test_effort_suit_le_meme_niveau(monkeypatch):
    _env(monkeypatch, "gemini-4-argon-low", indispo="x")
    assert te._modele_agy("taille: M") == "gemini-3.8-flash-low"
    assert te._effort_agy("taille: M") == "low"


def test_repli_configurable(monkeypatch):
    _env(monkeypatch, "gemini-4-argon-medium", indispo="x")
    monkeypatch.setenv("LAFORGE_AGY_REPLI_FORCE", "claude-sonnet-5-5-low")
    assert te._modele_agy("taille: M") == "claude-sonnet-5-5-low"
