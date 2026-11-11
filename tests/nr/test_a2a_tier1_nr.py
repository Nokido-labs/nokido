"""NR — A2A Tier 1 : securite d'abord, carte honnete, cycle de vie tracable.

Ecrit EN MEME TEMPS que le serveur (consigne owner n.4 : security by design, pas
apres coup). Ces tests portent sur le COMPORTEMENT, pas sur la presence du code.

Ce qu'ils verrouillent, et pourquoi chaque point a ete paye :
  - un client non authentifie est REFUSE, un faux jeton aussi ;
  - un coffre illisible REFUSE (fail-closed) — ouvrir faute d'avoir pu lire le
    secret est le defaut `sandbox=<inconnu>` du 2026-09-01, ou une entree
    invalide obtenait PLUS de droits qu'une valide ;
  - l'identite vient du JETON, par `verifier_slot`, et de lui seul : un en-tete
    declaratif n'etablit ni ne change rien (07/11, l'ancien test qui verrouillait
    l'identite declarative est reecrit) ; plus de repli sur le jeton du hub ;
  - cloisonnement : get/cancel ne servent que le proprietaire, autrui recoit la
    reponse d'une tache inconnue ; sortie en liste blanche ;
  - `taskId` client : inconnu => TaskNotFound, jamais de creation ni d'ecrasement ;
  - `canceled` atteignable (envoi non bloquant + tasks/cancel) ; registre borne ;
  - la carte n'annonce QUE des capacites prouvees ET joignables, en `protocolVersion`
    majeure.mineure ;
  - une capacite annoncee `streaming` sans `message/stream` serait un mensonge
    (mesure par le comportement : l'ancien `or True` etait un faux vert).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours tests/nr (code appele); sous-processus
#   git (code appele) (l.133)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom):
    chemin = ROOT / "tools" / (nom + ".py")
    if not chemin.exists():
        pytest.skip("%s absent" % chemin)
    for zone in ("tools", "app"):
        p = str(ROOT / zone)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ securite ----

# VERIFICATEUR EPINGLE (07/11). L'identite vient du JETON par la voie
# `verifier_slot` (app/forge_llm_format_bridge.py). Les tests remplacent ce
# verificateur par un double : aucun jeton reel n'est lu, copie ni affiche, et le
# chemin teste est celui qu'annonce le nom du test, pas l'etat du coffre ambiant.

def _slot(agent):
    """Double de `verifier_slot` : n'accepte que le jeton factice `jeton-<agent>`."""
    def _v(authorization):
        if not (authorization or "").lower().startswith("bearer "):
            return False, "missing_or_invalid_auth_header", None
        if authorization.split(" ", 1)[1].strip() != "jeton-" + agent:
            return False, "invalid_or_unrecognized_token", None
        return True, "", {"agent": agent, "tache": None, "voie": "jeton_agent"}
    return _v


def test_a2a_refuse_sans_bearer(monkeypatch):
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_verificateur", lambda: _slot("AGY"))
    ok, agent, motif = srv.admission({})
    assert ok is False and agent is None
    assert motif


def test_a2a_refuse_un_faux_jeton(monkeypatch):
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_verificateur", lambda: _slot("AGY"))
    ok, agent, motif = srv.admission({"Authorization": "Bearer pas-le-bon"})
    assert ok is False and agent is None and "invalid" in motif


def test_a2a_est_fail_closed_si_le_verificateur_est_illisible(monkeypatch):
    """Verificateur introuvable ou qui leve => REFUS. Contre-epreuve sandbox=<inconnu>."""
    srv = _charger("forge_a2a_server")

    def _absent():
        raise ImportError("test")
    monkeypatch.setattr(srv, "_verificateur", _absent)
    ok, agent, motif = srv.admission({"Authorization": "Bearer n-importe-quoi"})
    assert ok is False and agent is None and "FAIL-CLOSED" in motif

    def _leve(_a):
        raise RuntimeError("test")
    monkeypatch.setattr(srv, "_verificateur", lambda: _leve)
    ok, agent, motif = srv.admission({"Authorization": "Bearer n-importe-quoi"})
    assert ok is False and agent is None and "FAIL-CLOSED" in motif


