"""Le gate world-model doit couvrir le RESTART, pas seulement le STOP.

Mesure 2026-09-01 : la condition etait `act == "stop"`, alors qu'un restart
CONTIENT l'arret que ce gate refuse. Le garde n'avait pas cede -- il n'etait
pas sur le chemin. C'est la meme famille que « un garde branche sur un signal
que personne n'emet » : ici, un garde pose a cote du canal.

Le cas `running` est teste AUSSI, et il compte autant : elargir la condition
sans lui pourrait bloquer tout reveil, et le remede serait pire que le defaut.

Zero service externe : le world-model est remplace par une fixture, l'admission
et la sonde d'installation sont neutralisees. Aucun service reel n'est touche.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_ensure_service as fes  # noqa: E402

# NOM REEL importe par `forge_ensure_service` (tools/forge_ensure_service.py:850),
# MESURE et non deduit du dossier : le module vit dans `app/`, pas `tools/`.
#
# ⚠️ DEFAUT MESURE le 2026-09-10 : les deux fixtures ne posaient que le nom PLAT.
# Le gate importe `nokido_agent.app.forge_body_world_model` — une entree
# DIFFERENTE de `sys.modules` — donc le VRAI world-model repondait, et ce NR
# cessait de tester ce qu'il annonce (« zero service externe, le world-model est
# remplace par une fixture »).
_WM = "nokido_agent.app.forge_body_world_model"


def _poser_wm(monkeypatch, mod) -> None:
    """Pose le faux world-model sur TOUS les noms par lesquels il est atteint."""
    monkeypatch.setitem(sys.modules, "forge_body_world_model", mod)
    monkeypatch.setitem(sys.modules, _WM, mod)
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, "forge_body_world_model"):
        # `from nokido_agent.app.X import guard` passe par le paquet : sans ce
        # setattr, la prise depend de l'ordre des tests.
        monkeypatch.setattr(paquet, "forge_body_world_model", mod)


def _fixture_corps(monkeypatch, *, autorise: bool) -> None:
    """Remplace le world-model et neutralise ce qui toucherait le systeme."""
    faux = types.ModuleType("forge_body_world_model")
    faux.guard = lambda name, acte: {
        "allowed": autorise,
        "impact": {"reason": "organe essentiel (fixture)"},
    }
    _poser_wm(monkeypatch, faux)
    monkeypatch.setattr(fes, "_admission", lambda s, st: None)
    # Aucun service reel derriere : le chemin s'arrete proprement APRES le gate.
    monkeypatch.setattr(fes, "_installe", lambda name: False)


@pytest.mark.parametrize("etat", ["stopped", "restarted"])
def test_gate_refuse_les_deux_actes_destructeurs(monkeypatch, etat):
    """`stopped` etait deja garde ; `restarted` ne l'etait pas."""
    _fixture_corps(monkeypatch, autorise=False)
    r = fes.ensure("NokidoFixtureGate", etat)
    assert r["success"] is False, r
    assert r.get("refus") == "world_model_dangerous", r
    assert r.get("acte") in ("stop", "restart"), r


def test_running_ne_tombe_pas_sous_le_gate(monkeypatch):
    """Un demarrage ne detruit rien : le gate ne doit pas l'attraper."""
    _fixture_corps(monkeypatch, autorise=False)
    r = fes.ensure("NokidoFixtureGate", "running")
    assert r.get("refus") != "world_model_dangerous", r
    assert "NON INSTALLE" in str(r.get("detail", "")), r


def test_gate_laisse_passer_quand_le_world_model_autorise(monkeypatch):
    """Le gate refuse sur le VERDICT du corps, jamais sur le seul nom de l'acte."""
    _fixture_corps(monkeypatch, autorise=True)
    r = fes.ensure("NokidoFixtureGate", "restarted")
    assert r.get("refus") != "world_model_dangerous", r


def _world_model_illisible(monkeypatch) -> None:
    """Module present mais SANS `guard` : l'import echoue, comme en panne reelle."""
    _poser_wm(monkeypatch, types.ModuleType("forge_body_world_model"))
    monkeypatch.setattr(fes, "_admission", lambda s, st: None)
    monkeypatch.setattr(fes, "_installe", lambda name: False)


@pytest.mark.parametrize("etat", ["stopped", "restarted"])
def test_world_model_illisible_ne_desarme_pas_le_gate(monkeypatch, etat):
    """Troisieme etat : ni autorise ni refuse -- un acte destructeur s'arrete.

    Le `except: pass` d'origine rendait ce gate silencieusement inoperant des
    qu'un import echouait. Un garde qu'une panne neutralise sans trace ne garde
    rien.
    """
    monkeypatch.delenv("LAFORGE_LIFECYCLE_FORCE", raising=False)
    _world_model_illisible(monkeypatch)
    r = fes.ensure("NokidoFixtureGate", etat)
    assert r["success"] is False, r
    assert r.get("refus") == "world_model_illisible", r


def test_force_ouvre_la_porte_que_le_message_promet(monkeypatch):
    """L'echappatoire etait citee dans les refus et lue nulle part.

    Sans ce test, le message continuerait d'envoyer les agents vers une
    variable sans effet -- un mur annonce comme une porte.
    """
    monkeypatch.setenv("LAFORGE_LIFECYCLE_FORCE", "1")
    _fixture_corps(monkeypatch, autorise=False)
    r = fes.ensure("NokidoFixtureGate", "restarted")
    assert r.get("refus") != "world_model_dangerous", r
    assert "NON INSTALLE" in str(r.get("detail", "")), r


def test_force_ouvre_aussi_la_porte_quand_le_verdict_manque(monkeypatch):
    monkeypatch.setenv("LAFORGE_LIFECYCLE_FORCE", "1")
    _world_model_illisible(monkeypatch)
    r = fes.ensure("NokidoFixtureGate", "stopped")
    assert r.get("refus") != "world_model_illisible", r
