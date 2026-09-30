# -*- coding: utf-8 -*-
"""NR — la flotte edge n'envoie une requete LLM qu'a un noeud PROUVE capable de la servir.

Avant (27/09), `pick_best_edge` prenait tout noeud en ligne, et `forge_contract_net` tout noeud
tout court (meme STALE) : inscrire le premier noeud reel -- le recepteur world-vector de la VM
DNS, sans LLM -- lui aurait fait gagner l'election. Et un noeud edge passif (il ne pousse aucun
heartbeat) tombait STALE 5 min apres son inscription : `sonder_noeuds_http` le rafraichit en
lisant son /health, sans jamais declarer mort un noeud muet.

Meme doctrine pour la diffusion (28/09) : `broadcast_world_vector` POSTait l'etat-monde a tout
noeud inscrit -- l'hote ollama rendait 404 a chaque diffusion. Seul un noeud qui DECLARE
`world_vector` le recoit, meme STALE ; les autres sont dits, pas tus.
"""
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_edge_fleet as ef  # noqa: E402
import forge_contract_net as cn  # noqa: E402

VM = {"world_vector": True}


@pytest.fixture
def flotte(tmp_path, monkeypatch):
    monkeypatch.setattr(ef, "DB", tmp_path / "edge_fleet.db")
    return ef


def _vieillir(nom, secondes=3600):
    vieux = (datetime.now(timezone.utc) - timedelta(seconds=secondes)).isoformat()
    con = sqlite3.connect(str(ef.DB))
    con.execute("UPDATE edges SET last_seen=? WHERE name=?", (vieux, nom))
    con.commit()
    con.close()


def _par_nom(nom):
    return next(e for e in ef.list_edges() if e["name"] == nom)


def test_un_noeud_sans_llm_n_est_jamais_choisi(flotte):
    flotte.register_edge("edge-stackdns", "http://192.0.2.10:7460", capabilities=VM,
                         metrics={"ram_free_mb": 60000, "device_type": "edge-node"})
    flotte.register_edge("tel", "adb://SERIAL", capabilities={"runtime": "android"},
                         metrics={"ram_free_mb": 50000})
    assert flotte.pick_best_edge("general") is None  # => dispatch_request retombe sur la cascade

    flotte.register_edge("minipc", "http://192.0.2.20:11434", capabilities={"runtime": "ollama"},
                         metrics={"ram_free_mb": 4000})
    assert flotte.pick_best_edge("general")["name"] == "minipc"  # meme avec 15x moins de RAM


def test_contract_net_ecarte_hors_ligne_et_sans_llm(flotte):
    flotte.register_edge("edge-stackdns", "http://192.0.2.10:7460", capabilities=VM)
    flotte.register_edge("minipc", "http://192.0.2.20:11434", capabilities={"runtime": "ollama"})
    flotte.register_edge("vieux", "http://192.0.2.30:11434", capabilities={"runtime": "ollama"})
    _vieillir("vieux")
    bids = cn.collect_bids("code", providers=[], edges=flotte.list_edges(),
                           is_dead=lambda n, uc: False)
    assert [b["worker"] for b in bids] == ["edge:minipc"]


def test_la_sonde_rafraichit_un_noeud_passif_sans_toucher_ses_capacites(flotte):
    import forge_edge_node as node
    srv = HTTPServer(("127.0.0.1", 0), node._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        flotte.register_edge("edge-stackdns", url, capabilities=VM,
                             metrics={"device_type": "edge-node"})
        _vieillir("edge-stackdns")
        assert _par_nom("edge-stackdns")["status"] == "stale"

        rep = flotte.sonder_noeuds_http(timeout=5)
        assert rep == {"edge-stackdns": {"rafraichi": True}}
        e = _par_nom("edge-stackdns")
        assert e["status"] == "online" and e["capabilities"] == VM
        assert flotte.pick_best_edge("general") is None  # en ligne, mais ne sert toujours pas le chat
    finally:
        srv.shutdown()


def test_un_noeud_muet_vieillit_sans_etre_declare_mort(flotte):
    flotte.register_edge("muet", "http://127.0.0.1:9", capabilities=VM,
                         metrics={"device_type": "edge-node"})
    _vieillir("muet")
    rep = flotte.sonder_noeuds_http(timeout=1)
    assert rep["muet"]["rafraichi"] is False and rep["muet"]["motif"]
    assert _par_nom("muet")["status"] == "stale"  # STALE, pas supprime


def test_le_broadcast_world_vector_ne_vise_que_les_noeuds_qui_le_recoivent(flotte):
    import numpy as np
    from http.server import BaseHTTPRequestHandler
    import forge_edge_node as node

    recus = []

    class _Ollama(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            recus.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_a):
            pass

    vm = HTTPServer(("127.0.0.1", 0), node._Handler)
    ollama = HTTPServer(("127.0.0.1", 0), _Ollama)
    for s in (vm, ollama):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        flotte.register_edge("edge-stackdns", "http://127.0.0.1:%d" % vm.server_address[1],
                             capabilities=VM)
        flotte.register_edge("minipc", "http://127.0.0.1:%d" % ollama.server_address[1],
                             capabilities={"runtime": "ollama"})
        flotte.register_edge("tel", "adb://SERIAL", capabilities={"runtime": "android"})
        _vieillir("edge-stackdns")  # passif : STALE n'est pas DEAD, il recoit quand meme
        vec = np.random.default_rng(0).normal(size=4096).astype("float32")
        rep = flotte.broadcast_world_vector(vec, timeout=5)
        assert rep["edges"] == {"edge-stackdns": {"status": 200}}
        assert set(rep["ecartes"]) == {"minipc", "tel"}  # un filtre DIT ce qu'il ecarte
        assert recus == []  # effet cote recepteur : l'hote ollama ne recoit plus rien
    finally:
        vm.shutdown()
        ollama.shutdown()

def test_les_routes_web_importent_ce_qui_existe():
    # l'import exact des routes /api/edge/fleet et /api/edge/stats (chemin reel du rafraichissement)
    src = (ROOT / "app" / "web_hub" / "wired_routes.py").read_text(encoding="utf-8")
    assert "from app.forge_edge_fleet import list_edges, heartbeat_self, sonder_noeuds_http" in src
    assert "from app.forge_edge_fleet import fleet_stats, heartbeat_self, sonder_noeuds_http" in src
    from app.forge_edge_fleet import fleet_stats, heartbeat_self, list_edges, sonder_noeuds_http  # noqa: F401
    assert ef.sert_le_chat({"status": "online", "url": "http://x", "capabilities": {"chat": True}}) is True
