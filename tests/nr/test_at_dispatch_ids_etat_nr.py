# -*- coding: utf-8 -*-
"""NR — `@ids start/stop/status` doivent lire l'etat de l'IDS sur `app`.

`handle_at_ids` est un extrait de methode du monolithe : il recoit `app`, mais
huit lectures d'etat etaient restees en `getattr(self, "_ids_task" ...)`. `self`
n'existe pas dans cette fonction : NameError au demarrage (verification « deja
actif ? »), a l'arret et au statut, dans les deux modes (scapy et basique). Le
handler ECRIT pourtant deja cet etat sur `app` (`app._ids_task = ...`). Releve
par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Test statique : l'IDS demande scapy/pyshark et une interface reseau.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_l_ids_ne_lit_plus_self():
    assert "self" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ids")
