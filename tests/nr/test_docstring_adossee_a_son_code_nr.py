# -*- coding: utf-8 -*-
"""NR — une docstring est une AFFIRMATION ; son code en est la PREUVE.

    Claim    = la docstring (ce que le module dit de lui-meme)
    Evidence = le CORPS du code qu'elle decrit
    version  = l'empreinte de ce corps au moment ou la docstring a ete ecrite

LE TROU MESURE (2026-09-22)
    `forge_wiki_modules` derive le wiki des docstrings REELLES et refuse d'en
    inventer une -- c'est deja le bon principe. Mais son `empreinte_du_corpus`
    hache « chemin, docstring, API » et JAMAIS LE CORPS.

    Consequence : quand un corps change sans sa docstring, l'empreinte ne
    bouge pas. Le wiki est alors declare FRAIS en reproduisant fidelement une
    description devenue fausse.

        LE WIKI NE MENT PAS : IL REPETE FIDELEMENT UNE DOCSTRING QUI MENT.

    Et l'inverse compte autant : une docstring reecrite sur un corps inchange
    n'est pas une derive, c'est une clarification. Les deux ne doivent pas
    produire le meme signal.

CE QUE CE CONTRAT EXIGE
    1. une empreinte du CORPS SEUL, docstrings exclues -- sinon reformuler la
       prose changerait la « preuve », et tout deviendrait suspect ;
    2. un etat persistant (docstring, empreinte du corps) par module ;
    3. un verdict a TROIS etats, jamais deux :
         ALIGNE    le corps n'a pas bouge depuis la derniere docstring
         SUSPECTE  le corps a change, la docstring NON
         INCONNU   jamais observe, ou source illisible
       `INCONNU` n'est pas `ALIGNE` : un module jamais mesure ne se range pas
       du cote sain.

INSPIRATION MESUREE, PAS COPIEE : `langchain-ai/openwiki` (ingere en RAG le
2026-09-22, +9192 chunks). Son modele `Claim` / `Evidence{resource, version}`
pose la version par un RESOLVEUR deterministe, jamais par le modele, et
distingue `confirm` (revalider contre la version courante) de `add`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_wiki_modules as wm  # noqa: E402 — livrable, jamais d'importorskip


_AVEC_DOC = '''"""Fait la chose A."""


def travaille(x):
    return x + 1
'''

_CORPS_CHANGE = '''"""Fait la chose A."""


def travaille(x):
    return x * 2 + 41
'''

_DOC_CHANGEE = '''"""Fait la chose B, tout autrement."""


def travaille(x):
    return x + 1
'''


def _empreinte(source: str) -> str:
    f = getattr(wm, "empreinte_du_corps", None)
    assert f is not None, (
        "`forge_wiki_modules.empreinte_du_corps` ABSENTE — rien ne distingue "
        "une docstring alignee d'une docstring devenue fausse")
    return f(source)


# ── L'EMPREINTE PORTE LE CORPS, ET RIEN QUE LUI ─────────────────────────

def test_un_corps_qui_change_change_l_empreinte():
    assert _empreinte(_AVEC_DOC) != _empreinte(_CORPS_CHANGE), (
        "deux corps differents rendent la meme empreinte : la preuve ne "
        "prouve rien")


def test_une_docstring_reecrite_NE_change_PAS_l_empreinte():
    """CONTRE-EPREUVE, et elle est le coeur du contrat.

    Sans elle, on hacherait le fichier entier : reformuler une phrase rendrait
    tout le corpus « suspect », le signal crierait en permanence et finirait
    desarme. Un garde qui crie a faux se fait desarmer.
    """
    assert _empreinte(_AVEC_DOC) == _empreinte(_DOC_CHANGEE), (
        "reecrire la PROSE a change l'empreinte du CODE : le signal se "
        "declencherait sur des clarifications, et deviendrait inutilisable")


def test_une_source_illisible_rend_INCONNU_jamais_une_empreinte_vide():
    f = getattr(wm, "empreinte_du_corps", None)
    assert f is not None, "`empreinte_du_corps` ABSENTE"
    assert f("def (((") is None, (
        "une source non parsable rend une empreinte : ILLISIBLE serait "
        "confondu avec un corps reel, et deux fichiers casses paraitraient "
        "identiques")


# ── LE VERDICT A TROIS ETATS ────────────────────────────────────────────

def _verdict(**kw):
    f = getattr(wm, "verdict_docstring", None)
    assert f is not None, (
        "`forge_wiki_modules.verdict_docstring` ABSENTE — le trou mesure n'est "
        "toujours pas comble")
    return f(**kw)


def test_corps_inchange_donne_ALIGNE():
    assert _verdict(doc_actuelle="A", doc_vue="A",
                    corps_actuel="h1", corps_vu="h1") == "ALIGNE"


def test_corps_change_ET_docstring_inchangee_donne_SUSPECTE():
    """LE CAS QUI COMPTE : le code a bouge, la description non."""
    assert _verdict(doc_actuelle="A", doc_vue="A",
                    corps_actuel="h2", corps_vu="h1") == "SUSPECTE"


def test_docstring_reecrite_avec_le_corps_donne_ALIGNE():
    """L'auteur a mis a jour les deux : c'est un `confirm`, pas une derive."""
    assert _verdict(doc_actuelle="B", doc_vue="A",
                    corps_actuel="h2", corps_vu="h1") == "ALIGNE"


def test_jamais_observe_donne_INCONNU_et_non_ALIGNE():
    """`INCONNU != ALIGNE` — un module jamais mesure ne se range pas du cote
    sain. C'est la liste BLANCHE : n'est sain que ce qui est PROUVE sain."""
    assert _verdict(doc_actuelle="A", doc_vue=None,
                    corps_actuel="h1", corps_vu=None) == "INCONNU"


def test_source_illisible_donne_INCONNU():
    assert _verdict(doc_actuelle="A", doc_vue="A",
                    corps_actuel=None, corps_vu="h1") == "INCONNU"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
