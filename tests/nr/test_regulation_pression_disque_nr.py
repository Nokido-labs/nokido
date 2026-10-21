# -*- coding: utf-8 -*-
"""NR -- la pression DISQUE se regule, comme la RAM (owner 2026-10-19 : « disque toujours a 100 % et ram a plus
de 80 % tu autoregule mal ! »).

Mesure du 19/10, 14:04-14:12, apres une relance de pile : NokidoDeportEmbed 11 Go lus (~96 Mo/s),
NokidoMCP 7,4 Go, NokidoMemoryConsolidator 4,5 Go ; `disque.occupation_pct` (forge_vitals_channels.grp_disque,
en service depuis le 05/09) entre 56 et 83 % pendant tout l'episode. AUCUN regulateur ne lit ce canal : son seul
lecteur est un outil d'audit. Capteur sans effecteur -- les deux saturateurs sont pourtant DIFFERABLE au TOML
(essential=false, vague 4, battement lent) et l'executif Hamilton sait deja les ordonner, mais seulement pour
la RAM et par taille memoire. Il a fallu les arreter a la main.

Contrat -- etend forge_resource_manager, aucun module neuf :
  1. `pression_disque(echantillons, seuil, n)` : SATUREE seulement si les n derniers echantillons sont TOUS au-dessus
     du seuil (un fait qui dure se lit sur une fenetre, jamais sur un point) ; une fenetre incomplete ou trouee est
     ILLISIBLE, jamais NORMALE (UNKNOWN != NO) ;
  2. `attribuer_pression_disque(couts, total_mo_s)` : SOI quand les services du corps portent au moins la moitie du
     debit disque mesure ; couts ou total illisibles -> ILLISIBLE ;
  3. `ordre_delestage(..., grandeur=)` ordonne sur la grandeur demandee (debit d'E/S ici), defaut inchange (rss_mb) ;
  4. `regulation_disque(...)` compose 1-3 avec `classe_hamilton` et `gestes_observes` (pause avant arret, reprise
     apres calme -- decision owner 19/10) : seuls les DIFFERABLE qui lisent/ecrivent vraiment sont suspendus ;
     VITAL jamais ; pression hors corps signalee, jamais delestee ;
  5. le sampler l'appelle : `_regulation_disque_tick` est branche dans `_sampler_loop` et ne leve jamais.
"""
import inspect
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(60)

LENT = {"essential": False, "wave": 4, "heartbeat_tier": "slow"}
TOML = {
    "NokidoDeportEmbed": dict(LENT, name="NokidoDeportEmbed"),
    "NokidoMemoryConsolidator": dict(LENT, name="NokidoMemoryConsolidator"),
    "NokidoMCP": {"name": "NokidoMCP", "essential": True, "wave": 1, "neverSleep": True},
    "NokidoRepos": dict(LENT, name="NokidoRepos"),
}
REGISTRE = {"NokidoDeportEmbed": 8552, "NokidoMemoryConsolidator": 3964, "NokidoMCP": 26632, "NokidoRepos": 77}
COUTS = {"NokidoDeportEmbed": (96.0, 5.0), "NokidoMemoryConsolidator": (15.0, 2.0),
         "NokidoMCP": (42.0, 20.0), "NokidoRepos": (0.2, 0.0)}


def _non_critique(_svc):
    return False


@pytest.mark.parametrize("echs, attendu", [
    ([85, 90, 88, 92], "SATUREE"),
    ([10, 20, 85, 90, 88, 92], "SATUREE"),      # seule la fenetre des n derniers compte
    ([85, 30, 88, 92], "NORMALE"),              # un signal qui oscille n'est pas une saturation
    ([None, 90, 88, 92], "ILLISIBLE"),          # trou dans la fenetre : jamais NORMALE
    ([90, 88], "ILLISIBLE"),                    # fenetre incomplete
    ([], "ILLISIBLE"),
])
def test_saturation_lue_sur_une_fenetre(echs, attendu):
    assert rm.pression_disque(echs, seuil=80.0, n=4) == attendu


