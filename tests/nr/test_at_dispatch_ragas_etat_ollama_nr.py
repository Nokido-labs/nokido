# -*- coding: utf-8 -*-
"""NR — `@ragas <question>` doit lire l'etat d'Ollama sur `app`.

`handle_at_ragas` recoit `app`, mais le test « Ollama disponible ? » etait reste
en `getattr(self, "model_chat" ...)`, vestige de la methode du monolithe. `self`
n'existe pas ici : NameError apres la recherche RAG, avant toute generation --
l'evaluation RAGAS n'aboutissait jamais. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : l'evaluation demande Ollama et le RAG.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_ragas_ne_lit_plus_self():
    assert "self" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ragas")
