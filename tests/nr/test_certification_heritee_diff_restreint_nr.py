# -*- coding: utf-8 -*-
"""NR — un commit qui ne change QUE la version, le CHANGELOG et les workflows HÉRITE de la preuve de son ancêtre certifié.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la certification heritee par diff restreint"

CE QUI A ÉTÉ PAYÉ (21/10). 0.20.13 grillée sur TestPyPI ; 0.20.14 = 4a259ea58 (certifié, CI de référence ~3 h) + le bump
de version + une ligne `needs` de release.yml. Les gardes (dist_promotion.certifications, forge_dist_publish.
_lire_certification) n'acceptaient qu'une preuve du sha EXACT : 3 h de CI pour deux chaînes de version. Owner :
« tu me fais perdre trop de temps ». Décision owner : héritage par DIFF RESTREINT, EXPLICITE (drapeau) et DIT.
Contrat (tools/forge_dist_publish.py) :
  heritage_de_preuve(depot, certifie, cible) -> (ok, raison, fichiers)
    ok seulement si `certifie` est ANCÊTRE de `cible` et que CHAQUE ligne changée est : une ligne `version = "` de
    pyproject.toml, une ligne `__version__ = "` de nokido_agent/__init__.py, ou dans CHANGELOG.md / .github/workflows/ ;
    sinon (False, raison qui NOMME le fichier ou la ligne fautive, fichiers) ;
  _lire_certification(dossier, source_sha, herite_de=None, depot=ROOT) : avec `herite_de`, accepte les registres de
    l'ancêtre si l'héritage est valide (sinon SystemExit), et inscrit `heritage` dans le résultat ; sans lui, inchangé.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fdp(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("forge_dist_publish_herit_nr", ROOT / "tools" / "forge_dist_publish.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_dist_publish_herit_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _git(d, *a):
    r = subprocess.run(["git", "-c", "user.name=nr", "-c", "user.email=nr@nr", "-c", "safe.directory=*", *a], cwd=str(d),
                       capture_output=True, text=True, errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _ecrire(d: Path, chemin: str, texte: str):
    p = d / chemin
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte, encoding="utf-8")


def _commit(d, message) -> str:
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", message)
    return _git(d, "rev-parse", "HEAD")


PYPROJECT = '[project]\nname = "nokido-agent"\nversion = "%s"\ndependencies = ["%s"]\n'


@pytest.fixture
def depot(tmp_path):
    d = tmp_path / "depot"
    d.mkdir()
    _git(d, "init", "-q", "-b", "alpha")
    _ecrire(d, "pyproject.toml", PYPROJECT % ("0.20.13", "aiohttp==3.14.4"))
    _ecrire(d, "nokido_agent/__init__.py", '"""Nokido."""\n__version__ = "0.20.13"\n')
    _ecrire(d, "CHANGELOG.md", "# Changelog\n")
    _ecrire(d, ".github/workflows/release.yml", "jobs:\n  t:\n    needs: build\n")
    _ecrire(d, "app/forge_x.py", "X = 1\n")
    certifie = _commit(d, "certifie")
    return d, certifie


def _bump(d):
    _ecrire(d, "pyproject.toml", PYPROJECT % ("0.20.14", "aiohttp==3.14.4"))
    _ecrire(d, "nokido_agent/__init__.py", '"""Nokido."""\n__version__ = "0.20.14"\n')
    _ecrire(d, "CHANGELOG.md", "# Changelog\n\n## 0.20.14\n")
    _ecrire(d, ".github/workflows/release.yml", "jobs:\n  t:\n    needs: [build, audit-deps]\n")


def test_bump_changelog_et_workflow_heritent(monkeypatch, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _bump(d)
    cible = _commit(d, "chore(release): 0.20.14")
    ok, raison, fichiers = m.heritage_de_preuve(d, certifie, cible)
    assert ok is True, raison
    assert set(fichiers) == {"pyproject.toml", "nokido_agent/__init__.py", "CHANGELOG.md", ".github/workflows/release.yml"}


def test_un_fichier_de_code_interdit_l_heritage(monkeypatch, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _bump(d)
    _ecrire(d, "app/forge_x.py", "X = 2\n")
    cible = _commit(d, "bump + code")
    ok, raison, _f = m.heritage_de_preuve(d, certifie, cible)
    assert ok is False and "app/forge_x.py" in raison, raison


def test_une_autre_ligne_du_pyproject_interdit_l_heritage(monkeypatch, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _ecrire(d, "pyproject.toml", PYPROJECT % ("0.20.14", "aiohttp==3.15.0"))  # une dependance change : pas un bump
    cible = _commit(d, "bump + dependance")
    ok, raison, _f = m.heritage_de_preuve(d, certifie, cible)
    assert ok is False and "pyproject.toml" in raison, raison


def test_un_sha_qui_n_est_pas_ancetre_n_herite_pas(monkeypatch, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _git(d, "checkout", "-q", "-b", "autre", certifie + "~0")
    _ecrire(d, "app/forge_x.py", "X = 3\n")
    autre = _commit(d, "branche divergente")
    _git(d, "checkout", "-q", "alpha")
    _bump(d)
    cible = _commit(d, "bump")
    ok, raison, _f = m.heritage_de_preuve(d, autre, cible)
    assert ok is False and "ancetre" in raison, raison


def _dossier_preuve(tmp_path, sha_certifie) -> Path:
    dossier = tmp_path / "preuve"
    (dossier / "generations").mkdir(parents=True)
    (dossier / "generations" / "GEN-1.json").write_text(
        json.dumps({"depot": {"sha": sha_certifie}, "statut": "VERT", "tests": {"pytest": {}}}), encoding="utf-8")
    return dossier


def test_lire_certification_herite_et_le_dit(monkeypatch, tmp_path, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _bump(d)
    cible = _commit(d, "chore(release): 0.20.14")
    dossier = _dossier_preuve(tmp_path, certifie)
    c = m._lire_certification(str(dossier), cible, herite_de=certifie, depot=d)
    assert c["etat"] == "LUE" and c["generation_proof"]["fichier"] == "GEN-1.json", c
    assert c["heritage"]["de"] == certifie and "pyproject.toml" in c["heritage"]["fichiers"], c


def test_lire_certification_sans_heritage_refuse_toujours(monkeypatch, tmp_path, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _bump(d)
    cible = _commit(d, "chore(release): 0.20.14")
    with pytest.raises(SystemExit):
        m._lire_certification(str(_dossier_preuve(tmp_path, certifie)), cible, depot=d)


def _dp(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("dist_promotion_herit_nr", ROOT / "tools" / "dist_promotion.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "dist_promotion_herit_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _preuve_ci(racine: Path, sha: str):
    p = racine / "ci-reference-x" / "artefacts" / "ci_proof.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"target_sha": sha[:9], "observed_head": sha, "certification_state": "SUITE_COMPLETE",
                             "process_state": "CAPTURED", "incoherences": [], "non_couvert": []}), encoding="utf-8")


def test_promotion_herite_de_l_ancetre_certifie(monkeypatch, tmp_path, depot):
    dp = _dp(monkeypatch)
    d, certifie = depot
    _bump(d)
    cible = _commit(d, "chore(release): 0.20.14")
    _preuve_ci(tmp_path / "preuves", certifie)
    certs, raison, sha_preuve = dp.certifications_pour(cible, herite_de=certifie, racine=tmp_path / "preuves", depot=d)
    assert len(certs) == 1 and sha_preuve == certifie and raison == "", (certs, raison)
    certs, raison, _s = dp.certifications_pour(cible, racine=tmp_path / "preuves", depot=d)
    assert certs == [], "sans --herite-de, la preuve de l'ancetre ne certifie pas la cible"


def test_promotion_refuse_un_heritage_hors_diff_restreint(monkeypatch, tmp_path, depot):
    dp = _dp(monkeypatch)
    d, certifie = depot
    _bump(d)
    _ecrire(d, "app/forge_x.py", "X = 2\n")
    cible = _commit(d, "bump + code")
    _preuve_ci(tmp_path / "preuves", certifie)
    certs, raison, _s = dp.certifications_pour(cible, herite_de=certifie, racine=tmp_path / "preuves", depot=d)
    assert certs == [] and "app/forge_x.py" in raison, raison


def test_lire_certification_heritage_invalide_refuse(monkeypatch, tmp_path, depot):
    m = _fdp(monkeypatch)
    d, certifie = depot
    _bump(d)
    _ecrire(d, "app/forge_x.py", "X = 2\n")
    cible = _commit(d, "bump + code")
    with pytest.raises(SystemExit):
        m._lire_certification(str(_dossier_preuve(tmp_path, certifie)), cible, herite_de=certifie, depot=d)
