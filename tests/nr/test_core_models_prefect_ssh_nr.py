# -*- coding: utf-8 -*-
"""NR — `PrefectManager.run_ssh_command` doit atteindre la fonction SSH du monolithe.

La TUI instancie `forge_core_models.PrefectManager` (Nokido.py:1416) : @run
confirme, @ci lint/test/diff/env, @workflow et le reboot passent tous par
`run_ssh_command`, qui appelait `run_ssh(...)` -- fonction du monolithe jamais
liee dans `forge_core_models`. NameError a chaque commande distante, affiche
« name 'run_ssh' is not defined » ; dans les taches qui ne rattrapent que
RuntimeError, la tache mourait sans rien afficher. Releve par l'audit « noms non
definis » (mesures/audits/noms_non_definis.md).

Correctif : le meme acces que le jumeau `forge_prefect.PrefectManager`
(`_get_run_ssh()`, et RuntimeError explicite si le monolithe n'est pas charge).
Test statique : le chemin demande un hote SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_core_models.py"


def test_run_ssh_est_lie():
    assert "run_ssh" not in noms_globaux_non_lies(FICHIER, "PrefectManager.run_ssh_command")


def test_l_accesseur_importe_existe():
    assert imports_introuvables(FICHIER, "PrefectManager.run_ssh_command") == set()
