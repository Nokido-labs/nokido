# -*- coding: utf-8 -*-
"""NR — apres l'audit, le focus doit revenir au champ de saisie du chat.

`PatchMixin._handle_audit` redonne le focus au chat (pour que « t », « v » ou un
numero ne partent pas dans le terminal) par
`query_one("#chat-input", AutocompleteInput)` -- classe du seul monolithe :
NameError avale, focus jamais rendu, et les touches de choix partaient au
terminal. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `_lazy("AutocompleteInput")`, l'accesseur au monolithe deja defini
dans le module.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_classe_du_champ_de_saisie_est_liee():
    assert "AutocompleteInput" not in noms_globaux_non_lies(
        "app/forge_mixin_patch.py", "PatchMixin._handle_audit")
