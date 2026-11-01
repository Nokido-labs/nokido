"""NR : le runner BFCL appelle un modele Groq SERVI (mesure 26/10 : llama-3.3-70b-versatile -> HTTP 404).

Sonde du 26/10 : 3/3 « HTTP Error 404: Not Found » en 0,1 s -- modele retire. Le hub sert openai/gpt-oss-120b sur
Groq (offre gratuite, repond « OK » en 285 ms le meme jour), comme le runner HumanEval. Surchargeable par
LAFORGE_BFCL_GROQ_MODEL.
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bfcl_runner as fr  # noqa: E402


def _capture(monkeypatch):
    vus = []
    monkeypatch.setattr(fr, "_read_env", lambda nom, defaut=None: "cle-factice" if nom == "GROQ_API_KEY" else defaut)
    monkeypatch.setattr(fr, "_http_post", lambda url, body, headers=None, timeout=30: (
        vus.append(body) or {"choices": [{"message": {"content": "ok"}}]}))
    return vus


def test_groq_n_appelle_plus_le_modele_retire(monkeypatch):
    monkeypatch.delenv("LAFORGE_BFCL_GROQ_MODEL", raising=False)
    vus = _capture(monkeypatch)
    assert fr.call_llm("p", "groq") == "ok"
    assert vus[0]["model"] == "openai/gpt-oss-120b"


def test_un_429_groq_est_reessaye(monkeypatch):
    """26/10 : 28/50 cas perdus en 429 (limite par minute) faute de reessai sur Groq."""
    import urllib.error

    monkeypatch.setattr(fr, "_read_env", lambda nom, defaut=None: "cle-factice" if nom == "GROQ_API_KEY" else defaut)
    monkeypatch.setattr(fr.time, "sleep", lambda s: None)
    appels = []

    def post(url, body, headers=None, timeout=30):
        appels.append(1)
        if len(appels) == 1:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(fr, "_http_post", post)
    assert fr.call_llm("p", "groq") == "ok" and len(appels) == 2


def test_cerebras_appelle_le_modele_que_sert_le_hub(monkeypatch):
    """26/10 : llama3.1-70b -> 404 (retire) ; le hub sert gpt-oss-120b sur Cerebras (compte refuse SANS_SOLDE ce
    jour-la : le nom juste fait dire la vraie cause au lieu d'un 404 trompeur)."""
    vus = []
    monkeypatch.setattr(fr, "_read_env", lambda nom, defaut=None: "cle-factice" if nom == "CEREBRAS_API_KEY" else defaut)
    monkeypatch.setattr(fr, "_http_post", lambda url, body, headers=None, timeout=30: (
        vus.append(body) or {"choices": [{"message": {"content": "ok"}}]}))
    monkeypatch.delenv("LAFORGE_BFCL_CEREBRAS_MODEL", raising=False)
    fr.call_llm("p", "cerebras")
    assert vus[0]["model"] == "gpt-oss-120b"


def test_modele_groq_surchargeable(monkeypatch):
    monkeypatch.setenv("LAFORGE_BFCL_GROQ_MODEL", "autre/modele")
    vus = _capture(monkeypatch)
    fr.call_llm("p", "groq")
    assert vus[0]["model"] == "autre/modele"
