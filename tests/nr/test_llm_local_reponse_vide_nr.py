# -*- coding: utf-8 -*-
"""NR -- le repli LLM local ne prend plus une reponse VIDE pour un succes (curiosite, 15/10).

Mesure : `curiosity_driver` a detecte 50 lacunes et rendu 0 theme aux trois derniers cycles (17/09, 01/10,
14/10), avec « JSONDecodeError ... line 1 column 1 (char 0) » : `forge_watch_agent._llm_local` faisait
`return` sur la reponse brute du premier fournisseur qui repondait -- une chaine VIDE comprise.
Chemin REEL : `_llm_local`, appels HTTP doubles, coffre double.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_watch_agent as wa  # noqa: E402


def _banc(monkeypatch, reponses):
    appels = []

    def _faux(url, model, key, prompt, timeout=30, max_tokens=600):
        appels.append(url.split("//")[1].split("/")[0])
        rep = reponses.get(appels[-1], "")
        if isinstance(rep, Exception):
            raise rep
        return rep

    monkeypatch.setattr(wa, "_llm_call_openai_compat", _faux)
    coffre = types.ModuleType("nokido_agent.app.forge_secrets")
    coffre.get_secret = lambda nom: "cle-factice"
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", coffre)
    monkeypatch.delenv("LAFORGE_USE_FRUGAL", raising=False)
    return appels


def test_une_reponse_vide_passe_au_fournisseur_suivant(monkeypatch, caplog):
    appels = _banc(monkeypatch, {"api.cerebras.ai": "", "api.groq.com": '{"themes": []}'})
    with caplog.at_level(logging.WARNING):
        r = wa._llm_local("prompt")
    assert r == '{"themes": []}' and appels == ["api.cerebras.ai", "api.groq.com"]
    assert any("reponse VIDE" in x.getMessage() for x in caplog.records)


def test_un_blanc_seul_est_vide_aussi(monkeypatch):
    appels = _banc(monkeypatch, {"api.cerebras.ai": "  \n", "api.groq.com": "", "api.mistral.ai": "ok"})
    assert wa._llm_local("prompt") == "ok" and appels[-1] == "api.mistral.ai"


def test_une_reponse_pleine_du_premier_suffit(monkeypatch):
    appels = _banc(monkeypatch, {"api.cerebras.ai": "plein"})
    assert wa._llm_local("prompt") == "plein" and appels == ["api.cerebras.ai"]
