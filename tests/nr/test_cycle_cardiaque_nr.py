"""Non-regression du NOEUD SINUSAL (`app/forge_cardiac_node.py`).

Ce que ces tests protegent, et pourquoi chacun existe :

1. DENERVE N'EST PAS UNE EXTREMITE. Sans modulation lisible, le coeur retombe sur son
   rythme PROPRE, pas sur la periode la plus lente. Rendre 0.0 au lieu de None ferait
   d'une absence de signal une bradycardie DECIDEE -- « personne ne me commande » et
   « on me commande de ralentir » sont deux choses differentes.

2. LA BORNE HAUTE EST UNE CONTRAINTE DURE, PAS UN REGLAGE. Elle doit rester sous le
   plus court seuil du superviseur (90 s, tier `fast`). Une bradycardie au-dela ferait
   declarer figes D'UN COUP tous les organes perfuses : le rythme adaptatif deviendrait
   une panne systemique. Si quelqu'un remonte PERIODE_MAX_S un jour, ce test tombe.

3. LE POULS SE PUBLIE ET SE RELIT. C'est l'effet reel : un organe doit pouvoir
   s'accorder. On verifie l'aller-retour, pas l'import du module.

4. UN POULS PERIME N'EST PAS UN POULS. `lire()` doit rendre None au-dela de la
   peremption, pour que l'organe bascule en rythme d'echappement au lieu de se caler
   sur une cadence morte.

AUCUN test n'ecrit dans `sandbox/cardiac_pulse.json` : le pouls de PRODUCTION pilote
des organes vivants. Un test qui l'ecrirait ferait battre le corps au rythme d'une
suite de tests -- meme famille que les 16 mesures fabriquees du 2026-08-xx, ou des
tests nourrissaient l'agregat de production.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_APP = str(Path(__file__).resolve().parents[2] / "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_cardiac_node as CN  # noqa: E402


def test_denerve_rend_le_rythme_intrinseque_et_non_une_extremite():
    """Sans innervation, le coeur bat son rythme PROPRE."""
    assert CN.periode_pour(None) == CN.PERIODE_INTRINSEQUE_S
    # Et ce rythme n'est ni la borne basse ni la borne haute : un coeur denerve bat
    # PLUS VITE qu'un coeur au repos, le frein vagal dominant chez le sujet eveille.
    assert CN.PERIODE_MIN_S < CN.PERIODE_INTRINSEQUE_S < CN.PERIODE_MAX_S


def test_la_modulation_va_du_frein_a_l_accelerateur():
    """0 = frein dominant (lent), 1 = accelerateur a fond (rapide)."""
    assert CN.periode_pour(0.0) == CN.PERIODE_MAX_S
    assert CN.periode_pour(1.0) == CN.PERIODE_MIN_S
    # Monotone : plus de modulation, jamais plus lent.
    assert CN.periode_pour(0.75) < CN.periode_pour(0.25)
    # Hors bornes = borne, pas d'extrapolation.
    assert CN.periode_pour(5.0) == CN.PERIODE_MIN_S
    assert CN.periode_pour(-3.0) == CN.PERIODE_MAX_S


def test_la_bradycardie_maximale_reste_sous_le_seuil_du_superviseur():
    """CONTRAINTE DURE : au-dela de 90 s (tier `fast`), tous les organes perfuses
    seraient declares figes d'un coup."""
    assert CN.PERIODE_MAX_S < 90.0
    assert 0 < CN.PERIODE_MIN_S <= CN.PERIODE_MAX_S


def test_le_pouls_publie_est_relisible_par_un_organe(tmp_path, monkeypatch):
    """EFFET : le coeur publie, l'organe relit et peut s'accorder."""
    monkeypatch.setattr(CN, "PULSE", tmp_path / "cardiac_pulse.json")
    etat = CN.systole(7)
    assert etat["tick"] == 7
    relu = CN.lire()
    assert relu is not None, "un pouls frais doit etre lisible"
    assert relu["tick"] == 7
    assert relu["periode_s"] == etat["periode_s"]
    # La periode publiee est utilisable telle quelle comme duree d'attente.
    assert CN.PERIODE_MIN_S <= relu["periode_s"] <= CN.PERIODE_MAX_S
    # Le fichier porte bien du JSON, pas un scalaire nu : un organe qui ferait
    # `.get()` dessus ne doit pas exploser (defaut mesure le 2026-09-03 sur un
    # `.heartbeat` qui contenait un float).
    assert isinstance(json.loads((tmp_path / "cardiac_pulse.json").read_text("utf-8")), dict)


def test_un_pouls_perime_n_est_pas_un_pouls(tmp_path, monkeypatch):
    """Au-dela de la peremption, `lire()` rend None : l'organe passe en echappement
    plutot que de se caler sur une cadence morte."""
    chemin = tmp_path / "cardiac_pulse.json"
    monkeypatch.setattr(CN, "PULSE", chemin)
    CN.systole(1)
    fige = json.loads(chemin.read_text("utf-8"))
    fige["ts"] = time.time() - 10_000        # vieux de plusieurs heures
    chemin.write_text(json.dumps(fige), encoding="utf-8")
    assert CN.lire() is None


