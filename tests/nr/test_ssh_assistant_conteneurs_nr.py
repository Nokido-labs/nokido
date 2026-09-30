# -*- coding: utf-8 -*-
"""NR — l'assistant de configuration SSH (TUI) doit pouvoir se composer.

`SSHWizardScreen.compose` dispose ses champs dans des `Vertical` / `Horizontal`
(conteneurs Textual) que `forge_ssh` n'importait pas : NameError a l'ouverture
de l'assistant, avant tout affichage. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : import dans le meme bloc `try` que les autres imports Textual.
Test statique : l'ecran demande une application Textual.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_les_conteneurs_sont_lies():
    assert not ({"Vertical", "Horizontal"} & noms_globaux_non_lies("app/forge_ssh.py", "SSHWizardScreen.compose"))
