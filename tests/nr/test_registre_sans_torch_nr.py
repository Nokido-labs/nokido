"""NR -- importer le registre MCP ne charge plus torch (2026-10-02).

Mesure : forge_mcp_registry.py:56 importait evaluate_intent depuis forge_spike_router, dont la tete fait
`import torch` -- 2,2 s et torch en memoire dans chaque processus qui importe le registre, hub compris,
pour une fonction qui n'utilise que numpy et l'embedder. evaluate_intent vit desormais dans
forge_intent_risk ; forge_spike_router le reexporte. Chemin reel : un processus NEUF importe le registre
avec les chemins du hub.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_importer_le_registre_ne_charge_pas_torch():
    code = ("import sys; sys.path[:0] = [%r, %r, %r]; import forge_mcp_registry; "
            "print('TORCH' if 'torch' in sys.modules else 'SANS_TORCH')"
            % (str(RACINE / "app"), str(RACINE / "tools"), str(RACINE)))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=110, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().splitlines()[-1] == "SANS_TORCH", (
        "le registre MCP recharge torch a l'import -- evaluate_intent doit rester dans forge_intent_risk")


def test_le_registre_appelle_la_source_legere():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8", errors="replace")
    assert "from nokido_agent.app.forge_intent_risk import evaluate_intent" in src
    assert "from nokido_agent.app.forge_spike_router import evaluate_intent" not in src


def test_evaluate_intent_reste_le_meme_et_dit_ses_echecs(monkeypatch):
    from nokido_agent.app import forge_intent_risk as fir
    from nokido_agent.app import forge_npu_embedder as emb

    assert fir.evaluate_intent({"tools": []})["status"] == "safe"
    monkeypatch.setattr(emb, "get_embed", lambda textes: None)
    rendu = fir.evaluate_intent({"tools": [{"name": "rm", "arguments": {}}]})
    assert rendu["status"] == "error", "un embedder muet ne vaut pas « safe »"
