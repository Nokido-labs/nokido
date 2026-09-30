# -*- coding: utf-8 -*-
"""tests/test_forge_ui_campaign.py — Validation des 3 états (CONFORME / VIOLÉ / INDISPONIBLE) et du nommage de la route en cause."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import tools.forge_ui_campaign as ui_campaign


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
    class MockBrowser:
        def __init__(self, **kwargs):
            self.page = MagicMock()

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

    class MockBrowser:
        def __init__(self, **kwargs):
            self.page = MagicMock()

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
            return "nokido hub web hub"

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
