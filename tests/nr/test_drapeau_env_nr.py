"""NR — un drapeau d'environnement se lit d'UNE seule facon.

Cinq modules faisaient ce geste chacun de son cote ; le cliquet de duplication
l'a signale le 2026-09-02 sur `forge_authz_shadow.actif` /
`forge_intention_gate._rolescope_enabled`, deux fonctions au calcul identique.

Ce que ces tests ancrent, et qui divergeait deja entre les copies :
  * une variable POSEE MAIS VIDE ne se distinguait pas d'une absente ;
  * une valeur NON RECONNUE (`maybe`) valait « faux » dans les copies, ce qui
    fait passer une faute de frappe pour une desactivation volontaire ;
  * rien ne permettait de dire « personne n'a tranche » plutot que « on a
    tranche contre » -- la difference qui separe un garde desactive d'un garde
    jamais configure.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

from forge_drapeau_env import actif, declare, etat  # noqa: E402

NOM = "LAFORGE_DRAPEAU_DE_TEST"


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    monkeypatch.delenv(NOM, raising=False)


@pytest.mark.parametrize("valeur", ["1", "true", "TRUE", " on ", "yes", "oui"])
def test_vocabulaire_du_vrai(monkeypatch, valeur):
    monkeypatch.setenv(NOM, valeur)
    assert actif(NOM) is True


@pytest.mark.parametrize("valeur", ["0", "false", "OFF", " no ", "non"])
def test_vocabulaire_du_faux(monkeypatch, valeur):
    monkeypatch.setenv(NOM, valeur)
    assert actif(NOM, True) is False


def test_absent_rend_le_defaut_du_module():
    assert actif(NOM, True) is True
    assert actif(NOM, False) is False


def test_pose_mais_VIDE_vaut_non_declare(monkeypatch):
    """`SET X=` n'est pas une decision : c'est une variable qui traine."""
    monkeypatch.setenv(NOM, "   ")
    assert declare(NOM) is False
    assert actif(NOM, True) is True


def test_valeur_NON_RECONNUE_ne_vaut_pas_faux(monkeypatch):
    """Une faute de frappe ne doit pas eteindre un garde en silence."""
    monkeypatch.setenv(NOM, "maybe")
    assert actif(NOM, True) is True
    assert actif(NOM, False) is False


def test_trois_etats_distincts(monkeypatch):
    assert etat(NOM) == "NON_DECLARE"
    monkeypatch.setenv(NOM, "1")
    assert etat(NOM) == "ACTIF"
    monkeypatch.setenv(NOM, "0")
    assert etat(NOM) == "INACTIF"


def test_non_declare_n_est_pas_inactif(monkeypatch):
    """GARDE : « personne n'a tranche » != « on a tranche contre »."""
    assert etat(NOM, defaut=False) == "NON_DECLARE"
    monkeypatch.setenv(NOM, "0")
    assert etat(NOM, defaut=False) == "INACTIF"


def test_les_deux_appelants_gardent_leur_comportement(monkeypatch):
    """EQUIVALENCE avec les copies remplacees : defauts opposes, conserves."""
    import forge_authz_shadow as az
    import forge_intention_gate as ig

    monkeypatch.delenv("LAFORGE_AUTHZ_SHADOW", raising=False)
    monkeypatch.delenv("LAFORGE_INTENTION_GATE_ROLESCOPE", raising=False)
    assert az.actif() is True, "l'observation SHADOW est armee par defaut"
    assert ig._rolescope_enabled() is False, "le scope par role reste OFF par defaut"

    monkeypatch.setenv("LAFORGE_AUTHZ_SHADOW", "0")
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_ROLESCOPE", "1")
    assert az.actif() is False
    assert ig._rolescope_enabled() is True
