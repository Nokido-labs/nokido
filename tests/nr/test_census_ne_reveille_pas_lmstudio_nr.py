# -*- coding: utf-8 -*-
"""NR -- le census ne COMPLETE jamais une surface a la demande (LM Studio) (owner 30/10).

Mesure 30/10 : census lance 11:18:22, worker LM Studio ne 11:19:10 (qwen2.5-coder-7b charge, 5,36 Go) -> RAM 99 %.
Une completion envoyee a LM Studio le fait charger un modele JUSTE-A-TEMPS, hors de l'admission RAM de
forge_ensure_service (7 Go). Contrat : catalogue lu, completion NON tentee, motif dit (jamais « injoignable »).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_free_tier_census as C  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_cibler_ne_complete_pas_lmstudio(monkeypatch):
    def _interdit(*a, **k):
        raise AssertionError("completion envoyee a une surface a la demande")

    monkeypatch.setattr(C, "SURFACES", [("lmstudio", None, "http://127.0.0.1:1234/v1")])
    monkeypatch.setattr(C, "_lire_catalogue", lambda base, cle: (200, [{"id": "qwen"}], {}, ""))
    monkeypatch.setattr(C, "sonder", _interdit)
    r = C.cibler([("lmstudio", "qwen")])
    assert r and r[0].get("etat") == "A_LA_DEMANDE", r
    assert "joignable" not in r[0]


def test_la_boucle_du_census_saute_les_surfaces_a_la_demande():
    src = (ROOT / "tools" / "forge_free_tier_census.py").read_text(encoding="utf-8")
    boucle = src.split("for etiquette, env_key, base in SURFACES:", 1)[1].split("preuves = []", 1)[0]
    assert "A_LA_DEMANDE" in boucle
