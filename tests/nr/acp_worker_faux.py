"""Aide des NR du worker ACP : faux agent stdio + routeur reel, tout dans tmp_path. Aucun CLI, aucun etat vivant."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_hub as H  # noqa: E402
import forge_acp_router as R  # noqa: E402
import forge_acp_worker as W  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


def nouvelle_cle(kid="kid-test"):
    """(privee, kid, epingle) : cle Ed25519 GENEREE pour le test ; epingle = {kid: octets publics bruts}."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv, kid, {kid: pub}


PRIV, KID, EPINGLE = nouvelle_cle()
KEY = (PRIV, KID)
_SANS = object()
TEMOIN = "ghp_" + "Zq7" * 12

FAUX = r'''
import json, sys, time
def out(o): print(json.dumps(o), flush=True)
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
    elif meth == "session/new":
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s1"}})
    elif meth == "session/prompt":
        txt = m["params"]["prompt"][0]["text"]
        if txt == "lent":
            time.sleep(1.5)
        out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1",
             "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "re:" + txt}}}})
        out({"jsonrpc": "2.0", "id": m["id"], "result": {"stopReason": "end_turn"}})
'''


def routeur(tmp_path):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    base = tmp_path / "wts"
    base.mkdir(exist_ok=True)

    def route(agent):
        d = base / ("acp_" + agent)
        d.mkdir(exist_ok=True)
        return str(d)

    return R.ACPRouter(log_dir=tmp_path / "logs", route=route,
                       cmd_factory=lambda agent: [sys.executable, str(f)])


def worker(tmp_path, rt, epingle=EPINGLE, now=None, **kw):
    return W.AcpWorker(rt, jobs_dir=tmp_path / "jobs", epingle_fn=lambda: epingle,
                       nonce_path=tmp_path / "nonces.log", now=now or time.time, **kw)


def deposer(tmp_path, op, cle=KEY, **params):
    return H.deposer(op, _dossier=tmp_path / "jobs", _cle=cle, **params)


def resultat(tmp_path, jid):
    return H.resultat(jid, _dossier=tmp_path / "jobs")


def attendre(tmp_path, wk, jid, delai=20.0):
    fin = time.time() + delai
    while time.time() < fin:
        wk.scan()
        r = resultat(tmp_path, jid)
        if r["etat"] in ("ACHIEVED", "ILLISIBLE"):
            return r
        time.sleep(0.05)
    raise AssertionError("job non termine : %s" % jid)


def fermer_tout(rt):
    for i in list(rt.lister()):
        rt.fermer(i["id"])
