"""NR — elicitation MCP : le hub demande une confirmation a l'owner (26/09).

Contrat :
  - capacite d'une session : OUI / NON / INCONNU ; une session absente est INCONNUE, jamais NON ;
    le registre survit au redemarrage du hub ; la revision 2026-07-28 (MRTR) rend NON, dit ;
  - hors flux SSE, sans capacite, ou demande deja en cours -> INDISPONIBLE : on n'agit pas ;
  - la requete `elicitation/create` part DANS le flux SSE, la reponse du client la resout
    seulement depuis SA session et SON agent ;
  - seul `accept` avec `confirmer` coche vaut ACCEPTE ; decline/cancel/delai/erreur n'autorisent rien ;
  - le flux garde le heartbeat historique et rend la main a la fin du tool ;
  - le middleware du hub laisse passer `result` d'une reponse client (il la vidait) ;
  - un seul etat : les deux noms d'import designent le meme module.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))
sys.path.insert(0, str(RACINE / "tools"))

import forge_mcp_elicitation as me  # noqa: E402  (import strict)


@pytest.fixture(autouse=True)
def registre_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(me, "FICHIER_SESSIONS", tmp_path / "sessions.json")
    monkeypatch.setattr(me, "_sessions", None)
    me._EN_ATTENTE.clear()
    yield
    me._EN_ATTENTE.clear()


def _session(sid="s1", caps=None, revision="2025-11-25", client="claude-code"):
    me.enregistrer_session(sid, client, revision, {"elicitation": {}} if caps is None else caps)


# ── capacites ──────────────────────────────────────────────────────────────────────

def test_session_absente_est_inconnue_pas_non():
    assert me.capacite("jamais-vue")[0] == "INCONNU"
    assert me.capacite("")[0] == "INCONNU"


def test_client_sans_elicitation_est_non():
    _session(caps={"roots": {}})
    etat, raison = me.capacite("s1")
    assert etat == "NON" and "elicitation" in raison


def test_revision_2026_07_28_est_non_et_le_dit():
    _session(revision="2026-07-28")
    etat, raison = me.capacite("s1")
    assert etat == "NON" and "MRTR" in raison


def test_registre_survit_au_redemarrage(monkeypatch):
    _session()
    monkeypatch.setattr(me, "_sessions", None)   # le hub redemarre : memoire vide, fichier present
    assert me.capacite("s1")[0] == "OUI"


# ── demande / reponse, par le chemin reel du hub (flux SSE) ─────────────────────────

async def _servir(coro, canal, repondre=None, ping=0.05):
    """Joue le role du hub (flux) et du client (repondre(evt) -> body de reponse ou None)."""
    tache = me.lancer_avec_canal(coro, canal)
    evenements = []
    async for evt in me.flux(tache, canal, ping=ping):
        evenements.append(evt)
        if evt.startswith("data: ") and repondre:
            req = json.loads(evt[6:])
            rep = repondre(req)
            if rep is not None:
                assert me.recevoir_reponse(rep, canal.session_id, canal.agent) == (True, "ok")
    return tache.result(), evenements


def _accepte(confirmer=True):
    return lambda req: {"jsonrpc": "2.0", "id": req["id"],
                        "result": {"action": "accept", "content": {"confirmer": confirmer}}}


def test_confirmation_acceptee_passe_par_le_flux():
    _session()
    canal = me.Canal("s1", "CLAUDE")
    r, evts = asyncio.run(_servir(me.confirmer_owner("redemarrer le hub"), canal, _accepte()))
    assert r["etat"] == me.ACCEPTE
    req = json.loads([e for e in evts if e.startswith("data: ")][0][6:])
    assert req["method"] == "elicitation/create" and req["id"].startswith("elicit-")
    assert "redemarrer le hub" in req["params"]["message"]
    assert req["params"]["requestedSchema"] == me.SCHEMA_CONFIRMATION
    assert not me._EN_ATTENTE


def test_formulaire_valide_sans_cocher_est_un_refus():
    _session()
    r, _ = asyncio.run(_servir(me.confirmer_owner("x"), me.Canal("s1", "CLAUDE"), _accepte(False)))
    assert r["etat"] == me.REFUSE


@pytest.mark.parametrize("action,attendu", [("decline", "REFUSE"), ("cancel", "ANNULE"), ("bizarre", "INDISPONIBLE")])
def test_seul_accept_autorise(action, attendu):
    _session()
    rep = lambda req: {"jsonrpc": "2.0", "id": req["id"], "result": {"action": action}}  # noqa: E731
    r, _ = asyncio.run(_servir(me.confirmer_owner("x"), me.Canal("s1", "CLAUDE"), rep))
    assert r["etat"] == attendu


def test_erreur_du_client_n_autorise_rien():
    _session()
    rep = lambda req: {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32600, "message": "non"}}  # noqa: E731
    r, _ = asyncio.run(_servir(me.confirmer_owner("x"), me.Canal("s1", "CLAUDE"), rep))
    assert r["etat"] == me.INDISPONIBLE


def test_delai_depasse_expire():
    _session()
    r, _ = asyncio.run(_servir(me.confirmer_owner("x", delai=0.1), me.Canal("s1", "CLAUDE")))
    assert r["etat"] == me.EXPIRE and not me._EN_ATTENTE


def test_reponse_d_une_autre_session_ou_d_un_autre_agent_est_rejetee():
    _session()

    async def scenario():
        canal = me.Canal("s1", "CLAUDE")
        tache = me.lancer_avec_canal(me.confirmer_owner("x", delai=0.5), canal)
        req = await canal.sortants.get()
        rep = {"jsonrpc": "2.0", "id": req["id"], "result": {"action": "accept", "content": {"confirmer": True}}}
        assert me.recevoir_reponse(rep, "s2", "CLAUDE")[0] is False
        assert me.recevoir_reponse(rep, "s1", "GEMINI")[0] is False
        assert me.recevoir_reponse(dict(rep, id="elicit-inconnu"), "s1", "CLAUDE")[0] is False
        return await tache

    assert asyncio.run(scenario())["etat"] == me.EXPIRE


# ── ce qui n'autorise rien sans rien demander ─────────────────────────────────────────

def test_hors_flux_sse_indisponible():
    _session()
    assert asyncio.run(me.confirmer_owner("x"))["etat"] == me.INDISPONIBLE


@pytest.mark.parametrize("prep", ["absente", "sans_capacite"])
def test_sans_capacite_rien_n_est_emis(prep):
    if prep == "sans_capacite":
        _session(caps={})
    canal = me.Canal("s1", "CLAUDE")
    r, evts = asyncio.run(_servir(me.confirmer_owner("x"), canal))
    assert r["etat"] == me.INDISPONIBLE
    assert not [e for e in evts if e.startswith("data: ")]


def test_une_seule_demande_a_la_fois_par_appel():
    _session()

    async def deux():
        return await asyncio.gather(me.confirmer_owner("a", delai=0.2), me.confirmer_owner("b", delai=0.2))

    (r1, r2), _ = asyncio.run(_servir(deux(), me.Canal("s1", "CLAUDE")))
    assert sorted([r1["etat"], r2["etat"]]) == [me.EXPIRE, me.INDISPONIBLE]


# ── le flux garde le comportement historique du hub ──────────────────────────────────

def test_flux_sans_demande_ping_puis_rend_la_main():
    async def lent():
        await asyncio.sleep(0.18)
        return "resultat"

    r, evts = asyncio.run(_servir(lent(), me.Canal("s1", "CLAUDE"), ping=0.05))
    assert r == "resultat"
    assert evts and all(e == ": ping\n\n" for e in evts)


def test_flux_releve_l_exception_du_tool():
    async def casse():
        raise RuntimeError("boum")

    with pytest.raises(RuntimeError):
        asyncio.run(_servir(casse(), me.Canal("s1", "CLAUDE")))


def test_sse_requis_seulement_pour_confirmer_owner():
    assert me.sse_requis("hub", {"action": "confirmer_owner"})
    assert not me.sse_requis("hub", {"action": "whoami"})
    assert not me.sse_requis("run", {"action": "confirmer_owner"})


# ── transport ─────────────────────────────────────────────────────────────────────────

def test_est_reponse_client():
    assert me.est_reponse_client({"jsonrpc": "2.0", "id": "elicit-1", "result": {}})
    assert me.est_reponse_client({"jsonrpc": "2.0", "id": 3, "error": {}})
    assert not me.est_reponse_client({"jsonrpc": "2.0", "id": 3, "method": "tools/call"})
    assert not me.est_reponse_client({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_le_middleware_du_hub_laisse_passer_result_d_une_reponse():
    import hub_middleware as mw

    ok, propre, erreurs = mw.validate_mcp_body(
        {"jsonrpc": "2.0", "id": "elicit-1", "result": {"action": "accept", "content": {"confirmer": True}}})
    assert ok, erreurs
    assert propre["result"]["action"] == "accept"
    assert me.est_reponse_client(propre)
    ok, propre, _ = mw.validate_mcp_body({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "result": "intrus"})
    assert "result" not in propre   # une REQUETE ne transporte pas de result


def test_un_seul_etat_sous_les_deux_noms_d_import():
    assert sys.modules["nokido_agent.app.forge_mcp_elicitation"] is me
