"""NR 18/10 -- juge POLY-METRIQUE, pas 1 (chantier 1 de bb P1_preparation_takehome_anthropic_20261018).

Carto AGY (job_53f21306) : juger_gain ne connait que tests_* et duree_s (marge 10 %). Sur le takehome
(cycles simules a MINIMISER), un candidat 18 532 -> 1 487 cycles a duree pytest egale sortait NEUTRE -- et
juger_module_avec_gain le DEFAISAIT. Contrat : baseline et candidat portent `metrique` = {nom, valeur, bruit,
sens MIN|MAX} ; elle REMPLACE duree_s comme dimension de performance ; la CORRECTION reste eliminatoire
(jamais compensable par la vitesse) ; contrat invalide = INDECIDABLE (jamais NEUTRE) ; sans metrique,
comportement inchange.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_mutation_judge as J  # noqa: E402

TESTS = {"tests_ok": 3, "tests_total": 3, "tests_passes": ["a", "b", "c"], "duree_s": 0.4}


def _m(valeur, nom="cycles", bruit=0.0, sens="MIN"):
    return {"nom": nom, "valeur": valeur, "bruit": bruit, "sens": sens}


def test_moins_de_cycles_a_duree_egale_est_ameliore():
    v = J.juger_gain({**TESTS, "metrique": _m(18532)}, {**TESTS, "metrique": _m(1487)})
    assert v["verdict"] == "AMELIORE", v["pourquoi"]


def test_la_correction_reste_eliminatoire():
    perdu = {**TESTS, "tests_ok": 2, "tests_passes": ["a", "b"], "metrique": _m(10)}
    assert J.juger_gain({**TESTS, "metrique": _m(18532)}, perdu)["verdict"] == "DEGRADE"


def test_dans_le_bruit_est_neutre_et_au_dela_degrade():
    base = {**TESTS, "metrique": _m(100.0, nom="txt_s", bruit=5.0, sens="MAX")}
    assert J.juger_gain(base, {**TESTS, "metrique": _m(103.0, nom="txt_s", bruit=5.0, sens="MAX")})["verdict"] == "NEUTRE"
    assert J.juger_gain(base, {**TESTS, "metrique": _m(110.0, nom="txt_s", bruit=5.0, sens="MAX")})["verdict"] == "AMELIORE"
    assert J.juger_gain(base, {**TESTS, "metrique": _m(90.0, nom="txt_s", bruit=5.0, sens="MAX")})["verdict"] == "DEGRADE"


def test_une_metrique_degradee_n_est_jamais_rachetee_par_plus_de_tests():
    plus_de_tests = {"tests_ok": 4, "tests_total": 4, "tests_passes": ["a", "b", "c", "d"], "duree_s": 0.4,
                     "metrique": _m(20000)}
    assert J.juger_gain({**TESTS, "metrique": _m(18532)}, plus_de_tests)["verdict"] == "DEGRADE"


def test_contrat_invalide_est_indecidable_jamais_neutre():
    for mauvaise in (_m(10, sens="PLUS"), _m("vite"), _m(10, nom="autre")):
        v = J.juger_gain({**TESTS, "metrique": _m(18532)}, {**TESTS, "metrique": mauvaise})
        assert v["verdict"] == "INDECIDABLE", (mauvaise, v)


def test_sans_metrique_le_comportement_est_inchange():
    assert J.juger_gain(dict(TESTS), {**TESTS, "duree_s": 0.41})["verdict"] == "NEUTRE"
    assert J.juger_gain(dict(TESTS), {**TESTS, "duree_s": 0.2})["verdict"] == "AMELIORE"
