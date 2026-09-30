# -*- coding: utf-8 -*-
"""NR — `get_remote_context` doit atteindre la fonction SSH du monolithe.

La fonction interroge l'hote distant (hostname, noyau, uptime, memoire, disque)
par `run_ssh(...)`, fonction du monolithe jamais liee dans `forge_handlers` :
NameError au premier appel. Aucun appelant aujourd'hui, mais un test garde
qu'elle reste async et exportee. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : le meme acces que `forge_prefect` (`_get_run_ssh()`). Test statique :
le chemin demande un hote SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_run_ssh_est_lie():
    assert "run_ssh" not in noms_globaux_non_lies("app/forge_handlers.py", "get_remote_context")
