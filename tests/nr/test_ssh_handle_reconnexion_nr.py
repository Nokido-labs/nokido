# -*- coding: utf-8 -*-
"""NR — la reconnexion `@ssh <hote>` de forge_ssh lit le vrai nom et le noyau.

`handle_ssh` (forge_ssh) appelait `run_ssh(...)`, fonction du seul monolithe :
NameError rattrape en silence, titre du terminal laisse a l'IP et noyau jamais
lu -- le meme defaut que la copie de `forge_at_dispatch`. Le `run_ssh` du
monolithe n'est que `ssh_manager.run(...)` ; `ssh_manager` est deja lie en tete
de `handle_ssh`. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_run_ssh_n_est_plus_lu():
    assert "run_ssh" not in noms_globaux_non_lies("app/forge_ssh.py", "handle_ssh")
