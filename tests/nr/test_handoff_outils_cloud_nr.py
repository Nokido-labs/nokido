# Cause : _outils_lecture(autorises=None) accepte desormais un argument autorises ; les lambdas de test attendaient 0 argument.
"""NR : les outils partent aux fournisseurs CLOUD (messages structures) + garde swarm pointeur."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import forge_handoff  # noqa: E402


import http.server  # noqa: E402
import threading  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def serveur():
    """Faux fournisseur EXIGEANT : 403 sans User-Agent de navigateur/sonde, 404 si modele prefixe litellm,
    400 si l'historique d'outils n'est pas conforme OpenAI (assistant.tool_calls puis tool apparie)."""
    etat = {"requetes": [], "forcer": None, "modeles": {"openai/gpt-oss-20b", "gpt-oss:120b"}}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n))
            etat["requetes"].append(p)
            code, corps = 200, None
            if etat["forcer"]:
                code = etat["forcer"]
            elif (self.headers.get("User-Agent") or "").startswith("Python-urllib"):
                code = 403
            elif p.get("model") not in etat["modeles"]:
                code = 404
            else:
                msgs = p["messages"]
                if len(etat["requetes"]) == 1:
                    corps = {"choices": [{"message": {"content": "", "tool_calls": [
                        {"id": "call_abc", "type": "function",
                         "function": {"name": "lire_x", "arguments": json.dumps({"a": "1"})}}]}}]}
                else:
                    ass = [i for i, m in enumerate(msgs) if m.get("role") == "assistant" and m.get("tool_calls")]
                    ok = bool(ass) and ass[-1] + 1 < len(msgs)
                    if ok:
                        ids = {tc["id"] for tc in msgs[ass[-1]]["tool_calls"]}
                        suite = msgs[ass[-1] + 1:]
                        ok = bool(suite) and all(m.get("role") == "tool" and m.get("tool_call_id") in ids
                                                 for m in suite[:len(ids)])
                    if not ok:
                        code = 400
                    else:
                        corps = {"choices": [{"message": {"content": "fini", "tool_calls": []}}]}
            if corps is None:
                corps = {"error": "refuse"}
            data = json.dumps(corps).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    etat["url"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    yield etat
    srv.shutdown()


def _installer(monkeypatch, serveur, modeles=("groq/openai/gpt-oss-20b",)):
    monkeypatch.setattr(forge_handoff, "_cloud_slot_info",
                        lambda p: (serveur["url"], "k", list(modeles)))
    return serveur["requetes"]


def _agent():
    def lire_x(a: str) -> str:
        """Lit x."""
        return "CONTENU-" + a
    return forge_handoff.Agent(name="m", instructions="i", tools=[lire_x], model="openai/gpt-oss-20b",
                               text_handoff=False, provider="groq_fast")


def test_outils_transmis_et_boucle(monkeypatch, serveur):
    reqs = _installer(monkeypatch, serveur)
    ag = _agent()
    r = forge_handoff.run_swarm(ag, "go", {"m": ag}, max_rounds=4, throttle_check=False)
    assert len(reqs) == 2, "serveur exigeant : UA, modele nu, historique conforme"
    assert reqs[0].get("tools") and reqs[0]["messages"][0]["role"] == "system"
    assert reqs[0]["model"] == "openai/gpt-oss-20b"
    assert r.n_rounds >= 2
    assert any(m.get("role") == "tool" and "CONTENU-1" in m["content"] for m in r.messages)
    assert r.messages[-1]["content"] == "fini"


def test_modele_litellm_ollama_cloud_sans_prefixe(monkeypatch, serveur):
    reqs = _installer(monkeypatch, serveur, modeles=("openai/gpt-oss:120b",))
    ag = _agent()
    ag.model, ag.provider = "openai/gpt-oss:120b", "ollama_cloud_gptoss"
    forge_handoff.run_swarm(ag, "go", {"m": ag}, max_rounds=4, throttle_check=False)
    assert reqs and reqs[0]["model"] == "gpt-oss:120b"
    assert len(reqs) == 2


def test_source_unique_sonde():
    import forge_tool_call_probe as sonde

    assert callable(getattr(sonde, "appeler_avec_outils", None))
    assert not hasattr(forge_handoff, "_BASES_PAR_CLE")
    assert not hasattr(forge_handoff, "_cloud_http")


def test_echec_transport_pas_de_repli_aplati(monkeypatch, serveur):
    _installer(monkeypatch, serveur)
    serveur["forcer"] = 403
    plats = []
    monkeypatch.setattr(forge_handoff, "_call_router_provider", lambda *a, **k: plats.append(a) or {})
    monkeypatch.setattr(forge_handoff, "_call_router", lambda *a, **k: plats.append(a) or {})
    out = forge_handoff._llm_round(_agent(), [{"role": "user", "content": "x"}], with_tools=True)
    assert not plats
    assert out["message"]["content"] == ""
    assert out["tool_calls"] == []
    meta = out["_router_meta"]
    assert meta["ok"] is False and meta["http"] == 403 and meta["provider"] == "groq_fast"


def test_cli_pointeur_traverse_chemin_reel(monkeypatch, serveur, tmp_path):
    import forge_cli_swarm as sw

    _installer(monkeypatch, serveur)
    sonde = tmp_path / "sonde.json"
    sonde.write_text(json.dumps({"resultats": [
        {"fournisseur": "groq", "modele": "openai/gpt-oss-20b", "etat": "APPELLE"}]}), encoding="utf-8")
    cons = tmp_path / "c.txt"
    cons.write_text("lis", encoding="utf-8")
    monkeypatch.setattr(sw, "SONDE", str(sonde))
    monkeypatch.setattr(sw, "SORTIE_DIR", tmp_path)
    monkeypatch.setattr(sw, "_outils_lecture", lambda *a, **k: {"lire_x": _agent().tools[0]})
    assert sw.main(["--pointeur", str(cons), "--ptr", "x", "--membres", "groq_fast:openai/gpt-oss-20b"]) == 0
    res = json.loads(next(tmp_path.glob("cli_swarm_ptr_*.json")).read_text(encoding="utf-8"))
    a = res["answers"][0]
    assert a["ok"] is True and a["outils_appeles"] == ["lire_x"] and a["tours"] >= 2


def test_cli_pointeur_echec_transport_motif(monkeypatch, serveur):
    import forge_cli_swarm as sw

    _installer(monkeypatch, serveur)
    serveur["forcer"] = 403
    monkeypatch.setattr(sw, "_outils_lecture", lambda *a, **k: {"lire_x": _agent().tools[0]})
    res = sw._tourner_membre("groq_fast:openai/gpt-oss-20b", "lis", 3)
    assert res["ok"] is False
    assert "403" in res["text"] and "groq_fast" in res["text"]


def test_sans_outils_chemin_inchange(monkeypatch, serveur):
    reqs = _installer(monkeypatch, serveur)
    appels = []
    monkeypatch.setattr(forge_handoff, "_call_router_provider",
                        lambda flat, provider, **k: appels.append(flat) or
                        {"message": {"role": "assistant", "content": "ok"}, "tool_calls": [], "_router_meta": {}})
    out = forge_handoff._llm_round(_agent(), [{"role": "user", "content": "x"}], with_tools=False)
    assert out["message"]["content"] == "ok" and appels and not reqs


def test_swarm_pointeur_sans_outil_ok_false(monkeypatch, serveur):
    import forge_cli_swarm as sw

    _installer(monkeypatch, serveur)
    # le faux serveur rend d'abord un tool_call : on le remplace par une reponse en texte seul
    monkeypatch.setattr(forge_handoff, "_call_cloud_with_tools",
                        lambda agent, provider, full, tools: {
                            "message": {"role": "assistant", "content": "invente"}, "tool_calls": [],
                            "_router_meta": {"ok": True}})
    res = sw._tourner_membre("groq_fast:openai/gpt-oss-20b", "lis", 3)
    assert res["ok"] is False
    assert "aucun pointeur lu" in res["error"]
    assert res["text"] == "invente"
