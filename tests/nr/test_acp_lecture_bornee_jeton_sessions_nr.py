"""NR ACP : lecture bornee a la session, pas de repli sur le jeton MCP, sessions cloisonnees."""
import json
import os
import sys
import types

import pytest

from tools import forge_acp_client as C
from tools import forge_acp_server as S


def _client(cwd):
    c = C.ACPClient(cmd=["x"], cwd=cwd, on_log=lambda m: None)
    sent = []
    c._send = sent.append
    return c, sent


def _lire(c, path):
    c._handle_agent_request({"id": 1, "method": "fs/read_text_file", "params": {"path": path}})


def test_lecture_dans_cwd_ok_hors_cwd_refusee(tmp_path):
    cwd = tmp_path / "s"
    cwd.mkdir()
    (cwd / "a.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "dehors.txt").write_text("secret", encoding="utf-8")
    c, sent = _client(str(cwd))
    _lire(c, str(cwd / "a.txt"))
    assert sent[-1]["result"]["content"] == "ok"
    _lire(c, str(tmp_path / "dehors.txt"))
    assert "error" in sent[-1]
    _lire(c, str(cwd / ".." / "dehors.txt"))
    assert "error" in sent[-1]


def test_lien_symbolique_refuse(tmp_path):
    cwd = tmp_path / "s"
    cwd.mkdir()
    (tmp_path / "dehors.txt").write_text("secret", encoding="utf-8")
    try:
        os.symlink(tmp_path / "dehors.txt", cwd / "lien.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlink indisponible")
    c, sent = _client(str(cwd))
    _lire(c, str(cwd / "lien.txt"))
    assert "error" in sent[-1]


def test_cwd_inconnu_echec_ferme(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    c, sent = _client(str(tmp_path))
    c.cwd = ""
    _lire(c, str(tmp_path / "a.txt"))
    assert "error" in sent[-1]


def test_pas_de_repli_sur_jeton_mcp(monkeypatch):
    coffre = {"FORGE_MCP_TOKEN": "mcp-factice"}
    mod = types.ModuleType("nokido_agent.app.forge_secrets")
    mod.get_secret = lambda k: coffre.get(k)
    for n in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, n, types.ModuleType(n))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", mod)
    tok, _ = S._acp_secret_attendu()
    assert tok is None
    coffre["FORGE_ACP_TOKEN"] = "acp-factice"
    tok, src = S._acp_secret_attendu()
    assert tok == "acp-factice" and src == "FORGE_ACP_TOKEN"


def test_sessions_non_partagees_et_ids_non_devinables():
    # serve_ws cree un ACPServer PAR connexion : deux serveurs = deux tables.
    out_a, out_b = [], []
    a = S.ACPServer(brain=S.EchoBrain(), writer=out_a.append)
    b = S.ACPServer(brain=S.EchoBrain(), writer=out_b.append)
    a.handle_obj({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "."}})
    sid = json.loads(out_a[-1])["result"]["sessionId"]
    assert sid != "nokido-1" and len(sid) > 14
    b.handle_obj({"jsonrpc": "2.0", "id": 2, "method": "session/prompt",
                  "params": {"sessionId": sid, "prompt": "x"}})
    assert json.loads(out_b[-1])["error"]["code"] == -32602
    b.handle_obj({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})
    assert not a._sessions[sid].cancel.is_set()
