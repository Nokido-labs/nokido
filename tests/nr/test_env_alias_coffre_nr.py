# -*- coding: utf-8 -*-
"""NR -- forge_env_to_vault --alias : neutraliser un nom GENERIQUE du .env dont la valeur est au
coffre sous son VRAI nom (2026-10-01).

Mesure : le `password` du .env (fragment .pypirc collé, section [testpypi]) etait le jeton
TestPyPI, deja au coffre sous TESTPYPI_TOKEN ; le `password` du coffre etait le jeton PyPI. Pas
de conflit -- deux jetons sous un meme nom -- mais l'outil, qui compare par nom, refusait de
retirer la copie en clair. La garde reste l'EMPREINTE exacte. Aucune vraie valeur ici.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("env_to_vault_nr", ROOT / "tools" / "forge_env_to_vault.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


COFFRE = {"password": "jeton-pypi-nr", "TESTPYPI_TOKEN": "jeton-testpypi-nr"}


def _env(tmp_path, valeur):
    p = tmp_path / "Nokido.env"
    p.write_text("[testpypi]\nusername = __token__\npassword = %s\n" % valeur, encoding="utf-8")
    return p


def test_l_alias_vide_la_copie_en_clair_quand_l_empreinte_concorde(tmp_path):
    m = _module()
    p = _env(tmp_path, "jeton-testpypi-nr")
    n = m._neutraliser(p, COFFRE.get, appliquer=True, limiter_a={"password"},
                       alias={"password": "TESTPYPI_TOKEN"})
    texte = p.read_text(encoding="utf-8")
    assert n == 1 and "jeton-testpypi-nr" not in texte and "# password=" in texte


def test_sans_alias_le_meme_nom_reste_un_conflit_et_rien_n_est_vide(tmp_path):
    m = _module()
    p = _env(tmp_path, "jeton-testpypi-nr")
    assert m._neutraliser(p, COFFRE.get, appliquer=True, limiter_a={"password"}) == 0
    assert "jeton-testpypi-nr" in p.read_text(encoding="utf-8")


def test_un_alias_qui_ne_concorde_pas_ne_vide_rien(tmp_path):
    m = _module()
    p = _env(tmp_path, "autre-valeur")
    assert m._neutraliser(p, COFFRE.get, appliquer=True, limiter_a={"password"},
                          alias={"password": "TESTPYPI_TOKEN"}) == 0
    assert "autre-valeur" in p.read_text(encoding="utf-8")
