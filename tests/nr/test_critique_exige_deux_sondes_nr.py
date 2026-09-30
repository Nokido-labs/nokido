"""NR -- un service CRITIQUE n'est pas declare DOWN sur une sonde unique.

MESURE 2026-09-25 15:56:37 : le diagnostic ecrit « ❌ Services CRITIQUES DOWN : ['web_hub'] »
(-15 points) sur UNE sonde HTTP de 2 s, prise pendant le rechargement du superviseur -- et le MEME
rapport range NokidoWebHub en « sain » dans sa fusion de capteurs. Quelques minutes plus tard :7400
repondait 200. Constitution : une sonde unique ne decide pas. Un service critique qui echoue se
RE-SONDE une fois (delai, timeout plus long) avant d'etre declare tombe ; un rattrapage se dit.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_health_diagnostic as hd  # noqa: E402


class _Rep:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(echecs_par_port: dict):
    vus: dict = {}

    def urlopen(req, timeout=None):
        url = req.full_url
        port = url.split(":")[2].split("/")[0]
        vus[port] = vus.get(port, 0) + 1
        if vus[port] <= echecs_par_port.get(port, 0):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refuse"))
        return _Rep()
    return urlopen, vus


def test_un_critique_qui_se_rattrape_n_est_pas_down_et_le_rattrapage_se_dit(monkeypatch):
    monkeypatch.setattr(hd, "_RESONDE_DELAI_S", 0)
    urlopen, vus = _urlopen({"7400": 1})
    monkeypatch.setattr(hd.urllib.request, "urlopen", urlopen)
    r = hd.audit_services_http()
    assert r["web_hub"]["up"] is True
    assert r["web_hub"]["premiere_sonde"].startswith("URLError")
    assert vus["7400"] == 2


def test_un_critique_tombe_aux_deux_sondes_est_down_confirme(monkeypatch):
    monkeypatch.setattr(hd, "_RESONDE_DELAI_S", 0)
    urlopen, vus = _urlopen({"7400": 9})
    monkeypatch.setattr(hd.urllib.request, "urlopen", urlopen)
    r = hd.audit_services_http()
    assert r["web_hub"]["up"] is False and r["web_hub"]["sondes"] == 2
    assert vus["7400"] == 2


def test_un_non_critique_n_est_pas_re_sonde(monkeypatch):
    """Le cout reste borne : seuls les critiques (penalite -15) paient une seconde sonde."""
    monkeypatch.setattr(hd, "_RESONDE_DELAI_S", 0)
    urlopen, vus = _urlopen({"7420": 9})
    monkeypatch.setattr(hd.urllib.request, "urlopen", urlopen)
    r = hd.audit_services_http()
    assert r["graph_explorer"]["up"] is False
    assert vus["7420"] == 1
