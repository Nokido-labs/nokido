# -*- coding: utf-8 -*-
"""NR — la reconnexion `@ssh <hote>` doit lire le vrai nom et le noyau de la cible.

La tache `_reconnect` de `handle_at_ssh` appelait `run_ssh(...)` et
`_strip_ssh_output(...)`, deux fonctions du monolithe `Nokido.py` que l'extrait
n'importait pas. Chaque appel levait NameError, rattrape en silence : le titre du
terminal affichait l'IP au lieu du nom d'hote, et le noyau n'etait jamais lu.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Le `run_ssh` du monolithe n'est que `ssh_manager.run(command, sudo, timeout)` :
le correctif appelle `ssh_manager.run` directement et importe `_strip_ssh_output`
de `forge_ssh`. Test statique : le chemin demande un vrai serveur SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_reconnexion_n_appelle_que_des_noms_lies():
    manquants = noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ssh")
    assert not ({"run_ssh", "_strip_ssh_output"} & manquants)


def test_forge_ssh_definit_toujours_le_nettoyeur():
    assert "_strip_ssh_output" not in noms_globaux_non_lies(
        "app/forge_ssh.py", "_strip_ssh_output")
