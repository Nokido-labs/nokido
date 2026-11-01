# -*- coding: utf-8 -*-
"""NR — census free tier : echantillon CHAT tire du catalogue, erreurs distinguees, budget/timeout adaptes.

__FORGE_COLOR__ = "immunitaire/guard : P1_census_free_tier_echantillon_biaise_20261021"
Aucun reseau : faux /models, faux fournisseurs.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ft(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("ft_chat_nr", ROOT / "tools" / "forge_free_tier_census.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ft_chat_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def test_liste_blanche_chat_depuis_le_catalogue(monkeypatch):
    ft = _ft(monkeypatch)
    modeles = [
        {"id": "a/chat-8b", "architecture": {"modality": "text->text"}},
        {"id": "b/voix", "architecture": {"modality": "audio->text"}},
        {"id": "c/embedder", "type": "embedding"},
        {"id": "d/sans-meta-7b"},
        {"id": "e/whisper-asr"},
        {"id": "f/vision-gen", "task": "text-to-image"},
    ]
    ids = [m["id"] for m in ft.modeles_chat(modeles)]
    assert ids == ["a/chat-8b", "d/sans-meta-7b"]


def test_exclusions_non_chat():
    src = (ROOT / "tools" / "forge_free_tier_census.py").read_text(encoding="utf-8")
    for mot in ("asr", "speech", "audio", "ocr", "embed"):
        assert '"%s"' % mot in src


def test_fournisseur_sans_candidat_dit(monkeypatch, tmp_path, capsys):
    ft = _ft(monkeypatch)
    monkeypatch.setattr(ft, "SORTIE", tmp_path / "c.json")
    monkeypatch.setattr(ft, "SURFACES", [("faux", None, "https://x/v1")])
    monkeypatch.setattr(ft, "catalogue", lambda b, c: (200, [{"id": "z/asr-1b"}], {}))
    monkeypatch.setattr(sys, "argv", ["x"])
    ft.main()
    out = capsys.readouterr().out
    assert "NON SONDE" in out
    assert json.loads((tmp_path / "c.json").read_text())["fournisseurs"][0]["etat"] == "NON_SONDE"


def _http(code, corps=""):
    return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(corps.encode()))


def test_402_422_429_504_distingues(monkeypatch):
    ft = _ft(monkeypatch)
    cas = {402: "insufficient balance", 429: "rate limit", 504: "gateway timeout", 422: "unprocessable"}
    etats = {}
    for code, corps in cas.items():
        def faux(*a, _c=code, _b=corps, **k):
            raise _http(_c, _b)
        monkeypatch.setattr(ft, "_completer", faux)
        d = ft.sonder("https://x/v1", "k", "m")
        etats[code] = d["etat"]
        assert str(code) in d["motif"]
    assert etats[402] == "SANS_SOLDE" and etats[429] == "DEBIT"

    def faux_j(*a, **k):
        raise _http(429, "Rate limit reached (TPD) tokens per day")
    monkeypatch.setattr(ft, "_completer", faux_j)
    assert ft.sonder("https://x/v1", "k", "m")["etat"] == "QUOTA_EPUISE"
    assert ft._motif_http(504, "") != ft._motif_http(422, "")


def test_budget_raisonnement_256(monkeypatch):
    ft = _ft(monkeypatch)
    assert ft.budget_jetons("nvidia/nemotron-3-ultra") >= 256
    assert ft.budget_jetons("deepseek-r1") >= 256
    assert ft.budget_jetons("openai/gpt-oss-120b") >= 256
    assert ft.budget_jetons("meta/llama-3.1-8b-instruct") == 8
    vus = []

    def faux(base, cle, modele, outils, **k):
        vus.append(k.get("max_tokens"))
        return {"choices": [{"message": {"content": "ok"}}]}, {}
    monkeypatch.setattr(ft, "_completer", faux)
    ft.sonder("https://x/v1", "k", "nvidia/nemotron-3-ultra")
    assert vus and vus[0] >= 256


def test_timeout_nvidia_plus_long(monkeypatch):
    ft = _ft(monkeypatch)
    assert ft.timeout_pour("https://integrate.api.nvidia.com/v1") > ft.TIMEOUT
    assert ft.timeout_pour("https://api.groq.com/openai/v1") == ft.TIMEOUT
    vus = []

    class R:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def faux_open(req, timeout=None):
        vus.append(timeout)
        return R()
    monkeypatch.setattr(ft.urllib.request, "urlopen", faux_open)
    ft._completer("https://integrate.api.nvidia.com/v1", "k", "m", False)
    assert vus[0] > ft.TIMEOUT
