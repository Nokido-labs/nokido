"""NR -- protection MESUREE de la passerelle des pairs web (:8793, exposee par Funnel Tailscale).

Item P1_funnel_pairs_web_protection_mesuree_20261020. Chaque test frappe l'application ASGI
reelle (streamable_http_app, OAuth active) EN MEMOIRE, avec un jeton de pair forge par le meme
mecanisme que le serveur d'autorisation. Aucun reseau, aucune donnee reelle.

Controles (voir sandbox/workspace/rapport_funnel_protection_20261022.md) :
  C1 sans jeton / jeton invalide / mauvaise audience -> 401
  C2 jeton de pair : surface = liste figee, aucun outil d'ecriture/admin ; ring 2 pour lire_vivant
  C3 DLP sur chaque reponse (fail-closed si le pare-feu manque)
  C4 depots en quarantaine owner
  C5 aucune route admin exposee
  C6 journal d'audit de chaque acces  -> ABSENT : xfail strict (RED), a retourner en vert au GREEN
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTETES = {"Accept": "application/json, text/event-stream"}
SECRET_HEX = "ab" * 32
SECRET_ANT = "sk-ant-api03-" + "Q" * 40


@pytest.fixture
def banc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_pair_funnel", ROOT / "tools/forge_pair_mcp.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sandbox = tmp_path / "sandbox"
    (sandbox / "capsules_pair").mkdir(parents=True)
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(m2m)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(m, "dossier_sandbox", lambda: sandbox)
    monkeypatch.setattr(m, "chemin_m2m", lambda: str(m2m))
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", "cle-de-test-funnel")
    # Ring inconnu = refus (decision owner 22/10) : les sujets du banc sont des pairs LISTES (claude, ring 2).
    (tmp_path / "clients.json").write_text(json.dumps(
        [{"client_id": s, "client_name": "claude"} for s in ("pair-test", "pair-depot", "pair-aud", "pair-rev")]),
        encoding="utf-8")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(tmp_path / "clients.json"))
    monkeypatch.delenv("NOKIDO_OAUTH_PASSERELLE", raising=False)
    serveur = m.construire_serveur(oauth=True)
    app = serveur.streamable_http_app()
    serveur._nokido_oauth.poser_complements(app)
    return m, serveur, app, sandbox, m2m


def _jeton(serveur, sujet="pair-test", **plus):
    pont = serveur._nokido_oauth.PONT
    charge = {"sub": sujet, "aud": pont.AUDIENCE, "scope": pont.SCOPE, "resource": "nokido:pair",
              "exp": int(time.time()) + 600, "jti": "t-%s" % sujet, "replay": "multi"}
    charge.update(plus)
    return pont.forger_capacite(charge)


def _rpc(client, methode, params=None, jeton=None, ident=1):
    h = dict(ENTETES)
    if jeton is not None:
        h["Authorization"] = "Bearer " + jeton
    corps = {"jsonrpc": "2.0", "id": ident, "method": methode}
    if params is not None:
        corps["params"] = params
    return client.post("/mcp", json=corps, headers=h)


def _client(app):
    from starlette.testclient import TestClient
    return TestClient(app, base_url="http://127.0.0.1:8793")


# -- C1 : sans jeton -> refus -------------------------------------------------

def test_c1_sans_jeton_jeton_invalide_ou_mauvaise_audience_401(banc):
    _m, serveur, app, *_ = banc
    with _client(app) as c:
        assert _rpc(c, "tools/list").status_code == 401
        assert _rpc(c, "tools/list", jeton="n-importe-quoi").status_code == 401
        assert _rpc(c, "tools/list", jeton=_jeton(serveur, aud="nokido-github")).status_code == 401
        assert _rpc(c, "tools/list", jeton=_jeton(serveur, exp=int(time.time()) - 5)).status_code == 401
        assert _rpc(c, "tools/list", jeton=_jeton(serveur, scope="repo:ecrire")).status_code == 401
        r = _rpc(c, "tools/call", {"name": "etat_corps", "arguments": {}})
        assert r.status_code == 401


def test_c1_jeton_revoque_refuse_des_l_appel_suivant(banc):
    _m, serveur, app, *_ = banc
    with _client(app) as c:
        j = _jeton(serveur, sujet="pair-rev")
        assert _rpc(c, "tools/list", jeton=j).status_code == 200
        serveur._nokido_oauth.revoquer("t-pair-rev")
        assert _rpc(c, "tools/list", jeton=j).status_code == 401


# -- C2 : jeton de pair -> aucune route d'ecriture/admin ----------------------

def test_c2_avec_jeton_de_pair_la_surface_est_la_liste_figee_sans_admin(banc):
    m, serveur, app, *_ = banc
    with _client(app) as c:
        r = _rpc(c, "tools/list", jeton=_jeton(serveur))
        assert r.status_code == 200
        noms = {t["name"] for t in r.json()["result"]["tools"]}
        assert noms == set(m.OUTILS) | {"lire_annexe", "lire_vivant"}
        for faux in ("run", "governed_edit", "hub", "task", "shell"):
            r = _rpc(c, "tools/call", {"name": faux, "arguments": {}}, jeton=_jeton(serveur))
            corps = r.json()
            assert corps.get("error") or corps.get("result", {}).get("isError"), (faux, corps)


def test_c2_ring_du_pair_politique_versionnee_ring2_et_inconnu_ferme(banc, tmp_path, monkeypatch):
    m, *_ = banc
    clients = tmp_path / "clients.json"
    clients.write_text(json.dumps([
        {"client_id": "id-chatgpt", "client_name": "ChatGPT"},
        {"client_id": "id-claude", "client_name": "claude"},
        {"client_id": "id-intrus", "client_name": "claudeX"},
        {"client_id": "id-sans-nom"}]), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(clients))
    assert m._ring_du_pair("id-chatgpt") == 2
    assert m._ring_du_pair("id-claude") == 2
    assert m._ring_du_pair("id-intrus") is None
    assert m._ring_du_pair("id-sans-nom") is None
    assert m._ring_du_pair("id-inexistant") is None
    assert m.lire_vivant("id-intrus", "README.md")["ok"] is False
    monkeypatch.setattr(m, "_ring_du_pair", lambda c: 3)
    r = m.lire_vivant("x", "README.md")
    assert r["ok"] is False and "ring insuffisant" in r["erreur"]


def test_c2_lire_vivant_refuse_secrets_et_evasions_meme_ring2(banc, monkeypatch):
    m, *_ = banc
    monkeypatch.setattr(m, "_ring_du_pair", lambda c: 2)
    for chemin in (".env", "config/Nokido.env", "../../etc/passwd", "C:/Windows/win.ini",
                   "/etc/passwd", "RAG/embeddings.db", ".git/config"):
        assert m.lire_vivant("c", chemin)["ok"] is False, chemin


# -- C3 : DLP sur chaque reponse ----------------------------------------------

def test_c3_reponse_http_d_un_outil_est_redigee(banc):
    _m, serveur, app, sandbox, _db = banc
    (sandbox / "health_diagnostic.json").write_text(json.dumps(
        {"score": 71, "confiance": 0.5, "gaps": ["fuite " + SECRET_HEX, SECRET_ANT]}), encoding="utf-8")
    with _client(app) as c:
        r = _rpc(c, "tools/call", {"name": "etat_corps", "arguments": {}}, jeton=_jeton(serveur))
    assert r.status_code == 200
    assert "71" in r.text
    assert SECRET_HEX not in r.text and SECRET_ANT not in r.text


def test_c3_tout_outil_passe_par_rediger_ast():
    import ast
    arbre = ast.parse((ROOT / "tools/forge_pair_mcp.py").read_text(encoding="utf-8"))
    construire = next(n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "construire_serveur")
    outils = [n for n in ast.walk(construire) if isinstance(n, ast.AsyncFunctionDef)]
    assert len(outils) >= 11
    for f in outils:
        retours = [r.value for r in ast.walk(f) if isinstance(r, ast.Return)]
        assert retours, f.name
        for v in retours:
            appel = ast.dump(v)
            assert "rediger" in appel or "_au_nom_du_pair" in appel, f.name


def test_c3_sans_pare_feu_rien_n_est_rendu(banc, monkeypatch):
    import sys
    m, *_ = banc

    class _Casse:
        def __getattr__(self, nom):
            raise RuntimeError("pare-feu absent")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_semantic_firewall", _Casse())
    sortie = m.rediger({"ok": True, "x": "secret " + SECRET_HEX}, "t")
    assert sortie["ok"] is False and "contenu" not in sortie and SECRET_HEX not in json.dumps(sortie)


# -- C4 : depots en quarantaine owner -----------------------------------------

def test_c4_depot_via_http_entre_en_quarantaine_owner(banc):
    _m, serveur, app, _s, m2m = banc
    with _client(app) as c:
        j = _jeton(serveur, sujet="pair-depot")
        for nom, args in (("proposer_fait", {"texte": "fait", "domaine": "rules"}),
                          ("envoyer_message", {"intent": "COLLAB_PING", "texte": "salut"}),
                          ("soumettre_tache", {"objectif": "x", "destinataire": "CLAUDE", "genre": "executer"})):
            r = _rpc(c, "tools/call", {"name": nom, "arguments": args}, jeton=j)
            assert r.status_code == 200, (nom, r.text)
    con = sqlite3.connect(m2m)
    lignes = con.execute("SELECT to_agent, status, payload FROM agent_messages").fetchall()
    con.close()
    assert len(lignes) == 3
    for to, statut, payload in lignes:
        assert (to, statut) == ("OWNER_APPROBATION", "quarantaine")
        assert json.loads(payload)["approbation"] == "NEED_HUMAN_APPROVAL"


def test_c4_un_pair_ne_porte_pas_d_intent_qui_clot_ou_autorise(banc):
    m, *_ = banc
    for intent in ("OK_DONE", "AUTHZ_GRANTED", "NEED_HUMAN_APPROVAL", "LOCK_ACQUIRED", "PLAN_READY"):
        assert m.deposer_message("c", intent, "t", "OWNER")["ok"] is False, intent


# -- C5 : aucune route admin ---------------------------------------------------

CHEMINS_ADMIN = ("/admin", "/run", "/shell", "/hub", "/mcp/admin", "/api", "/docs", "/openapi.json",
                 "/metrics", "/status", "/health", "/tasks", "/jobs", "/restart", "/exec", "/.env",
                 "/sandbox", "/capsules")


def test_c5_aucune_route_admin_ni_avec_ni_sans_jeton(banc):
    _m, serveur, app, *_ = banc
    j = _jeton(serveur)
    with _client(app) as c:
        for chemin in CHEMINS_ADMIN:
            for h in ({}, {"Authorization": "Bearer " + j}):
                for verbe in ("get", "post"):
                    r = getattr(c, verbe)(chemin, headers=h)
                    assert r.status_code in (401, 404, 405), (verbe, chemin, bool(h), r.status_code)


def test_c5_inventaire_des_routes_est_exactement_celui_attendu(banc):
    _m, _s, app, *_ = banc
    chemins = {getattr(r, "path", "?") for r in app.routes}
    attendus = {"/mcp", "/consentement", "/authorize", "/token", "/register", "/revoke",
                "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/"}
    inattendus = chemins - attendus
    assert not inattendus, "routes non inventoriees : %s" % sorted(inattendus)


# -- CONTRAT (decision owner 22/10) : ring inconnu = refus, par CHAQUE outil --

OUTILS_PAIR = dict(
    etat_corps={}, point_ssot={}, recherche_rag=dict(requete="x"), journal_commits=dict(n=1),
    derniere_capsule={}, proposer_fait=dict(texte="t"), envoyer_message=dict(intent="i", texte="t"),
    soumettre_tache=dict(objectif="o"), suivre=dict(id="pair_x"), lire_reponses={},
    lire_annexe=dict(pointeur="annexe:c/n"), lire_vivant=dict(chemin="README.md"))


def test_pair_au_ring_inconnu_est_refuse_par_chaque_outil_pair_liste_inchange(banc):
    """Un client au jeton valide ABSENT de config/pairs_rings.json est refuse (ok:false, « pair hors
    politique », journal C6 deny) par TOUS les outils (OAuth actif) ; un pair liste n'est pas refuse."""
    _m, serveur, app, sandbox, _db = banc
    with _client(app) as c:
        inconnu = _jeton(serveur, sujet="client-sans-ring")
        liste = _jeton(serveur, sujet="pair-test")
        for outil, args in OUTILS_PAIR.items():
            r = _rpc(c, "tools/call", {"name": outil, "arguments": args}, jeton=inconnu)
            assert "pair hors politique" in r.text and "false" in r.text, (outil, r.text)
            r = _rpc(c, "tools/call", {"name": outil, "arguments": args}, jeton=liste)
            assert "pair hors politique" not in r.text, outil
    lignes = [json.loads(x) for x in (sandbox / "logs" / "pair_acces.jsonl").read_text(encoding="utf-8").splitlines()]
    refus = {x["outil"] for x in lignes if x["client"] == "client-sans-ring" and x["decision"] == "deny"}
    assert refus == set(OUTILS_PAIR)


