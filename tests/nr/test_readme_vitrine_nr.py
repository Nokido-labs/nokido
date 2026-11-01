"""NR 30/10 -- README vitrine courte, rien supprime, 8 langues gardees (item P1_readme_vitrine_courte_20261026).

Contrat owner : README.md = vitrine technique ~150-200 lignes ; le README complet vit dans docs/README_complet.md
(liens relatifs reecrits) ; chaque traduction a sa vitrine courte docs/i18n/README.<lang>.md ET garde son complet
docs/i18n/README_complet.<lang>.md.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import readme_deporter as D  # noqa: E402

LANGUES = ("ar", "de", "es", "fr", "ja", "pt-BR", "zh-CN")
PLAFOND = 220


def test_liens_relatifs_reecrits_absolus_intacts():
    texte = ("[a](docs/wiki/x.md) [b](LICENSE) [c](https://x.y/z) [d](#ancre) [e](../deja.md) "
             '<img src="assets/i.png"> <a href="mailto:x@y">m</a>')
    neuf, n = D.reecrire_liens(texte)
    assert "](../docs/wiki/x.md)" in neuf and "](../LICENSE)" in neuf and 'src="../assets/i.png"' in neuf
    assert "](https://x.y/z)" in neuf and "](#ancre)" in neuf and "](../deja.md)" in neuf and "mailto:x@y" in neuf
    assert n == 3


def test_le_deport_ne_reecrit_pas_un_complet_existant(tmp_path):
    (tmp_path / "docs" / "i18n").mkdir(parents=True)
    (tmp_path / "README.md").write_text("vitrine", "utf-8")
    (tmp_path / "docs" / "README_complet.md").write_text("complet", "utf-8")
    faits = D.deporter(tmp_path)
    assert (tmp_path / "docs" / "README_complet.md").read_text("utf-8") == "complet"
    assert any(f.startswith("SAUTE") for f in faits)


def _lignes(p: Path) -> int:
    return len(p.read_text("utf-8").splitlines())


def test_readme_est_une_vitrine_qui_pointe_le_complet_et_les_langues():
    readme = (RACINE / "README.md").read_text("utf-8")
    assert len(readme.splitlines()) <= PLAFOND
    assert "docs/README_complet.md" in readme
    for lang in LANGUES:
        assert "docs/i18n/README.%s.md" % lang in readme, lang


def test_le_complet_est_garde():
    assert _lignes(RACINE / "docs" / "README_complet.md") > 1000


def test_normalisation_des_liens_d_une_vitrine_traduite():
    texte = ("[a](go_services/x/) [b](../../docs/README_complet.zh-CN.md) [c](../../docs/i18n/README.fr.md) "
             "[d](#-connect-a-client) [e](../../LICENSE) [f](https://x.y) [g](README.ja.md) [h](README.md)")
    neuf, n = D.normaliser_vitrine_traduite(texte, "zh-CN")
    assert "](../../go_services/x/)" in neuf and "](README_complet.zh-CN.md)" in neuf and "](README.fr.md)" in neuf
    assert "](../wiki/04-MCP-Clients-Setup.md)" in neuf and "](../../LICENSE)" in neuf and "](https://x.y)" in neuf
    assert "](README.ja.md)" in neuf and "](../../README.md)" in neuf
    assert n == 5


@pytest.mark.parametrize("lang", LANGUES)
def test_les_liens_relatifs_d_une_vitrine_traduite_existent(lang):
    vitrine = RACINE / "docs" / "i18n" / ("README.%s.md" % lang)
    morts = []
    for cible in re.findall(r"\]\(([^)\s]+)\)", vitrine.read_text("utf-8")):
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#)", cible, re.I):
            continue
        if not (vitrine.parent / cible.split("#")[0]).resolve().exists():
            morts.append(cible)
    assert not morts, "%s : liens morts %s" % (lang, morts)


@pytest.mark.parametrize("lang", LANGUES)
def test_chaque_langue_a_sa_vitrine_et_garde_son_complet(lang):
    vitrine = RACINE / "docs" / "i18n" / ("README.%s.md" % lang)
    complet = RACINE / "docs" / "i18n" / ("README_complet.%s.md" % lang)
    assert _lignes(complet) > 1000, "complet %s perdu" % lang
    assert _lignes(vitrine) <= PLAFOND + 20, "vitrine %s trop longue" % lang
    assert re.search(r"README_complet\.%s\.md" % re.escape(lang), vitrine.read_text("utf-8")), lang
