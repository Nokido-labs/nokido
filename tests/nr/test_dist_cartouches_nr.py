"""NR -- le README du dist montre un cartouche CI qui EXISTE sur le dist (2026-10-02).

Owner : « le cartouche CI ne s'affiche plus ». Le README de la source pointait son cartouche vers
`ci-selfhosted.yml` (bloque hors du dist) branche `alpha` ; apres le renommage, ce chemin visait le
depot de distribution, qui n'a ni ce workflow ni cette branche. Le promoteur reecrit le cartouche
vers `release.yml` du dist, le badge de branche vers `main`, et n'expose jamais le depot prive.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _promoteur():
    spec = importlib.util.spec_from_file_location("promoteur_nr", RACINE / "tools" / "forge_dist_publish.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SOURCE = (
    "[![Branch](https://img.shields.io/badge/branch-alpha-orange)](https://github.com/Nokido-labs/nokido)\n"
    "[![CI](https://github.com/Nokido-labs/nokido-private/actions/workflows/ci-selfhosted.yml/badge.svg"
    "?branch=alpha)](https://github.com/Nokido-labs/nokido-private/actions/workflows/ci-selfhosted.yml)\n"
)


def test_le_cartouche_du_dist_vise_son_propre_workflow(tmp_path):
    m = _promoteur()
    (tmp_path / "README.md").write_text(SOURCE, encoding="utf-8")
    assert m._adapter_cartouches(tmp_path) == 1
    out = (tmp_path / "README.md").read_text(encoding="utf-8")
    depot = m.DIST_REPO_GITHUB
    assert "https://github.com/%s/actions/workflows/release.yml/badge.svg" % depot in out, out
    assert "](https://github.com/%s/actions/workflows/release.yml)" % depot in out, out
    assert "ci-selfhosted" not in out and "nokido-private" not in out, "le depot prive fuit dans le dist"
    assert "badge/branch-main-" in out and "branch-alpha" not in out


def test_un_readme_deja_juste_n_est_pas_reecrit(tmp_path):
    m = _promoteur()
    (tmp_path / "README.md").write_text("# rien a adapter\n", encoding="utf-8")
    assert m._adapter_cartouches(tmp_path) == 0


def test_les_traductions_du_dist_sont_adaptees_aussi(tmp_path):
    """Premier jet : le glob visait docs/i18n/<langue>/ alors que les fichiers sont
    docs/i18n/README.<langue>.md -- les 7 traductions partaient avec le cartouche casse."""
    m = _promoteur()
    i18n = tmp_path / "docs" / "i18n"
    i18n.mkdir(parents=True)
    ancien = SOURCE.replace("Nokido-labs/nokido-private", "user/Nokido")   # proprietaire d'avant le renommage
    (i18n / "README.fr.md").write_text(ancien, encoding="utf-8")
    assert m._adapter_cartouches(tmp_path) == 1
    out = (i18n / "README.fr.md").read_text(encoding="utf-8")
    assert "ci-selfhosted" not in out and "user/Nokido/actions" not in out, out
    assert "https://github.com/%s/actions/workflows/release.yml/badge.svg" % m.DIST_REPO_GITHUB in out


def test_les_traductions_de_la_source_portent_les_cartouches_du_readme():
    """Les traductions etaient restees sur `user/Nokido` apres le renommage : la source doit
    porter les MEMES cartouches que README.md, ligne pour ligne."""
    lignes = lambda p: [l for l in p.read_text(encoding="utf-8").splitlines()
                        if l.startswith("[![Branch]") or l.startswith("[![CI]")]
    ref = lignes(RACINE / "README.md")
    assert len(ref) == 2, ref
    traductions = sorted((RACINE / "docs" / "i18n").glob("README*.md"))
    assert traductions, "aucune traduction lue : le test ne prouverait rien"
    for p in traductions:
        assert lignes(p) == ref, p.name
        assert "github.com/user/Nokido" not in p.read_text(encoding="utf-8"), p.name


def test_la_promotion_adapte_les_cartouches_apres_le_bloc_pip():
    src = (RACINE / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    i_pip, i_cart = src.find("_aligner_bloc_pip(dist, paquet"), src.find("_adapter_cartouches(dist)")
    i_commit = src.find("committed = commit_version(")
    assert 0 < i_pip < i_cart < i_commit, (i_pip, i_cart, i_commit)
