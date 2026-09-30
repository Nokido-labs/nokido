# -*- coding: utf-8 -*-
"""NR — `process_user_input` (forge_handlers) doit lier les types du routage.

Le pipeline compare l'intention NLU a `AgentType.CHAT/ACTION/RAG` et construit un
`SupervisorAnalysis` en court-circuit : deux classes de `forge_core_models`
jamais importees dans l'extrait -> NameError des la fusion NLU + superviseur.
Import depuis `forge_core_models`, le module du classifieur qui produit ces
valeurs. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_handlers.py"


def test_les_types_du_routage_sont_lies():
    assert not ({"AgentType", "SupervisorAnalysis"} & noms_globaux_non_lies(FICHIER, "process_user_input"))


def test_les_types_importes_existent():
    assert imports_introuvables(FICHIER, "process_user_input") == set()
