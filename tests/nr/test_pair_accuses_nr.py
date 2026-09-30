# -*- coding: utf-8 -*-
"""NR — les cinq accuses d'un echange de pair : envoye, recu, lu, repondu, reponse lue.

Owner 2026-09-29 : « des accuses lecture/envoi/reception/reponse seraient les bienvenus, nous
avons l'agent postal pour cela ». Ce NR parcourt un echange complet sur des bases TEMPORAIRES
(M2M et postal) et exige que chaque etape soit horodatee au bon moment -- ni avant, ni jamais --
et qu'un pair ne suive QUE ses propres depots.
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.66)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def monde(monkeypatch, tmp_path):
    base = tmp_path / "m2m.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
                "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    charge = {"intent": "HANDOFF_NEXT", "pointer_ref": "pair:pair_0123456789abcdef", "destinataire": "CLAUDE",
              "genre": "executer", "texte": "revoir le design", "provenance": {"client": "nouveau"}}
    con.execute("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?)",
                ("pair_0123456789abcdef", "PAIR:nouveau", "OWNER_APPROBATION", "pair_0123456789abcdef",
                 "pair.soumettre_tache", json.dumps(charge), "quarantaine", "2026-09-29T09:00:00+00:00"))
    con.commit()
    con.close()
    from nokido_agent.app import forge_postal, forge_ordres_bureau
    monkeypatch.setattr(forge_postal, "DB", tmp_path / "postal.db")
    monkeypatch.setattr(forge_ordres_bureau, "JOURNAL", tmp_path / "ordres.jsonl")
    q = _charger("forge_pair_quarantaine_nr_accuses", "forge_pair_quarantaine.py")
    monkeypatch.setattr(q, "chemin_m2m", lambda: str(base))
    pm = _charger("forge_pair_mcp_nr_accuses", "forge_pair_mcp.py")
    monkeypatch.setattr(pm, "chemin_m2m", lambda: str(base))
    monkeypatch.setattr(pm, "_quarantaine", lambda: q)
    registre = tmp_path / "clients.json"
    registre.write_text(json.dumps([{"client_id": "nouveau", "client_name": "Claude"},
                                    {"client_id": "gpt", "client_name": "ChatGPT"}]), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(registre))
    return q, pm, forge_postal, forge_ordres_bureau


def test_un_echange_complet_pose_les_cinq_accuses_dans_l_ordre(monde):
    q, pm, postal, ob = monde
    ident = "pair_0123456789abcdef"
    e = q.suivi(ident)["etapes"]
    assert e["envoye"] and e["recu"] is None and e["lu"] is None and e["repondu"] == []

    r = q.approuver(ident, preuve=ob.emettre_preuve("pair-approuver", ident))
    assert r["ok"] and r["accuse"]["courrier"], r
    assert q.suivi(ident)["etapes"]["recu"] is None, "recu avant que le facteur n'ait livre"

    con = postal._conn()
    canal = con.execute("SELECT recipient_channel FROM mail WHERE trace_id=?", ("pair:" + ident,)).fetchone()[0]
    con.close()
    postal.facteur(canal)
    e = q.suivi(ident)["etapes"]
    assert e["recu"] and e["lu"] is None

    assert q.accuser_lecture(ident, "CLAUDE")["ok"]
    assert q.suivi(ident)["etapes"]["lu"]

    rep = q.repondre("nouveau", "pair:" + ident, "OK_DONE", "fait",
                     preuve=ob.emettre_preuve("pair-repondre", "nouveau"))
    assert rep["ok"], rep
    e = q.suivi(ident)["etapes"]
    assert len(e["repondu"]) == 1 and e["reponse_lue"][0]["lue"] is False and e["reponse_lue"][0]["a"] is None

    assert [x["id"] for x in pm.relever_reponses("nouveau")["reponses"]] == [rep["id"]]
    e = q.suivi(ident)["etapes"]
    assert e["reponse_lue"][0]["lue"] is True and e["reponse_lue"][0]["a"], e


def test_un_pair_ne_suit_que_ses_propres_depots(monde):
    q, pm, _postal, _ob = monde
    assert pm.suivre_depot("nouveau", "pair_0123456789abcdef")["ok"] is True
    autre = pm.suivre_depot("gpt", "pair_0123456789abcdef")
    assert autre["ok"] is False and "PAIR:" not in json.dumps(autre), "le refus ne doit pas dire a qui il appartient"
    assert pm.suivre_depot("nouveau", "pair_pas-un-identifiant")["ok"] is False, "identifiant mal forme accepte"
