"""NR -- le detail `usage` de la reponse ACP session/prompt (lecture / ecriture du cache, sortie) n'est plus jete.
Sans lui, aucune economie de tokens ne se mesure (28/10 : 35 423 tokens « used », sans savoir combien en cache).
Faux agent stdio, tmp_path seulement."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402

USAGE = {"inputTokens": 12, "outputTokens": 3, "cachedReadTokens": 35000, "cachedWriteTokens": 400,
         "totalTokens": 35415}

FAUX = r'''
import json, sys
avec_usage = sys.argv[1] == "1"
def out(o): print(json.dumps(o), flush=True)
for line in sys.stdin:
    m = json.loads(line); meth = m.get("method"); p = m.get("params") or {}
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1"}})
    elif meth in ("session/set_mode", "session/set_model"):
        out({"jsonrpc": "2.0", "id": m["id"], "result": {}})
    elif meth == "session/prompt":
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}})
        res = {"stopReason": "end_turn"}
        if avec_usage:
            res["usage"] = %s
        out({"jsonrpc": "2.0", "id": m["id"], "result": res})
''' % json.dumps(USAGE)


def _ouvrir(tmp_path, avec_usage):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda agent: [sys.executable, str(f), "1" if avec_usage else "0"])
    res = r.ouvrir("codex", prompt_initial="salut")
    journal = [json.loads(l) for l in (tmp_path / "logs" / ("%s.jsonl" % res["session"])).read_text(
        encoding="utf-8").splitlines()]
    r.fermer(res["session"])
    return res, journal


def test_usage_de_la_reponse_rendu_et_journalise(tmp_path):
    res, journal = _ouvrir(tmp_path, True)
    assert res["reponse"]["usage"] == USAGE
    rep = [e for e in journal if e.get("kind") == "reponse"]
    assert rep and rep[-1]["payload"]["usage"] == USAGE


def test_sans_usage_aucune_cle_inventee(tmp_path):
    res, _ = _ouvrir(tmp_path, False)
    assert "usage" not in res["reponse"]  # absent = inconnu, jamais un zero fabrique
    assert res["reponse"]["text"] == "ok"
