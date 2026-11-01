"""NR -- un fournisseur injoignable (timeout, 401, 402, 404, 429) ne doit JAMAIS recevoir le score 0.0 (constitution : UNKNOWN != NO).

Defaut mesure 24/10 : 11 fournisseurs du swarm:forge_agent_proxy a 0.0 exact (injoginables, erreurs de transport/connexion jugees comme mauvaises reponses).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402


def _faux_proxy(monkeypatch, reponse):
    async def ask(modele, prompt, **k):
        return reponse
    mod = types.ModuleType("nokido_agent.app.forge_agent_proxy")
    mod.ask = ask
    monkeypatch.setitem(sys.modules, "nokido_agent", sys.modules.get("nokido_agent") or types.ModuleType("nokido_agent"))
    monkeypatch.setitem(sys.modules, "nokido_agent.app", sys.modules.get("nokido_agent.app") or types.ModuleType("nokido_agent.app"))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_agent_proxy", mod)


@pytest.mark.parametrize("rep", [
    {"ok": False, "text": "", "error": "Provider 'docker' indisponible : cle absente"},
    {"ok": True, "text": "   "},
    {"text": "", "error": "connexion refusee"},
])
def test_reponse_erreur_du_proxy_leve_une_erreur(monkeypatch, rep):
    _faux_proxy(monkeypatch, rep)
    with pytest.raises(Exception) as ei:
        C._appel_proxy("docker", {"prompt": "x"})
    assert not isinstance(ei.value, (C.NonSupporte,))


def test_reponse_ok_passe(monkeypatch):
    _faux_proxy(monkeypatch, {"ok": True, "text": "def f(): pass"})
    assert C._appel_proxy("m", {"prompt": "x"})["texte"] == "def f(): pass"


def test_unite_toute_en_erreur_est_indisponible_pas_zero(monkeypatch):
    _faux_proxy(monkeypatch, {"ok": False, "text": "", "error": "Provider 'glm' indisponible"})
    doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["code", "raisonnement"],
                         lambda cible, modele, req: C._appel_proxy(modele, req),
                         unites={"swarm:forge_agent_proxy": ["glm"]}, sleep=lambda s: None)
    u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["glm"]
    assert u["etat"] == "INDISPONIBLE"
    assert "indisponible" in u["motif"].lower()
    for b in u["bancs"].values():
        assert b["valeur"] is None and b["echantillon"] == 0
    assert "0.0" not in json.dumps(u["fiche"].get("force", {}))


def test_mauvaise_reponse_reste_un_echec_du_modele(monkeypatch):
    _faux_proxy(monkeypatch, {"ok": True, "text": "pas du code"})
    doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["raisonnement"],
                         lambda cible, modele, req: C._appel_proxy(modele, req),
                         unites={"swarm:forge_agent_proxy": ["cerebras"]}, sleep=lambda s: None)
    u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["cerebras"]
    assert u["etat"] == "OK" and u["bancs"]["raisonnement"]["valeur"] == 0.0
    assert u["bancs"]["raisonnement"]["echantillon"] > 0


def test_invalider_fiches_fausses_marque_sans_supprimer(tmp_path):
    reg = {"swarm:forge_agent_proxy:docker": {"force": {"code": {"valeur": 0.0, "echantillon": 12}}},
           "swarm:forge_agent_proxy:cerebras": {"force": {"code": {"valeur": 1.0, "echantillon": 12}}}}
    p = tmp_path / "census.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    n = C.invalider_faux_zeros(p, ["docker", "glm"])
    out = json.loads(p.read_text(encoding="utf-8"))
    assert n == 1
    assert out["swarm:forge_agent_proxy:docker"]["force"]["code"]["valeur"] == 0.0   # rien supprime
    assert out["swarm:forge_agent_proxy:docker"]["invalide"]["motif"]
    assert "invalide" not in out["swarm:forge_agent_proxy:cerebras"]


# NOUVEAU TEST : fournisseur injoignable (timeout) ne doit PAS donner 0.0
def test_unite_injoginable_timeout_ne_donne_pas_zero(monkeypatch):
    """Un fournisseur injoignable (timeout) ne doit JAMAIS recevoir le score 0.0 : doit être INDISPONIBLE avec motif."""
    def mock_ask(modele, prompt, **k):
        # Simule un timeout (qui lève URLError dans la vraie implémentation)
        import asyncio
        asyncio.sleep(1000)  # durée trop longue
    _faux_proxy(monkeypatch, None)  # Override la fonction ask pour lever un timeout

    # Patch pour forcer un timeout
    import nokido_agent.app.forge_agent_proxy
    original_ask = nokido_agent.app.forge_agent_proxy.ask

    async def timeout_ask(modele, prompt, **k):
        raise asyncio.TimeoutError("timeout")

    nokido_agent.app.forge_agent_proxy.ask = timeout_ask

    try:
        doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["code"],
                             lambda cible, modele, req: C._appel_proxy(modele, req),
                             unites={"swarm:forge_agent_proxy": ["timeout_test"]}, sleep=lambda s: None)

        u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["timeout_test"]
        # L'unite doit être INDISPONIBLE, pas OK avec une valeur
        assert u["etat"] == "INDISPONIBLE", f"Expected INDISPONIBLE, got {u['etat']}"
        assert "timeout" in u["motif"].lower() or "error" in u["motif"].lower(), f"Expected timeout/error in motif, got: {u['motif']}"

        # Tous les bancs doivent avoir valeur=None et echantillon=0 (jamais 0.0)
        for b_name, b in u["bancs"].items():
            assert b["valeur"] is None, f"Banc {b_name} should have None value, got {b['valeur']}"
            assert b["echantillon"] == 0, f"Banc {b_name} should have 0 samples, got {b['echantillon']}"
            # Vérifie que la fiche ne contient pas 0.0
            fiche_force = u["fiche"].get("force", {})
            if b_name in fiche_force:
                force_val = fiche_force[b_name].get("valeur")
                assert force_val is None, f"Force valeur for {b_name} should be None, got {force_val}"

        # Vérifie que la JSON ne contient pas 0.0
        fiche_json = json.dumps(u["fiche"])
        assert "0.0" not in fiche_json, f"Fiche should not contain 0.0, got: {fiche_json}"

    finally:
        # Restore l'original
        nokido_agent.app.forge_agent_proxy.ask = original_ask


# NOUVEAU TEST : fournisseur qui retourne HTTP 401 ne doit PAS donner 0.0
def test_unite_401_ne_donne_pas_zero(monkeypatch):
    """Un fournisseur qui retourne 401 (auth error) ne doit JAMAIS recevoir le score 0.0 : doit être INDISPONIBLE."""
    async def mock_ask(modele, prompt, **k):  # le vrai ask est ASYNCHRONE (sinon TypeError au lieu du 401)
        return {"ok": True, "text": "", "error": "HTTP 401 Unauthorized"}

    _faux_proxy(monkeypatch, None)

    import nokido_agent.app.forge_agent_proxy
    original_ask = nokido_agent.app.forge_agent_proxy.ask
    nokido_agent.app.forge_agent_proxy.ask = mock_ask

    try:
        doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["raisonnement"],
                             lambda cible, modele, req: C._appel_proxy(modele, req),
                             unites={"swarm:forge_agent_proxy": ["401_test"]}, sleep=lambda s: None)

        u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["401_test"]
        assert u["etat"] == "INDISPONIBLE", f"Expected INDISPONIBLE, got {u['etat']}"
        assert "401" in u["motif"].lower(), f"Expected 401 in motif, got: {u['motif']}"

        for b_name, b in u["bancs"].items():
            assert b["valeur"] is None, f"Banc {b_name} should have None value, got {b['valeur']}"
            assert b["echantillon"] == 0, f"Banc {b_name} should have 0 samples, got {b['echantillon']}"

        fiche_json = json.dumps(u["fiche"])
        assert "0.0" not in fiche_json, f"Fiche should not contain 0.0, got: {fiche_json}"

    finally:
        nokido_agent.app.forge_agent_proxy.ask = original_ask


# NOUVEAU TEST : fournisseur qui retourne HTTP 404 ne doit PAS donner 0.0
def test_unite_404_ne_donne_pas_zero(monkeypatch):
    """Un fournisseur qui retourne 404 (not found) ne doit JAMAIS recevoir le score 0.0 : doit être INDISPONIBLE."""
    async def mock_ask(modele, prompt, **k):  # le vrai ask est ASYNCHRONE
        return {"ok": True, "text": "", "error": "HTTP 404 Not Found"}

    _faux_proxy(monkeypatch, None)

    import nokido_agent.app.forge_agent_proxy
    original_ask = nokido_agent.app.forge_agent_proxy.ask
    nokido_agent.app.forge_agent_proxy.ask = mock_ask

    try:
        doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["raisonnement"],
                             lambda cible, modele, req: C._appel_proxy(modele, req),
                             unites={"swarm:forge_agent_proxy": ["404_test"]}, sleep=lambda s: None)

        u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["404_test"]
        assert u["etat"] == "INDISPONIBLE", f"Expected INDISPONIBLE, got {u['etat']}"
        assert "404" in u["motif"].lower(), f"Expected 404 in motif, got: {u['motif']}"

        for b_name, b in u["bancs"].items():
            assert b["valeur"] is None, f"Banc {b_name} should have None value, got {b['valeur']}"
            assert b["echantillon"] == 0, f"Banc {b_name} should have 0 samples, got {b['echantillon']}"

        fiche_json = json.dumps(u["fiche"])
        assert "0.0" not in fiche_json, f"Fiche should not contain 0.0, got: {fiche_json}"

    finally:
        nokido_agent.app.forge_agent_proxy.ask = original_ask


# NOUVEAU TEST : fournisseur qui retourne HTTP 429 ne doit PAS donner 0.0
def test_unite_429_ne_donne_pas_zero(monkeypatch):
    """Un fournisseur qui retourne 429 (rate limit) ne doit JAMAIS recevoir le score 0.0 : doit être INDISPONIBLE."""
    async def mock_ask(modele, prompt, **k):  # le vrai ask est ASYNCHRONE
        return {"ok": True, "text": "", "error": "HTTP 429 Rate limit exceeded"}

    _faux_proxy(monkeypatch, None)

    import nokido_agent.app.forge_agent_proxy
    original_ask = nokido_agent.app.forge_agent_proxy.ask
    nokido_agent.app.forge_agent_proxy.ask = mock_ask

    try:
        doc = C.lancer_bancs(["swarm:forge_agent_proxy"], ["raisonnement"],
                             lambda cible, modele, req: C._appel_proxy(modele, req),
                             unites={"swarm:forge_agent_proxy": ["429_test"]}, sleep=lambda s: None)

        u = doc["cibles"]["swarm:forge_agent_proxy"]["unites"]["429_test"]
        assert u["etat"] == "INDISPONIBLE", f"Expected INDISPONIBLE, got {u['etat']}"
        assert "429" in u["motif"].lower(), f"Expected 429 in motif, got: {u['motif']}"

        for b_name, b in u["bancs"].items():
            assert b["valeur"] is None, f"Banc {b_name} should have None value, got {b['valeur']}"
            assert b["echantillon"] == 0, f"Banc {b_name} should have 0 samples, got {b['echantillon']}"

        fiche_json = json.dumps(u["fiche"])
        assert "0.0" not in fiche_json, f"Fiche should not contain 0.0, got: {fiche_json}"

    finally:
        nokido_agent.app.forge_agent_proxy.ask = original_ask
