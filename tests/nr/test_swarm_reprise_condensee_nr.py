"""NR (A) reprise finale a historique condense + delai proportionnel ; (B) post_flight en OBSERVATION seule.
Faux hf / faux transport, aucun reseau."""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402
from app import forge_handoff as fh  # noqa: E402


def lire_fichier(chemin: str) -> str:
    """Lit un fichier."""
    return GROS


GROS = "contenu"
APPEL = {"id": "c1", "function": {"name": "lire_fichier", "arguments": '{"chemin": "x"}'}}


class _Hf:
    def __init__(self, finals):
        self.finals, self.appels = list(finals), []

    def _llm_round(self, agent, messages, with_tools):
        self.appels.append({"outils": len(agent.tools), "msgs": [dict(m) for m in messages]})
        if len(self.appels) == 1:
            return {"message": {"content": ""}, "tool_calls": [APPEL], "_router_meta": {"ok": True, "tools": True}}
        return self.finals.pop(0)


def _agent():
    return fh.Agent(name="m", instructions="i", tools=[lire_fichier], text_handoff=False)


def _r(contenu, fr):
    return {"message": {"content": contenu}, "tool_calls": [],
            "_router_meta": {"ok": True, "tools": True, "finish_reason": fr}}


def test_reprise_condensee_messages_neufs():
    hf, trace = _Hf([_r("", "tool_calls"), _r("fondee", "stop")]), {}
    msgs, _ = S._boucle_membre(hf, _agent(), "ma question", 2, trace)
    m = hf.appels[2]["msgs"]
    assert hf.appels[2]["outils"] == 0 and len(m) == 1 and m[0]["role"] == "user"
    c = m[0]["content"]
    assert "ma question" in c and "EXTRAITS LUS" in c and "- lire_fichier:" in c and S.CONSIGNE_FINALE in c
    assert not any(x.get("role") == "tool" or x.get("tool_calls") for x in m)
    assert trace["reprise_condensee"] is True and msgs[-1]["content"] == "fondee"


def test_condense_trop_gros_tronque_et_dit():
    global GROS
    GROS = "x" * 30000
    try:
        hf, trace = _Hf([_r("", "tool_calls"), _r("ok", "stop")]), {}
        S._boucle_membre(hf, _agent(), "q", 2, trace)
        c = hf.appels[2]["msgs"][0]["content"]
        assert trace["condense_ecarte_car"] > 0
        assert len(c) < S.SEUIL_CONSIGNE + 1000
    finally:
        GROS = "contenu"


def test_length_reprise_double_inchangee():
    hf, trace = _Hf([_r("", "length"), _r("ok", "stop")]), {}
    S._boucle_membre(hf, _agent(), "q", 2, trace)
    assert trace.get("reprise_length") is True and not trace.get("reprise_condensee")


def test_contenu_aucune_reprise():
    hf, trace = _Hf([_r("deja", "stop")]), {}
    S._boucle_membre(hf, _agent(), "q", 2, trace)
    assert len(hf.appels) == 2 and not trace.get("reprise_condensee")


class _Sonde:
    def __init__(self):
        self.timeout = None

    @staticmethod
    def max_tokens_double_actif():
        import forge_tool_call_probe as p
        return p.max_tokens_double_actif()

    def appeler_avec_outils(self, base, cle, modele, messages, schema, timeout, **kw):
        self.timeout = timeout
        return {"choices": [{"message": {"content": "SECRET_REPONSE"}}]}


class _Fw:
    def __init__(self, ok=True, lever=False):
        self.ok, self.lever = ok, lever

    def pre_flight(self, *a, **k):
        return types.SimpleNamespace(ok=True, dlp_triggered=False)

    def post_flight(self, response, task="", session_id="", expected_fmt="text"):
        if self.lever:
            raise RuntimeError("boom")
        return types.SimpleNamespace(ok=self.ok, reason="x", tag="INJECTION", response=response + "MODIF")


def _appel(monkeypatch, fw):
    sonde = _Sonde()
    monkeypatch.setattr(fh, "_cloud_slot_info", lambda p: ("http://b", "k", ["m"]))
    monkeypatch.setattr(fh, "_sonde", lambda: sonde)
    import nokido_agent.app.forge_semantic_firewall as mod
    monkeypatch.setattr(mod, "get_firewall", lambda: fw)
    ag = fh.Agent(name="m", instructions="i", tools=[], text_handoff=False, provider="p", model="m")
    r = fh._call_cloud_with_tools(ag, "p", [{"role": "user", "content": "SECRET_CONSIGNE"}], [])
    return r, sonde


def test_timeout_60_puis_120_si_double(monkeypatch):
    _, s = _appel(monkeypatch, _Fw())
    assert s.timeout == fh.TIMEOUT_CLOUD_S == 60
    import forge_tool_call_probe as p
    with p.max_tokens_double():
        _, s = _appel(monkeypatch, _Fw())
    assert s.timeout == 120


def test_post_flight_non_ok_observation(monkeypatch, caplog):
    avant = fh.POST_FLIGHT_ALERTES
    with caplog.at_level(logging.WARNING):
        r, _ = _appel(monkeypatch, _Fw(ok=False))
    assert r["message"]["content"] == "SECRET_REPONSE"
    assert r["_router_meta"]["post_flight"] == {"ok": False, "motifs": ["INJECTION"]}
    assert fh.POST_FLIGHT_ALERTES == avant + 1
    log = caplog.text
    assert "[post_flight][observation]" in log and "SECRET_REPONSE" not in log and "SECRET_CONSIGNE" not in log


def test_post_flight_leve_illisible(monkeypatch):
    r, _ = _appel(monkeypatch, _Fw(lever=True))
    assert r["message"]["content"] == "SECRET_REPONSE"
    assert r["_router_meta"]["post_flight"] == {"ok": None, "motifs": ["ILLISIBLE"]}


def test_post_flight_ok(monkeypatch):
    r, _ = _appel(monkeypatch, _Fw(ok=True))
    assert r["_router_meta"]["post_flight"]["ok"] is True
