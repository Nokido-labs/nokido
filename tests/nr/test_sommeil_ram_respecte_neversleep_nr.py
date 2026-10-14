# -*- coding: utf-8 -*-
"""NR -- le sommeil RAM du gestionnaire de ressources respecte neverSleep (2026-10-11).

Mesure : RESOURCE_MANAGER endormait NokidoNetcfgUI (neverSleep au TOML depuis 83cf9e4a7, porte d'entree de la tuile
netcfg) 16 fois en deux heures (sandbox/supervisor_ordres.jsonl), jusque 10 s apres son demarrage.
`_non_essential_sains` partait d'une liste curatee croisee avec les capacites critiques, jamais avec neverSleep --
que le superviseur (rafale RAM) et le bail de priorite respectent deja. TOML et capacites remplaces par des
doublures : jamais un vrai sommeil.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402
from nokido_agent.app import forge_service_capabilities as caps  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.fixture
def corps(monkeypatch):
    audits = []
    monkeypatch.setattr(rm, "_SUPERVISOR_NON_ESSENTIAL", ["NokidoNetcfgUI", "NokidoGraph", "NokidoCritique"])
    monkeypatch.setattr(caps, "is_critical", lambda s: s == "NokidoCritique")
    monkeypatch.setattr(caps, "why_critical", lambda s: "critique de test")
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda action, domain, reason="", **kw: audits.append((action, reason, kw)))
    return audits


def test_un_service_never_sleep_n_est_jamais_propose_au_sommeil(corps, monkeypatch):
    monkeypatch.setattr(rm, "_services_du_toml", lambda: {
        "NokidoNetcfgUI": {"name": "NokidoNetcfgUI", "essential": False, "neverSleep": True},
        "NokidoGraph": {"name": "NokidoGraph", "essential": False},
        "NokidoCritique": {"name": "NokidoCritique", "essential": False}})
    assert rm._non_essential_sains() == ["NokidoGraph"]
    assert ("sleep_skipped", "neverSleep au TOML", {"target": "NokidoNetcfgUI"}) in corps


def test_toml_illisible_garde_le_comportement_d_avant_et_le_dit(corps, monkeypatch):
    monkeypatch.setattr(rm, "_services_du_toml", lambda: None)
    assert rm._non_essential_sains() == ["NokidoNetcfgUI", "NokidoGraph"]
    assert any(a[0] == "sleep_neversleep_illisible" for a in corps), "l'abstention de la garde doit etre DITE"
