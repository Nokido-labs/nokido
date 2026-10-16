# -*- coding: utf-8 -*-
"""NR — Le modèle Gemini dans gemini_poll_daemon dépend de l'appelant et non d'un GEMINI_MODEL global figé.

Décision owner du 15/10/2026 :
- La voie clé API (call_gemini_api_rest) passe par le palier gratuit où seule la famille flash-lite répond.
- Le modèle par défaut pour la voie clé API doit être flash-lite (ex: gemini-2.5-flash-lite).
- L'appelant peut spécifier un modèle qui prime sur le défaut.
- Un GEMINI_MODEL global (ex: gemini-2.5-pro dans Nokido.env) ne doit plus s'imposer sur la voie clé API.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gemini_poll_daemon as D


def test_defaut_cle_api_est_flash_lite():
    """Le modèle par défaut sur la voie clé API est flash-lite."""
    assert "flash-lite" in D.DEFAULT_GEMINI_API_MODEL, (
        f"DEFAULT_GEMINI_API_MODEL doit être de la famille flash-lite, reçu: {D.DEFAULT_GEMINI_API_MODEL}"
    )


def test_call_llm_utilise_flash_lite_par_defaut_sur_cle_api(monkeypatch):
    """Quand api_key est fournie sans modèle, call_gemini_api_rest reçoit le modèle flash-lite."""
    captured_models = []

    def fake_api_rest(prompt, api_key, model, timeout=120):
        captured_models.append(model)
        return "reponse OK"

    monkeypatch.setattr(D, "call_gemini_api_rest", fake_api_rest)

    res = D.call_llm("mon prompt", api_key="cle-api-test")
    assert res == "reponse OK"
    assert len(captured_models) == 1
    assert "flash-lite" in captured_models[0], (
        f"Le modèle transmis doit être flash-lite, reçu: {captured_models[0]}"
    )


def test_call_llm_respecte_modele_appelant(monkeypatch):
    """Quand l'appelant fournit son modèle, call_gemini_api_rest le reçoit directement."""
    captured_models = []

    def fake_api_rest(prompt, api_key, model, timeout=120):
        captured_models.append(model)
        return "reponse OK"

    monkeypatch.setattr(D, "call_gemini_api_rest", fake_api_rest)

    res = D.call_llm("mon prompt", api_key="cle-api-test", model="gemini-3.1-pro-preview")
    assert res == "reponse OK"
    assert captured_models == ["gemini-3.1-pro-preview"]


def test_call_llm_sans_api_key_utilise_cli_oauth(monkeypatch):
    """Sans api_key, call_llm délègue au CLI OAuth."""
    monkeypatch.setattr(D, "call_gemini_cli", lambda prompt, timeout=120: "cli OK")

    res = D.call_llm("mon prompt", api_key="")
    assert res == "cli OK"
