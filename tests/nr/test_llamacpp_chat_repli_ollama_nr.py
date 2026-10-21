"""NR 18/10 -- audit Gemini web VERIFIE (mesure du jour : :8080 accepte TCP puis timeout, /health et /v1/models muets en
2 s ; Ollama :11434 repond en 0,04 s) + decision owner : `_llamacpp_chat` (2 boucles autonomes) perdait 30 s par appel
avant de rendre "".

Contrat :
  * une sonde `/health` de :8080 a <= 1,5 s choisit la voie AVANT l'appel (on ne raccourcit pas le delai de l'appel :
    une generation legitime peut prendre plus que quelques secondes) ; son resultat est garde 60 s ;
  * :8080 muet -> repli sur Ollama :11434 (`/v1/chat/completions`), sans attendre 30 s ;
  * :8080 vivant -> comportement d'avant.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_autonomous_loops as al  # noqa: E402


class _Rep(io.BytesIO):
    status = 200


def _reponse(texte):
    return _Rep(json.dumps({"choices": [{"message": {"content": texte}}]}).encode())


def _brancher(monkeypatch, llama_vivant: bool):
    appels = []

    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        appels.append((url, timeout))
        if ":8080" in url:
            if not llama_vivant:
                raise TimeoutError("timed out")
            return _Rep(b'{"status":"ok"}') if url.endswith("/health") else _reponse("depuis 8080")
        if ":11434" in url:
            return _reponse("depuis ollama")
        raise AssertionError("url inattendue %s" % url)
    monkeypatch.setattr(al.urllib.request, "urlopen", urlopen)
    for nom in ("_LLAMA_SANTE_CACHE", "_llama_sante_cache"):
        if hasattr(al, nom):
            monkeypatch.setattr(al, nom, {})
    return appels


def test_8080_muet_repli_ollama_sans_attendre_30_s(monkeypatch):
    appels = _brancher(monkeypatch, llama_vivant=False)
    assert al._llamacpp_chat("bonjour") == "depuis ollama"
    sondes = [t for u, t in appels if ":8080" in u]
    assert sondes and all(t is not None and t <= 1.5 for t in sondes), (
        "la voie :8080 doit etre sondee a <= 1,5 s, jamais attendue 30 s : %s" % appels)


def test_8080_vivant_comportement_inchange(monkeypatch):
    appels = _brancher(monkeypatch, llama_vivant=True)
    assert al._llamacpp_chat("bonjour") == "depuis 8080"
    assert not [u for u, _ in appels if ":11434" in u]


def test_la_sante_est_gardee_60_s(monkeypatch):
    appels = _brancher(monkeypatch, llama_vivant=False)
    al._llamacpp_chat("un")
    al._llamacpp_chat("deux")
    assert len([u for u, _ in appels if u.endswith("/health")]) == 1, "la sonde de sante doit etre mise en cache"
