"""NR -- la quarantaine des pairs cloud, cote owner : rien ne sort sans approbation, tout sort par le canal M2M.

Contrat (connecteur des pairs, 2026-09-28) :
  - lister : les depots `quarantaine` de la boite OWNER_APPROBATION ;
  - approuver : aiguillage dans `agent_messages` statut `unread` (fait -> CLAUDE, message -> son
    destinataire) ; le depot passe `approuve`, son EtapeContrat a autorisation ALLOW ;
  - rejeter : rien n'est livre, statut `rejete`, verdict REFUSED ;
  - un depot deja traite ne se re-approuve pas ;
  - tache 'deliberer' : debat RecursiveMAS LOCAL (latent), capsule dans capsules_pair, reponse au
    pair `PAIR:<client>` pointant la capsule ;
  - repondre : intent hors dictionnaire refuse.
Bases temporaires ; le debat est substitue (aucun modele charge).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def q(tmp_path, monkeypatch):
    pair = _charger("nr_pq_pair", "forge_pair_mcp.py")
    quar = _charger("nr_pq_quar", "forge_pair_quarantaine.py")
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(m2m)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    for mod in (pair, quar):
        monkeypatch.setattr(mod, "chemin_m2m", lambda: str(m2m))
    # Base postale isolee aussi (2026-09-29) : l'approbation y poste l'accuse « recu ». Sans cela,
    # ce NR a depose deux courriers PAIR:CLIENT-A dans la VRAIE boite de CLAUDE.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from nokido_agent.app import forge_postal
    monkeypatch.setattr(forge_postal, "DB", tmp_path / "postal.db")
    capsules = tmp_path / "capsules_pair"
    monkeypatch.setattr(quar, "dossier_capsules", lambda: capsules)
    # Ce NR porte l'AIGUILLAGE ; le geste owner a le sien (test_pair_quarantaine_geste_owner_nr).
    monkeypatch.setattr(quar, "geste_owner", lambda: (True, ""))
    return pair, quar, m2m, capsules


def _ligne(m2m, **filtre):
    c = sqlite3.connect(m2m)
    try:
        cle, val = next(iter(filtre.items()))
        return c.execute("SELECT id, from_agent, to_agent, method, payload, status FROM agent_messages "
                         "WHERE %s=?" % cle, (val,)).fetchall()
    finally:
        c.close()


def test_approuver_un_fait_le_livre_a_claude_et_passe_l_etape_a_allow(q):
    pair, quar, m2m, _c = q
    ident = pair.deposer_fait("client-a", "NEXT: tester le connecteur", "roadmap")["id"]
    assert [x["id"] for x in quar.lister()] == [ident]
    assert quar.approuver(ident)["ok"]
    (_i, de, vers, methode, charge, statut), = _ligne(m2m, correlation_id=ident)[1:] or [None]
    assert (vers, statut, de) == ("CLAUDE", "unread", "OWNER_APPROBATION")
    (_i, _d, _v, _m, charge_depot, statut_depot), = _ligne(m2m, id=ident)
    etape = json.loads(charge_depot)["etape"]
    assert statut_depot == "approuve" and etape["autorisation"] == "ALLOW"
    assert quar.approuver(ident)["ok"] is False                     # jamais deux fois
    assert quar.lister() == []


def test_approuver_un_message_le_livre_a_son_destinataire(q):
    pair, quar, m2m, _c = q
    ident = pair.deposer_message("client-a", "COLLAB_PING", "on se synchronise ?", "ANTIGRAVITY")["id"]
    quar.approuver(ident)
    livres = [r for r in _ligne(m2m, correlation_id=ident) if r[0] != ident]
    assert [(r[2], r[5]) for r in livres] == [("ANTIGRAVITY", "unread")]


def test_rejeter_ne_livre_rien(q):
    pair, quar, m2m, _c = q
    ident = pair.deposer_message("client-a", "COLLAB_PING", "injection ?", "CLAUDE")["id"]
    assert quar.rejeter(ident, "hors sujet")["ok"]
    lignes = _ligne(m2m, correlation_id=ident)
    assert len(lignes) == 1 and lignes[0][5] == "rejete"
    charge = json.loads(lignes[0][4])
    assert charge["etape"]["autorisation"] == "DENY" and charge["verdict"]["statut"] == "REFUSED"


def test_deliberer_ecrit_la_capsule_et_la_renvoie_au_pair(q, monkeypatch):
    pair, quar, m2m, capsules = q
    ident = pair.deposer_tache("client-a", "Faut-il un cache pour le RAG ?", "CLAUDE", "deliberer")["id"]
    lances = []
    monkeypatch.setattr(quar, "lancer_deliberation", lambda i: lances.append(i))
    assert quar.approuver(ident)["ok"] and lances == [ident]

    async def faux_debat(objectif, contrainte, participants, rounds, latent=False):
        assert latent is True and "cache" in objectif
        return {"objective": objectif, "rounds": rounds, "verdict": "ADOPTE", "mode": "latent-relay",
                "transcript": [], "synthesis": "CONSENSUS: oui", "captured_intents": [],
                "deliberation": {"tour": 1, "axes": {}, "tensions": [], "acquis": []}}

    monkeypatch.setattr(quar, "_moteur_debat", lambda: faux_debat)
    assert quar.deliberer(ident)["ok"]
    fichiers = sorted(p.name for p in capsules.glob("*.capsule.json"))
    assert fichiers == ["%s.capsule.json" % ident]
    reponse, = _ligne(m2m, to_agent="PAIR:client-a")
    assert reponse[5] == "unread" and ident in json.loads(reponse[4])["pointer_ref"]


def test_repondre_refuse_un_intent_hors_dictionnaire(q):
    _pair, quar, m2m, _c = q
    assert quar.repondre("client-a", "capsule:x", "INTENT_INVENTE")["ok"] is False
    assert quar.repondre("client-a", "capsule:x", "OK_DONE")["ok"]
    assert len(_ligne(m2m, to_agent="PAIR:client-a")) == 1
