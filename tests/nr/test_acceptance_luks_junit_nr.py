"""NR (owner 2/11) : acceptation -- motif LUKS lisible et rapport JUnit.

Ne d'un pipeline GitLab rouge 13/13 (job retire ensuite : doublon du run GitHub, decision owner 2/11). Restent deux
acquis utiles a toute plate-forme : (1) un conteneur NON privilegie (pas de /dev/mapper/control) ne peut pas prouver
le chiffrement at-rest -- le FAIL le DIT (« runner privilegie requis ») au lieu d'un refus opaque ; (2) le rapport
d'acceptation s'ecrit aussi en JUnit XML (onglet Tests d'une CI, sans traces ni JSON a ouvrir)."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_privilegie_nr",
                                                  RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# (2/11) les tests de l'image GitLab sont partis avec le job : voir test_miroirs_depot_public_nr (miroir sans CI)


def _faux_sh(refus: str):
    def sh(cmd, timeout=600, input=None):  # noqa: A002 -- meme signature que le module
        if "losetup" in cmd and "--show" in cmd:
            return 1, refus
        return 0, ""
    return sh


def test_luks_refuse_sans_device_mapper_dit_runner_privilegie(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m.shutil, "which", lambda n: "/usr/sbin/" + n)
    monkeypatch.setattr(m, "sh", _faux_sh("losetup: cannot find an unused loop device"))
    monkeypatch.setattr(m, "DM_CONTROL", tmp_path / "absent" / "control")
    etat, detail = m.mesurer_volume_luks()
    assert etat == "FAIL", "decision owner : le job reste rouge sans runner privilegie"
    assert "runner privilegie requis" in detail and "losetup refuse" in detail


# l'ecrivain JUnit reste prouve ci-dessous (utile a toute CI qui publie un rapport de tests)


def test_le_rapport_d_acceptation_s_ecrit_en_junit(tmp_path):
    import xml.etree.ElementTree as ET
    m = _module()
    r = {"paquet_install": {"etat": "PASS", "detail": "ok", "duree_s": 1.5},
         "paquet_arret": {"etat": "FAIL", "detail": "FileNotFoundError: 'pgrep'", "duree_s": 0.2},
         "reglage_gpu": {"etat": "NON_TESTE", "detail": "aucun GPU", "duree_s": 0.0},
         "paquet_premier_usage": {"etat": "MESURE", "detail": "HTTP 200", "duree_s": 3.0}}
    xml = tmp_path / "r.xml"
    m.ecrire_junit(r, xml, suite="parcours-paquet")
    racine = ET.parse(xml).getroot()
    cas = {c.get("name"): c for c in racine.iter("testcase")}
    assert set(cas) == set(r)
    assert cas["paquet_arret"].find("failure") is not None
    assert "pgrep" in cas["paquet_arret"].find("failure").text
    assert cas["reglage_gpu"].find("skipped") is not None
    assert cas["paquet_install"].find("failure") is None and cas["paquet_install"].get("time") == "1.5"
    assert all(c.get("classname") == "parcours-paquet" for c in cas.values())


def test_luks_refuse_avec_device_mapper_garde_le_motif_d_avant(tmp_path, monkeypatch):
    m = _module()
    ctl = tmp_path / "control"
    ctl.write_text("", encoding="utf-8")
    monkeypatch.setattr(m.shutil, "which", lambda n: "/usr/sbin/" + n)
    monkeypatch.setattr(m, "sh", _faux_sh("losetup: autre refus"))
    monkeypatch.setattr(m, "DM_CONTROL", ctl)
    etat, detail = m.mesurer_volume_luks()
    assert etat == "FAIL" and "runner privilegie" not in detail