def test_a2a_l_identite_vient_du_jeton_jamais_de_l_entete(monkeypatch):
    """`X-Agent-Name` est IGNORE : l'identite est celle du slot prouve par le jeton.

    Remplace le test qui verrouillait l'identite DECLARATIVE (Bearer valide +
    `X-Agent-Name: AGY` => agent == "AGY") : un jeton valide de CLAUDE ne doit pas
    pouvoir se faire passer pour AGY en posant un en-tete.
    """
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_verificateur", lambda: _slot("CLAUDE"))
    ok, agent, _ = srv.admission({"X-Agent-Name": "ADMIN"})
    assert ok is False and agent is None, "un nom sans jeton n'identifie jamais"
    ok, agent, _ = srv.admission({"Authorization": "Bearer jeton-CLAUDE",
                                  "X-Agent-Name": "AGY"})
    assert ok is True and agent == "CLAUDE", (
        "l'en-tete declaratif a ecrase l'identite du jeton : %r" % agent)


def test_a2a_n_a_plus_de_repli_sur_le_jeton_du_hub():
    """Aucune constante `FORGE_MCP_TOKEN` / `FORGE_A2A_TOKEN` dans le CODE du serveur.

    Le jeton du hub ne designe aucun slot : l'accepter, c'est n'avoir aucune
    identite. Mesure par l'AST (les commentaires et docstrings ne comptent pas).
    """
    import ast
    src = (ROOT / "tools" / "forge_a2a_server.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    docs = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            d = ast.get_docstring(n, clean=False)
            if d:
                docs.add(d)
    consts = [n.value for n in ast.walk(arbre)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and n.value not in docs]
    fautifs = [c for c in consts if "FORGE_MCP_TOKEN" in c or "FORGE_A2A_TOKEN" in c
               or "X-Agent-Name" in c]
    assert not fautifs, "repli jeton hub / identite declarative encore present : %r" % fautifs


# -------------------------------------------------------- cycle de vie ----

def _texte(t):
    return {"message": {"role": "user", "parts": [{"kind": "text", "text": t}]}}


def test_a2a_cycle_message_send_puis_get():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("message/send", _texte("salut"), 1, "AGY")
    t = rep["result"]
    assert t["status"]["state"] == srv.TERMINEE
    assert t["artifacts"], "une tache terminee doit porter un artefact"
    lu = srv.traiter("tasks/get", {"id": t["id"]}, 2, "AGY")["result"]
    assert lu["id"] == t["id"]
    assert lu["status"]["state"] == srv.TERMINEE


def test_a2a_annuler_une_tache_achevee_est_refuse_explicitement():
    """Le silence ferait croire a l'appelant qu'il a annule."""
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send",
                    {"message": {"role": "user", "parts": []}}, 1, "AGY")["result"]
    rep = srv.traiter("tasks/cancel", {"id": t["id"]}, 2, "AGY")
    assert "error" in rep and rep["error"]["code"] == -32002


# ------------------------------------------------------- cloisonnement ----

def test_a2a_get_et_cancel_ne_servent_que_le_proprietaire():
    """Autre appelant = reponse IDENTIQUE a une tache inconnue (spec 13.1)."""
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send", {**_texte("secret d'AGY"),
                                     "configuration": {"blocking": False}},
                    1, "AGY")["result"]
    inconnu_get = srv.traiter("tasks/get", {"id": "task-inexistante"}, 7, "CLAUDE")
    autrui_get = srv.traiter("tasks/get", {"id": t["id"]}, 7, "CLAUDE")
    assert autrui_get == inconnu_get, "la reponse revele l'existence de la tache"
    inconnu_cancel = srv.traiter("tasks/cancel", {"id": "task-inexistante"}, 8, "CLAUDE")
    autrui_cancel = srv.traiter("tasks/cancel", {"id": t["id"]}, 8, "CLAUDE")
    assert autrui_cancel == inconnu_cancel
    # et la tache d'AGY n'a PAS ete annulee par CLAUDE
    lu = srv.traiter("tasks/get", {"id": t["id"]}, 9, "AGY")["result"]
    assert lu["status"]["state"] != srv.ANNULEE