def test_un_pouls_illisible_rend_none_sans_lever(tmp_path, monkeypatch):
    """Trois etats : lisible, perime, illisible. Aucun ne doit casser l'appelant --
    un organe qui plante en lisant le coeur serait pire que l'absence de coeur."""
    chemin = tmp_path / "cardiac_pulse.json"
    monkeypatch.setattr(CN, "PULSE", chemin)
    assert CN.lire() is None, "fichier absent"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert CN.lire() is None, "contenu invalide"
    chemin.write_text("1788425347.3", encoding="utf-8")
    assert CN.lire() is None, "scalaire nu : ce n'est pas un pouls"


class _Hormone:
    def __init__(self, name: str, level: float) -> None:
        self.name, self.level = name, level


def _faux_endocrine(monkeypatch, hormones):
    """Injecte un endocrine CONTROLE. Sans cela ce test lirait l'endocrine reel, ce
    qui le rendrait dependant de l'etat de la machine -- donc impur, donc hors de la
    suite pure, donc gardien de rien."""
    import types

    faux = types.ModuleType("forge_endocrine")
    faux.scan = lambda: list(hormones)
    monkeypatch.setitem(sys.modules, "forge_endocrine", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_endocrine", faux)
    # ⚠️ LES DEUX CLEFS `sys.modules` NE SUFFISENT PAS. `innervation()` fait
    # `from nokido_agent.app import forge_endocrine` — et cette forme lit
    # d'abord l'ATTRIBUT du paquet. Des qu'un autre test du meme processus a
    # importe le vrai module, l'attribut existe et passe DEVANT `sys.modules` :
    # le vrai endocrine repond, `innervation()` rend `DENERVE` (None), et le
    # test echoue en suite alors qu'il passe seul. Mesure 2026-09-10, CI de
    # reference sur 67e23bdd1.
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, "forge_endocrine"):
        monkeypatch.setattr(paquet, "forge_endocrine", faux)


def test_l_innervation_module_sur_les_chronotropes(monkeypatch):
    """Une modulation se lit AVEC sa provenance, sinon un rythme inexplique devient
    indebuggable. Et le denominateur est publie : « 2/5 retenues » distingue un
    filtre qui a trie d'un capteur qui n'a rien vu."""
    _faux_endocrine(monkeypatch, [
        _Hormone("adrenaline", 0.8),
        _Hormone("CORTISOL_FRUSTRATION", 0.4),
        _Hormone("TSH_VECTORIZATION", 0.99),      # saturee, doit etre IGNOREE
    ])
    modulation, raison = CN.innervation()
    assert modulation is not None
    assert 0.0 <= modulation <= 1.0
    # L'adrenaline (poids 1.0) domine le cortisol pondere : 0.8 > 0.4 * 0.5.
    assert abs(modulation - 0.8) < 1e-6, "la TSH saturee ne doit pas piloter le coeur"
    assert "2/5" in raison or "2/3" in raison, "le denominateur doit etre publie"


def test_sans_chronotrope_le_coeur_est_declare_DENERVE(monkeypatch):
    """Aucune hormone chronotrope active n'est pas « frein maximal » : c'est
    l'absence de commande, et le coeur retombe sur son rythme propre."""
    _faux_endocrine(monkeypatch, [_Hormone("TSH_VECTORIZATION", 0.99)])
    modulation, raison = CN.innervation()
    assert modulation is None
    assert "DENERVE" in raison
    assert CN.periode_pour(modulation) == CN.PERIODE_INTRINSEQUE_S


@pytest.mark.parametrize("interdite", ["TSH_VECTORIZATION", "INSULIN_VECTORIZATION"])
def test_les_hormones_metaboliques_ne_pilotent_pas_le_coeur(interdite):
    """Regression du 2026-09-03 : en prenant le MAX de TOUTES les hormones, le coeur se
    calait sur TSH_VECTORIZATION (0,972, TTL 4 h) et battait a sa periode MINIMALE en
    permanence. Une valeur saturee quatre heures n'est pas une tension, c'est une
    constante -- ce n'etait pas une regulation mais un emballement."""
    assert interdite not in CN.CHRONOTROPES


def test_le_chronotrope_direct_est_l_adrenaline():
    """L'adrenaline agit en direct (TTL court, la bonne echelle de temps) ; le cortisol
    est PERMISSIF, donc pondere. Si ces poids s'inversent, le rythme suivra une hormone
    plus lente que lui."""
    assert CN.CHRONOTROPES.get("adrenaline") == 1.0
    assert 0.0 < CN.CHRONOTROPES.get("CORTISOL_FRUSTRATION", 0.0) < 1.0
