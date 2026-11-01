# -*- coding: utf-8 -*-
"""NR -- l'effort d'AGY suit la TAILLE de la tache (owner 30/10 : « adapter l'effort du LLM distant selon la tache,
economie de tokens max, AGY je le paye aussi »).

Mesure 30/10 : une tache whoami (petite) a coute 405 518 tokens d'entree et 611 s sous `--effort high`, le defaut de
`_effort_agy`. Contrat : l'effort vient de LA table unique `forge_palier_effort.resoudre("agy", taille)` (S/M/L ->
low ; haut seulement sur escalade verifiee) ; LAFORGE_AGY_EFFORT = forcage explicite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.mark.parametrize("desc", ["taille: L\nrefonte", "taille: S\npetit", "taille: M", "sans taille declaree"])
def test_effort_lu_dans_la_table(monkeypatch, desc):
    import forge_palier_effort as pe
    monkeypatch.delenv("LAFORGE_AGY_EFFORT", raising=False)
    t = te._taille_tache(desc) or "M"
    assert te._effort_agy(desc) == pe.resoudre("agy", t)["effort"]
    if t in ("S", "M"):
        assert te._effort_agy(desc) == "low"


def test_effort_suit_la_table_si_elle_change(monkeypatch):
    import forge_palier_effort as pe
    monkeypatch.delenv("LAFORGE_AGY_EFFORT", raising=False)
    monkeypatch.setitem(pe.TABLE, "agy", {"S": (None, "low"), "M": (None, "low"), "L": (None, "high")})
    assert te._effort_agy("taille: L") == "high"


def test_le_forcage_explicite_prime(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_EFFORT", "high")
    assert te._effort_agy("taille: S") == "high"


def test_la_delegation_passe_la_consigne():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    corps = src.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]
    assert "_effort_agy(desc)" in corps
