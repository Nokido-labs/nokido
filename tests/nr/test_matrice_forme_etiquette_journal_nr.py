# -*- coding: utf-8 -*-
"""NR -- une sortie console prefixee d'une etiquette `[...]` n'est pas un objet JSON (enquete de soif, 15/10).

Premiere enquete de l'effecteur de soif (AGY, `9e12655ec128`, 48 cycles « Capacites : ratchet_check=
REGRESSION ») : `_forme_sortie` lisait `[IPv6 autorisee (defaut)] HTTP 403 -> [{"code": ...` comme un
objet (`obj:result`) ; a 4 formes vues 1 fois chacune, `max` gardait la plus ANCIENNE ; le cliquet
bloquait `run|action,code,network` (gele `texte:long`) sur un faux changement de contrat.
Le garde n'est pas affaibli : c'est l'INSTRUMENT qui est corrige.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_regression_matrix as rm  # noqa: E402


def test_etiquette_de_journal_n_est_pas_un_objet():
    for s in ('[IPv6 autorisee (defaut)] HTTP 403 -> [{"code": 9109, "message": "x"}]\n[IPv4 FORCEE] HTTP 200 -> {"result":{"id":"1"}}',
              '[compte via handler IPv4] HTTP 200 success = True\n{"text": "x"}',
              "[nokido] 0.20.11 publie"):
        assert rm._forme_sortie(s).startswith("texte:"), (s, rm._forme_sortie(s))


def test_vrais_objets_meme_tronques_restent_des_objets():
    assert rm._forme_sortie('{"result": {"id": "10f6f92f58650c85') .startswith("obj:")
    assert rm._forme_sortie('{"ok": true, "stdout": "a"}') == "obj:ok,stdout"
    assert rm._forme_sortie('[{"a": 1}, {"a": 2}]').startswith("obj:")
    assert rm._forme_sortie("[]").startswith("obj:")
    assert rm._forme_sortie('[true, null]').startswith("obj:")


def test_egalite_departagee_par_la_plus_recente():
    formes = {"obj:result": {"n": 1, "last": "2026-09-16T14:21"},
              "texte:long": {"n": 1, "last": "2026-09-18T18:16"},
              "texte:moyen": {"n": 1, "last": "2026-10-14T12:52"}}
    assert rm._forme_dominante(formes) == "texte:moyen"
    formes["obj:result"]["n"] = 2
    assert rm._forme_dominante(formes) == "obj:result"      # la frequence prime toujours