def test_a2a_get_ne_rend_que_la_liste_blanche():
    """En sortie : state, attempt, cause_echec, empreinte opaque (+ id/contextId/kind)."""
    import json as _json
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send", _texte("contenu-prive-42"), 1, "AGY")["result"]
    for meth in ("tasks/get",):
        lu = srv.traiter(meth, {"id": t["id"]}, 2, "AGY")["result"]
        assert set(lu) <= {"kind", "id", "contextId", "status", "metadata"}, set(lu)
        assert set(lu["status"]) <= {"state", "timestamp"}
        assert set(lu["metadata"]) == {"attempt", "cause_echec", "empreinte"}
        assert "contenu-prive-42" not in _json.dumps(lu)
        assert isinstance(lu["metadata"]["empreinte"], str) and lu["metadata"]["empreinte"]


def test_a2a_la_tache_ne_porte_aucun_champ_hors_schema():
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send", _texte("x"), 1, "AGY")["result"]
    assert not [k for k in t if ":" in k], "champ hors schema : %r" % list(t)


# -------------------------------------------------------------- taskId ----

def test_a2a_taskid_inconnu_fourni_par_le_client_est_refuse():
    """Spec 3.4.2 : taskId inconnu => TaskNotFoundError, jamais de creation."""
    srv = _charger("forge_a2a_server")
    for params in ({**_texte("a"), "taskId": "task-choisi-par-le-client"},
                   {"message": {"role": "user", "taskId": "task-choisi-par-le-client",
                                "parts": [{"kind": "text", "text": "a"}]}}):
        rep = srv.traiter("message/send", params, 1, "AGY")
        assert rep.get("error", {}).get("code") == -32001, rep
    rep = srv.traiter("tasks/get", {"id": "task-choisi-par-le-client"}, 2, "AGY")
    assert rep["error"]["code"] == -32001, "la tache a ete creee par le client"


def test_a2a_taskid_existant_n_est_pas_ecrase():
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send", {**_texte("premier"),
                                     "configuration": {"blocking": False}},
                    1, "AGY")["result"]
    # autrui ne peut ni ecraser ni continuer la tache d'AGY
    rep = srv.traiter("message/send", {**_texte("intrus"), "taskId": t["id"]}, 2, "CLAUDE")
    assert rep.get("error", {}).get("code") == -32001
    # le proprietaire continue la tache : meme id, meme contexte, historique ALLONGE
    rep = srv.traiter("message/send", {**_texte("suite"), "taskId": t["id"],
                                       "contextId": "ctx-autre"}, 3, "AGY")
    r = rep["result"]
    assert r["id"] == t["id"] and r["contextId"] == t["contextId"]
    assert len(r["history"]) == 2
    # une tache terminale ne redemarre pas
    rep = srv.traiter("message/send", {**_texte("encore"), "taskId": t["id"]}, 4, "AGY")
    assert "error" in rep


# ------------------------------------------------------------ canceled ----

