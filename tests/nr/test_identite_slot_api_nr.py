"""tests/nr/test_identite_slot_api_nr.py -- identite de slot sur les proxys API (lot 1, 07/11).

Chemin REEL : jeton court emis par `forge_cli_route._obtenir_jeton_auth` (vrai
`IntegrityManager`, secret de TEST pose ici, jamais le coffre), presente au vrai
handler Starlette de l'ingress, trace ecrite par le vrai recorder
`forge_token_monitor.log_call` dans une base TEMPORAIRE, relue par
`forge_quota_tracker.consommation_slot`. Seul l'appel au hub (`ask_via_hub`) est
simule : il partirait sur le reseau.

Contrat :
1. le slot (agent, tache) vient du jeton court VERIFIE, jamais d'un en-tete ou du corps ;
2. slot inconnu, jeton invalide ou jeton du hub = 401 ;
3. chaque appel proxy laisse une ligne : slot, tache, modele, jetons, cout ; cout
   inconnu = NULL / UNKNOWN_PRICING, jamais 0 ;
4. la lecture par slot passe par un INDEX (pas de balayage de table).
"""

from __future__ import annotations

import base64
import json
import sqlite3

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from nokido_agent.app import forge_integrity
from nokido_agent.app import forge_llm_format_bridge as bridge
from nokido_agent.app import forge_quota_tracker as qt
from nokido_agent.app import forge_secrets
from nokido_agent.app import forge_token_monitor as tm
from nokido_agent.tools import forge_anthropic_ingress as anth
from nokido_agent.tools import forge_cli_route as cr
from nokido_agent.tools import forge_gemini_ingress as gem

pytestmark = pytest.mark.timeout(60)

_SECRET_TEST = "secret-de-test-slot-nr-0123456789"
_JETON_AGENT_TEST = "jeton-agent-de-test-claude-headless"


@pytest.fixture
def banc(tmp_path, monkeypatch):
    """Manager au secret de TEST, coffre simule, base de trace temporaire, hub simule."""
    monkeypatch.setattr(forge_integrity, "_manager", forge_integrity.IntegrityManager(_SECRET_TEST))
    coffre = {"FORGE_TOKEN_CLAUDE_HEADLESS": _JETON_AGENT_TEST}
    monkeypatch.setattr(forge_secrets, "get_secret", lambda k, *a, **kw: coffre.get(k, ""))
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    base = tmp_path / "trace.db"
    monkeypatch.setattr(tm, "DB", str(base))

    async def faux_ask(prompt, provider, max_tokens, thread_id, agent, ring=3, cli_identity=""):
        return bridge.AskResult(True, reply="reponse simulee", provider="groq", it=40, ot=12)

    monkeypatch.setattr(bridge, "ask_via_hub", faux_ask)
    app = Starlette(routes=[
        Route("/v1/messages", anth.messages, methods=["POST"]),
        Route("/v1beta/models/{rest:path}", gem.generate, methods=["POST"]),
    ])
    return TestClient(app, raise_server_exceptions=True), base


def _lignes(base):
    with sqlite3.connect(str(base)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM token_usage")]


def _post_anthropic(client, jeton, extra_headers=None, body=None):
    h = {"Authorization": f"Bearer {jeton}"}
    h.update(extra_headers or {})
    return client.post("/v1/messages", headers=h, json=body or {
        "model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": "bonjour"}]})


def test_slot_vient_du_jeton_court_et_se_trace(banc):
    client, base = banc
    jeton = cr._obtenir_jeton_auth("claude", tache="tache_abc123")
    assert jeton
    # Usurpation tentee par en-tete ET par le corps : ignoree.
    r = _post_anthropic(client, jeton, {"X-Nokido-Slot": "OWNER", "X-Nokido-Tache": "volee"}, {
        "model": "claude-sonnet-4-5", "metadata": {"user_id": "OWNER"},
        "messages": [{"role": "user", "content": "bonjour"}]})
    assert r.status_code == 200, r.text
    lignes = _lignes(base)
    assert len(lignes) == 1
    l = lignes[0]
    assert l["agent_id"] == "CLAUDE_CLI"
    assert l["session_id"] == "tache_abc123"
    assert l["source"] == "proxy_slot"
    assert l["model"] == "claude-sonnet-4-5"
    assert l["prompt_tokens"] == 40 and l["completion_tokens"] == 12
    # groq sert, le modele demande n'est pas celui servi : cout INCONNU, jamais 0.
    assert l["cost_usd"] is None
    assert l["cost_kind"] == "UNKNOWN_PRICING"
    assert l["measurement_kind"] == "ESTIMATED"
    assert l["transport"] == "anthropic_ingress"


