"""NR -- pool de sessions ACP chaudes par (agent, profil). Faux agent stdio, tmp_path, horloge injectee."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402
import forge_acp_worker as W  # noqa: E402

FAUX = r'''
import json, sys, time
store = sys.argv[1]
def out(o): print(json.dumps(o), flush=True)
def note(**k):
    with open(store, "a", encoding="utf-8") as f: f.write(json.dumps(k) + "\n")
n = 0
for line in sys.stdin:
    m = json.loads(line); meth = m.get("method"); p = m.get("params") or {}
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1, "agentCapabilities": {}}})
    elif meth == "session/new":
        n += 1
        note(ev="new", meta=p.get("_meta"))
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s%d" % n}})
    elif meth in ("session/set_mode", "session/set_model"):
        out({"jsonrpc": "2.0", "id": m["id"], "result": {}})
    elif meth == "session/prompt":
        txt = p["prompt"][0]["text"]
        if "lent" in txt:
            time.sleep(1.5)
        used = 130000 if "gros" in txt else 1000
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": p["sessionId"],
             "update": {"sessionUpdate": "usage_update", "used": used, "size": 200000}}})
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": p["sessionId"],
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "re:" + txt}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
'''


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    store = tmp_path / "store.jsonl"
    wt = tmp_path / "wt"
    wt.mkdir()
    h = Horloge()
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt), horloge=h,
                    cmd_factory=lambda agent: [sys.executable, str(f), str(store)])
    yield r, h, store, tmp_path
    for s in list(r._sessions):
        try:
            r._fermer_reel(s, "")
        except KeyError:
            pass


def _news(store):
    if not store.exists():
        return []
    return [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines() if '"new"' in l]


def _journal(tmp_path, sid):
    p = tmp_path / "logs" / f"{sid}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def _worker(tp, r):
    return W.AcpWorker(router=r, jobs_dir=tp / "jobs", nonce_path=tp / "n", battre=lambda **k: None,
                       veto=lambda *a: None, lever=lambda: None)


def test_reutilisee_sous_ttl(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un")
    assert a["reutilisee"] is False
    r.fermer(a["session"])
    h.t += 100
    b = r.ouvrir("claude", prompt_initial="deux")
    assert b["session"] == a["session"] and b["reutilisee"] is True
    assert b["reponse"]["text"] == "re:deux"
    assert len(_news(store)) == 1
    kinds = [e["kind"] for e in _journal(tp, a["session"])]
    assert "pool_liberee" in kinds and "pool_reutilisee" in kinds


def test_neuve_apres_ttl_et_purge(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un")
    r.fermer(a["session"])
    h.t += 300
    assert r.purger() == [a["session"]]
    assert a["session"] not in r._sessions
    b = r.ouvrir("claude", prompt_initial="deux")
    assert b["session"] != a["session"] and b["reutilisee"] is False
    assert len(_news(store)) == 2


def test_ttl_depasse_sans_purge_session_neuve(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un")
    r.fermer(a["session"])
    h.t += 241
    b = r.ouvrir("claude", prompt_initial="deux")
    assert b["session"] != a["session"]


def test_recyclage_taches(env):
    r, h, store, tp = env
    sid = None
    for i in range(5):
        res = r.ouvrir("claude", prompt_initial="t%d" % i)
        sid = sid or res["session"]
        assert res["session"] == sid
        r.fermer(res["session"])
    assert sid not in r._sessions
    assert any(e["kind"] == "pool_recyclee" and e["payload"]["motif"] == "taches" for e in _journal(tp, sid))
    sixieme = r.ouvrir("claude", prompt_initial="t6")
    assert sixieme["session"] != sid and sixieme["reutilisee"] is False


def test_recyclage_used(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="gros")
    r.fermer(a["session"])
    assert a["session"] not in r._sessions
    assert any(e["kind"] == "pool_recyclee" and e["payload"]["motif"] == "used" for e in _journal(tp, a["session"]))
    b = r.ouvrir("claude", prompt_initial="petit")
    assert b["session"] != a["session"]


def test_isolee_hors_pool(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un")
    r.fermer(a["session"])
    iso = r.ouvrir("claude", prompt_initial="iso", isolee=True)
    assert iso["session"] != a["session"] and iso["reutilisee"] is False
    r.fermer(iso["session"])
    assert iso["session"] not in r._sessions
    assert a["session"] in r._sessions
    iso2 = r.ouvrir("claude", prompt_initial="iso2", isolee=True)
    r.fermer(iso2["session"])
    c = r.ouvrir("claude", prompt_initial="trois")
    assert c["session"] == a["session"]


def test_profils_differents(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un", profil="projet")
    r.fermer(a["session"])
    b = r.ouvrir("claude", prompt_initial="deux", profil="nu")
    assert b["session"] != a["session"] and b["reutilisee"] is False
    r.fermer(b["session"])
    c = r.ouvrir("claude", prompt_initial="trois", profil="nu")
    assert c["session"] == b["session"]


def test_occupee_jamais_reutilisee(env):
    r, h, store, tp = env
    a = r.ouvrir("claude")
    res = {}

    def lent():
        res["a"] = r.envoyer(a, "lent", timeout=20)

    th = threading.Thread(target=lent)
    th.start()
    b = r.ouvrir("claude", prompt_initial="vite", timeout=20)
    th.join()
    assert b["session"] != a and b["reutilisee"] is False
    assert res["a"]["text"] == "re:lent"


def test_deux_ouvrir_concurrents_sur_session_libre(env):
    r, h, store, tp = env
    a = r.ouvrir("claude", prompt_initial="un")
    r.fermer(a["session"])
    sortie = []

    def go(t):
        sortie.append(r.ouvrir("claude", prompt_initial=t, timeout=20))

    ths = [threading.Thread(target=go, args=(t,)) for t in ("lent1", "lent2")]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert len({o["session"] for o in sortie}) == 2
    assert sorted(o["reutilisee"] for o in sortie) == [False, True]


def test_worker_isolee_non_booleen_refuse(env):
    r, h, store, tp = env
    w = _worker(tp, r)
    for mauvais in ("oui", 1, None):
        with pytest.raises(W._Refus):
            w.executer("ouvrir", {"agent": "claude", "texte": "x", "isolee": mauvais})
    assert r.lister() == []


def test_worker_isolee_et_reutilisee(env):
    r, h, store, tp = env
    w = _worker(tp, r)
    a = w.executer("ouvrir", {"agent": "claude", "texte": "un"})
    w.executer("fermer", {"session": a["session"]})
    b = w.executer("ouvrir", {"agent": "claude", "texte": "deux"})
    assert b["session"] == a["session"] and b["reutilisee"] is True
    w.executer("fermer", {"session": b["session"]})
    c = w.executer("ouvrir", {"agent": "claude", "texte": "iso", "isolee": True})
    assert c["session"] != a["session"]


def test_boucle_watch_appelle_purger(env):
    r, h, store, tp = env
    w = _worker(tp, r)
    a = r.ouvrir("claude", prompt_initial="un")
    r.fermer(a["session"])
    h.t += 500
    stop = threading.Event()
    th = threading.Thread(target=w.boucle, args=(0.05, stop))
    th.start()
    for _ in range(100):
        if a["session"] not in r._sessions:
            break
        stop.wait(0.05)
    stop.set()
    th.join()
    assert a["session"] not in r._sessions
