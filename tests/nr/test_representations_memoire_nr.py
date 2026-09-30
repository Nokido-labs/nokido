# -*- coding: utf-8 -*-
"""NR — ZERO ZONE D'OMBRE sur les representations d'une source.

« Zero zone d'ombre » ne veut pas dire « zero manque » : cela veut dire que tout manque
est NOMME, ATTRIBUE et EXPLICABLE. Une case absente du resultat est la zone d'ombre
elle-meme — pire qu'un `NON`, parce qu'elle ne se voit pas.

Le cas sentinelle est `memory:MEMORY` : relie, present, lexicalement indexe, et
VECTORIELLEMENT bloque faute de producteur vivant. Il doit sortir comme un etat
justifiable, jamais comme une panne de la memoire entiere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_memory_availability as M  # noqa: E402

SENTINELLE = "memory:MEMORY"


def _matrice(source):
    try:
        return M.representations(source)
    except Exception as exc:  # noqa: BLE001
        pytest.skip("base RAG injoignable (%s) — on ne conclut pas d'une source qui "
                    "se tait" % exc)


def test_les_cinq_representations_sont_toujours_presentes():
    """Aucune case absente, y compris pour une source qui n'existe pas.

    Le cas « source inconnue » est le plus revelateur : c'est la que le code est tente
    de ne rien rendre du tout.
    """
    for source in (SENTINELLE, "source:qui-n-existe-pas-2026"):
        r = _matrice(source)["representations"]
        for repr_ in M.REPRESENTATIONS:
            assert repr_ in r, "representation %s ABSENTE pour %s" % (repr_, source)
            cell = r[repr_]
            assert cell["valeur"] in (M.OUI, M.NON, M.UNKNOWN, M.N_A, M.BLOQUE,
                                      "PARTIEL", "DEGRADE"), cell
            # Toute valeur qui n'est pas un OUI franc doit porter une explication ou
            # une population : un manque sans raison est une zone d'ombre deguisee.
            if cell["valeur"] not in (M.OUI,):
                assert cell["raison"] or cell["population"] is not None, (
                    "%s=%s sans raison NI population : manque non explicable"
                    % (repr_, cell["valeur"]))


def test_une_capacite_bloquee_n_est_pas_une_panne_de_la_memoire():
    """`vector = BLOQUE` ne doit contaminer ni le relationnel ni le lexical.

    C'est tout l'objet du chantier : une representation indisponible faute de
    ressources est un etat NOMME, pas une memoire cassee.
    """
    r = _matrice(SENTINELLE)["representations"]
    assert r["relationnel"]["valeur"] == M.OUI, r["relationnel"]
    assert r["lexical"]["valeur"] == M.OUI, r["lexical"]
    if r["vectoriel"]["valeur"] == M.BLOQUE:
        assert r["vectoriel"]["raison"], "un BLOQUE sans raison n'est pas justifiable"
        # L'hybride se DEGRADE, il ne tombe pas : une voie reste ouverte.
        assert r["hybride"]["valeur"] in ("DEGRADE", M.UNKNOWN), r["hybride"]


def test_appartenance_lexicale_mesuree_par_rowid_et_non_par_phrase():
    """Anti-regression du surcomptage mesure le 2026-09-05.

    `MATCH 'source:"memory:MEMORY"'` rendait 144 entrees pour 16 chunks : le tokenizer
    coupe `memory:MEMORY_ARCHIVE`, donc la source VOISINE etait comptee dans la notre.
    Une population lexicale ne peut pas depasser la population relationnelle.
    """
    m = _matrice(SENTINELLE)["representations"]
    rel, lex = m["relationnel"], m["lexical"]
    if lex["valeur"] in (M.UNKNOWN, M.N_A) or not isinstance(lex["population"], dict):
        pytest.skip("lexical non mesurable ici : %s" % lex["raison"])
    assert lex["population"]["attendus"] == rel["population"]
    assert lex["population"]["indexes"] <= rel["population"], (
        "population lexicale (%s) SUPERIEURE au relationnel (%s) : le comptage attrape "
        "des sources voisines" % (lex["population"], rel["population"]))


def test_hybride_reste_derive_et_ne_devient_pas_un_index():
    """L'hybride est une capacite COMPOSEE.

    S'il devenait une table, il deviendrait une source de verite concurrente — et le
    corps en a deja paye (deux index qui divergent silencieusement).
    """
    r = _matrice(SENTINELLE)["representations"]["hybride"]
    assert "deriv" in (r["producteur"] or "").lower(), r
    assert r["population"] is None, "l'hybride ne doit compter aucune population propre"