def test_a2a_canceled_est_atteignable_par_le_vrai_chemin():
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send", {**_texte("long"),
                                     "configuration": {"blocking": False}},
                    1, "AGY")["result"]
    assert t["status"]["state"] == srv.SOUMISE
    rep = srv.traiter("tasks/cancel", {"id": t["id"]}, 2, "AGY")
    assert rep["result"]["status"]["state"] == srv.ANNULEE
    lu = srv.traiter("tasks/get", {"id": t["id"]}, 3, "AGY")["result"]
    assert lu["status"]["state"] == srv.ANNULEE, "canceled doit rester consultable"
    # idempotent (spec 3.3.1) : re-annuler rend le meme etat, pas une erreur
    rep = srv.traiter("tasks/cancel", {"id": t["id"]}, 4, "AGY")
    assert rep["result"]["status"]["state"] == srv.ANNULEE


def test_a2a_l_executeur_differe_termine_les_soumises_et_respecte_l_annulation():
    """Le travail non bloquant est fait par l'executeur, pas par `tasks/get`."""
    srv = _charger("forge_a2a_server")
    a = srv.traiter("message/send", {**_texte("a"), "configuration": {"blocking": False}},
                    1, "AGY")["result"]
    b = srv.traiter("message/send", {**_texte("b"), "configuration": {"blocking": False}},
                    2, "AGY")["result"]
    assert srv.traiter("tasks/get", {"id": a["id"]}, 3, "AGY")["result"]["status"][
        "state"] == srv.SOUMISE, "get ne doit pas executer la tache"
    srv.traiter("tasks/cancel", {"id": b["id"]}, 4, "AGY")
    srv.executer_en_attente()
    la = srv.traiter("tasks/get", {"id": a["id"]}, 5, "AGY")["result"]
    lb = srv.traiter("tasks/get", {"id": b["id"]}, 6, "AGY")["result"]
    assert la["status"]["state"] == srv.TERMINEE and la["metadata"]["attempt"] == 1
    assert lb["status"]["state"] == srv.ANNULEE, "l'executeur a ressuscite une annulee"


# --------------------------------------------------------------- borne ----

def test_a2a_le_registre_des_taches_est_borne_sans_evincer_d_active(monkeypatch):
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "MAX_TACHES", 3)
    srv._TACHES.clear()
    actives = [srv.traiter("message/send", {**_texte("a%d" % i),
                                            "configuration": {"blocking": False}},
                           i, "AGY")["result"]["id"] for i in range(2)]
    for i in range(5):
        rep = srv.traiter("message/send", _texte("t%d" % i), 10 + i, "AGY")
        assert "result" in rep
        assert len(srv._TACHES) <= 3
    for tid in actives:
        lu = srv.traiter("tasks/get", {"id": tid}, 99, "AGY")
        assert "result" in lu, "une tache ACTIVE a ete evincee"
    # plein d'actives : refus explicite, jamais d'eviction d'une active
    srv.traiter("message/send", {**_texte("a3"), "configuration": {"blocking": False}},
                50, "AGY")
    rep = srv.traiter("message/send", {**_texte("de trop"),
                                       "configuration": {"blocking": False}}, 51, "AGY")
    assert "error" in rep
    assert len(srv._TACHES) <= 3
    for tid in actives:
        assert "result" in srv.traiter("tasks/get", {"id": tid}, 99, "AGY")


# ------------------------------------------- HTTP, dans le processus ----

