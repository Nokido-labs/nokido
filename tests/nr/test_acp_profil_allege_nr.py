"""NR -- profil allege de session ACP claude (options session/new `_meta.claudeCode.options`).
Faux agent stdio qui enregistre les params EXACTS de session/new et session/load. tmp_path seulement."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402
import forge_acp_worker as W  # noqa: E402

FAUX = r'''
import json, sys
store = sys.argv[1]
variante = sys.argv[2]       # "sort" : sort apres chaque tour (comme le vrai claude-agent-acp)
def out(o): print(json.dumps(o), flush=True)
def note(**k):
    with open(store, "a", encoding="utf-8") as f: f.write(json.dumps(k) + "\n")
def connues():
    try:
        return {json.loads(l).get("sid") for l in open(store, encoding="utf-8") if '"new"' in l}
    except OSError:
        return set()
MODES = {"currentModeId": "default", "availableModes": [{"id": "default"}, {"id": "bypassPermissions"}]}
for line in sys.stdin:
    m = json.loads(line); meth = m.get("method"); p = m.get("params") or {}
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1,
             "agentCapabilities": {"loadSession": True}}})
    elif meth == "session/new":
        note(ev="new", sid="s1", cles=sorted(p), meta=p.get("_meta"))
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1", "modes": MODES}})
    elif meth == "session/load":
        note(ev="reprise", sid=p.get("sessionId"), cles=sorted(p), meta=p.get("_meta"))
        if p.get("sessionId") not in connues():
            out({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32002, "message": "session introuvable"}})
        else:
            out({"jsonrpc": "2.0", "id": m["id"], "result": {"modes": MODES}})
    elif meth in ("session/set_mode", "session/set_model"):
        out({"jsonrpc": "2.0", "id": m["id"], "result": {}})
    elif meth == "session/prompt":
        txt = p["prompt"][0]["text"]
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "re:" + txt}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
        if variante == "sort":
            sys.exit(1)
'''

OPT_PROJET = {"settingSources": ["project", "local"], "skills": [], "strictMcpConfig": True, "plugins": []}
OPT_NU = {"settingSources": [], "skills": [], "strictMcpConfig": True, "plugins": []}


def _routeur(tmp_path, variante="stay"):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    store = tmp_path / "store.jsonl"
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda agent: [sys.executable, str(f), str(store), variante])
    return r, store


def _evts(store):
    return [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines()]


def _journal(tmp_path, sid):
    p = tmp_path / "logs" / f"{sid}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def _attendre_mort(r, sid):
    cli = r._sessions[sid]["cli"]
    for _ in range(100):
        if cli.proc.poll() is not None:
            return
        time.sleep(0.05)
    raise AssertionError("le faux agent aurait du sortir")


def _fermer(r):
    for i in list(r.lister()):
        r.fermer(i["id"])


def test_defaut_est_projet_options_B_exactes(tmp_path):
    r, store = _routeur(tmp_path)
    try:
        sid = r.ouvrir("claude")
        new = [e for e in _evts(store) if e["ev"] == "new"][0]
        assert new["meta"] == {"claudeCode": {"options": OPT_PROJET}}
        assert [j for j in _journal(tmp_path, sid) if j["kind"] == "ouverte"][0]["payload"]["profil"] == "projet"
    finally:
        _fermer(r)


def test_profil_nu_options_C_exactes(tmp_path):
    r, store = _routeur(tmp_path)
    try:
        r.ouvrir("claude", profil="nu")
        new = [e for e in _evts(store) if e["ev"] == "new"][0]
        assert new["meta"] == {"claudeCode": {"options": OPT_NU}}
    finally:
        _fermer(r)


def test_profil_complet_sans_aucun_meta(tmp_path):
    r, store = _routeur(tmp_path)
    try:
        r.ouvrir("claude", profil="complet")
        new = [e for e in _evts(store) if e["ev"] == "new"][0]
        assert "_meta" not in new["cles"] and new["meta"] is None
    finally:
        _fermer(r)


def test_profil_inconnu_refuse_dit_et_ne_lance_rien(tmp_path):
    r, store = _routeur(tmp_path)
    try:
        with pytest.raises(R.ProfilInconnuError) as e:
            r.ouvrir("claude", profil="tout_sauf_ca")
        assert "tout_sauf_ca" in str(e.value)
        assert not store.exists() or not [x for x in _evts(store) if x["ev"] == "new"]
    finally:
        _fermer(r)


def test_profil_rejoue_a_la_reprise_session_load(tmp_path):
    r, store = _routeur(tmp_path, variante="sort")
    try:
        sid = r.ouvrir("claude", profil="nu")
        assert r.envoyer(sid, "un", timeout=20)["text"] == "re:un"
        _attendre_mort(r, sid)
        assert r.envoyer(sid, "deux", timeout=20)["text"] == "re:deux"
        rp = [e for e in _evts(store) if e["ev"] == "reprise"]
        assert len(rp) == 1
        assert rp[0]["meta"] == {"claudeCode": {"options": OPT_NU}}
    finally:
        _fermer(r)


def test_agent_non_claude_profil_ignore_dit_dans_le_journal(tmp_path):
    r, store = _routeur(tmp_path)
    try:
        sid = r.ouvrir("codex", profil="nu")
        new = [e for e in _evts(store) if e["ev"] == "new"][0]
        assert new["meta"] is None
        assert "profil_ignore" in [j["kind"] for j in _journal(tmp_path, sid)]
    finally:
        _fermer(r)


def _worker(tmp_path, r):
    return W.AcpWorker(router=r, jobs_dir=tmp_path / "jobs", epingle_fn=lambda: None,
                       nonce_path=tmp_path / "n", battre=lambda **k: None, veto=lambda *a: None,
                       lever=lambda: None)


def test_worker_ouvrir_transmet_profil_et_refuse_inconnu(tmp_path):
    r, store = _routeur(tmp_path)
    w = _worker(tmp_path, r)
    try:
        res = w.executer("ouvrir", {"agent": "claude", "profil": "nu"})
        assert res["ok"] is True
        new = [e for e in _evts(store) if e["ev"] == "new"][-1]
        assert new["meta"] == {"claudeCode": {"options": OPT_NU}}
        with pytest.raises(W._Refus):
            w.executer("ouvrir", {"agent": "claude", "profil": "inconnu"})
    finally:
        _fermer(r)


def test_pointeur_tasks_db_remplace_par_consigne_courte(tmp_path):
    r, _ = _routeur(tmp_path)
    w = _worker(tmp_path, r)
    try:
        res = w.executer("ouvrir", {"agent": "claude", "prompt": "tasks.db:T-42"})
        texte = res["reponse"]["text"]
        assert "T-42" in texte and "sandbox/tasks.db" in texte and "lecture seule" in texte
        assert "tasks.db:T-42" not in texte
        assert (W.ROOT / "sandbox" / "tasks.db").as_posix() in texte  # absolu : le cwd de l'agent est un worktree
        assert w.executer("ouvrir", {"agent": "claude", "prompt": "salut"})["reponse"]["text"] == "re:salut"
    finally:
        _fermer(r)
