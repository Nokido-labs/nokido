"""NR -- le wiki GitHub du depot public se construit depuis `docs/wiki` du dist (tools/forge_wiki_github.py).

Paye le 2026-10-06 : la premiere publication est passee par un script ponctuel hors depot. Ce NR garde
ce qui faisait le wiki LISIBLE (YAML retire, liens de page sans `.md`, liens vers le depot absolus), et les
deux proprietes que le script n'avait pas : le clone du wiki (`.git`) survit a la reconstruction, et une
page retiree a la source disparait du wiki au lieu d'y survivre. Le dernier test emprunte le chemin reel
(`__main__` + drapeaux CLI), pas seulement les fonctions.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
OUTIL = RACINE / "tools" / "forge_wiki_github.py"


def _outil():
    spec = importlib.util.spec_from_file_location("wiki_github_nr", OUTIL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(depot: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=nr", "-c", "user.email=nr@example.invalid",
                    "-c", "commit.gpgsign=false", "-C", str(depot), *args], check=True, capture_output=True)


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    wiki = dist / "docs" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "Home.md").write_text(
        "---\ntype: guide\n---\n\n# Nokido Wiki\n\n[FR](Home.fr.md) [Install](01-Installation.md#prereq) "
        "[Manifeste](../../MANIFESTO.md) [Arch](../ARCHITECTURE.md) [ext](https://example.org) [x](#ancre)\n",
        encoding="utf-8")
    (wiki / "Home.fr.md").write_text("# Wiki Nokido\n\n[EN](Home.md)\n", encoding="utf-8")
    (wiki / "01-Installation.md").write_text("# 01 — Installation\n\n[absente](Inconnue.md)\n", encoding="utf-8")
    (wiki / "01-Installation.fr.md").write_text("# 01 — Installation (fr)\n", encoding="utf-8")
    _git(dist, "init", "-q")
    _git(dist, "add", "-A")
    _git(dist, "commit", "-q", "-m", "init")
    _git(dist, "tag", "v9.9.9")
    return dist


def test_yaml_retire_et_liens_reecrits():
    m = _outil()
    texte, retire = m.retirer_yaml("---\na: 1\n---\n\n# T\n")
    assert retire and texte == "# T\n"
    assert m.retirer_yaml("# sans yaml\n") == ("# sans yaml\n", False)
    out, st = m.reecrire_liens("[a](B.md#x) [b](../../F.md) [c](https://e.org) [d](Z.md) [e](../../../hors.md)",
                               {"B"}, "https://github.com/o/r")
    assert "[a](B#x)" in out
    assert "[b](https://github.com/o/r/blob/main/F.md)" in out
    assert "[c](https://e.org)" in out
    assert "[e](../../../hors.md)" in out, "un lien qui sort du depot reste tel quel"
    assert st["liens_page"] == 2 and st["liens_depot"] == 1 and st["pages_inconnues"] == ["Z.md"]


def test_barre_laterale_bilingue_sans_les_accueils():
    m = _outil()
    s = m.barre_laterale({"Home": "H", "Home.fr": "H", "02-B": "B en", "01-A": "A en", "01-A.fr": "A fr"})
    en, fr = s.split("**Français**")
    assert en.index("(01-A)") < en.index("(02-B)") and "(01-A.fr)" not in en
    assert "(01-A.fr)" in fr and "(02-B)" not in fr
    assert s.count("(Home)") == 1 and s.count("(Home.fr)") == 1


def test_construit_au_commit_garde_le_clone_et_retire_les_pages_mortes(tmp_path):
    m = _outil()
    dist = _dist(tmp_path)
    # une modification NON commitee ne doit pas partir sur le wiki : on publie le commit
    (dist / "docs" / "wiki" / "Home.md").write_text("# BROUILLON\n", encoding="utf-8")
    sortie = tmp_path / "wiki"
    (sortie / ".git").mkdir(parents=True)
    (sortie / ".git" / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (sortie / "Page-Retiree.md").write_text("# vieille page\n", encoding="utf-8")
    cr = m.construire(dist, sortie, "https://github.com/o/r")
    assert (sortie / ".git" / "HEAD").exists(), "le clone du wiki doit survivre a la reconstruction"
    assert cr["retirees"] == ["Page-Retiree.md"] and not (sortie / "Page-Retiree.md").exists()
    home = (sortie / "Home.md").read_bytes().decode("utf-8")
    assert "BROUILLON" not in home and home.startswith("# Nokido Wiki")
    assert "\r\n" not in home
    assert "[Install](01-Installation#prereq)" in home
    assert "[Manifeste](https://github.com/o/r/blob/main/MANIFESTO.md)" in home
    assert "[Arch](https://github.com/o/r/blob/main/docs/ARCHITECTURE.md)" in home
    assert cr["pages"] == 4 and cr["yaml_retires"] == 1 and cr["pages_inconnues"] == ["Inconnue.md"]
    assert "v9.9.9" in (sortie / "_Footer.md").read_text(encoding="utf-8")
    assert "(01-Installation.fr)" in (sortie / "_Sidebar.md").read_text(encoding="utf-8")


def test_point_d_entree_cli_dit_le_lien_inconnu_et_echoue(tmp_path):
    dist = _dist(tmp_path)
    r = subprocess.run([sys.executable, str(OUTIL), "--dist", str(dist), "--sortie", str(tmp_path / "w")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Inconnue.md" in r.stdout and "pas un clone du wiki" in r.stdout, r.stdout


def _promoteur():
    spec = importlib.util.spec_from_file_location("promoteur_wiki_nr", RACINE / "tools" / "forge_dist_publish.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_le_promoteur_construit_le_wiki_apres_le_commit_du_dist():
    import inspect
    src = inspect.getsource(_promoteur().main)
    assert "_construire_wiki(dist)" in src, "la promotion ne reconstruit plus le wiki"
    assert src.index("commit_version(") < src.index("_construire_wiki(dist)"), (
        "le wiki se lit au COMMIT du dist : le construire avant le commit publierait l'etat precedent")


def test_un_wiki_inconstructible_ne_casse_pas_la_promotion(tmp_path, capsys, monkeypatch):
    # GIT_DIR vers un depot absent : ls-tree echoue meme si tmp_path vit sous un depot parent
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "absent.git"))
    _promoteur()._construire_wiki(tmp_path)
    assert "[wiki] NON construit" in capsys.readouterr().out
