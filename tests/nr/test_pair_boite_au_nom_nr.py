# -*- coding: utf-8 -*-
"""NR (19/10, tache claude.ai apr_1f4408f74c3c9af4 jamais recue) : une reponse adressee au NOM d'un pair arrive.

Mesure : l'ordre `pair-repondre` (cible = nom du pair, comme les rings de config/pairs_rings.json) livre dans
`PAIR:claude` ; `lire_reponses` ne relevait que `PAIR:<client_id OAuth>` des identifiants du meme pair. La session
claude.ai du jour (nouvel identifiant) a vu sa boite vide -- le message dormait `unread` dans `PAIR:claude`. La releve
lit desormais aussi la boite au NOM du pair (registre OAuth, `_nom_du_client`) -- jamais celle d'un AUTRE pair.
"""
import sqlite3

from nokido_agent.tools import forge_pair_mcp as P


def _base(tmp_path, monkeypatch, nom):
    db = tmp_path / "m2m.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE agent_messages (id TEXT, from_agent TEXT, to_agent TEXT, correlation_id TEXT, method TEXT, "
              "payload TEXT, result TEXT, status TEXT, created_at TEXT, read_at TEXT)")
    for ident, boite in (("apr_nom", "PAIR:claude"), ("apr_autre", "PAIR:chatgpt"), ("apr_id", "PAIR:uuid-x")):
        c.execute("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (ident, "OWNER_APPROBATION", boite, "", "pair.reponse", '{"texte": "x"}', None, "unread",
                   "2026-10-19T09:53:30", None))
    c.commit()
    c.close()
    monkeypatch.setattr(P, "chemin_m2m", lambda: db)
    monkeypatch.setattr(P, "_client_valide", lambda c: True)
    monkeypatch.setattr(P, "clients_du_meme_pair", lambda c: [c])
    monkeypatch.setattr(P, "_nom_du_client", lambda c: nom)
    monkeypatch.setattr(P, "_accuser_reponse_lue", lambda c, r: None)


def test_la_boite_au_nom_du_pair_est_relevee_jamais_celle_d_un_autre(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch, "claude")
    r = P.relever_reponses("uuid-x")
    assert r["ok"] and {x["id"] for x in r["reponses"]} == {"apr_nom", "apr_id"}


def test_client_sans_nom_au_registre_comportement_d_avant(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch, None)
    r = P.relever_reponses("uuid-x")
    assert {x["id"] for x in r["reponses"]} == {"apr_id"}
