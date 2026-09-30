"""NR -- le semeur de jetons RELIT LA VALEUR ecrite, et n'affiche jamais une fin de jeton.

Mesure du 2026-09-28 (fenetre de maintenance du coffre) : `--generate-missing --overwrite` a
imprime « FORGE_MCP_TOKEN SEME et RELU » alors que l'ecriture avait ete REFUSEE par la garde des
noms reserves. La relecture testait la PRESENCE d'une valeur (`if get_secret(key)`) -- l'ancienne
etait toujours la -- et `val` etait videe avant la relecture : l'egalite etait impossible a tester.

Et `--verify` / l'import depuis un fichier affichaient `...` + les 6 derniers caracteres de chaque
jeton (fuite partielle ; « ne jamais lancer --verify » etait devenu une consigne de memoire).

Contrat : SEME et RELU seulement si la valeur relue EST celle ecrite (empreinte) ; refus ou
ecriture sans effet = echec dit, rc 1 ; aucune sortie ne contient une fin de jeton.
Valeurs factices ; le vrai coffre n'est jamais touche (get_secret / set_secret substitues).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def semeur(monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_semeur", ROOT / "tools/forge_vault_seed_agent_tokens.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    coffre = {}
    etat = {"refuse": False}

    def _set(k, v):
        if etat["refuse"]:
            return False                       # refus SANS lever : le cas mesure
        coffre[k] = v
        return True

    monkeypatch.setattr(fs, "get_secret", lambda k, *a, **kw: coffre.get(k))
    monkeypatch.setattr(fs, "set_secret", _set)
    return mod, coffre, etat


def _lancer(mod, monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["forge_vault_seed_agent_tokens.py", *args])
    rc = mod.main()
    s = capsys.readouterr()
    return rc, s.out + s.err


def test_rotation_refusee_n_est_pas_dite_semee(semeur, monkeypatch, capsys):
    mod, coffre, etat = semeur
    cle = mod.EXPECTED_KEYS[0]
    coffre[cle] = "ancienne-valeur-de-test-0001"
    etat["refuse"] = True
    rc, sortie = _lancer(mod, monkeypatch, capsys, "--generate-missing", "--overwrite",
                         "--agents", cle.replace("FORGE_TOKEN_", ""))
    assert rc == 1
    assert "SEME et RELU" not in sortie and "NON ECRIT" in sortie
    assert coffre[cle] == "ancienne-valeur-de-test-0001"


def test_rotation_ecrite_et_relue_identique(semeur, monkeypatch, capsys):
    mod, coffre, _etat = semeur
    cle = mod.EXPECTED_KEYS[0]
    coffre[cle] = "ancienne-valeur-de-test-0001"
    rc, sortie = _lancer(mod, monkeypatch, capsys, "--generate-missing", "--overwrite",
                         "--agents", cle.replace("FORGE_TOKEN_", ""))
    assert rc == 0 and "SEME et RELU" in sortie
    assert coffre[cle] != "ancienne-valeur-de-test-0001" and coffre[cle] not in sortie


def test_verify_et_import_n_affichent_aucune_fin_de_jeton(semeur, monkeypatch, capsys, tmp_path):
    mod, coffre, _etat = semeur
    for k in mod.EXPECTED_KEYS:
        coffre[k] = "valeur-secrete-de-test-" + k[-6:] + "ZQXW42"
    _rc, sortie = _lancer(mod, monkeypatch, capsys, "--verify")
    assert "ZQXW42" not in sortie
    f = tmp_path / "import.env"
    f.write_text(f"{mod.EXPECTED_KEYS[0]}=nouvelle-valeur-de-test-QQRRSS\n", encoding="utf-8")
    _rc, sortie = _lancer(mod, monkeypatch, capsys, "--from-env-file", str(f), "--overwrite")
    assert "QQRRSS" not in sortie
