# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `tools/forge_trace_replay.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`
ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs
de chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la
metrique `couverture prouvee` — le marqueur en tete sert exactement a l'en
exclure. Le remplacer par un vrai test de comportement est un progres ; le
supprimer sans le remplacer rend le module non mesurable.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    assert importlib.import_module("forge_trace_replay") is not None


# ---------------------------------------------------------------------------
# HERMETICITE DE L'IMPORT (mesure 2026-09-16)
#
# `test_le_module_se_charge` echouait en PermissionError sur
# logs/trace_replay.log, et j'ai d'abord classe ca « defaut d'environnement ».
# C'etait une facon de ranger un symptome sans le comprendre. MESURE :
#   - lecture du fichier OK, ecriture REFUSEE sous LaForgeSbxOffline ET
#     LaForgeSbxOnline (deux comptes distincts) ;
#   - le module n'importe PAS forge_trace_spine : l'edition du jour est hors
#     de cause, et c'est prouve, pas suppose ;
#   - la cause est dans le module : `logging.basicConfig(handlers=[
#     RotatingFileHandler(...)])` s'execute AU NIVEAU MODULE, donc a l'import.
#
# Un import doit definir des capacites, pas produire d'effet de bord exigeant
# une ACL. Sinon le test d'un module mesure le COMPTE qui l'execute, et un
# defaut reel reste invisible tant que la CI ne l'exerce pas sous contrainte.
#
# Ces tests sont STRUCTURELS (AST) : ils valent quel que soit le compte, la ou
# un test d'ecriture reelle rendrait vert ou rouge selon qui le lance.
# ---------------------------------------------------------------------------

_EFFETS_INTERDITS = ("basicConfig", "RotatingFileHandler", "FileHandler")


def _module_ast():
    import ast
    chemin = ROOT / "tools" / "forge_trace_replay.py"
    return ast.parse(chemin.read_text(encoding="utf-8")), ast


def test_aucun_journal_n_est_OUVERT_a_l_import():
    arbre, ast = _module_ast()
    fautifs = []
    for noeud in arbre.body:                      # NIVEAU MODULE uniquement
        # Une DEFINITION n'est pas une EXECUTION : `configurer_journal` est
        # declaree au niveau module, mais son corps ne s'execute qu'a l'appel.
        # Sans cette exclusion, le test condamnait le correctif lui-meme --
        # troisieme instrument faux de la journee.
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for n in ast.walk(noeud):
            if isinstance(n, ast.Call):
                nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if nom in _EFFETS_INTERDITS:
                    fautifs.append("%s ligne %d" % (nom, getattr(n, "lineno", 0)))
    assert not fautifs, (
        "le module ouvre son journal a l'IMPORT (%s) : il devient inimportable "
        "par tout compte sans droit d'ecriture sur logs/, et son propre test "
        "mesure alors les ACL et non le code" % ", ".join(fautifs)
    )


def test_la_configuration_du_journal_est_un_appel_EXPLICITE():
    arbre, ast = _module_ast()
    fonctions = {n.name for n in arbre.body if isinstance(n, ast.FunctionDef)}
    assert "configurer_journal" in fonctions, (
        "retirer la configuration de l'import ne suffit pas : il faut un point "
        "d'entree qui la fasse, sinon le module perd son journal en silence"
    )


def test_la_docstring_du_module_est_en_TETE():
    m = importlib.import_module("forge_trace_replay")
    assert m.__doc__, (
        "un import place avant la docstring la transforme en chaine inerte : "
        "`__doc__` vaut None et toute lecture par docstring est aveugle"
    )
