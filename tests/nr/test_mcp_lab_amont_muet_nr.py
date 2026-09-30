"""NR — une dependance amont injoignable rend 503, pas 502.

Mesure 2026-09-06 : la CI locale a rougi sur
`test_ui_pages_rendent_nr::test_aucune_page_ne_rend_une_erreur_serveur` avec
`{'/mcp_lab/api/tools': 502}` — pendant une coupure PASSAGERE du hub, constatee au meme
instant (mes propres appels MCP echouaient, `/health` repondait encore). La page etait
saine : c'est son amont qui se taisait. Le gate a donc lu « defaut du portail » la ou il
fallait lire « amont muet ».

Le corps sait deja faire cette distinction (un service on-demand eteint rend 503, une
reponse legitime). Ce test la verrouille pour le portail :
  1. hub injoignable (erreur de connexion / expiration) -> **503** ;
  2. hub qui repond MAL (autre exception) -> **502**, une vraie panne de passerelle ;
  3. hub qui repond -> 200.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools", "app/web_hub"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import mcp_lab  # noqa: E402


def _appel(monkeypatch, boum):
    async def _faux():
        if boum is not None:
            raise boum
        return {"result": {"tools": [{"name": "run"}]}}

    monkeypatch.setattr(mcp_lab, "_list_tools_streamable_http", _faux)
    return asyncio.run(mcp_lab.list_tools())


@pytest.mark.parametrize("erreur", [
    httpx.ConnectError("connexion refusee"),
    httpx.ConnectTimeout("delai depasse"),
    httpx.ReadTimeout("lecture expiree"),
    ConnectionError("reset"),
    TimeoutError("expire"),
])
def test_un_hub_injoignable_rend_503_et_le_dit(monkeypatch, erreur):
    with pytest.raises(HTTPException) as e:
        _appel(monkeypatch, erreur)
    assert e.value.status_code == 503, e.value.status_code
    assert "injoignable" in str(e.value.detail)


def test_un_hub_qui_repond_mal_reste_un_502(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _appel(monkeypatch, ValueError("json casse"))
    assert e.value.status_code == 502, e.value.status_code


def test_le_chemin_nominal_rend_les_outils(monkeypatch):
    out = _appel(monkeypatch, None)
    assert out["ok"] is True and out["data"]["result"]["tools"][0]["name"] == "run"
