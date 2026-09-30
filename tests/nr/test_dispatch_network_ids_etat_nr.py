# -*- coding: utf-8 -*-
"""NR — `forge_dispatch_network` : l'etat de l'IDS se lit sur `app`, pas sur `self`.

`_ids_is_running(app)`, `_ids_cancel(app)` et `handle_ids(app, args)` recoivent
`app` mais lisaient/ecrivaient l'etat de l'IDS sur `self`, vestige des methodes du
monolithe : NameError a chaque appel. Aucun appelant en production aujourd'hui
(seuls des tests importent le module), mais c'est la version « reseau » du
dispatcher, ecrite pour servir. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : l'IDS demande scapy et une interface reseau.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_aucun_self_orphelin_dans_le_module():
    assert "self" not in noms_non_lies_du_module("app/forge_dispatch_network.py")
