# -*- coding: utf-8 -*-
"""NR — `@ssh <hote> <user> <port> <cle>` doit accepter le chemin de cle.

`handle_at_ssh` construisait `Path(_ssh_parts[3])` sans que le module importe
`Path` : des qu'on donnait le 4e argument (chemin de cle privee), NameError --
hors de tout `try`, l'erreur remontait au dispatcher de la TUI. Releve par l'audit
« noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : le chemin demande la TUI et un gestionnaire SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_path_est_lie_dans_handle_at_ssh():
    assert "Path" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ssh")