def test_gemini_trace_le_meme_slot(banc):
    client, base = banc
    jeton = cr._obtenir_jeton_auth("gemini", tache="tache_g1")
    r = client.post("/v1beta/models/gemini-2.5-pro:generateContent",
                    headers={"Authorization": f"Bearer {jeton}"},
                    json={"contents": [{"role": "user", "parts": [{"text": "bonjour"}]}]})
    assert r.status_code == 200, r.text
    (l,) = _lignes(base)
    assert l["agent_id"] == "GEMINI_CLI"
    assert l["session_id"] == "tache_g1"
    assert l["model"] == "gemini-2.5-pro"
    assert l["transport"] == "gemini_ingress"


def test_jeton_sans_tache_trace_unknown(banc):
    client, base = banc
    jeton = cr._obtenir_jeton_auth("claude")
    assert _post_anthropic(client, jeton).status_code == 200
    (l,) = _lignes(base)
    assert l["agent_id"] == "CLAUDE_CLI"
    assert l["session_id"] == "UNKNOWN"


def test_slot_inconnu_refuse(banc):
    client, base = banc
    jeton = forge_integrity.get_manager().create_manifest(
        agent_id="SLOT_FANTOME_XYZ", ring=forge_integrity.IntegrityRing.UNTRUSTED, duration_s=60)
    assert _post_anthropic(client, jeton).status_code == 401
    assert not base.exists() or not _lignes(base)


def test_tache_falsifiee_casse_la_signature(banc):
    client, _ = banc
    jeton = cr._obtenir_jeton_auth("claude", tache="tache_a")
    charge, sig = jeton.split(".")[:2]
    payload = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
    payload["scopes"]["tache"] = ["tache_b"]
    charge2 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    assert _post_anthropic(client, f"{charge2}.{sig}").status_code == 401


def test_jeton_du_hub_n_est_pas_un_slot(banc, monkeypatch):
    client, _ = banc
    monkeypatch.setenv("FORGE_MCP_TOKEN", "valeur-de-test-du-hub")
    assert _post_anthropic(client, "valeur-de-test-du-hub").status_code == 401


def test_jeton_agent_direct_porte_l_agent_sans_tache(banc):
    client, base = banc
    assert _post_anthropic(client, _JETON_AGENT_TEST).status_code == 200
    (l,) = _lignes(base)
    assert l["agent_id"] == "CLAUDE_HEADLESS"
    assert l["session_id"] == "UNKNOWN"


def test_consommation_par_slot_sur_fenetre_et_sans_balayage(banc):
    client, base = banc
    j1 = cr._obtenir_jeton_auth("claude", tache="t1")
    j2 = cr._obtenir_jeton_auth("claude", tache="t2")
    for j in (j1, j1, j2):
        assert _post_anthropic(client, j).status_code == 200
    # Une ligne a cout CONNU pour verifier la somme partielle.
    tm.log_call("CLAUDE_CLI", "groq", "x", 1, 1, 1.0, source="proxy_slot",
                session_id="t1", cost_usd=0.5, alerter=False)
    c = qt.consommation_slot("CLAUDE_CLI", tache="t1", fenetre_s=3600)
    assert c["ok"] is True
    assert c["appels"] == 3
    assert c["jetons_entree"] == 81 and c["jetons_sortie"] == 25
    assert c["appels_cout_inconnu"] == 2
    assert c["cout_connu_usd"] == pytest.approx(0.5)
    assert c["cout_usd"] == "UNKNOWN"  # jamais 0 ni 0.5 quand une part est inconnue
    tous = qt.consommation_slot("CLAUDE_CLI", fenetre_s=3600)
    assert tous["appels"] == 4
    assert qt.consommation_slot("GEMINI_CLI", fenetre_s=3600)["appels"] == 0
    # Fenetre passee : rien.
    assert qt.consommation_slot("CLAUDE_CLI", fenetre_s=3600,
                                maintenant=__import__("time").time() - 86400)["appels"] == 0
    # Sans balayage : le plan passe par l'index du slot.
    plan = qt.plan_consommation_slot(str(base))
    assert "idx_token_usage_slot" in plan, plan
    assert "SCAN token_usage" not in plan.replace("SCAN token_usage USING", ""), plan


def test_cout_tout_connu_rend_un_nombre(banc):
    _, base = banc
    tm.log_call("CLAUDE_CLI", "groq", "x", 1, 1, 1.0, source="proxy_slot",
                session_id="t9", cost_usd=0.25, alerter=False)
    c = qt.consommation_slot("CLAUDE_CLI", tache="t9", fenetre_s=3600)
    assert c["cout_usd"] == pytest.approx(0.25)


def test_base_absente_dit_ok_false(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "DB", str(tmp_path / "absente.db"))
    c = qt.consommation_slot("CLAUDE_CLI", fenetre_s=60)
    assert c["ok"] is False
    assert not (tmp_path / "absente.db").exists()
