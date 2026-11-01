"""NR -- reprise finale sans outils : la charge n'envoie NI `tools: []` NI `tool_choice`.

Recette 29/10 08 h 40 : gpt-oss:120b ignore tool_choice="none" ; la reprise (984e8edc1) part avec un agent sans
outils. Plusieurs API OpenAI-compatibles refusent un tableau `tools` vide : sans outil, les deux cles sont omises.
Faux transport, aucun reseau."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_tool_call_probe as P  # noqa: E402
from app import forge_handoff as fh  # noqa: E402


def _charge(monkeypatch, **kw) -> dict:
    vus = {}

    def fausse_requete(_url, _cle, charge):
        vus["corps"] = json.loads(charge)
        raise OSError("coupe ici")

    monkeypatch.setattr(P, "requete", fausse_requete)
    try:
        P.appeler_avec_outils("http://x", "", "m", [{"role": "user", "content": "q"}], **kw)
    except OSError:
        pass
    return vus["corps"]


def test_sans_outils_ni_tools_ni_tool_choice(monkeypatch):
    """tool_choice=None et aucun outil : les deux cles absentes."""
    corps = _charge(monkeypatch, tools=[], tool_choice=None)
    assert "tools" not in corps and "tool_choice" not in corps


def test_avec_outils_inchange(monkeypatch):
    """Avec outils : tools et tool_choice envoyes comme avant."""
    corps = _charge(monkeypatch, tools=[{"type": "function"}], tool_choice="none")
    assert corps["tools"] == [{"type": "function"}] and corps["tool_choice"] == "none"


def test_handoff_agent_sans_outils_passe_tool_choice_none_python(monkeypatch):
    """_call_cloud_with_tools : schema vide -> tool_choice=None transmis a la voie unique."""
    vus = {}

    class _Sonde:
        @staticmethod
        def appeler_avec_outils(*_a, **k):
            vus.update(k)
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(fh, "_sonde", lambda: _Sonde)
    monkeypatch.setattr(fh, "_cloud_slot_info", lambda p: ("http://x", "", ["m"]))
    agent = fh.Agent(name="a", instructions="i", tools=[], text_handoff=False)
    agent.tool_choice = "none"
    fh._call_cloud_with_tools(agent, "p", [{"role": "user", "content": "q"}], [])
    assert vus.get("tool_choice") is None
