"""NR -- 2a (decision owner du 2026-10-13) : le portail relaie le coffre POUR l'owner, par delegation.

MESURE QUI L'A DECLENCHE. Campagne UI du 13/10 : `/llm_dashboard` en defaut 3 passes sur 3, `403` sur
`/api/providers/acces`. Le portail relayait sous WEBHUB (ring 2) et les cinq routes du coffre du hub
exigent ring <= 1 : tout le panneau cles/acces ne pouvait QUE refuser, quelle que soit la personne connectee.

LA FORME RETENUE n'invente aucun mecanisme : WEBHUB avait DEJA le droit de deleguer au registre
(`ring_min_delegue: 1`). Il declare le sujet OWNER_PORTAIL, qui n'a aucun jeton propre.

Ce que ces tests verrouillent :
1. le chemin reel du videur rend ring 1, `via=delegated:WEBHUB`, acteur distinct du sujet ;
2. le sujet n'est declare QUE pour une session verifiee (auth active, `dev-bypass` exclu) ;
3. le sujet n'a JAMAIS de jeton direct : ni le semeur ni le chargeur ne lui en associent ;
4. sans le jeton de WEBHUB, declarer OWNER_PORTAIL n'ouvre rien.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_videur as V  # noqa: E402

REGISTRE = ROOT / "config" / "agent_identities.json"
FAUX_WEBHUB = "jeton-derive-du-portail-pour-test"
FAUX_MASTER = "jeton-maitre-pour-test"


def _agents():
    return json.loads(REGISTRE.read_text(encoding="utf-8"))["agents"]


def test_le_sujet_owner_est_declare_ring_1_sans_jeton_direct():
    sujet = _agents()["OWNER_PORTAIL"]
    assert sujet["ring"] == 1 and sujet["jeton_direct"] is False
    assert int(_agents()["WEBHUB"]["delegation"]["ring_min_delegue"]) >= 1


def test_le_videur_rend_le_ring_owner_par_delegation_de_webhub():
    r = V.resolve_identity("OWNER_PORTAIL", FAUX_WEBHUB, local=True,
                           agent_tokens={"WEBHUB": FAUX_WEBHUB}, hub_token=FAUX_MASTER)
    assert r["agent"] == "OWNER_PORTAIL" and r["ring"] == 1, r
    assert r["via"] == "delegated:WEBHUB" and r.get("acteur") == "WEBHUB", r


def test_sans_le_jeton_de_webhub_le_nom_declare_n_ouvre_rien():
    r = V.resolve_identity("OWNER_PORTAIL", "jeton-inconnu", local=True,
                           agent_tokens={"WEBHUB": FAUX_WEBHUB}, hub_token=FAUX_MASTER)
    assert r["ring"] > 1, r


def test_le_portail_ne_declare_le_sujet_que_pour_une_session_verifiee():
    import importlib

    pv = importlib.import_module("app.web_hub.provider_views")
    assert pv.sujet_owner("admin", True) == "OWNER_PORTAIL"
    assert pv.sujet_owner("admin", False) == ""          # auth coupee : l'en-tete viendrait du client
    assert pv.sujet_owner("dev-bypass", True) == ""
    assert pv.sujet_owner("", True) == ""


def test_le_sujet_n_a_jamais_de_jeton_ni_seme_ni_charge():
    import forge_auth_tokens as T
    import forge_vault_seed_agent_tokens as G

    assert "FORGE_TOKEN_OWNER_PORTAIL" not in G._cles_du_registre(3)
    assert "OWNER_PORTAIL" not in T._agents_connus()


# --- 5. le CHEMIN DE LA ROUTE (mesure du 2026-10-14) -----------------------------------------------
# Les tests ci-dessus prouvaient le videur ; la route du coffre ne l'appelait jamais. `request.state.ring`
# n'est pose que par `_exiger_identite`, que ces routes ne traversent pas, et le porteur ne reconnait que
# le maitre : sonde reelle, jeton WEBHUB + OWNER_PORTAIL -> 403, et la campagne UI (session ETABLIE) aussi.

def _route_du_coffre(monkeypatch, jetons=None):
    import importlib

    pa = importlib.import_module("nokido_agent.app.forge_provider_admin")
    vid = importlib.import_module("nokido_agent.app.forge_videur")
    monkeypatch.setattr(vid, "capture", lambda *a, **k: None)          # jamais le vrai journal chiffre
    monkeypatch.setattr(pa, "_ring_du_porteur", lambda r: 99)          # aucun maitre : la delegation seule
    monkeypatch.setattr(pa, "etat_des_acces", lambda: [])
    monkeypatch.setattr(pa, "_JETONS_AGENTS", jetons)
    monkeypatch.setattr(pa, "_CACHE_DELEGATEURS", {"t": 0.0, "jetons": {}})
    return pa


def _appel(pa, agent, jeton, hote="127.0.0.1"):
    import asyncio

    from starlette.requests import Request

    req = Request({"type": "http", "method": "GET", "path": "/api/access", "query_string": b"",
                   "headers": [(b"authorization", ("Bearer " + jeton).encode()), (b"x-agent-name", agent.encode())],
                   "client": (hote, 50000)})
    return asyncio.run(pa.api_list_access(req)).status_code


def test_la_route_du_coffre_accepte_la_delegation_par_son_vrai_chemin(monkeypatch):
    pa = _route_du_coffre(monkeypatch, jetons=lambda: {"WEBHUB": FAUX_WEBHUB})
    assert _appel(pa, "OWNER_PORTAIL", FAUX_WEBHUB) == 200


def test_le_jeton_du_portail_en_son_propre_nom_reste_refuse(monkeypatch):
    pa = _route_du_coffre(monkeypatch, jetons=lambda: {"WEBHUB": FAUX_WEBHUB})
    assert _appel(pa, "WEBHUB", FAUX_WEBHUB) == 403, "ring 2 direct : seule la DELEGATION est admise"
    assert _appel(pa, "OWNER_PORTAIL", "jeton-inconnu") == 403
    assert _appel(pa, "OWNER_PORTAIL", FAUX_WEBHUB, hote="192.0.2.10") == 403, "delegation hors local"


def test_sans_injection_les_delegateurs_du_registre_sont_lus_au_coffre(monkeypatch):
    import importlib

    pa = _route_du_coffre(monkeypatch, jetons=None)
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    monkeypatch.setattr(fs, "get_secret", lambda k: FAUX_WEBHUB if k == "FORGE_TOKEN_WEBHUB" else None)
    assert set(pa._jetons_delegateurs()) >= {"WEBHUB"}
    assert "OWNER_PORTAIL" not in pa._jetons_delegateurs(), "le sujet n'est pas un delegateur"
    assert _appel(pa, "OWNER_PORTAIL", FAUX_WEBHUB) == 200
