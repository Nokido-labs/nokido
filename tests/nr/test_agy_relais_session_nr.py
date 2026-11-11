# -*- coding: utf-8 -*-
"""NR owner 4/11 (« gemini_cli ne tourne pas depuis le compte des jobs ? il faudrait pourtant » ; gemini CLI = AGY CLI).
Mesure job_c21ccd6e8336 : le compte des jobs n'atteint pas %USERPROFILE% (WinError 5) ; via le hub, agy rend
« authentication failed or timed out » (OAuth lie a la session interactive) ; le relais :8770 que GeminiCLI tente en
premier n'existait plus (5 s perdues). Remede : relais dans la session owner (tools/forge_agy_relay.py, runAs
interactive) ; GeminiCLI l'attend le temps d'une vraie reponse et ne se rappelle pas lui-meme depuis le relais."""
import importlib
import io
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app"), str(RACINE / "tools")]
R = importlib.import_module("forge_agy_relay")
P = importlib.import_module("nokido_agent.app.forge_agent_proxy")


def test_relais_n_ecoute_que_la_machine():
    assert R.adresse_autorisee("127.0.0.1") and R.adresse_autorisee("::1")
    assert not R.adresse_autorisee("localhost")


def test_relais_valide_et_delegue():
    vu = []
    rep = R.traiter({"prompt": "dis OK", "system_prompt": "sys"}, lambda p, s: vu.append((p, s)) or "OK")
    assert rep == {"response": "OK"} and vu == [("dis OK", "sys")]
    assert "error" in R.traiter({"prompt": ""}, lambda p, s: "x")
    assert "error" in R.traiter({"prompt": "x" * 40000}, lambda p, s: "x")
    assert "error" in R.traiter({"prompt": "dis OK"}, lambda p, s: (_ for _ in ()).throw(RuntimeError("agy KO")))


def test_relais_rend_ce_qu_il_reveille():
    assert R.inactif(dernier=0.0, maintenant=16 * 60.0, limite_s=15 * 60.0)
    assert not R.inactif(dernier=0.0, maintenant=60.0, limite_s=15 * 60.0)


def test_geminicli_attend_le_relais_le_temps_d_une_vraie_reponse(monkeypatch):
    vu = {}

    def _urlopen(req, timeout=None):
        vu["url"], vu["timeout"] = req.full_url, timeout
        return io.BytesIO(json.dumps({"response": "OK"}).encode())
    monkeypatch.setattr(P.urllib.request, "urlopen", _urlopen) if hasattr(P, "urllib") else None
    import urllib.request as ur
    monkeypatch.setattr(ur, "urlopen", _urlopen)
    monkeypatch.delenv("LAFORGE_AGY_RELAY_INTERNE", raising=False)
    assert P.GeminiCLI._demander_relais("dis OK", None) == "OK"
    assert vu["url"].endswith(":8770/v1/ask") and vu["timeout"] >= 60, "5 s coupaient toute vraie reponse d'agy"


def test_le_relais_ne_se_rappelle_pas_lui_meme(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_RELAY_INTERNE", "1")
    assert P.GeminiCLI._demander_relais("dis OK", None) is None
