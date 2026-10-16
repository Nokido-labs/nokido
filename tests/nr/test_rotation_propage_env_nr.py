"""NR — la rotation des jetons realigne les variables d'environnement utilisateur (2026-10-15).

Mesure : apres la derniere rotation, les 9 agents avaient « registre PERIME » (coffre
different de HKCU) ; codex, configure par `bearer_token_env_var`, envoyait l'ancien jeton
et le hub le refusait en 401 a chaque demarrage. La rotation ne propageait pas a HKCU.
Le registre reel n'est jamais touche ici : `presentes` et `poser` sont injectes.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

OUTIL = Path(__file__).resolve().parents[2] / "tools" / "forge_hub_token_rotation.py"


@pytest.fixture
def rot():
    spec = importlib.util.spec_from_file_location("forge_hub_token_rotation_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seules_les_variables_presentes_sont_realignees(rot):
    poses = []
    out = rot._propager_env({"FORGE_TOKEN_CODEX": "neuf-1", "FORGE_TOKEN_AUTRE": "neuf-2"},
                            presentes={"FORGE_TOKEN_CODEX"},
                            poser=lambda nom, val: poses.append((nom, val)) or "MISE A JOUR")
    assert poses == [("FORGE_TOKEN_CODEX", "neuf-1")]
    assert any("FORGE_TOKEN_AUTRE" in l and "absente" in l for l in out)


def test_aucune_valeur_n_est_affichee(rot):
    out = "\n".join(rot._propager_env({"FORGE_TOKEN_CODEX": "valeur-secrete-xyz"},
                                      presentes={"FORGE_TOKEN_CODEX"},
                                      poser=lambda nom, val: "MISE A JOUR"))
    assert "valeur-secrete-xyz" not in out
    assert rot.fp("valeur-secrete-xyz") in out


def test_execute_propage_la_nouvelle_valeur(rot, monkeypatch, capsys):
    # Chemin reel : execute() renouvelle au coffre PUIS propage la valeur NEUVE.
    coffre = {}
    secrets_factices = types.ModuleType("nokido_agent.app.forge_secrets")
    secrets_factices.set_secret = lambda cle, valeur: coffre.__setitem__(cle, valeur) or True
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", secrets_factices)
    monkeypatch.setattr(rot, "_vault_tokens", lambda: (None, {"FORGE_TOKEN_CODEX": "jeton-perime-qx7"}))
    monkeypatch.setattr(rot, "CONFIG_FILES", [])
    vus = {}
    monkeypatch.setattr(rot, "_propager_env", lambda nouvelles, **kw: vus.update(nouvelles) or ["  ENV ok"])
    assert rot.execute(["FORGE_TOKEN_CODEX"]) == 0
    assert vus == {"FORGE_TOKEN_CODEX": coffre["FORGE_TOKEN_CODEX"]}
    assert coffre["FORGE_TOKEN_CODEX"] != "jeton-perime-qx7"
    assert "jeton-perime-qx7" not in capsys.readouterr().out