def test_attribution_du_debit_disque():
    assert rm.attribuer_pression_disque(COUTS, 134.0)["verdict"] == "SOI"
    assert rm.attribuer_pression_disque({"NokidoRepos": (5.0, 0.0)}, 134.0)["verdict"] == "NON_SOI"
    for couts, total in ((None, 134.0), ({}, 134.0), (COUTS, None), (COUTS, 0.0)):
        assert rm.attribuer_pression_disque(couts, total)["verdict"] == "ILLISIBLE", (couts, total)


def test_ordre_delestage_par_debit_d_e_s():
    cands = [{"service": "Petit", "classe": "DIFFERABLE", "rss_mb": 900, "io_mo_s": 3.0},
             {"service": "Liseur", "classe": "DIFFERABLE", "rss_mb": 40, "io_mo_s": 96.0},
             {"service": "Hub", "classe": "VITAL", "rss_mb": 1900, "io_mo_s": 42.0}]
    r = rm.ordre_delestage(cands, "SOI", grandeur="io_mo_s")
    assert [d["service"] for d in r["delester"]] == ["Liseur", "Petit"]
    # defaut inchange : la RAM reste ordonnee par memoire
    assert [d["service"] for d in rm.ordre_delestage(cands, "SOI")["delester"]] == ["Petit", "Liseur"]


def _regler(echs, couts=COUTS, total=134.0, etat=None, t=1000.0):
    return rm.regulation_disque(echs, couts, total, TOML, REGISTRE, etat or {}, t,
                                est_critique=_non_critique, seuil=80.0, n=4)


def test_saturation_du_corps_suspend_les_differables_qui_lisent():
    r = _regler([85, 90, 88, 92])
    assert r["pression"] == "SATUREE" and r["verdict"] == "SOI"
    assert r["gestes"] == {"NokidoDeportEmbed": "SUSPENDRE", "NokidoMemoryConsolidator": "SUSPENDRE"}
    assert [d["service"] for d in r["delester"]][:1] == ["NokidoDeportEmbed"]   # plus gros debit d'abord
    assert "NokidoMCP" not in r["gestes"]       # VITAL : jamais
    assert "NokidoRepos" not in r["gestes"]     # DIFFERABLE mais muet sur le disque : rien a rendre
    assert set(r["etat"]) == {"NokidoDeportEmbed", "NokidoMemoryConsolidator"}


@pytest.mark.parametrize("echs, couts", [
    ([85, 30, 88, 92], COUTS),                          # oscillation
    ([None, 90, 88, 92], COUTS),                        # illisible
    ([85, 90, 88, 92], {"NokidoRepos": (5.0, 0.0)}),    # pression hors corps
])
def test_rien_ne_se_suspend_sans_saturation_prouvee_du_corps(echs, couts):
    r = _regler(echs, couts=couts)
    assert "SUSPENDRE" not in r["gestes"].values()
    assert r["motif"]


def test_la_reprise_attend_un_calme_durable():
    pause = _regler([85, 90, 88, 92])["etat"]
    r = _regler([85, 30, 20, 10], etat=pause, t=1010.0)
    assert r["gestes"].get("NokidoDeportEmbed") == "MAINTENIR_PAUSE"


def test_le_sampler_regule_le_disque(monkeypatch):
    assert "_regulation_disque_tick" in inspect.getsource(rm._sampler_loop)
    ordres = []
    monkeypatch.setattr(rm, "_registre_corps", lambda: None)
    monkeypatch.setattr(rm, "_echantillons_disque", lambda: [90.0, 91.0, 92.0, 93.0])
    monkeypatch.setattr(rm, "_ordre_superviseur", lambda svc, geste: ordres.append((svc, geste)))
    r = rm._regulation_disque_tick()
    assert r["gestes"] == {} and ordres == []
    assert "ILLISIBLE" in r["motif"]
