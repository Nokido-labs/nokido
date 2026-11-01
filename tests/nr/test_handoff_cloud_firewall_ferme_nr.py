"""NR -- voie cloud avec outils : firewall introuvable = REFUS journalise, jamais un envoi sans pre_flight.

Gate de recidive 29/10 (chemin d'erreur muet, forge_handoff.py:438) : `except ImportError: pass` autour du
pre_flight laissait partir le contenu au cloud SANS filtrage (regle d'or 4) et sans trace. Faux transport."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

from app import forge_handoff as fh  # noqa: E402


def lire(x: str = "") -> str:
    """Outil factice."""
    return x


def test_firewall_introuvable_refuse_sans_envoyer(monkeypatch):
    """ImportError du firewall : aucun appel au transport, motif explicite dans _router_meta."""
    envois = []

    class _Sonde:
        @staticmethod
        def appeler_avec_outils(*a, **k):
            envois.append((a, k))
            return {"choices": [{"message": {"content": "fuite"}}]}

    monkeypatch.setattr(fh, "_sonde", lambda: _Sonde)
    monkeypatch.setattr(fh, "_cloud_slot_info", lambda p: ("http://x", "", ["m"]))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_semantic_firewall", None)  # import -> ImportError
    agent = fh.Agent(name="a", instructions="i", tools=[lire], text_handoff=False)
    rep = fh._call_cloud_with_tools(agent, "p", [{"role": "user", "content": "q"}], [fh._build_tool_schema(lire)])
    assert envois == []
    meta = rep["_router_meta"]
    assert meta["ok"] is False and "firewall" in meta["error"]
