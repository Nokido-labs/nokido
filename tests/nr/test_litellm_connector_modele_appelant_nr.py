# -*- coding: utf-8 -*-
"""NR — Le modèle Gemini dans forge_litellm_connector dépend de l'appelant et non d'un GEMINI_MODEL global figé.

Décision owner du 15/10/2026 :
- La voie clé API directe (Mode A) passe par le palier gratuit où seule la famille flash-lite répond.
- Le modèle par défaut pour cette voie doit être de la famille flash-lite (ex: gemini/gemini-2.5-flash-lite).
- L'appelant peut spécifier un modèle qui prime sur le défaut.
- Un GEMINI_MODEL global (ex: gemini-2.5-pro dans Nokido.env) ne doit plus s'imposer à l'appelant.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_litellm_connector as C


def test_defaut_cle_api_est_flash_lite():
    """Le modèle par défaut pour la voie clé API est flash-lite."""
    assert "flash-lite" in C.DEFAULT_GEMINI_API_MODEL, (
        f"DEFAULT_GEMINI_API_MODEL doit être de la famille flash-lite, reçu: {C.DEFAULT_GEMINI_API_MODEL}"
    )


@pytest.mark.asyncio
async def test_complete_utilise_flash_lite_par_defaut_meme_si_env_pro(monkeypatch):
    """En Mode A (sans proxy), sans modèle passé par l'appelant, le modèle est flash-lite même si _ENV porte pro."""
    # Désactiver proxy local pour forcer Mode A
    monkeypatch.setattr(C, "LITELLM_USE_PROXY", False)
    monkeypatch.setattr(C, "_cle_gemini", lambda: "fake-api-key")
    monkeypatch.setattr(C, "_ENV", dict(C._ENV, GEMINI_MODEL="gemini/gemini-2.5-pro"))

    captured_models = []

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Réponse mockée"
    mock_resp.choices = [mock_choice]

    mock_litellm = MagicMock()
    def fake_completion(**kwargs):
        captured_models.append(kwargs.get("model"))
        return mock_resp

    mock_litellm.completion.side_effect = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", mock_litellm)

    res = await C.complete([{"role": "user", "content": "bonjour"}])
    assert res == "Réponse mockée"
    assert len(captured_models) == 1
    assert "flash-lite" in captured_models[0], (
        f"Le modèle appelé doit être de la famille flash-lite, reçu: {captured_models[0]}"
    )


@pytest.mark.asyncio
async def test_complete_respecte_modele_appelant(monkeypatch):
    """En Mode A, si l'appelant fournit son modèle, celui-ci est utilisé directement."""
    monkeypatch.setattr(C, "LITELLM_USE_PROXY", False)
    monkeypatch.setattr(C, "_cle_gemini", lambda: "fake-api-key")

    captured_models = []

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Réponse OK"
    mock_resp.choices = [mock_choice]

    mock_litellm = MagicMock()
    def fake_completion(**kwargs):
        captured_models.append(kwargs.get("model"))
        return mock_resp

    mock_litellm.completion.side_effect = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", mock_litellm)

    res = await C.complete([{"role": "user", "content": "test"}], model="gemini-3.1-pro-preview")
    assert res == "Réponse OK"
    assert captured_models == ["gemini/gemini-3.1-pro-preview"]


@pytest.mark.asyncio
async def test_propose_via_connector_transmet_modele(monkeypatch):
    """propose_via_connector transmet le paramètre model à complete()."""
    captured_kwargs = []

    async def fake_complete(messages, model=None, max_tokens=800, timeout=60.0):
        captured_kwargs.append(model)
        return "prop OK"

    monkeypatch.setattr(C, "complete", fake_complete)

    res = await C.propose_via_connector("tache", model="custom-appelant-model")
    assert res == "prop OK"
    assert captured_kwargs == ["custom-appelant-model"]
