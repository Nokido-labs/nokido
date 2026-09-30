# -*- coding: utf-8 -*-
"""NR — `forge_mixin_ai` doit lier `AgentType` et `AGENT_META` qu'il utilise.

Le mixin compare `self.current_agent` a `AgentType.CHAT/ACTION/RAG` (bascule
d'agent, choix du modele) et lit `AGENT_META[...]` pour l'icone : deux noms que
seul le monolithe definit (AgentType de `forge_core_models`, le meme que la TUI ;
AGENT_META expose par `forge_mixin_ui`). NameError sur chaque bascule d'agent.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_le_mixin_lie_ses_noms():
    assert not ({"AgentType", "AGENT_META"} & noms_non_lies_du_module("app/forge_mixin_ai.py"))
