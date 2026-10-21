# -*- coding: utf-8 -*-
"""NR -- executif a priorites Hamilton : classer, puis delester par ordre de priorite (owner 2026-10-18, audit RAM).

Owner : « certaines surfaces sont mal autoregulees et gonflent ou restent ouvertes a tort » ; « l'architecture
d'Hamilton ne pourrait pas aider ? pour une autoregulation intelligente couplee a l'existant ». Mesure du soir :
l'eviction est surtout SAUTEE (evict_skipped 540 contre evict_detresse 33) et la pression du soir etait NON-SOI
(pilote mtkbtsvc, ~5 k handles/min) -- delester le corps n'y aurait rien rendu.

Premier pas, PUR (aucune E/S) -- etend forge_resource_manager, aucun module neuf :
  1. `classe_hamilton(decl, critique)` range un service du TOML en VITAL / UTILE / DIFFERABLE / ETEINT par
     liste BLANCHE : n'est DIFFERABLE que ce qui est PROUVE differable sur tous ses champs ; un champ absent
     ou inattendu ne tombe jamais du cote delestable ;
  2. `ordre_delestage(candidats, verdict, detresse)` ne deleste QUE sous pression SOI : NON_SOI, NOYAU,
     INCERTAIN ou un verdict inconnu -> rien, et le dit ; sous SOI les DIFFERABLE d'abord (plus gros d'abord),
     les UTILE seulement en detresse, les VITAL jamais ; chaque decision porte son motif.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(60)

FOND = {"essential": False, "wave": 5, "heartbeat_tier": "slow"}


@pytest.mark.parametrize("decl, attendu", [
    ({"essential": True, "wave": 5, "heartbeat_tier": "slow"}, "VITAL"),
    ({"essential": False, "neverSleep": True, "wave": 5, "heartbeat_tier": "slow"}, "VITAL"),
    ({"essential": False, "wave": 1, "heartbeat_tier": "slow"}, "VITAL"),
    ({"essential": False, "wave": 2}, "VITAL"),
    (FOND, "DIFFERABLE"),
    ({"essential": False, "wave": 4}, "DIFFERABLE"),
    ({"essential": False, "wave": 4, "heartbeat_tier": "fast"}, "UTILE"),
    ({"essential": False, "wave": 3, "heartbeat_tier": "slow"}, "UTILE"),
    # liste BLANCHE : un champ absent ou inattendu n'est jamais une preuve de differabilite
    ({"wave": 5, "heartbeat_tier": "slow"}, "UTILE"),
    ({"essential": False, "heartbeat_tier": "slow"}, "UTILE"),
    ({"essential": False, "wave": "5", "heartbeat_tier": "slow"}, "UTILE"),
    ({"essential": False, "wave": 5, "heartbeat_tier": "tiede"}, "UTILE"),
    ({"essential": False, "wave": 5, "disabled": True}, "ETEINT"),
])
def test_classement_par_liste_blanche(decl, attendu):
    assert rm.classe_hamilton(decl) == attendu


def test_un_porteur_de_capacite_critique_est_vital():
    assert rm.classe_hamilton(FOND, critique=True) == "VITAL"


def _cands():
    return [
        {"service": "Petit", "classe": "DIFFERABLE", "rss_mb": 200},
        {"service": "Gros", "classe": "DIFFERABLE", "rss_mb": 900},
        {"service": "Cerveau", "classe": "UTILE", "rss_mb": 5000},
        {"service": "Hub", "classe": "VITAL", "rss_mb": 4000},
    ]


@pytest.mark.parametrize("verdict", ["NON_SOI", "NOYAU", "INCERTAIN", "", None, "soi"])
def test_hors_pression_soi_rien_n_est_deleste_et_c_est_dit(verdict):
    r = rm.ordre_delestage(_cands(), verdict, detresse=True)
    assert r["delester"] == []
    assert {e["service"] for e in r["epargnes"]} == {"Petit", "Gros", "Cerveau", "Hub"}
    assert r["motif"] and all(e["motif"] for e in r["epargnes"])


def test_sous_pression_soi_les_differables_d_abord_les_plus_gros_en_tete():
    r = rm.ordre_delestage(_cands(), "SOI", detresse=False)
    assert [d["service"] for d in r["delester"]] == ["Gros", "Petit"]
    epargnes = {e["service"]: e["motif"] for e in r["epargnes"]}
    assert set(epargnes) == {"Cerveau", "Hub"}
    assert all(d["motif"] for d in r["delester"]) and all(epargnes.values())


def test_en_detresse_les_utiles_suivent_les_vitaux_jamais():
    r = rm.ordre_delestage(_cands(), "SOI", detresse=True)
    assert [d["service"] for d in r["delester"]] == ["Gros", "Petit", "Cerveau"]
    assert [e["service"] for e in r["epargnes"]] == ["Hub"]


def test_une_classe_inconnue_n_est_jamais_delestee():
    r = rm.ordre_delestage([{"service": "X", "classe": "BIZARRE", "rss_mb": 9000},
                            {"service": "Y", "rss_mb": 9000}], "SOI", detresse=True)
    assert r["delester"] == []
    assert {e["service"] for e in r["epargnes"]} == {"X", "Y"}


def test_un_rss_illisible_passe_apres_les_rss_mesures():
    r = rm.ordre_delestage([{"service": "Muet", "classe": "DIFFERABLE", "rss_mb": None},
                            {"service": "Mesure", "classe": "DIFFERABLE", "rss_mb": 10}], "SOI")
    assert [d["service"] for d in r["delester"]] == ["Mesure", "Muet"]
