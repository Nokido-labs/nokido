#!/usr/bin/env python3
"""NR — la fonction qui empeche les certificats ANONYMES en produisait un.

DEFAUT MESURE le 2026-09-10. `ci_local._sha_courant()` appelait `_sp.run(...)` —
un alias de `subprocess` importe dans une AUTRE fonction (ligne ~3120). Resultat a
CHAQUE appel :

    NameError: name '_sp' is not defined
    -> avale par l'`except Exception`
    -> `[temoin] sha indetermine (NameError)`
    -> UI_ACCEPTANCE_WITNESS avec `tested_sha: null`

Autrement dit : la fonction ecrite la veille (commit d22fcc676) POUR garantir
qu'un temoin porte le SHA qu'il certifie rendait `None` en silence. Le garde
anti-anonymat etait lui-meme anonyme.

DEUX LECONS, et la seconde est la plus large :

1. Un import dans une fonction n'existe PAS dans les autres. Un import n'est pas
   un contrat entre fonctions — exactement comme `sys.path.insert` place dans une
   fonction n'amorce rien pour les autres (meme journee, meme motif, deux
   endroits differents du meme fichier).

2. Un `except Exception` qui journalise sans echouer transforme un defaut de CODE
   en etat « indetermine » plausible. Le message etait meme rassurant : « le
   temoin le dira ». Il ne disait rien d'autre que l'absence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.47)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

ci = pytest.importorskip("ci_local")


def test_le_sha_courant_n_est_pas_none_dans_un_depot_git():
    """Le depot EST un depot git : la fonction doit rendre un sha, pas None.

    C'est la contre-epreuve directe du defaut : `None` etait le symptome, et il
    passait pour une reponse legitime.
    """
    sha = ci._sha_courant(env={})       # env vide -> force le chemin `git rev-parse`
    assert sha, "sha None dans un depot git : la fonction est cassee, pas le depot"
    assert len(sha) >= 7
    assert all(c in "0123456789abcdef" for c in sha.lower()), sha


def test_le_sha_de_la_ci_prime_sur_le_depot():
    """`GITHUB_SHA` designe le commit que le workflow a CHECKOUT ; il fait
    autorite sur ce que `git rev-parse` rend dans le repertoire courant."""
    faux = "0" * 40
    assert ci._sha_courant(env={"GITHUB_SHA": faux}) == faux


def test_un_environnement_vide_ne_rend_pas_le_sha_de_la_ci():
    """Symetrie : sans `GITHUB_SHA`, on retombe sur le depot, pas sur une valeur
    heritee d'un autre run."""
    sha = ci._sha_courant(env={"GITHUB_SHA": "   "})
    assert sha and sha != "   "


def test_la_fonction_n_utilise_aucun_alias_importe_ailleurs():
    """GARDE DE FOND. Toute reference a un nom importe dans une AUTRE fonction
    rejouerait le defaut. On verifie la source, parce qu'un `except` masque
    l'erreur a l'execution — c'est precisement ce qui l'a rendu invisible."""
    import ast
    import inspect
    src = inspect.getsource(ci._sha_courant)
    arbre = ast.parse(src.lstrip())
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    interdits = {"_sp"}          # alias connu pour vivre dans une autre fonction
    assert not (noms & interdits), (
        f"reference a un alias importe ailleurs : {noms & interdits}"
    )
