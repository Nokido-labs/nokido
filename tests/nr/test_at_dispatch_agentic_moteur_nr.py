# -*- coding: utf-8 -*-
"""NR — `@agentic` doit trouver le moteur agentique avant de s'en servir.

`handle_at_agentic` lisait `agentic_engine` (status, reset, verify, et la tache
d'analyse de `@agentic <tache>`) comme un global, alors que seul le monolithe le
definit : NameError sur toutes les sous-commandes, hors de tout `try`, jusqu'au
dispatcher de la TUI. Seule la closure `_reverify` le lisait correctement, par
`app_ctx().agentic_engine`. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `agentic_engine = get_agentic()` en tete (meme source que
`app_ctx().agentic_engine`). Test statique : le moteur demande la TUI et le RAG.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_moteur_agentique_est_lie():
    assert "agentic_engine" not in noms_globaux_non_lies(
        "app/forge_at_dispatch.py", "handle_at_agentic")
