# -*- coding: utf-8 -*-
"""tests/test_forge_ui_campaign.py — Validation des 3 états (CONFORME / VIOLÉ / INDISPONIBLE) et du nommage de la route en cause."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tools.forge_ui_campaign as ui_campaign


@pytest.fixture(autouse=True)
def _registre_isole(tmp_path, monkeypatch):
    """Le registre des routes instables est calcule a l'IMPORT depuis OUT : patcher OUT ne le redirige pas. Mesure du
    14/10 : ces tests incrementaient les compteurs du VRAI registre (146 -> 174 en deux lancements)."""
    monkeypatch.setattr(ui_campaign, "_REGISTRE_INSTABLES", tmp_path / "routes_instables.json")
    monkeypatch.setattr(ui_campaign, "_COMPTEURS_INSTABLES", tmp_path / "routes_instables_compteurs.json")


def _page_simulee():
    """Page Playwright simulee : ses methodes attendues (await) sont asynchrones ; `on` reste synchrone, comme la vraie."""
    page = MagicMock()
    for nom in ("add_init_script", "evaluate", "wait_for_load_state", "wait_for_function"):
        setattr(page, nom, AsyncMock(return_value=None))
    return page


class _MethodesRecentes:
    """Les methodes que la campagne appelle depuis le 31/07 (date du dernier passage sur ce test) : sans elles, la
    doublure PLANTAIT, et le test VIOLE obtenait son rouge par ce plantage, pas par le contrat qu'il pretend juger."""

    async def count_interactive_document(self):
        return 0

    async def eval_js(self, expr):
        return None

    async def fill(self, selector, text, timeout_ms=5000):
        return None

    async def click(self, selector, timeout_ms=5000):
        return None


@pytest.mark.asyncio
async def test_ui_gate_state_indisponible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode INDISPONIBLE (rc=2) : web_hub :7400 injoignable."""
    out_dir = tmp_path / "ui_campaign"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ui_campaign, "OUT", out_dir)

    # Mock opener pour lever une exception sur /health
    mock_opener = MagicMock()
    mock_opener.open.side_effect = Exception("ConnectionRefusedError")
    with patch("urllib.request.build_opener", return_value=mock_opener), \
         patch("asyncio.sleep", return_value=None):
        rc = await ui_campaign.run()

    assert rc == 2
    report_file = out_dir / "report.json"
    assert report_file.exists()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["verdict"] == "INDISPONIBLE"
    assert report["route_en_cause"] == []


@pytest.mark.asyncio
async def test_ui_gate_state_viole_and_named_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode VIOLÉ (rc=1) : la route /dashboard échoue son contrat et est explicitement nommée."""
    out_dir = tmp_path / "ui_campaign"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ui_campaign, "OUT", out_dir)

    mock_opener = MagicMock()
    mock_res = MagicMock()
    mock_res.status = 200
    mock_opener.open.return_value = mock_res

    # Mock PlaywrightBrowser context
    class MockBrowser(_MethodesRecentes):
        def __init__(self, **kwargs):
            self.page = _page_simulee()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def goto(self, url, *args, **kwargs):
            return url

        async def wait(self, seconds):
            pass

        async def screenshot(self, path, full_page=True):
            return str(path)

        async def dom_text(self):
            # Text missing "nokido hub" for /dashboard contract
            return "empty content"

        async def url(self):
            return "http://127.0.0.1:7400/dashboard"

        async def get_interactive_elements(self):
            return []

    with patch("urllib.request.build_opener", return_value=mock_opener), \
         patch("tools.forge_ui_campaign.PlaywrightBrowser", MockBrowser), \
         patch.object(ui_campaign, "ROUTES", [("/dashboard", "portail dashboard")]):
        rc = await ui_campaign.run()

    assert rc == 1
    report_file = out_dir / "report.json"
    assert report_file.exists()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["verdict"] == "VIOLÉ"
    assert "/dashboard" in report["route_en_cause"]


@pytest.mark.asyncio
async def test_ui_gate_state_conforme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode CONFORME (rc=0) : tous les contrats UI sont validés."""
    out_dir = tmp_path / "ui_campaign"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ui_campaign, "OUT", out_dir)

    mock_opener = MagicMock()
    mock_res = MagicMock()
    mock_res.status = 200
    mock_opener.open.return_value = mock_res

    class MockBrowser(_MethodesRecentes):
        def __init__(self, **kwargs):
            self.page = _page_simulee()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def goto(self, url, *args, **kwargs):
            return url

        async def wait(self, seconds):
            pass

        async def screenshot(self, path, full_page=True):
            return str(path)

        async def dom_text(self):
            # > 40 caracteres : depuis le 29/08 la campagne juge VIDE une page plus courte (signal « page vide »).
            return "nokido hub web hub -- portail : services, agents, memoire et veille du poste"

        async def url(self):
            return "http://127.0.0.1:7400/dashboard"

        async def get_interactive_elements(self):
            return []

    with patch("urllib.request.build_opener", return_value=mock_opener), \
         patch("tools.forge_ui_campaign.PlaywrightBrowser", MockBrowser), \
         patch.object(ui_campaign, "ROUTES", [("/dashboard", "portail dashboard")]):
        rc = await ui_campaign.run()

    assert rc == 0
    report_file = out_dir / "report.json"
    assert report_file.exists()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["verdict"] == "CONFORME"
    assert report["route_en_cause"] == []
