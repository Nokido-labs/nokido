"""NR -- COMMERCIAL.md archive dans docs/archive/ (decision owner 26/10).

Deux trous payes par la premiere livraison : (1) des liens relatifs faux depuis docs/ et
docs/i18n/ (`../archive` pointait HORS de docs), (2) la liste blanche d'identite de
forge_dist_publish ignorait le nouveau chemin : le nom civil du titulaire, legitime dans
ce document, aurait fait REFUSER la publication.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIEN = re.compile(r"\]\(([^)#\s]*COMMERCIAL(?:\.fr)?\.md)\)")
SOURCES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "docs" / "CLA.md",
           ROOT / "docs" / "COMMERCIAL_LICENSE.md", *sorted((ROOT / "docs" / "i18n").glob("README.*.md")),
           *sorted((ROOT / "docs" / "archive").glob("COMMERCIAL*.md"))]


def _identite_autorisee() -> set:
    arbre = ast.parse((ROOT / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "IDENTITE_AUTORISEE" for t in n.targets):
            return {e.value for e in n.value.args[0].elts}
    raise AssertionError("IDENTITE_AUTORISEE introuvable")


def test_le_document_est_archive_pas_copie():
    assert (ROOT / "docs" / "archive" / "COMMERCIAL.md").is_file()
    assert (ROOT / "docs" / "archive" / "COMMERCIAL.fr.md").is_file()
    assert not (ROOT / "COMMERCIAL.md").exists(), "une copie a la racine n'est pas un archivage"


def test_chaque_lien_vers_commercial_resout():
    vus, casses = 0, []
    for src in SOURCES:
        if not src.is_file():
            continue
        for cible in LIEN.findall(src.read_text(encoding="utf-8")):
            vus += 1
            if not (src.parent / cible).resolve().is_file():
                casses.append("%s -> %s" % (src.relative_to(ROOT).as_posix(), cible))
    assert vus >= 10, "le test ne voit plus les liens (%d) : il ne prouverait rien" % vus
    assert not casses, casses


def test_la_liste_blanche_d_identite_suit_le_document():
    autorises = _identite_autorisee()
    for p in (ROOT / "docs" / "archive").glob("COMMERCIAL*.md"):
        assert p.relative_to(ROOT).as_posix() in autorises
