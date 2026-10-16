# -*- coding: utf-8 -*-
"""NR -- un refus de SOLDE ou de PALIER bascule la meme famille chez un fournisseur mesure joignable (15/10).

Owner 15/10 : « des LLM peuvent etre injoignables par un provider et joignables par un autre » -> matrice
modele x fournisseur (tools/forge_provider_catalogue.py --matrice), consultee par `forge_agent_proxy.ask`.
Chemin REEL : `ask()` du proxy, avec de faux emplacements (aucun appel reseau) et une matrice temporaire.
  1. 429 code 1113 (sans solde) chez zAI -> meme famille chez OpenRouter, reponse OK, bascule DITE ;
  2. un 429 de DEBIT ne bascule pas (ce n'est pas un refus du couple) ;
  3. un appel deja issu d'une bascule ne rebascule pas (pas de boucle).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.tools import forge_provider_catalogue as cat  # noqa: E402


class _Faux(ap.Provider):
    api_key_env = ""
    cost_tier = 0

    def __init__(self, name, model, comportement):
        self.name, self.model, self.display_name = name, model, name
        self._c = comportement
        self.appels = []

    def is_available(self):
        return True

    async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout):
        return await self.ask_tracked(message, thread_messages, system_prompt, max_tokens, timeout)

    async def ask_tracked(self, message, thread_messages, system_prompt, max_tokens, timeout):
        self.appels.append(self.model)
        if isinstance(self._c, Exception):
            raise self._c
        return self._c


@pytest.fixture
def banc(tmp_path, monkeypatch):
    monkeypatch.setattr(cat, "MATRICE", tmp_path / "matrice.json")
    cat.MATRICE.write_text(json.dumps({"mesure_le": time.strftime("%Y-%m-%dT%H:%M:%S"), "familles": {"glm-5": [
        {"fournisseur": "zai", "modele": "glm-5", "etat": "SANS_SOLDE", "latence_ms": 300},
        {"fournisseur": "openrouter", "modele": "z-ai/glm-5", "etat": "JOIGNABLE", "latence_ms": 900}]}}),
        encoding="utf-8")
    zai = _Faux("zai_glm5_2", "glm-5", RuntimeError(
        "Error code: 429 - {'error': {'code': '1113', 'message': 'Insufficient balance or no resource package.'}}"))
    orf = _Faux("openrouter_free", "openrouter/free", "OK")
    monkeypatch.setitem(ap._PROVIDERS, "zai_glm5_2", zai)
    monkeypatch.setitem(ap._PROVIDERS, "openrouter_free", orf)
    monkeypatch.setattr(ap, "_journaliser_echec_fournisseur", lambda *a, **k: None)
    monkeypatch.setattr(ap, "_emit", lambda *a, **k: None)
    return zai, orf


def test_sans_solde_bascule_vers_un_fournisseur_joignable(banc):
    zai, orf = banc
    r = asyncio.run(ap.ask("zai_glm5_2", "dis OK", rag_context=False, raw=True))
    assert r["ok"] and r["text"] == "OK" and orf.appels == ["z-ai/glm-5"], r
    b = r["bascule"]
    assert (b["de"], b["vers"], b["modele"], b["refus"]) == ("zai_glm5_2", "openrouter_free", "z-ai/glm-5", "SANS_SOLDE")


def test_un_debit_ne_bascule_pas(banc):
    zai, orf = banc
    zai._c = RuntimeError("Error code: 429 - {'message': 'Rate limit exceeded', 'code': '1300'}")
    r = asyncio.run(ap.ask("zai_glm5_2", "dis OK", rag_context=False, raw=True))
    assert not r["ok"] and "bascule" not in r and orf.appels == []


def test_pas_de_rebascule(banc):
    zai, orf = banc
    r = asyncio.run(ap.ask("zai_glm5_2", "dis OK", rag_context=False, raw=True, _bascule=False))
    assert not r["ok"] and orf.appels == []
