"""NR -- une hormone jetee faute de place chez un abonne est COMPTEE et exposee, plus jamais `except: pass` (13/10).

Fiche de veille v8 (AGC Luminary099) : l'Executive ne jetait jamais un travail sans lever une alarme nommee (1201/1202).
`_push_to_subscribers` faisait `except Exception: pass` sur une file pleine -- le recepteur ne recevait pas, et
personne ne pouvait le savoir.
"""
from __future__ import annotations

import asyncio

import nokido_agent.app.forge_hormones as H


def test_une_file_pleine_compte_l_evenement_jete(monkeypatch):
    q = asyncio.Queue(maxsize=1)
    monkeypatch.setattr(H, "_SUBSCRIBERS", [q])
    monkeypatch.setattr(H, "_JETES", {"file_pleine": 0, "autre": 0})
    H._push_to_subscribers({"hormone": "test", "payload": {}})
    H._push_to_subscribers({"hormone": "test", "payload": {}})
    assert q.qsize() == 1
    assert H._JETES["file_pleine"] == 1


def test_le_compteur_est_expose_dans_l_etat_du_systeme(monkeypatch):
    monkeypatch.setattr(H, "_JETES", {"file_pleine": 3, "autre": 1})
    assert H.system_state()["evenements_jetes"] == {"file_pleine": 3, "autre": 1}
