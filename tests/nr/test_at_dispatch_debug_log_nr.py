# -*- coding: utf-8 -*-
"""NR — `@scan` et `@ids` ne doivent pas casser sur leur propre journal de debug.

Quatre appels a `debug_log(...)` (fin de @scan, fin de @scan basique, alerte
@ids, connexion vue par l'IDS basique) visaient la fonction du monolithe, jamais
importee dans l'extrait `forge_at_dispatch`. Effets : le scan finissait sur
« ❌ Scan: name 'debug_log' is not defined » APRES avoir injecte ses resultats ;
dans l'IDS basique, l'exception sautait la mise a jour de l'etat precedent, et les
memes connexions etaient re-signalees a chaque tour. Releve par l'audit « noms
non definis » (mesures/audits/noms_non_definis.md).

Test statique : ces chemins demandent nmap/scapy et la TUI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_debug_log_est_lie_dans_tout_le_module():
    assert "debug_log" not in noms_non_lies_du_module("app/forge_at_dispatch.py")
