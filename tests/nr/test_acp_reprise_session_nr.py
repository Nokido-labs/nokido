"""NR -- reprise de session ACP : le vrai claude-agent-acp SORT (rc=1) des qu'aucun tour n'est actif.
Faux agent stdio qui sort apres chaque tour, comme le vrai. tmp_path seulement, aucun CLI reel, aucun etat vivant."""
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
store = sys.argv[1]          # journal d'appels + sessions connues (fichier)
variante = sys.argv[2]       # load | resume | noload
def out(o): print(json.dumps(o), flush=True)
def note(**k):
    with open(store, "a", encoding="utf-8") as f: f.write(json.dumps(k) + "\n")
def connues():
    try:
        return {json.loads(l).get("sid") for l in open(store, encoding="utf-8") if '"new"' in l}
    except OSError:
        return set()
note(ev="start")
for line in sys.stdin:
    m = json.loads(line); meth = m.get("method"); p = m.get("params") or {}
    if meth == "initialize":
        caps = {"loadSession": variante in ("load", "noload")}
        if variante == "resume":
            caps["sessionCapabilities"] = {"resume": {}, "list": {}, "close": {}}
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1, "agentCapabilities": caps}})
    elif meth == "session/new":
        note(ev="new", sid="s1")
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1", "modes": {
            "currentModeId": "default",
            "availableModes": [{"id": "default"}, {"id": "bypassPermissions"}]}}})
    elif meth in ("session/load", "session/resume"):
        note(ev="reprise", methode=meth, sid=p.get("sessionId"), cwd=p.get("cwd"))
        if variante == "noload" and "ECHEC" in open(store).read():
            out({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32002, "message": "session introuvable"}})
        elif p.get("sessionId") not in connues():
            out({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32002, "message": "session introuvable"}})
        else:
            out({"jsonrpc": "2.0", "id": m["id"], "result": {"modes": {"currentModeId": "default",
                 "availableModes": [{"id": "default"}, {"id": "bypassPermissions"}]}}})
    elif meth == "session/set_mode":
        note(ev="set_mode", mode=p.get("modeId"))
        out({"jsonrpc": "2.0", "id": m["id"], "result": {}})
    elif meth == "session/prompt":
        txt = p["prompt"][0]["text"]
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "re:" + txt}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
        sys.stderr.write("fin de tour, plus rien d'actif\n"); sys.stderr.flush()
        sys.exit(1)   # comme le vrai : sort des qu'aucun tour n'est actif
'''


def _routeur(tmp_path, variante="load"):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    store = tmp_path / "store.jsonl"
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda agent: [sys.executable, str(f), str(store), variante])
    return r, store, wt


def _evts(store):
    return [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines()]


def _attendre_mort(r, sid):
    cli = r._sessions[sid]["cli"]
    for _ in range(100):
        if cli.proc.poll() is not None:
            return
        time.sleep(0.05)
    raise AssertionError("le faux agent aurait du sortir")


def _journal(tmp_path, sid):
    p = tmp_path / "logs" / f"{sid}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def _fermer(r):
    for i in list(r.lister()):
        r.fermer(i["id"])


def test_envoyer_apres_la_mort_de_l_agent_relance_et_charge_la_session(tmp_path):
    r, store, wt = _routeur(tmp_path)
    try:
        sid = r.ouvrir("claude")
        assert r.envoyer(sid, "un", timeout=20)["text"] == "re:un"
        _attendre_mort(r, sid)
        rep = r.envoyer(sid, "deux", timeout=20)
        assert rep["text"] == "re:deux" and rep["stopReason"] == "end_turn"
        ev = _evts(store)
        assert [e["ev"] for e in ev].count("start") == 2
        rp = [e for e in ev if e["ev"] == "reprise"]
        assert len(rp) == 1 and rp[0]["methode"] == "session/load" and rp[0]["sid"] == "s1"
        assert Path(rp[0]["cwd"]).resolve() == wt.resolve()          # MEME cwd
        assert "reprise" in [l["kind"] for l in _journal(tmp_path, sid)]
    finally:
        _fermer(r)


def test_reprise_par_session_resume_quand_c_est_la_methode_annoncee(tmp_path):
    r, store, _ = _routeur(tmp_path, "resume")
    try:
        sid = r.ouvrir("claude")
        r.envoyer(sid, "un", timeout=20)
        _attendre_mort(r, sid)
        assert r.envoyer(sid, "deux", timeout=20)["text"] == "re:deux"
        assert [e["methode"] for e in _evts(store) if e["ev"] == "reprise"] == ["session/resume"]
    finally:
        _fermer(r)


def test_reprise_impossible_est_une_erreur_dite_jamais_un_faux_succes(tmp_path):
    r, store, _ = _routeur(tmp_path, "noload")
    try:
        sid = r.ouvrir("claude")
        r.envoyer(sid, "un", timeout=20)
        _attendre_mort(r, sid)
        with store.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ev": "ECHEC"}) + "\n")      # la session n'est plus chargeable
        with pytest.raises(RuntimeError) as e:
            r.envoyer(sid, "deux", timeout=20)
        msg = str(e.value)
        assert "reprise impossible" in msg and "session introuvable" in msg
        assert "re:deux" not in msg
        assert "reprise_echec" in [l["kind"] for l in _journal(tmp_path, sid)]
    finally:
        _fermer(r)


def test_ouvrir_avec_prompt_initial_repond_dans_le_meme_appel(tmp_path):
    r, store, _ = _routeur(tmp_path)
    try:
        res = r.ouvrir("claude", prompt_initial="bonjour", timeout=20)
        assert res["reponse"]["text"] == "re:bonjour"
        assert res["session"] in {i["id"] for i in r.lister()}
        # sans prompt_initial : toujours l'identifiant seul
        assert isinstance(r.ouvrir("claude"), str)
    finally:
        _fermer(r)


def test_le_worker_ouvrir_accepte_prompt_et_rend_session_et_reponse(tmp_path):
    r, _, _ = _routeur(tmp_path)
    w = W.AcpWorker(router=r, jobs_dir=tmp_path / "jobs", epingle_fn=lambda: None, nonce_path=tmp_path / "n",
                    battre=lambda **k: None, veto=lambda *a: None, lever=lambda: None)
    try:
        res = w.executer("ouvrir", {"agent": "claude", "prompt": "salut"})
        assert res["ok"] is True and res["reponse"]["text"] == "re:salut" and res["session"]
        with pytest.raises(W._Refus):
            w.executer("ouvrir", {"agent": "claude", "mode": "bypassPermissions", "prompt": "x"})
    finally:
        _fermer(r)


def test_aucun_mode_non_sur_a_la_reprise(tmp_path):
    r, store, _ = _routeur(tmp_path)
    try:
        sid = r.ouvrir("claude")
        r.envoyer(sid, "un", timeout=20)
        _attendre_mort(r, sid)
        r.envoyer(sid, "deux", timeout=20)
        modes = [e["mode"] for e in _evts(store) if e["ev"] == "set_mode"]
        assert modes and set(modes) == {R.MODES_SURS["claude"]}
    finally:
        _fermer(r)
