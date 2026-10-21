"""NR -- macOS est une plateforme de la distribution publique (owner 20/10 : « pas une version publique au rabais »).

Mesure du 20/10 au soir : `distribution/manifest.toml` ne declarait que windows-x64 et linux-x64, aucun fichier
`distribution/platforms/macos-*.toml` n'existait -- alors que `install.sh` gere Darwin, que le runtime traite
`sys.platform == "darwin"` dans une dizaine de modules, que la CI publique provisionne macOS (brew) et que le pack
`local-llm` epingle DEJA des binaires macos-arm64 et macos-x64 (llama-server, qdrant, caddy, ollama, deno, go). Rien ne
se publiait donc pour macOS. Garde : deux plateformes macOS (arm64, x64), installees par `install.sh`, avec les memes
prerequis que linux, declarees par le manifeste racine et par chacun des packs ; le manifeste se valide.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
DIST = RACINE / "distribution"
MAC = ("macos-arm64", "macos-x64")


def _toml(rel):
    return tomllib.loads((DIST / rel).read_text(encoding="utf-8"))


def _ra():
    spec = importlib.util.spec_from_file_location("release_assets_macos_nr", RACINE / "tools" / "forge_release_assets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_le_manifeste_racine_declare_macos():
    assert set(MAC) <= set(_toml("manifest.toml")["plateformes"])


@pytest.mark.parametrize("plateforme", MAC)
def test_une_plateforme_macos_s_installe_par_install_sh(plateforme):
    d = _toml("platforms/%s.toml" % plateforme)
    assert d["id"] == plateforme and d["os"] == "macos" and d["arch"] == plateforme.split("-")[1], d
    assert d["prerequis"] == _toml("platforms/linux-x64.toml")["prerequis"]
    (inst,) = [c for c in d["composant"] if c["id"] == "installeur"]
    assert inst["chemin"] == "install.sh", inst


@pytest.mark.parametrize("pack", ["knowledge", "ml", "local-llm", "netcfg"])
def test_chaque_pack_sert_macos(pack):
    assert set(MAC) <= set(_toml("packs/%s.toml" % pack)["plateformes"]), pack


def test_le_manifeste_avec_macos_se_valide():
    v = _ra().valider_manifeste()
    assert v["ok"], v["erreurs"]
    assert set(MAC) <= set(v["plateformes"]), sorted(v["plateformes"])
