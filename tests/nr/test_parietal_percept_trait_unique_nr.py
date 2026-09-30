"""NR : le percept parietal coute UN calcul, meme sous N appels concurrents.

MESURE du 2026-09-17 sur `/api/vital/parietal_percept`, apres avoir retire le
balayage de 24,9 Go qui tuait deja le service :

    1 appel   ->  2,2 s   (/health max  234 ms)
    4 appels  ->  5,9 s   (/health max  796 ms)
    20 appels -> 44,5 s   (/health max 5359 ms)

44,5 vaut 20 x 2,2 : le travail SERIALISE. La route appelante etant declaree
`def`, chaque requete immobilise un ouvrier du threadpool anyio pendant toute
la duree, et `/health` -- synchrone lui aussi -- voit son delai monter avec la
file. C'est ce mecanisme qui fait lire une SATURATION comme une PANNE.

Or `fuse()` rend un PERCEPT : un instantane de l'etat ambiant, agrege sur cinq
organes. Le recalculer vingt fois par seconde ne produit aucune connaissance
supplementaire. D'ou un cache a TRAIT UNIQUE.

Ce NR verrouille le comportement, pas la forme :
  * N appels concurrents ne declenchent QU'UN calcul ;
  * chaque appelant recoit tout de meme un percept complet ;
  * l'age est RENDU, jamais masque -- un signal qui tait son age se fait
    prendre pour une preuve de vie ;
  * passe le TTL, le calcul repart : un cache qui ne se perime pas n'est plus
    un cache, c'est un gel.
"""
from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE / "app") not in sys.path:
    sys.path.insert(0, str(RACINE / "app"))


@pytest.fixture()
def fusion(monkeypatch):
    mod = importlib.import_module("forge_parietal_fusion")
    # cache vide a chaque test : sinon un test heriterait du percept du
    # precedent et mesurerait autre chose que lui-meme
    monkeypatch.setitem(mod._PERCEPT_CACHE, "val", None)
    monkeypatch.setitem(mod._PERCEPT_CACHE, "ts", 0.0)
    return mod


def _compteur_lent(mod, monkeypatch, duree=0.25):
    appels = {"n": 0}

    def _calcule():
        appels["n"] += 1
        time.sleep(duree)          # simule le cout reel mesure
        return {"salience": 0.5, "priority": 2, "tag": "neutral", "focus": []}

    monkeypatch.setattr(mod, "_fuse_calcule", _calcule)
    return appels


def test_vingt_appels_concurrents_ne_font_qu_un_calcul(fusion, monkeypatch):
    appels = _compteur_lent(fusion, monkeypatch)
    recus: list[dict] = []
    verrou = threading.Lock()

    def _tirer():
        r = fusion.fuse()
        with verrou:
            recus.append(r)

    fils = [threading.Thread(target=_tirer) for _ in range(20)]
    debut = time.monotonic()
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=30)
    ecoule = time.monotonic() - debut

    assert appels["n"] == 1, (
        f"{appels['n']} calculs pour 20 appels : le trait unique ne tient pas, "
        "et chaque calcul immobilise un ouvrier du threadpool"
    )
    assert len(recus) == 20, "des appelants sont repartis sans percept"
    assert ecoule < 3.0, (
        f"{ecoule:.2f} s pour 20 appels : la serialisation persiste"
    )


def test_chaque_appelant_recoit_un_percept_complet(fusion, monkeypatch):
    _compteur_lent(fusion, monkeypatch, duree=0.05)
    r = fusion.fuse()
    for cle in ("salience", "priority", "tag", "focus"):
        assert cle in r, f"la cle {cle!r} manque : le cache appauvrit le percept"


def test_l_age_du_percept_est_rendu(fusion, monkeypatch):
    _compteur_lent(fusion, monkeypatch, duree=0.05)
    premier = fusion.fuse()
    assert premier.get("cache_age_s") == 0.0, "le calcul frais doit annoncer un age nul"
    time.sleep(0.2)
    second = fusion.fuse()
    assert second.get("cache_age_s", 0) > 0, (
        "un percept servi depuis le cache doit DIRE son age : un signal qui "
        "tait son age se fait prendre pour une preuve de vie"
    )


def test_le_cache_se_perime(fusion, monkeypatch):
    appels = _compteur_lent(fusion, monkeypatch, duree=0.01)
    monkeypatch.setattr(fusion, "_PERCEPT_TTL_S", 0.15)
    fusion.fuse()
    assert appels["n"] == 1
    time.sleep(0.25)
    fusion.fuse()
    assert appels["n"] == 2, (
        "le cache ne se perime pas : un cache qui ne expire jamais n'est plus "
        "un cache, c'est un gel de l'observation"
    )


def test_le_cache_ne_masque_pas_un_appelant_isole(fusion, monkeypatch):
    """Controle NEGATIF : sans cache, 3 appels donnent bien 3 calculs."""
    appels = _compteur_lent(fusion, monkeypatch, duree=0.01)
    monkeypatch.setattr(fusion, "_PERCEPT_TTL_S", 0.0)   # cache desarme
    for _ in range(3):
        fusion.fuse()
    assert appels["n"] == 3, (
        "avec un TTL nul le calcul devrait repartir a chaque appel ; s'il ne "
        "le fait pas, le compteur ne mesure rien et les autres tests non plus"
    )
