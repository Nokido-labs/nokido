"""References mortes dans les configs — et surtout : ne pas confondre
« absent » avec « je ne peux pas voir »."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_config_refs_audit as cra  # noqa: E402


@pytest.fixture()
def conf(tmp_path, monkeypatch):
    """Un faux depot avec un seul fichier de config scanne."""
    monkeypatch.setattr(cra, "ROOT", tmp_path)
    monkeypatch.setattr(cra, "EXTRA_FILES", [])
    monkeypatch.setattr(cra, "SCAN_GLOBS", ["*.toml"])
    return tmp_path


def test_reference_morte_detectee(conf, monkeypatch):
    """Le cas PYBIN : un interpreteur cite qui n'existe pas.

    `_is_observable` est force a True : ce test porte sur la DETECTION. Sous le
    compte du hub, tmp_path vit dans le profil owner et serait juge inobservable —
    l'abstention a son propre test.
    """
    monkeypatch.setattr(cra, "_is_observable", lambda p: True)
    mort = (conf / "envs" / "jamais_cree" / "python.exe").as_posix()
    (conf / "c.toml").write_text(f'PYBIN = "{mort}"\n', encoding="utf-8")
    res = cra.scan()
    assert len(res) == 1 and res[0]["reference"].endswith("python.exe")


def test_le_silence_est_compte(conf, monkeypatch):
    """« rien trouve » et « rien pu regarder » ne doivent pas se lire pareil."""
    monkeypatch.setattr(cra, "_is_observable", lambda p: False)
    (conf / "c.toml").write_text('CMD = "C:/ailleurs/outil.exe"\n', encoding="utf-8")
    assert cra.scan() == []
    assert cra.LAST_UNOBSERVABLE == 1


def test_reference_vivante_ignoree(conf, monkeypatch):
    monkeypatch.setattr(cra, "_is_observable", lambda p: True)
    reel = conf / "bin"
    reel.mkdir()
    (reel / "outil.exe").write_bytes(b"x")
    (conf / "c.toml").write_text(f'CMD = "{(reel / "outil.exe").as_posix()}"\n', encoding="utf-8")
    assert cra.scan() == []


def test_invisible_nest_PAS_declare_mort(conf, monkeypatch):
    """Mesure 24-07 : lance depuis le hub, le scanner declarait morts 4 binaires
    bien presents — le compte de service ne voit pas le profil owner."""
    mort = (conf / "hors_perimetre" / "outil.exe").as_posix()
    (conf / "c.toml").write_text(f'CMD = "{mort}"\n', encoding="utf-8")
    monkeypatch.setattr(cra, "_is_observable", lambda p: False)
    assert cra.scan() == []


def test_chemin_avec_ESPACES_detecte(conf, monkeypatch):
    """Le depot vit dans '%NOKIDO_WORKSPACE%'. Un motif s'arretant
    au premier blanc tronquait tous les chemins du projet et n'en voyait aucun."""
    monkeypatch.setattr(cra, "_is_observable", lambda p: True)
    (conf / "c.toml").write_text(
        'CMD = "%NOKIDO_WORKSPACE%/LaForge/absent/outil.exe"\n', encoding="utf-8")
    res = cra.scan()
    assert len(res) == 1
    assert res[0]["reference"].endswith("outil.exe")
    assert "Script python IA" in res[0]["reference"]


def test_ligne_commentee_ignoree(conf, monkeypatch):
    """Commenter une reference morte EST le remede : la re-signaler ferait du bruit
    sur un probleme deja resolu (mesure sur ma propre correction de NETCFG_EXE)."""
    monkeypatch.setattr(cra, "_is_observable", lambda p: True)
    (conf / "c.toml").write_text(
        '# NETCFG_EXE = "%NOKIDO_WORKSPACE%/absent/outil.exe"\n',
        encoding="utf-8")
    assert cra.scan() == []


def test_chemin_templatise_ignore(conf):
    """${VAR} n'est pas resoluble ici : ne pas accuser."""
    (conf / "c.toml").write_text('CMD = "${PYTHON}/bin/x.exe"\n', encoding="utf-8")
    assert cra.scan() == []


def test_extensions_non_executables_ignorees(conf):
    (conf / "c.toml").write_text('DATA = "C:/donnees/inexistant.parquet"\n', encoding="utf-8")
    assert cra.scan() == []


def test_is_observable_sur_racine_lisible(tmp_path):
    assert cra._is_observable(tmp_path / "absent.exe") is True
