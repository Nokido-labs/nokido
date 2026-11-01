# -*- coding: utf-8 -*-
"""NR -- suites mesurees du 28/10 : finish_reason/raisonnement, reprise length, 429 Retry-After, modele dans la cle du pool."""
from __future__ import annotations

import dataclasses
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_acp_router as R  # noqa: E402
import forge_cli_swarm as S  # noqa: E402
import forge_tool_call_probe as P  # noqa: E402


class _Rep:
    def __init__(self, corps):
        self._b = json.dumps(corps).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _corps(content="", fr="stop", raison=None):
    msg = {"role": "assistant", "content": content}
    if raison is not None:
        msg["reasoning"] = raison
    return {"choices": [{"message": msg, "finish_reason": fr}]}


def _http429(entetes):
    return urllib.error.HTTPError("u", 429, "x", entetes, io.BytesIO(b"{}"))


def _appel():
    return P.appeler_avec_outils("http://x", "k", "m", [{"role": "user", "content": "a"}], [])


def test_finish_reason_et_longueur_raisonnement(monkeypatch):
    monkeypatch.setattr(P.urllib.request, "urlopen", lambda *a, **k: _Rep(_corps("", "length", "abcdef")))
    c = _appel()
    assert c["_finish_reason"] == "length" and c["_raisonnement_car"] == 6
    assert "abcdef" not in json.dumps({k: v for k, v in c.items() if k.startswith("_")})


def test_429_retry_after_1_reprise(monkeypatch):
    suites = [_http429({"Retry-After": "1"}), _Rep(_corps("ok"))]
    dormis = []

    def faux(*a, **k):
        x = suites.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    monkeypatch.setattr(P.urllib.request, "urlopen", faux)
    monkeypatch.setattr(P.time, "sleep", lambda s: dormis.append(s))
    assert _appel()["choices"][0]["message"]["content"] == "ok"
    assert dormis == [1.0]


def test_429_sans_entete_pas_de_reprise(monkeypatch):
    n = []

    def faux(*a, **k):
        n.append(1)
        raise _http429({})

    monkeypatch.setattr(P.urllib.request, "urlopen", faux)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    try:
        _appel()
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 429
    assert len(n) == 1


def test_429_retry_after_trop_long_pas_de_reprise(monkeypatch):
    n = []

    def faux(*a, **k):
        n.append(1)
        raise _http429({"Retry-After": "60"})

    monkeypatch.setattr(P.urllib.request, "urlopen", faux)
    try:
        _appel()
    except urllib.error.HTTPError:
        pass
    assert len(n) == 1


def test_max_tokens_double_borne(monkeypatch):
    vus = []

    def faux(req, timeout=0):
        vus.append(json.loads(req.data)["max_tokens"])
        return _Rep(_corps("ok"))

    monkeypatch.setattr(P.urllib.request, "urlopen", faux)
    P.appeler_avec_outils("http://x", "k", "m", [], [], max_tokens=1000)
    with P.max_tokens_double():
        P.appeler_avec_outils("http://x", "k", "m", [], [], max_tokens=1000)
        P.appeler_avec_outils("http://x", "k", "m", [], [], max_tokens=3000)
    assert vus == [1000, 2000, 4096]


class _HF:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.doubles = []

    def _llm_round(self, agent, messages, with_tools=True):
        self.doubles.append(P.max_tokens_double_actif())
        return self.reponses.pop(0)


def _rep(content="", tc=None, fr=None, rais=None, **meta):
    m = {"ok": True, "provider": "p", "tools": True}
    if fr:
        m["finish_reason"] = fr
    if rais is not None:
        m["raisonnement_car"] = rais
    m.update(meta)
    return {"message": {"role": "assistant", "content": content}, "tool_calls": tc or [], "_router_meta": m}


class _Ag:
    tools = []


def lire(x=""):
    return "contenu"


def _ag():
    a = _Ag()
    a.tools = [lire]
    return a


def _etapes():
    return [_rep(tc=[{"id": "1", "function": {"name": "lire", "arguments": "{}"}}])]


def test_tour_final_length_vide_reprise_double(monkeypatch):
    hf = _HF(_etapes() + [_rep("", fr="length", rais=300), _rep("reponse", fr="stop")])
    trace = {}
    monkeypatch.setattr(dataclasses, "replace", lambda a, **k: a)
    msgs, n = S._boucle_membre(hf, _ag(), "q", 2, trace)
    assert msgs[-1]["content"] == "reponse"
    assert hf.doubles == [False, False, True]
    assert trace.get("reprise_length") is True


def test_motif_finish_reason_si_vide(monkeypatch):
    hf = _HF(_etapes() + [_rep("", fr="length", rais=300), _rep("", fr="length", rais=512)])
    trace = {}
    monkeypatch.setattr(dataclasses, "replace", lambda a, **k: a)
    S._boucle_membre(hf, _ag(), "q", 2, trace)
    assert "finish_reason=length" in S._motif_vide(trace)
    assert "raisonnement 512 car." in S._motif_vide(trace)


def test_motif_429():
    assert S._motif_http({"http": 429, "retry_after": 7}) == "HTTP 429 (Retry-After 7 s)"
    assert S._motif_http({"http": 429}) == "HTTP 429"


def _routeur(tmp_path):
    faux = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "    m=json.loads(line); me=m.get('method')\n"
        "    if me=='initialize': res={'protocolVersion':1,'agentCapabilities':{}}\n"
        "    elif me=='session/new': res={'sessionId':'s1','modes':{'availableModes':[]},"
        "'models':{'availableModels':[{'modelId':'X'},{'modelId':'Y'}]}}\n"
        "    elif me in ('session/set_model','session/set_mode'): res={}\n"
        "    else: continue\n"
        "    print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':res}),flush=True)\n")
    f = tmp_path / "faux.py"
    f.write_text(faux, encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    return R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                       cmd_factory=lambda a: [sys.executable, str(f)])


def test_pool_modele_dans_la_cle(tmp_path):
    r = _routeur(tmp_path)
    s1 = r.ouvrir("codex", modele="X")
    r._sessions[s1]["libre"] = True
    s2 = r.ouvrir("codex", modele="Y")
    assert s2 != s1
    s3 = r.ouvrir("codex", modele="X")
    assert s3 == s1
    for s in list(r._sessions):
        try:
            r.fermer(s)
        except Exception:
            pass
