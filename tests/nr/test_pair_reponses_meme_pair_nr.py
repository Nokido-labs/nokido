# -*- coding: utf-8 -*-
"""NR — la session du jour d'un pair lit la reponse adressee a son inscription d'hier.

Mesure 2026-09-29 : claude.ai s'inscrit comme un NOUVEAU client OAuth a chaque autorisation
(trois « Claude » au registre) ; la reponse de l'owner, adressee a PAIR:<id d'hier>, etait
invisible a la session du jour (« limite par conversation », owner). Regroupement par NOM de
client -- jamais au-dela : ChatGPT ne lit pas ce qui va a Claude, un client sans nom ne lit que
ses propres reponses.
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def pair(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("forge_pair_mcp_nr_meme_pair", ROOT / "tools" / "forge_pair_mcp.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    base = tmp_path / "m2m.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
                "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(m, "chemin_m2m", lambda: str(base))
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_postal
    monkeypatch.setattr(forge_postal, "DB", tmp_path / "postal.db")   # l'accuse « reponse lue » y est poste
    registre = tmp_path / "clients.json"
    registre.write_text(json.dumps([{"client_id": "ancien", "client_name": "Claude"},
                                    {"client_id": "nouveau", "client_name": "Claude"},
                                    {"client_id": "gpt", "client_name": "ChatGPT"},
                                    {"client_id": "anonyme"}]), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(registre))
    return m, base


def _poser(base, ident, vers):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?)",
                (ident, "OWNER_APPROBATION", vers, ident, "pair.reponse", json.dumps({"intent": "OK_DONE"}),
                 "unread", "2026-09-29T10:00:00+00:00"))
    con.commit()
    con.close()


def test_la_session_du_jour_lit_la_reponse_de_l_inscription_d_hier(pair):
    m, base = pair
    _poser(base, "r_hier", "PAIR:ancien")
    _poser(base, "r_gpt", "PAIR:gpt")
    lues = [r["id"] for r in m.relever_reponses("nouveau")["reponses"]]
    assert lues == ["r_hier"], lues
    assert m.relever_reponses("nouveau")["reponses"] == [], "une reponse lue revient"
    assert [r["id"] for r in m.relever_reponses("gpt")["reponses"]] == ["r_gpt"]


def test_sans_nom_ou_sans_registre_on_ne_lit_que_les_siennes(pair, monkeypatch):
    m, base = pair
    assert m.clients_du_meme_pair("anonyme") == ["anonyme"]
    assert m.clients_du_meme_pair("inconnu") == ["inconnu"]
    monkeypatch.delenv("NOKIDO_BRIDGE_OAUTH_CLIENTS")
    assert m.clients_du_meme_pair("nouveau") == ["nouveau"]
