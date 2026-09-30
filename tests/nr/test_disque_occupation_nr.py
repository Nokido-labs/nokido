# -*- coding: utf-8 -*-
"""NR — A0-3c : l'occupation disque est MESUREE, et son absence ne vaut pas zero.

Le regulateur ne connaissait que la RAM. L'owner a mesure « ram 86 % et nvme 100 % » :
deux symptomes qu'aucune entree ne reliait, alors que c'est probablement UN phenomene
-- une machine qui pagine ecrit sur le disque. Le canal qui l'aurait dit (`swp`) etait
lui-meme muet depuis le 2026-08-05, et pour la MEME cause : les compteurs de
performance Windows sont refuses aux comptes de service.

Ce que ce garde protege, dans l'ordre d'importance :

1. **Un compteur refuse rend RIEN, jamais 0.** C'est le coeur. `% Disk Time` a zero
   decrit un disque au repos ; un compteur inaccessible ne decrit rien du tout. Les
   confondre inverse le diagnostic exactement quand il compte -- pendant une
   saturation, personne ne regarde un canal qui affiche « 0 % ».
2. **Un ratio n'a pas de valeur a sa premiere collecte.** Meme contrat que `_debit` :
   sans reference, on ne publie pas. Sinon chaque demarrage du regulateur commence
   par un faux « disque au repos ».
3. **Le cout reste celui d'un tick.** La requete PDH est gardee ouverte : ~0,3 ms.
   `typeperf` aurait coute ~2 s, soit cent fois le palier `serie` entier.
4. **Les noms de compteurs sont ANGLAIS.** `PdhAddEnglishCounterW` est langue-agnostique.
   Sur cette machine ils s'appellent « \\Disque physique(_Total)\\Pourcentage du temps
   disque » : un chemin anglais passe a `typeperf` echoue en « aucun compteur valide »,
   ce qui se lit comme une absence de compteurs et envoie chercher une panne
   systeme inexistante.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

vc = pytest.importorskip("forge_vitals_channels")


def test_le_canal_disque_est_declare_en_serie():
    """En `sonde` il ne tournerait JAMAIS : `echantillon("sonde")` n'a aucun appelant
    dans le depot (mesure 2026-09-05, seul le palier `serie` est consomme)."""
    assert vc.GROUPES.get("disque") == (vc.grp_disque, "serie")
    assert "dbsy" in vc.SCHEMA and "dq" in vc.SCHEMA


def test_premiere_collecte_ne_publie_aucune_valeur():
    etat: dict = {}
    vals, note = vc.grp_disque(etat)
    if "ILLISIBLE" in note:
        pytest.skip("compteurs de performance refuses a ce compte : %s" % note[:70])
    assert vals == {}, "un ratio publie une valeur sans reference"
    assert "premiere collecte" in note


def test_seconde_collecte_mesure_et_reste_au_prix_d_un_tick():
    import time

    etat: dict = {}
    _v, note = vc.grp_disque(etat)
    if "ILLISIBLE" in note:
        pytest.skip("compteurs de performance refuses a ce compte")
    time.sleep(1.05)
    t0 = time.perf_counter()
    vals, note = vc.grp_disque(etat)
    ms = (time.perf_counter() - t0) * 1000.0
    assert "dbsy" in vals and isinstance(vals["dbsy"], (int, float))
    assert vals["dbsy"] >= 0.0
    assert ms < 50.0, "la requete PDH n'est pas gardee ouverte : %.1f ms par lecture" % ms


def test_un_compteur_refuse_rend_une_RAISON_et_zero_canal(monkeypatch):
    """Le cas paye : refus lu comme « disque au repos »."""
    monkeypatch.setitem(vc._PDH, "query", None)
    monkeypatch.setitem(vc._PDH, "compteurs", {})
    monkeypatch.setitem(vc._PDH, "amorce", False)
    monkeypatch.setitem(vc._PDH, "panne", "compteurs refuses A CE COMPTE (test)")
    vals, note = vc.grp_disque({})
    assert vals == {}, "un refus a produit une valeur"
    assert "ILLISIBLE" in note and "refus" in note.lower()


def test_les_chemins_de_compteurs_sont_en_anglais():
    """Un chemin localise casserait sur toute machine d'une autre langue -- et sur
    CELLE-CI, ou les compteurs sont en francais, un chemin francais passe a l'API
    English echouerait a l'inverse."""
    for _cle, chemin in vc._PDH_COMPTEURS:
        assert chemin.startswith("\\PhysicalDisk("), chemin
        assert "Disque" not in chemin, "chemin localise : %s" % chemin


def test_l_occupation_est_OBSERVEE_et_non_declaree_entree_de_l_arbitre():
    """Exposer une mesure n'est pas poser une politique : la regle vient en A0-4.

    Et elle vit dans `CONTRAT_OBSERVE`, PAS dans `CONTRAT` -- mon premier jet l'avait
    mise dans le second et le garde d'egalite stricte l'a refuse, a juste titre : le
    rapport aurait annonce « couverture complete des entrees » en comptant une
    grandeur qui n'entre dans aucune decision.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    audit = pytest.importorskip("forge_arbitre_entrees_audit")
    assert "disque_occupation_pct" in audit.CONTRAT_OBSERVE
    assert "disque_occupation_pct" not in audit.CONTRAT, \
        "une grandeur non recue par arbitrer_pression est declaree comme son entree"
    assert "AUCUNE consommation" in audit.CONTRAT_OBSERVE["disque_occupation_pct"][2]


def test_pas_de_valeur_est_INCONNUE_jamais_zero():
    sys.path.insert(0, str(ROOT / "tools"))
    audit = pytest.importorskip("forge_arbitre_entrees_audit")
    etat, _r = audit._classer("disque_occupation_pct", None, "")
    assert etat == audit.INCONNUE
    etat, _r = audit._classer("disque_occupation_pct", 0.0, "")
    assert etat == audit.MESUREE, "0 % mesure est une MESURE, pas une absence"
