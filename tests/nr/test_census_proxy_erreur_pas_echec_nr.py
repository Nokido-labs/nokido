"""NR -- une reponse d'ERREUR du proxy n'est pas un echec du modele (constitution : UNKNOWN != NO).

Defaut mesure 24/10 : 11 fournisseurs du swarm:forge_agent_proxy a 0.0 exact (injoignables, texte d'erreur/vide juge
comme mauvaise reponse). Rapport : sandbox/workspace/rapport_bancs_faux_zero_20261024.md
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
    {"ok": False, "text": "", "error": "Provider returned empty response"},
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