def test_a2a_http_identite_par_jeton_et_cloisonnement_bout_en_bout(monkeypatch):
    """Serveur monte DANS le processus de test (TestServer, port ephemere loopback),
    jamais comme service. Verificateur double : aucun jeton reel."""
    import asyncio
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer
    srv = _charger("forge_a2a_server")

    def _v(authorization):
        jetons = {"Bearer jeton-AGY": "AGY", "Bearer jeton-CLAUDE": "CLAUDE"}
        ag = jetons.get(authorization or "")
        if not ag:
            return False, "invalid_or_unrecognized_token", None
        return True, "", {"agent": ag, "tache": None, "voie": "jeton_agent"}
    monkeypatch.setattr(srv, "_verificateur", lambda: _v)

    async def _scenario():
        client = TestClient(TestServer(srv.construire_app(port=0)))
        await client.start_server()
        try:
            r = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 1,
                                                "method": "message/send",
                                                "params": _texte("x")},
                                  headers={"X-Agent-Name": "AGY"})
            assert r.status == 401, "un en-tete seul a ouvert la facade"
            r = await client.post("/a2a", json={
                "jsonrpc": "2.0", "id": 1, "method": "message/send",
                "params": {**_texte("y"), "configuration": {"blocking": False}}},
                headers={"Authorization": "Bearer jeton-AGY", "X-Agent-Name": "CLAUDE"})
            t = (await r.json())["result"]
            # en-tete declaratif ignore : la tache est a AGY, pas a CLAUDE
            r = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 2,
                                                "method": "tasks/get",
                                                "params": {"id": t["id"]}},
                                  headers={"Authorization": "Bearer jeton-CLAUDE"})
            assert (await r.json())["error"]["code"] == -32001
            await asyncio.sleep(0.05)   # laisse l'executeur differe tourner
            r = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 3,
                                                "method": "tasks/get",
                                                "params": {"id": t["id"]}},
                                  headers={"Authorization": "Bearer jeton-AGY"})
            assert (await r.json())["result"]["status"]["state"] == srv.TERMINEE
            r = await client.post("/a2a", data="[1,2]",
                                  headers={"Authorization": "Bearer jeton-AGY",
                                           "Content-Type": "application/json"})
            assert (await r.json())["error"]["code"] == -32600
        finally:
            await client.close()

    asyncio.run(_scenario())


# ------------------------------------------------------- version carte ----

def test_a2a_carte_servie_porte_une_protocol_version_conforme():
    """Spec 4.4.x : `protocolVersion` = version majeure.mineure (ex. "0.3", "1.0")."""
    import re
    srv = _charger("forge_a2a_server")
    c = srv.carte_servie(etendue=False, port=7783)
    assert re.fullmatch(r"\d+\.\d+", c["protocolVersion"]), c["protocolVersion"]


def test_a2a_tache_inconnue_rend_une_erreur_jsonrpc():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("tasks/get", {"id": "inexistante"}, 9, "AGY")
    assert rep["error"]["code"] == -32001


def test_a2a_methode_inconnue_rend_32601():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("truc/machin", {}, 9, "AGY")
    assert rep["error"]["code"] == -32601


# --------------------------------------------------------------- carte ----

def test_la_carte_n_annonce_que_le_prouve_et_joignable():
    """REGLE FONDATRICE : la carte dit ce que Nokido peut prouver MAINTENANT."""
    card = _charger("forge_a2a_card")
    tous = {s["id"]: s for s in card.etats()}
    publies = {s["id"] for s in card.carte()["skills"]}
    for sid in publies:
        assert tous[sid]["verified"], "%s publie sans NR qui le prouve" % sid
        assert tous[sid]["available"], "%s publie alors qu'il ne repond pas" % sid


def test_la_carte_n_annonce_pas_le_streaming_non_implemente():
    """Annoncer une capacite absente est le meme defaut qu'une skill non prouvee.

    Ancien faux vert (`... or True`) retire : on mesure le COMPORTEMENT du serveur,
    pas la presence d'une chaine dans son source.
    """
    card = _charger("forge_a2a_card")
    srv = _charger("forge_a2a_server")
    c = card.carte()
    rep = srv.traiter("message/stream", _texte("x"), 1, "AGY")
    sert_stream = "error" not in rep or rep["error"]["code"] != -32601
    assert c["capabilities"]["streaming"] is sert_stream, (
        "carte streaming=%s mais le serveur %s `message/stream`"
        % (c["capabilities"]["streaming"], "sert" if sert_stream else "ne sert pas"))


def test_la_carte_declare_son_schema_de_securite():
    card = _charger("forge_a2a_card")
    c = card.carte()
    assert c["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert c["security"], "une carte sans exigence de securite invite l'anonyme"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
