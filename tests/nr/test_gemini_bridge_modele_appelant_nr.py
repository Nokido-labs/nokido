# -*- coding: utf-8 -*-
"""NR — Le modèle Gemini dans GeminiBridge dépend de l'appelant et non d'un GEMINI_MODEL global figé.

Décision owner du 15/10/2026 :
- La voie clé API (GEMINI_API_KEY) est le palier gratuit où seule la famille flash-lite répond.
- Le modèle par défaut pour cette voie doit être de la famille flash-lite.
- L'appelant peut spécifier son modèle qui prime sur le défaut.
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

import forge_gemini_bridge as G


def test_defaut_cle_api_est_flash_lite_meme_avec_env_pro(monkeypatch):
    """Le défaut pour la voie clé API est flash-lite, même si GEMINI_MODEL=gemini-2.5-pro."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    bridge = G.GeminiBridge()
    assert "flash-lite" in bridge.model, (
        f"Le modèle par défaut doit être de la famille flash-lite, reçu: {bridge.model}"
    )


def test_modele_appelant_instanciation(monkeypatch):
    """L'appelant peut spécifier son modèle à l'instanciation."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    bridge = G.GeminiBridge(model="gemini-3.1-pro-preview")
    assert bridge.model == "gemini-3.1-pro-preview"


@pytest.mark.asyncio
async def test_modele_appelant_dans_ask(monkeypatch):
    """Dans ask(), le paramètre model passé par l'appelant surcharge le modèle par défaut."""
    bridge = G.GeminiBridge(api_key="test-key", model="gemini-2.5-flash-lite")
    bridge._has_sec = False  # pas de loopback pour test unitaire pur

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Réponse OK"
    mock_client.models.generate_content.return_value = mock_resp
    bridge._client = mock_client

    # Appel avec modèle explicite de l'appelant
    res = await bridge.ask("bonjour", model="gemini-special-test")
    assert res == "Réponse OK"
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args[1]
    assert call_kwargs.get("model") == "gemini-special-test", (
        f"Le modèle transmis à generate_content doit être celui de l'appelant, reçu: {call_kwargs.get('model')}"
    )


def test_get_gemini_bridge_respecte_modele():
    """get_gemini_bridge prend en compte le modèle passé par l'appelant."""
    G.reset_bridge()
    b1 = G.get_gemini_bridge()
    assert "flash-lite" in b1.model

    b2 = G.get_gemini_bridge(model="gemini-custom-caller")
    assert b2.model == "gemini-custom-caller"
    G.reset_bridge()
