"""NR -- le registre des cles publiques d'agents quitte sandbox/ (decision owner 2026-09-28).

Mesure (audit ACL du 2026-09-28) : `forge_agent_keys` tenait son ledger dans
`sandbox/agent_keys.json`, et `sandbox\\` est modifiable par LaForgeSandboxUsers et
LaForgeTrusted -- n'importe quel compte bac a sable pouvait y enregistrer la cle publique
d'un agent. Le ledger n'etait cable nulle part (decable le 2026-09-21) : le trou n'etait
pas exploitable, mais le portail va s'y adosser.

Ce que ce NR verrouille :
  - chemin par defaut sous `%ProgramData%\\NokidoCles`, dossier cree PAR L'OWNER (ecriture
    SYSTEM + Administrateurs, lecture Utilisateurs), jamais sous sandbox/ ;
  - le module NE CREE JAMAIS ce dossier : cree par lui, il heriterait l'ACL de
    ProgramData (sous-dossiers creables par tout utilisateur) -- un compte bac a sable
    aurait pu le pre-creer a son profit. Absent -> l'ecriture LEVE.
"""
import importlib

import pytest

JWK_NR = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}


@pytest.fixture
def ak(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_agent_keys")
    monkeypatch.setattr(mod, "_CACHE", None)
    return mod


def test_le_chemin_par_defaut_n_est_plus_sous_sandbox(ak, monkeypatch):
    monkeypatch.delenv("FORGE_AGENT_KEYS_PATH", raising=False)
    chemin = ak._chemin_par_defaut()
    ok = chemin.parent.name == "NokidoCles" and "sandbox" not in {p.lower() for p in chemin.parts}
    assert ok, "le registre des cles publiques est encore sous sandbox/"


def test_l_ecriture_ne_cree_jamais_le_dossier(ak, monkeypatch, tmp_path):
    cible = tmp_path / "NokidoCles_absent" / "agent_keys.json"
    monkeypatch.setattr(ak, "_CHEMIN", cible)
    with pytest.raises(OSError):
        ak.enregistrer("WEBHUB", JWK_NR)
    assert not cible.parent.exists(), "le module a cree le dossier du registre (ACL heritee)"


def test_dans_un_dossier_existant_l_ecriture_marche(ak, monkeypatch, tmp_path):
    cible = tmp_path / "agent_keys.json"
    monkeypatch.setattr(ak, "_CHEMIN", cible)
    entree = ak.enregistrer("WEBHUB", JWK_NR)  # identite declaree au registre
    assert entree["status"] == "ACTIVE" and cible.exists()
