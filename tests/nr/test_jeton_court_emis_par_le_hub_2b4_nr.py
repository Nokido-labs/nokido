"""NR -- etape 2b-4 du correctif du coffre : les CapabilityToken sont EMIS par le hub (2026-09-28).

Table 2b-4 (mesuree par lecture de code) : le hub (SYSTEM) est le seul a VERIFIER les
CapabilityToken (`_resolve_ring`) -- donc HMAC conserve, conformement au plan. Mais
`forge_agent_credential._echanger` les SIGNAIT dans le process appelant (`login_agent`
local) : `forge_hub_client`, `forge_state_encoder`, `forge_rss_watcher`,
`forge_openai_proxy`, hors du hub, avaient donc besoin de MCP_DEV_SECRET -- la cle qui
fabrique un jeton de N'IMPORTE QUEL ring. Tant qu'ils la lisent, elle ne peut pas etre
scellee (2b-6).

Ce que ce NR verrouille :
  - hors SYSTEM, le jeton court vient du hub (`POST /api/login`, identifiant PROPRE de
    l'agent) et la signature locale n'est pas tentee quand le hub repond ;
  - sous SYSTEM (le hub lui-meme), signature locale -- un appel HTTP du hub a lui-meme
    peut le bloquer ;
  - compte illisible -> voie du hub (on ne suppose jamais SYSTEM) ;
  - l'identifiant ne part QUE vers le loopback : une URL de hub non locale est refusee ;
  - TRANSITION jusqu'a 2b-6 : hub injoignable -> signature locale, et c'est dit.
"""
import importlib
import io
import json
import logging
import urllib.request

import pytest

PROPRE_NR = "identifiant-propre-agent-nr-2b4-" + "s" * 24
EMIS_HUB = "emis-par-le-hub-nr-2b4"
EMIS_LOCAL = "signe-localement-nr-2b4"


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def cred(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_agent_credential")
    ja = importlib.import_module("nokido_agent.app.forge_auth_tokens")
    appels = {"local": 0, "http": [], "hub_repond": True}

    def _login_local(role, **kw):
        appels["local"] += 1
        return EMIS_LOCAL

    def _urlopen(req, timeout=0):
        appels["http"].append(req.full_url)
        if not appels["hub_repond"]:
            raise OSError("hub injoignable (simule)")
        corps = json.loads(req.data.decode())
        ok = corps.get("role_id") == "STATE_ENCODER" and corps.get("secret_id") == PROPRE_NR
        return _Reponse(json.dumps({"token": EMIS_HUB if ok else ""}).encode())

    monkeypatch.setattr(ja, "login_agent", _login_local)
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(mod, "_reste_du_jeton", lambda brut: 1800.0)
    monkeypatch.delenv("LAFORGE_HUB_URL", raising=False)
    mod._appels_nr = appels
    return mod


def _rearmer(cred, monkeypatch):
    if hasattr(cred, "_TRANSITION_DITE"):
        monkeypatch.setitem(cred._TRANSITION_DITE, "locale", False)


def test_hors_system_le_jeton_vient_du_hub(cred, monkeypatch):
    monkeypatch.setattr(cred, "_sous_system", lambda: False, raising=False)
    emis, _reste = cred._echanger("state_encoder", PROPRE_NR)
    ok = emis == EMIS_HUB
    assert ok, "le jeton court n'a pas ete emis par le hub"
    assert cred._appels_nr["local"] == 0, "signature locale tentee alors que le hub repond"
    assert cred._appels_nr["http"] and cred._appels_nr["http"][0].endswith("/api/login")


def test_sous_system_signature_locale_sans_http(cred, monkeypatch):
    monkeypatch.setattr(cred, "_sous_system", lambda: True, raising=False)
    emis, _ = cred._echanger("state_encoder", PROPRE_NR)
    assert emis == EMIS_LOCAL
    assert not cred._appels_nr["http"], "le hub s'appellerait lui-meme"


def test_compte_illisible_prend_la_voie_du_hub(cred, monkeypatch):
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")

    def _illisible():
        raise OSError("jeton de process illisible (simule)")

    monkeypatch.setattr(mv, "_sid_courant", _illisible)
    emis, _ = cred._echanger("state_encoder", PROPRE_NR)
    assert emis == EMIS_HUB


def test_l_identifiant_ne_part_que_vers_le_loopback(cred, monkeypatch):
    monkeypatch.setattr(cred, "_sous_system", lambda: False, raising=False)
    monkeypatch.setenv("LAFORGE_HUB_URL", "http://exemple.invalid:8766")
    cred._echanger("state_encoder", PROPRE_NR)
    assert not any("exemple.invalid" in u for u in cred._appels_nr["http"]), (
        "l'identifiant de l'agent est parti vers un hote non local")


def test_hub_injoignable_transition_locale_dite(cred, monkeypatch, caplog):
    _rearmer(cred, monkeypatch)
    monkeypatch.setattr(cred, "_sous_system", lambda: False, raising=False)
    cred._appels_nr["hub_repond"] = False
    with caplog.at_level(logging.WARNING):
        emis, _ = cred._echanger("state_encoder", PROPRE_NR)
    assert emis == EMIS_LOCAL
    assert "TRANSITION" in caplog.text
