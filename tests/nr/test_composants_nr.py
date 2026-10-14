# -*- coding: utf-8 -*-
"""Installeur PRODUIT des composants natifs epingles (tools/forge_composants.py, 2026-10-09).

Avant lui, seul le banc de mesure savait poser llama.cpp, Qdrant, Caddy et Ollama : une installation en une commande
reposait sur un banc de test. Ce qui ne doit pas revenir : une archive acceptee avec une somme ou une taille fausse,
une plateforme sans composant epingle, un dispatcher construit de facon non reproductible.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(60)
PLATEFORMES = ("windows-x64", "linux-x64", "macos-arm64", "macos-x64")


def _c():
    spec = importlib.util.spec_from_file_location("forge_composants_nr", ROOT / "tools" / "forge_composants.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("plat", PLATEFORMES)
def test_chaque_plateforme_a_tous_ses_composants_epingles(plat):
    m = _c()
    for cid in ("llama-server-%s-cpu" % plat, "qdrant-%s" % plat, "caddy-%s" % plat, "ollama-%s" % plat,
                "go-toolchain-%s" % plat):
        c = m.composant(cid)
        assert c["url"].startswith("https://") and len(c["sha256"]) == 64 and c["taille"] > 0, cid


@pytest.mark.parametrize("sysplat,machine,attendu", [("win32", "AMD64", "windows-x64"),
                                                     ("linux", "x86_64", "linux-x64"),
                                                     ("darwin", "arm64", "macos-arm64"),
                                                     ("darwin", "x86_64", "macos-x64")])
def test_plateforme(monkeypatch, sysplat, machine, attendu):
    m = _c()
    monkeypatch.setattr(m.sys, "platform", sysplat)
    monkeypatch.setattr(m.platform, "machine", lambda: machine)
    monkeypatch.setattr(m, "WIN", sysplat == "win32")
    assert m.plateforme() == attendu


def test_une_archive_a_la_somme_fausse_est_refusee_et_effacee(tmp_path):
    m = _c()
    src = tmp_path / "src" / "arch.zip"
    src.parent.mkdir()
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("bin/outil", "x")
    vrai = hashlib.sha256(src.read_bytes()).hexdigest()
    c = {"id": "essai", "url": src.as_uri(), "sha256": "0" * 64, "taille": src.stat().st_size}
    with pytest.raises(ValueError, match="FAUSSE"):
        m.telecharger(c, tmp_path / "dl")
    assert not (tmp_path / "dl" / "arch.zip").exists(), "une archive refusee ne reste pas sur le disque"
    c["sha256"] = vrai
    arch = m.telecharger(c, tmp_path / "dl")
    m.extraire(arch, tmp_path / "x")
    assert (tmp_path / "x" / "bin" / "outil").read_text() == "x"


def test_le_dispatcher_se_construit_de_facon_reproductible(monkeypatch, tmp_path):
    m = _c()
    appels = []
    monkeypatch.setattr(m.shutil, "which", lambda n: "/opt/go/bin/go" if n == "go" else None)

    def faux_sh(cmd, timeout=600, cwd=None, env=None):
        appels.append((cmd, cwd, env))
        Path(cmd[cmd.index("-o") + 1]).write_text("binaire")
        return 0, ""
    monkeypatch.setattr(m, "sh", faux_sh)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "go_services" / "forge_dispatcher").mkdir(parents=True)
    ok, detail = m.construire_dispatcher(tmp_path / "dl")
    cmd, cwd, env = appels[0]
    assert ok and detail["go"] == "PATH"
    assert cmd[:2] == ["/opt/go/bin/go", "build"] and "-trimpath" in cmd and "-buildvcs=false" in cmd
    assert env["CGO_ENABLED"] == "0" and Path(env["GOCACHE"]).parent == tmp_path / "sandbox"
    assert "GOFLAGS" not in env, "la construction ne reecrit jamais go.mod"
    assert cwd == tmp_path / "go_services" / "forge_dispatcher"
