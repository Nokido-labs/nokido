# -*- coding: utf-8 -*-
"""NR -- Nokido installe lui-meme sa chaine Lean, dans son arborescence, a la version epinglee (owner 15/10).

Owner : « personnaliser l'install de Lean pour le mettre dans notre repertoire de travail ». Contrat (sans reseau) :
  1. une archive officielle d'elan par plateforme ; une plateforme inconnue leve, jamais une devinette ;
  2. la conformite se lit dans `lean --version` contre `formel/lean-toolchain` ;
  3. idempotent : chaine deja conforme -> rien n'est telecharge ;
  4. installation dont la verification echoue -> ECHEC dit, jamais CONFORME ;
  5. la chaine de NOKIDO (sandbox/.elan_home) est lancee avec son ELAN_HOME, une autre garde l'environnement.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_lean_provision as lp  # noqa: E402
import forge_lean_verify as lv  # noqa: E402


@pytest.mark.parametrize("systeme,machine,attendu", [
    ("Windows", "AMD64", "elan-x86_64-pc-windows-msvc.zip"),
    ("Linux", "x86_64", "elan-x86_64-unknown-linux-gnu.tar.gz"),
    ("Darwin", "arm64", "elan-aarch64-apple-darwin.tar.gz"),
])
def test_une_archive_officielle_par_plateforme(systeme, machine, attendu):
    assert lp.archive_elan(systeme, machine) == attendu


def test_plateforme_inconnue_leve():
    with pytest.raises(RuntimeError):
        lp.archive_elan("Plan9", "x86_64")
    with pytest.raises(RuntimeError):
        lp.archive_elan("Linux", "mips")


def test_conformite_lue_contre_la_chaine_du_depot():
    chaine = lp.chaine_epinglee()
    assert chaine.startswith("leanprover/lean4:v")
    v = chaine.rsplit(":v", 1)[-1]
    assert lp.conforme("Lean (version %s, x86_64-w64-windows-gnu, commit abc, Release)" % v, chaine)
    assert not lp.conforme("Lean (version 4.0.0, x86_64, Release)", chaine) and not lp.conforme(None, chaine)


def test_idempotent_rien_n_est_telecharge_si_conforme(monkeypatch, tmp_path):
    v = lp.chaine_epinglee().rsplit(":v", 1)[-1]
    monkeypatch.setattr(lp, "version_installee", lambda home=None, lancer=None: "Lean (version %s, x, Release)" % v)

    def interdit(url):
        raise AssertionError("aucun telechargement attendu")

    r = lp.installer(tmp_path / ".elan_home", telecharger=interdit)
    assert r["etat"] == "CONFORME" and r["deja_installee"] is True


def test_installation_non_verifiee_est_un_echec(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "version_installee", lambda home=None, lancer=None: None)
    monkeypatch.setattr(lp, "archive_elan", lambda: "elan-x86_64-pc-windows-msvc.zip")
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("elan-init.exe", b"factice")
    lances = []
    r = lp.installer(tmp_path / ".elan_home", telecharger=lambda url: tampon.getvalue(),
                     executer=lambda cmd: lances.append(cmd) or type("R", (), {"stdout": "", "stderr": ""})())
    assert r["etat"] == "ECHEC" and "non conforme" in r["raison"]
    assert "--no-modify-path" in lances[0] and lp.chaine_epinglee() in lances[0]


def test_elan_home_pose_seulement_pour_la_chaine_de_nokido():
    env = lv._env_pour(str(lv.ELAN_HOME_NOKIDO / "bin" / "lake.exe"))
    assert env is not None and env["ELAN_HOME"] == str(lv.ELAN_HOME_NOKIDO)
    assert lv._env_pour(str(Path.home() / ".elan" / "bin" / "lake.exe")) is None
