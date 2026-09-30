# -*- coding: utf-8 -*-
"""NR — un instrument de CLOTURE ne doit pas compter des morts imaginaires.

CE QUI A ETE PAYE (2026-09-18). `forge_roadmap_keeper --verify` confronte l'intention
ecrite au code reel et rend `dead` quand la reference `forge_*` n'existe pas. Sur les
6 morts qu'il annoncait, l'un etait `forge_tier_guard` -- qui EXISTE, mais comme
TRIGGER SQLite, pas comme fichier `.py`.

Consequence, et c'est elle qui compte : un instrument de cloture qui invente des morts
fait fermer des chantiers qui n'existent pas, et surtout il fait douter des VRAIS. Le
depot a la regle symetrique pour les gardes qui crient a faux : ils se font desarmer.

Mesure apres correctif : `dead` passe de 6 a 5, `done_to_close` de 32 a 33.

PRECAUTION QUE CE NR VERROUILLE : si la base est ILLISIBLE, on ne requalifie RIEN et le
comportement d'origine s'applique. Mieux vaut un faux mort signale qu'un vrai mort
masque par une base qu'on n'a pas pu lire -- c'est le sens de lecture qui protege.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools", RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_roadmap_keeper as FRK  # noqa: E402


@pytest.fixture(autouse=True)
def _cache_propre():
    """Le cache de process ne doit pas faire fuiter un test dans l'autre."""
    FRK._OBJETS_SQL = None
    yield
    FRK._OBJETS_SQL = None


def test_un_objet_SQL_n_est_pas_un_module_MORT(monkeypatch):
    """MORSURE — le cas exact paye : un trigger nomme `forge_*` sans fichier `.py`."""
    monkeypatch.setattr(FRK, "_objets_sql", lambda: {"forge_tier_guard"})
    assert FRK._module_exists("forge_tier_guard") is True, (
        "un trigger SQL est declare mort : l'instrument invente un chantier")


def test_un_nom_vraiment_absent_reste_MORT(monkeypatch):
    """Contre-epreuve : reconnaitre d'autres formes ne doit rien rendre permissif."""
    monkeypatch.setattr(FRK, "_objets_sql", lambda: {"forge_tier_guard"})
    assert FRK._module_exists("forge_ceci_n_existe_nulle_part") is False


def test_un_module_py_reste_trouve_sans_toucher_a_la_base(monkeypatch):
    """Le chemin d'origine prime : aucune requete n'est faite quand le fichier existe."""
    def _interdit():
        raise AssertionError("la base ne doit pas etre consultee pour un module present")
    monkeypatch.setattr(FRK, "_objets_sql", _interdit)
    assert FRK._module_exists("forge_roadmap_keeper") is True


def test_une_base_illisible_ne_requalifie_RIEN(monkeypatch):
    """ILLISIBLE n'est pas « aucun objet » : on retombe sur le comportement d'origine."""
    monkeypatch.setattr(FRK, "_objets_sql", lambda: set())
    assert FRK._module_exists("forge_tier_guard") is False


def test_le_lecteur_de_catalogue_ne_leve_jamais(monkeypatch):
    """Un instrument qui casse ce qu'il mesure est pire que pas d'instrument."""
    monkeypatch.setattr(FRK, "_OBJETS_SQL", None)
    monkeypatch.setitem(sys.modules, "forge_db_path", None)   # import casse
    assert isinstance(FRK._objets_sql(), set)


def test_le_catalogue_n_est_lu_qu_UNE_fois(monkeypatch):
    """Cache de process : sans lui, CHAQUE reference rouvrirait la base.

    On compte les ouvertures REELLES en substituant `sqlite3.connect`, pas en
    comptant les appels d'un faux qu'on aurait pose soi-meme -- une premiere
    version de ce test mesurait son propre monkeypatch et ne prouvait rien.
    """
    import sqlite3

    ouvertures = {"n": 0}
    vrai_connect = sqlite3.connect

    def _compte(*a, **k):
        ouvertures["n"] += 1
        return vrai_connect(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", _compte)
    FRK._OBJETS_SQL = None
    for _ in range(4):
        FRK._objets_sql()
    assert ouvertures["n"] <= 1, (
        "la base est rouverte a chaque reference : %d ouvertures" % ouvertures["n"])
