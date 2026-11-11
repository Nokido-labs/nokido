# -*- coding: utf-8 -*-
"""NR -- 9/11 : la cle Mistral Studio renvoie 402 billing_api_budget_exhausted (code 2303) sur 6 modeles (mesure
20 h 36) ; `forge_key_rotation.mark_http` ignorait 402 (aucune branche) : la cle restait SERVIE par resolve()
(job_29163b526580 : cle_servie=True apres marquage). Un 402 = budget/paiement epuise : la cle sort de la rotation
(jusqu'a un succes 200 ou une nouvelle cle), a la difference d'un 429 (quota temporaire)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_key_rotation as K  # noqa: E402


def _espion(monkeypatch):
    vus = []
    monkeypatch.setattr(K, "mark", lambda env, key, status, reason="": vus.append((status, reason)))
    return vus


def test_un_402_sort_la_cle_de_la_rotation(monkeypatch):
    vus = _espion(monkeypatch)
    K.mark_http("MISTRAL_API_KEY", "k", 402, '{"type":"billing_api_budget_exhausted","code":"2303"}')
    assert vus and vus[0][0] == "bad" and "402" in vus[0][1], vus


def test_un_429_reste_un_quota_temporaire(monkeypatch):
    vus = _espion(monkeypatch)
    K.mark_http("MISTRAL_API_KEY", "k", 429, "")
    assert vus == [("quota", "http429")], vus
