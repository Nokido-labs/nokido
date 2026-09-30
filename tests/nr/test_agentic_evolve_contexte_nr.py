# -*- coding: utf-8 -*-
"""NR — `forge_agentic.handle_evolve` doit lier RAG et versionnement AVANT de les lire.

La liaison `rag_engine` / `version_manager` (par `app_ctx()`) etait restee APRES
la branche `start`, et en double a la fin de `handle_agentic`, la fonction
precedente. Dans `handle_evolve`, ces deux noms sont donc des locales lues avant
affectation : `@evolve <requete>` et `@evolve bench` levaient UnboundLocalError
des `if not rag_engine`. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import lus_avant_affectation, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_agentic.py"


def test_rag_et_versionnement_lies_avant_lecture():
    assert not ({"rag_engine", "version_manager"} & lus_avant_affectation(FICHIER, "handle_evolve"))


def test_aucun_global_orphelin():
    assert noms_globaux_non_lies(FICHIER, "handle_evolve") == set()
