# -*- coding: utf-8 -*-
"""NR — toute commande `@ids` commencait par un NameError.

`handle_at_ids` teste `if HAS_IDS:` des sa premiere instruction utile, mais
`HAS_IDS` n'est defini que LOCALEMENT dans `handle_at_scan` (et dans le
monolithe) : `@ids start`, `@ids stop`, `@ids status`, l'aide meme -- tout levait
NameError, hors de tout `try`, jusqu'au dispatcher de la TUI. Releve par l'audit
« noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : le meme calcul que `handle_at_scan`. Test statique : l'IDS demande
scapy/pyshark et une interface reseau.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_disponibilite_de_l_ids_est_liee():
    assert "HAS_IDS" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ids")
