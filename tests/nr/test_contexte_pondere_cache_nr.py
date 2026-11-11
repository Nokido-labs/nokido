"""NR : forge_contexte_par_source pese chaque source au prix du cache, pas seulement en tokens x tours.

Debat tokens T11 (5/11) : « 58 % du volume » n'est pas 58 % du cout. Un bloc s'ecrit une fois en cache (poids 1,25)
puis se relit a chaque tour (poids 0,1). Un bloc jamais relu pese donc quand meme son ecriture : tokens x tours le
comptait zero.
"""
import importlib.util
import pathlib

import pytest

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_contexte_par_source.py"
_spec = importlib.util.spec_from_file_location("fcps_pondere_nr", _CHEMIN)
fcps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcps)


def _attachment(kind, car):
    return {"type": "attachment", "attachment": {"type": kind}, "rendered": [{"content": "x" * car}]}


def _appel(n):
    return {"type": "assistant", "requestId": "r%d" % n, "message": {"usage": {}, "content": []}}


def _entrees():
    return [_attachment("relu", 1000), _appel(1), _appel(2), _appel(3), _attachment("jamais_relu", 500)]


def _source(res, nom):
    return next(s for s in res["sources"] if s["source"] == nom)


def test_ecriture_plus_lectures_au_poids_du_cache():
    res = fcps.analyser(_entrees())
    k = res["calibration"]["tokens_par_car"]
    assert _source(res, "attachment:relu")["pondere_est"] == round(1000 * k * (1.25 + 0.1 * 3))


def test_un_bloc_jamais_relu_coute_son_ecriture():
    res = fcps.analyser(_entrees())
    s = _source(res, "attachment:jamais_relu")
    assert s["tokens_tours_est"] == 0
    assert s["pondere_est"] == round(500 * res["calibration"]["tokens_par_car"] * 1.25)


def test_les_parts_ponderees_font_un():
    res = fcps.analyser(_entrees())
    assert sum(s["part_ponderee"] for s in res["sources"]) == pytest.approx(1.0)
    assert sum(f["part_ponderee"] for f in res["familles"]) == pytest.approx(1.0)
