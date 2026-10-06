"""NR -- connecteur MCP des PAIRS cloud : surface FIGEE, lecture en liste blanche, collaboration en QUARANTAINE.

Owner, 2026-09-28 : claude.ai et ChatGPT sont des PAIRS (M2M / A2A), pas de simples lecteurs, et
ecrivent dans le SSoT -- mais un texte venu du cloud peut etre une injection. Contrat :
  - les outils exposes sont EXACTEMENT la liste figee (aucun run / edit / job / fichier / secret) ;
  - recherche RAG : seules les sources de la liste blanche sortent ; SSoT : roadmap et rules seulement ;
  - tout depot d'un pair entre dans `agent_messages` au statut `quarantaine`, vers la boite
    d'approbation owner, avec une EtapeContrat (harness) au statut REQUESTED et NEED_HUMAN_APPROVAL :
    les clients ne relevent que `unread`, donc rien n'atteint un agent avant approbation ;
  - debit borne par client ; intent M2M hors dictionnaire refuse ; destinataire hors liste refuse ;
  - un pair ne lit que les reponses qui lui sont adressees ;
  - toute sortie est bornee et REDIGEE -- y compris les formes que le pare-feu ne connait pas
    (cle Anthropic, jeton hexadecimal de 64 caracteres : mesure du 2026-09-28).
Donnees factices ; bases temporaires.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pair(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_pair_mcp", ROOT / "tools/forge_pair_mcp.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sandbox = tmp_path / "sandbox"
    (sandbox / "capsules_pair").mkdir(parents=True)
    rag, m2m = tmp_path / "rag.db", tmp_path / "m2m.db"
    c = sqlite3.connect(rag)
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    c.executemany("INSERT INTO rag_fts VALUES (?,?,?,?)", [
        ("c1", "le routeur local choisit un modele", "https://exemple.org/routeur", "web"),
        ("c2", "le routeur local et une note interne privee", "session:2026-09-28:notes", "memo"),
        ("c3", "le routeur local dans la doc Go", "docset:Go#net", "doc"),
        ("c4", "le routeur local offensif", "exegol:outil", "sec"),
    ])
    c.commit()
    c.close()
    c = sqlite3.connect(m2m)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(m, "dossier_sandbox", lambda: sandbox)
    monkeypatch.setattr(m, "chemin_rag", lambda: rag)
    monkeypatch.setattr(m, "chemin_m2m", lambda: str(m2m))
    return m, sandbox, m2m


def _lignes(m2m):
    c = sqlite3.connect(m2m)
    try:
        return c.execute("SELECT from_agent, to_agent, method, payload, status FROM agent_messages").fetchall()
    finally:
        c.close()


def test_la_surface_exposee_est_exactement_la_liste_figee(pair):
    m, _s, _db = pair
    serveur = m.construire_serveur(oauth=False)
    noms = sorted(t.name for t in asyncio.run(serveur.list_tools()))
    assert noms == sorted(m.OUTILS)
    assert set(m.OUTILS) == {"etat_corps", "point_ssot", "recherche_rag", "journal_commits",
                             "derniere_capsule", "proposer_fait", "envoyer_message",
                             "soumettre_tache", "lire_reponses",
                             "suivre"}   # accuses de SES depots, lecture seule (owner 2026-09-29)
    source = (ROOT / "tools/forge_pair_mcp.py").read_text(encoding="utf-8")
    for interdit in ("governed_edit", "run_job", "forge_mcp_registry", "nokido_hub", "get_secret",
                     "forge_machine_vault", "trusted_script"):
        assert interdit not in source, interdit


def test_chaque_capsule_porte_la_regle_de_depot_prive(pair):
    """Owner 2026-10-06 : le depot de distribution est PUBLIC ; claude.ai y poussait ses branches
    (commits signes Claude, un Co-Authored-By). La regle voyage avec CHAQUE capsule, meme une
    capsule qui ne nomme aucun depot."""
    m, sandbox, _ = pair
    (sandbox / "capsules_pair" / "mission.capsule.json").write_text(
        json.dumps({"missions": [{"branche": "claude/x"}]}), encoding="utf-8")
    r = m.lire_derniere_capsule()
    assert r["ok"] and r["regle_de_depot"]["depot_de_travail"] == "Nokido-labs/nokido-private"
    assert "Nokido-labs/nokido " in r["regle_de_depot"]["interdit"]
    assert "Co-Authored-By" in r["regle_de_depot"]["commits"]


def test_recherche_rag_ne_rend_que_les_sources_exposables(pair):
    m, _s, _db = pair
    r = m.rechercher_rag("routeur local", 10)
    sources = {x["source"] for x in r["resultats"]}
    assert r["ok"] and sources == {"https://exemple.org/routeur", "docset:Go#net"}


def test_point_ssot_refuse_hors_liste_blanche(pair):
    m, _s, _db = pair
    assert m.lire_point_ssot("memory")["ok"] is False


def test_un_depot_entre_en_quarantaine_avec_son_etape_de_harness(pair):
    m, _s, db = pair
    r = m.deposer_fait("client-claude", "NEXT: brancher le connecteur", "roadmap")
    assert r["ok"] and r["statut"] == "quarantaine"
    (de, vers, methode, charge, statut), = _lignes(db)
    charge = json.loads(charge)
    assert (de, vers, methode, statut) == ("PAIR:client-claude", "OWNER_APPROBATION", "pair.proposer_fait",
                                           "quarantaine")
    assert charge["approbation"] == "NEED_HUMAN_APPROVAL" and charge["intent"] == "FACT_PROPOSED"
    assert set(charge["etape"]) == {"objectif", "etat_avant", "capacite", "preconditions", "autorisation",
                                    "action", "observation", "effet_attendu", "effet_observe", "preuve",
                                    "etat_apres", "prochain_objectif"}
    assert charge["verdict"]["statut"] == "REQUESTED"
    assert charge["provenance"]["confiance"] == "EXTERNE_NON_VERIFIEE"


def test_debit_intent_et_destinataire_bornes(pair, monkeypatch):
    m, _s, _db = pair
    assert m.deposer_message("client-x", "INTENT_INVENTE", "salut", "CLAUDE")["ok"] is False
    assert m.deposer_message("client-x", "COLLAB_PING", "salut", "ROOT_SHELL")["ok"] is False
    assert m.deposer_tache("client-x", "analyse", "CLAUDE", "formater_disque")["ok"] is False
    monkeypatch.setattr(m, "DEBIT_PAR_HEURE", 2)
    assert m.deposer_message("client-x", "COLLAB_PING", "un", "CLAUDE")["ok"]
    assert m.deposer_tache("client-x", "deux", "ANTIGRAVITY", "deliberer")["ok"]
    assert m.deposer_fait("client-x", "trois", "roadmap")["ok"] is False
    assert m.deposer_fait("", "anonyme", "roadmap")["ok"] is False


def test_un_pair_ne_lit_que_ses_reponses(pair):
    m, _s, db = pair
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?)", [
        ("r1", "CLAUDE", "PAIR:client-a", "r1", "notify", json.dumps({"intent": "OK_DONE", "pointer_ref": "cap:1"}), "unread", "2026-09-28T10:00:00+00:00"),
        ("r2", "CLAUDE", "PAIR:client-b", "r2", "notify", json.dumps({"intent": "OK_DONE", "pointer_ref": "cap:2"}), "unread", "2026-09-28T10:00:01+00:00"),
    ])
    c.commit()
    c.close()
    r = m.relever_reponses("client-a")
    assert [x["id"] for x in r["reponses"]] == ["r1"]
    assert m.relever_reponses("client-a")["reponses"] == []          # lue une fois
    assert [x["id"] for x in m.relever_reponses("client-b")["reponses"]] == ["r2"]


def test_avec_oauth_un_appel_sans_jeton_est_refuse_401_rfc9728(pair, monkeypatch, tmp_path):
    """Chemin reel HTTP : sans habilitation, 401 + defi portant `resource_metadata` (RFC 9728),
    et la passerelle chargee est celle des pairs -- sans rester forcee dans l'environnement."""
    import os

    from starlette.testclient import TestClient

    m, _s, _db = pair
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", "cle-de-test-pair")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(tmp_path / "clients_pair.json"))
    monkeypatch.delenv("NOKIDO_OAUTH_PASSERELLE", raising=False)
    serveur = m.construire_serveur(oauth=True)
    assert serveur._nokido_oauth.PONT.AUDIENCE == "nokido-pair"
    assert "NOKIDO_OAUTH_PASSERELLE" not in os.environ
    application = serveur.streamable_http_app()
    serveur._nokido_oauth.poser_complements(application)
    with TestClient(application) as client:
        r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 401
        assert "resource_metadata" in r.headers.get("www-authenticate", "")


def test_toute_sortie_est_redigee_meme_ce_que_le_pare_feu_ignore(pair):
    m, sandbox, _db = pair
    jeton_hex = "e3" * 32
    cle_ant = "sk-ant-api03-" + "Z" * 40
    cle_gh = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    (sandbox / "health_diagnostic.json").write_text(json.dumps(
        {"score": 87, "confiance": 0.9, "gaps": ["❌ fuite " + jeton_hex, "❌ " + cle_ant, "❌ " + cle_gh]}),
        encoding="utf-8")
    sortie = m.rediger(m.lire_etat_corps(), "etat_corps")["contenu"]
    assert "87" in sortie
    for valeur in (jeton_hex, cle_ant, cle_gh):
        assert valeur not in sortie
