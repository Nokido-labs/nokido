"""NR -- tour final ignore par le modele (tool_choice=none, finish_reason=tool_calls) : UNE reprise sans outils declares.
Faux hf, aucun reseau. La voie aplatie n'est jamais utilisee (with_tools=True partout)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402
from app import forge_handoff as fh  # noqa: E402


def lire_fichier(chemin: str) -> str:
    """Lit un fichier."""
    return "contenu"


APPEL = {"id": "c1", "function": {"name": "lire_fichier", "arguments": '{"chemin": "x"}'}}


class _Hf:
    def __init__(self, finals):
        self.finals, self.appels = list(finals), []

    def _llm_round(self, agent, messages, with_tools):
        self.appels.append({"with_tools": with_tools, "outils": len(agent.tools),
                            "choice": getattr(agent, "tool_choice", "auto")})
        if len(self.appels) == 1:
            return {"message": {"content": ""}, "tool_calls": [APPEL], "_router_meta": {"ok": True, "tools": True}}
        return self.finals.pop(0)


def _agent():
    return fh.Agent(name="m", instructions="i", tools=[lire_fichier], text_handoff=False)


def _r(contenu, fr, appels=()):
    return {"message": {"content": contenu}, "tool_calls": list(appels),
            "_router_meta": {"ok": True, "tools": True, "finish_reason": fr}}


def test_final_vide_tool_calls_reprise_sans_outils():
    hf, trace = _Hf([_r("", "tool_calls", [APPEL]), _r("reponse fondee", "stop")]), {}
    msgs, _ = S._boucle_membre(hf, _agent(), "q", 2, trace)
    assert len(hf.appels) == 3
    assert hf.appels[1]["outils"] == 1 and hf.appels[2]["outils"] == 0
    assert hf.appels[2]["with_tools"] is True
    assert trace.get("reprise_condensee") is True  # assertion remplacee (ex reprise_sans_outils)
    assert msgs[-1]["content"] == "reponse fondee"
    assert sum(1 for m in msgs if m.get("role") == "tool") == 1  # appel final ignore


def test_final_vide_length_pas_de_reprise_sans_outils():
    hf, trace = _Hf([_r("", "length"), _r("ok", "stop")]), {}
    S._boucle_membre(hf, _agent(), "q", 2, trace)
    assert trace.get("reprise_length") is True
    assert not trace.get("reprise_sans_outils")
    assert all(a["outils"] == 1 for a in hf.appels[1:])


def test_final_avec_contenu_aucune_reprise():
    hf, trace = _Hf([_r("deja", "stop")]), {}
    S._boucle_membre(hf, _agent(), "q", 2, trace)
    assert len(hf.appels) == 2 and not trace.get("reprise_sans_outils")


def test_agent_sans_outils_voie_avec_outils(monkeypatch):
    vus = {}
    monkeypatch.setattr(fh, "_call_cloud_with_tools",
                        lambda agent, prov, full, schema: vus.setdefault("schema", schema) or {})
    monkeypatch.setattr(fh, "_call_router_provider", lambda *a, **k: (_ for _ in ()).throw(AssertionError("aplati")))
    ag = fh.Agent(name="m", instructions="i", tools=[], text_handoff=False, provider="p", model="m")
    ag.voie_outils_vide = True
    fh._llm_round(ag, [{"role": "user", "content": "q"}], with_tools=True)
    assert vus["schema"] == []
