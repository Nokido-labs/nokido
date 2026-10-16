"""NR — une SEULE cle arme les deux portes de l'evolution, le frein gagne toujours (debat RSI 15/10).

AGY, tour 2 : le juge lisait `LAFORGE_EVOLUTION_ARMED`, l'applicateur `LAFORGE_APPLIER_ARMED` --
armer l'un laissait l'autre en « plan seul » sans le dire, et le demon des boucles ne charge pas
Nokido.env. Codex, tour 2 : la cle fichier n'etait pas lue par la porte, elle devait etre CODEE.
Frein, cle et verrou humain sont simules : aucun fichier de sandbox/ n'est touche.
"""
import sys
import types

import pytest

from nokido_agent.app import forge_mutation_judge as juge
from nokido_agent.app import forge_proposal_applier as app


@pytest.fixture
def portes(monkeypatch, tmp_path):
    opsec = types.ModuleType("nokido_agent.app.forge_opsec")
    opsec.human_lock_state = lambda: ("LIBRE", "")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_opsec", opsec)
    monkeypatch.setattr(juge, "_FREIN_EVOLUTION", tmp_path / "evolution.halt")
    monkeypatch.setattr(juge, "_CLE_ARMEMENT", tmp_path / "evolution.armed")
    for v in ("LAFORGE_EVOLUTION_ARMED", "LAFORGE_APPLIER_ARMED"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def test_desarme_par_defaut(portes):
    assert juge.evolution_autorisee()["etat"] == "DESARMEE"
    assert app.arme() is False


def test_la_cle_arme_les_deux_portes(portes):
    # Contenu `tout` : la cle porte une portee depuis le 15/10 (test_portee_cle_armement_nr).
    (portes / "evolution.armed").write_text("tout", encoding="utf-8")
    r = juge.evolution_autorisee()
    assert r["autorisee"] is True and r["etat"] == "ARMEE" and "evolution.armed" in r["motif"]
    assert app.arme() is True
    assert app.porte_evolution()["autorisee"] is True


def test_le_frein_gagne_sur_la_cle(portes):
    (portes / "evolution.armed").write_text("tout", encoding="utf-8")
    (portes / "evolution.halt").write_text("revert non prouve", encoding="utf-8")
    assert juge.evolution_autorisee()["etat"] == "HALTED"
    assert app.arme() is False


def test_le_frein_gagne_sur_la_variable(portes, monkeypatch):
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    (portes / "evolution.halt").write_text("2 reverts", encoding="utf-8")
    assert juge.evolution_autorisee()["etat"] == "HALTED"
    assert app.arme() is False


def test_la_variable_arme_encore_sans_cle(portes, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    assert juge.evolution_autorisee()["etat"] == "ARMEE"
    assert app.arme() is True


def test_verrou_humain_prioritaire(portes, monkeypatch):
    opsec = types.ModuleType("nokido_agent.app.forge_opsec")
    opsec.human_lock_state = lambda: ("VERROUILLE", "kill-switch")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_opsec", opsec)
    (portes / "evolution.armed").write_text("tout", encoding="utf-8")
    assert juge.evolution_autorisee()["etat"] == "VERROU_HUMAIN"
