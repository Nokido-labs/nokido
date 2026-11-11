# -*- coding: utf-8 -*-
"""NR — /llm_dashboard / /providers : acces SSH consultable par WEBHUB (ring 2) et repli gracieux.

Contexte mesure le 2026-10-13 :
La route `/llm_dashboard` redirige vers `/llm-dashboard` qui redirige vers `/providers`.
Sur `/providers`, `chargerAcces()` appelle `GET /api/providers/acces`.
Le webhub (ring 2) relaie vers `GET /api/access` du hub.
Avant correctif :
  - `api_list_access` exigeait ring <= 1, rejetant WEBHUB (ring 2) avec HTTP 403.
  - `api_etat_acces` renvoyait le 403 brut au navigateur.
  - La campagne UI relevait l'erreur API 403 et marquait `/llm_dashboard` comme DEGRADE.

Ce test verifie :
  1. `api_list_access` autorise la lecture d'etat d'acces pour ring <= 2 (WEBHUB),
     mais refuse toujours ring > 2 (ring 3, ring 4).
  2. Les mutations (`api_set_access`, `api_delete_access`) exigent TOUJOURS ring <= 1.
  3. `api_etat_acces` dans provider_views degrade gracieusement en HTTP 200 (ok=False)
     sur upstream 403/502/503/504 pour eviter une erreur API console bloquante.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

pytest.importorskip("starlette")
pytest.importorskip("fastapi")

import forge_provider_admin as PA
from app.web_hub import provider_views as PV


class _Requete:
    def __init__(self, headers=None, ring=None, path_params=None):
        self.headers = dict(headers or {})
        self.path_params = dict(path_params or {})
        if ring is not None:
            self.state = type("Etat", (), {"ring": ring})()


def _statut_et_json(coro):
    resp = asyncio.run(coro)
    import json
    return resp.status_code, json.loads(resp.body.decode("utf-8"))


def test_api_list_access_autorise_ring_2_et_refuse_ring_superieur(monkeypatch):
    """MORSURE — ring 2 (WEBHUB) doit pouvoir lire l'etat des acces (qui ne contient aucun secret)."""
    # Fake etat_des_acces pour eviter de dependre de l'etat reel du coffre
    monkeypatch.setattr(PA, "etat_des_acces", lambda: [{"cle": "SSH_HOST", "source": "coffre"}])

    req_ring1 = _Requete(ring=1)
    req_ring2 = _Requete(ring=2)
    req_ring3 = _Requete(ring=3)
    req_ring4 = _Requete(ring=4)

    # Ring 1 et Ring 2 doivent passer (200)
    code1, corps1 = _statut_et_json(PA.api_list_access(req_ring1))
    assert code1 == 200, f"Ring 1 rejete avec {code1}"
    assert corps1.get("ok") is True

    code2, corps2 = _statut_et_json(PA.api_list_access(req_ring2))
    assert code2 == 200, f"Ring 2 (WEBHUB) rejete avec {code2} : bloque /providers et /llm_dashboard"
    assert corps2.get("ok") is True

    # Ring > 2 doit etre refuse (403)
    code3, _ = _statut_et_json(PA.api_list_access(req_ring3))
    assert code3 == 403, f"Ring 3 accepte a tort avec {code3}"

    code4, _ = _statut_et_json(PA.api_list_access(req_ring4))
    assert code4 == 403, f"Ring 4 accepte a tort avec {code4}"


def test_mutations_acces_restent_strictement_ring_1():
    """L'ecriture et suppression d'acces SSH restent strictement restreintes a ring <= 1."""
    req_ring2 = _Requete(ring=2, path_params={"cle": "SSH_HOST"})
    req_ring2.json = lambda: asyncio.sleep(0, result={"valeur": "localhost"})

    code_set, _ = _statut_et_json(PA.api_set_access(req_ring2))
    assert code_set == 403, f"api_set_access autorise ring 2 ({code_set}) : doit exiger ring <= 1"

    code_del, _ = _statut_et_json(PA.api_delete_access(req_ring2))
    assert code_del == 403, f"api_delete_access autorise ring 2 ({code_del}) : doit exiger ring <= 1"


def test_webhub_api_etat_acces_repli_gracieux(monkeypatch):
    """MORSURE — si le hub repond 403 ou 50x, api_etat_acces doit degrader en 200 avec ok=False."""
    # Simuler hub renvoyant 403
    async def _hub_403(*args, **kwargs):
        return 403, {"error": "ring <= 2 required"}

    monkeypatch.setattr(PV, "_vers_hub", _hub_403)
    code, corps = _statut_et_json(PV.api_etat_acces())
    assert code == 200, f"api_etat_acces renvoie code HTTP {code} au lieu de 200 gracieux sur 403"
    assert corps.get("ok") is False
    assert "error" in corps

    # Simuler hub renvoyant 200
    async def _hub_200(*args, **kwargs):
        return 200, {"ok": True, "acces": [{"cle": "SSH_HOST"}]}

    monkeypatch.setattr(PV, "_vers_hub", _hub_200)
    code_ok, corps_ok = _statut_et_json(PV.api_etat_acces())
    assert code_ok == 200
    assert corps_ok.get("ok") is True
    assert len(corps_ok.get("acces", [])) == 1
