# -*- coding: utf-8 -*-
"""NR — `@loop start/stop/status` de la TUI ne doivent pas lire `self`.

La TUI route `@loop` vers `forge_hub_handlers.handle_loop` (Nokido.py:4323).
Cette fonction recoit `app`, mais trois tests « un loop tourne-t-il deja ? »
etaient restes en `hasattr(self, "_loop_task")`, vestige de la methode du
monolithe : NameError immediat sur `start`, `stop` et `status`. La boucle
d'amelioration etait donc inaccessible depuis la TUI. Releve par l'audit « noms
non definis » (mesures/audits/noms_non_definis.md).

Test statique : le chemin demande la TUI, Ollama et un gestionnaire de versions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_handle_loop_ne_lit_plus_self():
    assert "self" not in noms_globaux_non_lies("app/forge_hub_handlers.py", "handle_loop")
