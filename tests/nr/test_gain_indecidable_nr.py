# -*- coding: utf-8 -*-
"""Non-regression — un gain qu'on n'a PAS PU mesurer n'est pas un gain NUL.

Troisieme site du meme motif dans la meme journee (2026-09-08), apres
`forge_goap_intuition._confidence` et `forge_frugal_cascade._ask_self_confidence` :
une absence de mesure rendue sous la forme d'une mesure.

MESURE : `juger_gain` compare `mesurer(tests)` avant et apres. Avec `tests=[]` —
le cas de tout appelant qui ne fournit pas de suite ciblee — les deux etats valent
`{tests_ok: 0, tests_total: 0, duree_s: ~0}`. Or les trois branches capables de
rendre AMELIORE ou DEGRADE exigent toutes `bd > 0`. Le verdict tombait donc en
NEUTRE, « aucun gain mesure vs baseline », et `juger_module_avec_gain` RESTAURAIT
la mutation en la declarant jugee.

Le comportement conservateur est JUSTE et ne change pas ici : on ne conserve que ce
qui est PROUVE meilleur. Ce qui change est le VERDICT — `GAIN_INDECIDABLE` au lieu
de `SURVIT_SANS_GAIN`, et `INDECIDABLE` au lieu de `NEUTRE`. La difference n'est pas
cosmetique : elle dit a l'appelant que la boucle a besoin de TESTS, la ou « pas de
gain » l'envoie chercher un meilleur patch. C'est le prealable au raccordement de
`forge_autonomous_loops` sur le chemin ferme (elle emprunte aujourd'hui
`juger_module`, sans gain, alors que la docstring du chemin ferme la designe).

Hermetique : fonctions pures, temoins patches. Aucun test lance, aucun git, aucun
fichier ecrit.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.106)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mutation_judge as MJ  # noqa: E402

VIDE = {"tests_ok": 0, "tests_total": 0, "duree_s": 0.0}


def test_aucun_test_rend_indecidable_et_non_neutre():
    """Sans suite fournie, rien n'a ete mesure : le gain est INCONNU."""
    g = MJ.juger_gain(dict(VIDE), dict(VIDE))
    assert g["verdict"] == "INDECIDABLE", g
    assert "mesur" in g["pourquoi"].lower()


def test_le_motif_nomme_ce_qui_manque():
    """Un verdict d'abstention doit dire QUOI fournir, sinon il n'aide personne."""
    g = MJ.juger_gain(dict(VIDE), dict(VIDE))
    assert "test" in g["pourquoi"].lower()


def test_egalite_mesuree_reste_neutre():
    """Deux etats REELLEMENT mesures et egaux : NEUTRE, c'est une mesure."""
    base = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    cand = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    assert MJ.juger_gain(base, cand)["verdict"] == "NEUTRE"


def test_ameliore_inchange():
    base = {"tests_ok": 2, "tests_total": 3, "duree_s": 10.0}
    cand = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    assert MJ.juger_gain(base, cand)["verdict"] == "AMELIORE"


def test_degrade_inchange():
    base = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    cand = {"tests_ok": 2, "tests_total": 3, "duree_s": 10.0}
    assert MJ.juger_gain(base, cand)["verdict"] == "DEGRADE"


def test_plus_rapide_a_couverture_egale_reste_ameliore():
    base = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    cand = {"tests_ok": 3, "tests_total": 3, "duree_s": 8.0}
    assert MJ.juger_gain(base, cand)["verdict"] == "AMELIORE"


def test_le_juge_ferme_nomme_l_indecidable_et_restaure_quand_meme(monkeypatch):
    """Comportement INCHANGE (on restaure), verdict HONNETE (on dit pourquoi).

    Chemin reel de `juger_module_avec_gain`, avec ses trois dependances remplacees :
    la mesure, le juge de survie et la restauration.
    """
    monkeypatch.setattr(MJ, "mesurer", lambda tests=None, cwd=None: dict(VIDE))
    monkeypatch.setattr(MJ, "juger_module", lambda rel, nouveau, tests: {"verdict": "SURVIT"})
    monkeypatch.setattr(MJ, "patron_sain", lambda rel: {"ok": False})  # pas d'ecriture disque
    monkeypatch.setattr(MJ, "_journaliser", lambda rel, r: None)

    r = MJ.juger_module_avec_gain("app/peu_importe.py", "x = 1\n", tests=[])
    assert r["verdict"] == "GAIN_INDECIDABLE", r
    assert r["gain"]["verdict"] == "INDECIDABLE"
    assert "test" in r["note"].lower(), "la note doit dire ce qui manque"


def test_le_juge_ferme_conserve_toujours_sur_ameliore(monkeypatch):
    """Le chemin nominal n'est pas touche par la distinction."""
    base = {"tests_ok": 2, "tests_total": 3, "duree_s": 10.0}
    cand = {"tests_ok": 3, "tests_total": 3, "duree_s": 10.0}
    etats = [base, cand]
    monkeypatch.setattr(MJ, "mesurer", lambda tests=None, cwd=None: etats.pop(0))
    monkeypatch.setattr(MJ, "juger_module", lambda rel, nouveau, tests: {"verdict": "SURVIT"})
    monkeypatch.setattr(MJ, "_journaliser", lambda rel, r: None)

    r = MJ.juger_module_avec_gain("app/peu_importe.py", "x = 1\n", tests=["t.py"])
    assert r["verdict"] == "AMELIORE", r
