"""NR — forge_provision_clients n'ecrit plus les jetons de TOUS les agents en clair dans
C:\\tmp quand on ne lui demande qu'une reparation ciblee (2026-10-15).

Mesure : `C:\\tmp\\mcp_client_configs.txt` existait depuis le 2026-08-03, lisible par le
compte de bac a sable du hub. Toute execution hors --dry-run le reecrivait, y compris
--patch-codex, le geste prevu pour reparer le seul jeton de codex.
Les effets reels de l'outil (registre HKCU, ~/.codex/config.toml) sont neutralises ici.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

OUTIL = Path(__file__).resolve().parents[2] / "tools" / "forge_provision_clients.py"


@pytest.fixture
def outil(monkeypatch, tmp_path):
    secrets_factices = types.ModuleType("nokido_agent.app.forge_secrets")
    secrets_factices.get_secret = lambda cle: "jeton-factice-" + cle
    secrets_factices.set_secret = lambda cle, valeur: True
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", secrets_factices)
    spec = importlib.util.spec_from_file_location("forge_provision_clients_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", str(tmp_path / "mcp_client_configs.txt"))
    # Aucun effet hors du test : ni registre, ni config codex, ni lecture de l'environnement.
    monkeypatch.setattr(mod, "_sync_env", lambda tok, dry: [])
    monkeypatch.setattr(mod, "_check_env", lambda tok: [])
    monkeypatch.setattr(mod, "_patch_codex", lambda jeton, dry: [])
    return mod


def _lancer(mod, monkeypatch, *drapeaux):
    monkeypatch.setattr(sys, "argv", ["forge_provision_clients.py", *drapeaux])
    mod.main()
    return Path(mod.OUT).exists()


@pytest.mark.parametrize("drapeau", ["--apply", "--patch-codex", "--check"])
def test_un_mode_cible_n_ecrit_pas_les_jetons(outil, monkeypatch, capsys, drapeau):
    assert not _lancer(outil, monkeypatch, drapeau)
    assert "NON emises" in capsys.readouterr().out


def test_emettre_reste_possible_sur_demande(outil, monkeypatch):
    assert _lancer(outil, monkeypatch, "--check", "--emettre")


def test_sans_mode_cible_l_emission_reste_le_defaut(outil, monkeypatch):
    assert _lancer(outil, monkeypatch)


def test_dry_run_n_ecrit_rien(outil, monkeypatch):
    assert not _lancer(outil, monkeypatch, "--dry-run")
