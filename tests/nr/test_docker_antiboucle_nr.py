# -*- coding: utf-8 -*-
"""NR — une prothese qui demarre bien et meurt vite ne se relance pas indefiniment.

Directive owner, inscrite dans `services.toml` depuis le 2026-07-25 : « lancer Docker
OUI, le faire BOUCLER NON ».

Mesure du 2026-09-05 : le moteur a demarre PROPREMENT trois fois de suite — 12 s a
chaque fois, `docker daemon recovered (29.7.2)` — puis est mort seul au bout de
10 min, 16 s, puis 31 s. Le keeper relancait a chaque mort sans jamais remarquer que
le motif se REPETAIT.

Un cooldown ne suffit pas : il ESPACE les relances, il ne les COMPTE pas. Or une
prothese qui demarre bien et meurt vite n'est pas une prothese absente — c'est une
prothese INSTABLE. La relancer sans fin consomme la machine et masque la cause.

Trois proprietes, et la troisieme est aussi importante que les deux autres :
la reprise doit rester possible, sinon le garde devient une panne de plus.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

k = pytest.importorskip("forge_docker_keeper")


@pytest.fixture(autouse=True)
def _etat_propre():
    k._vies_courtes.clear()
    k._STATE["last_boot_ok_ts"] = 0.0
    yield
    k._vies_courtes.clear()
    k._STATE["last_boot_ok_ts"] = 0.0


def _vie(duree_s: float, monkeypatch):
    """Simule une vie achevee de `duree_s` secondes."""
    faux = 10_000.0
    k._STATE["last_boot_ok_ts"] = faux - duree_s
    monkeypatch.setattr(k.time, "monotonic", lambda: faux)
    return k._noter_fin_de_vie()


def test_sans_demarrage_connu_aucune_vie_n_est_comptee(monkeypatch):
    """Trois etats : on ne compte pas comme vie courte ce qu'on n'a pas mesure."""
    k._STATE["last_boot_ok_ts"] = 0.0
    assert k._noter_fin_de_vie() is None
    assert k._vies_courtes == []


def test_une_vie_courte_est_comptee(monkeypatch):
    assert _vie(30.0, monkeypatch) == pytest.approx(30.0)
    assert k._vies_courtes == [30.0]
    assert not k._boucle_detectee()


def test_la_boucle_est_detectee_au_seuil(monkeypatch):
    for _ in range(k._VIES_COURTES_MAX):
        _vie(20.0, monkeypatch)
    assert k._boucle_detectee(), \
        "N demarrages suivis de morts rapides doivent suspendre la relance"


def test_une_vie_longue_absout_les_precedentes(monkeypatch):
    """La reprise doit rester possible : un garde sans sortie est une panne de plus."""
    _vie(20.0, monkeypatch)
    _vie(20.0, monkeypatch)
    assert len(k._vies_courtes) == 2
    _vie(k._VIE_COURTE_S + 60.0, monkeypatch)
    assert k._vies_courtes == [], "une vie longue doit remettre le compteur a zero"
    assert not k._boucle_detectee()


def test_une_fin_de_vie_ne_se_compte_qu_une_fois(monkeypatch):
    """Sans remise a zero, un meme deces serait compte a chaque tick."""
    _vie(20.0, monkeypatch)
    assert k._noter_fin_de_vie() is None
    assert len(k._vies_courtes) == 1


def test_le_seuil_reste_reglable():
    assert k._VIE_COURTE_S > 0 and k._VIES_COURTES_MAX >= 2
