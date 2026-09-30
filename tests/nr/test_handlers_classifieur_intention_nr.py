# -*- coding: utf-8 -*-
"""NR — `process_user_input` (forge_handlers) doit lier son classifieur d'intention.

L'etape 1 du pipeline appelle `intent_classifier.classify_hybrid(...)`, global du
monolithe (Nokido.py:1737) jamais lie dans l'extrait : NameError a la premiere
etape de routage. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md). Ce chemin reste casse en amont et en aval
(interface avec l'appelant, implementation `_execute_routing_plan` perdue) :
voir le rapport.

Correctif : `_g("intent_classifier")`, l'accesseur deja importe par le module.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_classifieur_est_lie():
    assert "intent_classifier" not in noms_globaux_non_lies("app/forge_handlers.py", "process_user_input")