def test_politique_illisible_refuse_tout_pair(banc, monkeypatch):
    m, serveur, app, *_ = banc
    monkeypatch.setattr(m, "chemin_politique_rings", lambda: "/inexistant/pairs_rings.json")
    with _client(app) as c:
        r = _rpc(c, "tools/call", {"name": "etat_corps", "arguments": {}}, jeton=_jeton(serveur, sujet="pair-test"))
    assert "pair hors politique" in r.text


# -- C6 : journal d'audit de chaque acces -------------------------------------

def test_c6_journal_sans_jeton_ni_corps(banc):
    _m, serveur, app, sandbox, _db = banc
    j = _jeton(serveur, sujet="pair-aud")
    with _client(app) as c:
        _rpc(c, "tools/call", {"name": "recherche_rag", "arguments": {"requete": "CORPS-SECRET-XYZ"}}, jeton=j)
        _rpc(c, "tools/list", jeton="mauvais-jeton-abc")
    brut = (sandbox / "logs" / "pair_acces.jsonl").read_text(encoding="utf-8")
    assert j not in brut and "mauvais-jeton-abc" not in brut and "CORPS-SECRET-XYZ" not in brut
    assert all(set(json.loads(x)) == {"ts", "client", "outil", "decision", "code"} for x in brut.splitlines())
    assert '"code": 401' in brut


def test_c6_chaque_acces_laisse_une_ligne_d_audit(banc):
    _m, serveur, app, sandbox, _db = banc
    with _client(app) as c:
        _rpc(c, "tools/call", {"name": "etat_corps", "arguments": {}}, jeton=_jeton(serveur, sujet="pair-aud"))
        _rpc(c, "tools/call", {"name": "etat_corps", "arguments": {}})
    journal = sandbox / "logs" / "pair_acces.jsonl"
    lignes = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lignes) >= 2
    assert {x.get("decision") for x in lignes} >= {"allow", "deny"}
    assert any(x.get("client") == "pair-aud" and x.get("outil") == "etat_corps" for x in lignes)
