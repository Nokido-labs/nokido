"""NR -- une note de doc (datation, ports arretes) ne se pose JAMAIS au-dessus d'un frontmatter.

Mesure 2026-09-28 (regeneration du wiki) : `forge_docs_datation --apply` a pose la note de revue
en ligne 0 des pages `24-Cloud-Peers*.md`, AU-DESSUS du `---`. Cause : `_point_d_insertion` ne
cherchait le H1 que dans les 12 premieres lignes, et le frontmatter OKF de ces pages en fait 14
(liste `sources`). Le gate L1 (`test_wiki_openwiki_nr`) a rougi : `missing_frontmatter`.
Chemin reel : `traiter()` de la datation sur un fichier, et la fonction partagee.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.48)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]

FRONTMATTER_LONG = """---
type: guide
title: 99 -- page de test
status: draft
resource: repo://docs/wiki/99.md
generated: {by: nr, at: 2026-09-28T16:30:00+02:00}
sources:
  - {resource: "repo://a.py"}
  - {resource: "repo://b.py"}
  - {resource: "repo://c.py"}
  - {resource: "repo://d.py"}
  - {resource: "repo://e.py"}
empreinte: INCONNUE
---

# 99 -- page de test

Corps.
"""


def _charger(nom):
    spec = importlib.util.spec_from_file_location("nr_" + nom, ROOT / "tools" / (nom + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_datation_pose_la_note_apres_le_titre_meme_derriere_un_long_frontmatter(tmp_path):
    datation = _charger("forge_docs_datation")
    page = tmp_path / "99.md"
    page.write_text(FRONTMATTER_LONG, encoding="utf-8")
    etat, _ = datation.traiter(page, True, racine=tmp_path)
    assert etat in ("DATEE", "MISE_A_JOUR")
    texte = page.read_text(encoding="utf-8")
    assert texte.startswith("---\ntype: guide\n")                       # frontmatter intact, en tete
    assert texte.index("# 99 -- page de test") < texte.index(datation.MARQUEUR)
    # idempotent : un second passage ne deplace rien
    avant = texte
    datation.traiter(page, True, racine=tmp_path)
    assert page.read_text(encoding="utf-8") == avant


def test_une_page_deja_abimee_est_reparee(tmp_path):
    """La note deja posee AU-DESSUS du frontmatter (ancien defaut) redescend apres le titre."""
    datation = _charger("forge_docs_datation")
    page = tmp_path / "99.md"
    abimee = "\n" + datation.note("2026-09-28", 0) + FRONTMATTER_LONG
    page.write_text(abimee, encoding="utf-8")
    datation.traiter(page, True, racine=tmp_path)
    texte = page.read_text(encoding="utf-8")
    assert texte.startswith("---\ntype: guide\n")
    assert texte.index("# 99 -- page de test") < texte.index(datation.MARQUEUR)
    assert "2026-09-28" in texte                                         # date inscrite CONSERVEE


def test_relue_remplace_la_date_inscrite_et_seulement_pour_les_pages_nommees(tmp_path, monkeypatch):
    """--relue = le geste EXPLICITE « j'ai relu cette page » : la date du jour remplace la date
    inscrite de CETTE page ; les autres gardent la leur (l'instrument n'efface pas ce qu'il mesure)."""
    datation = _charger("forge_docs_datation")
    for nom in ("relue.md", "autre.md"):
        (tmp_path / nom).write_text("# Titre\n\n" + datation.note("2026-07-01", 90) + "corps\n", encoding="utf-8")
    monkeypatch.setattr(datation, "ROOT", tmp_path.parent)
    assert datation.main(["--dossier", tmp_path.name, "--apply", "--relue", "relue.md"]) == 0
    aujourd_hui = datation.date.today().isoformat()
    assert aujourd_hui in (tmp_path / "relue.md").read_text(encoding="utf-8")
    assert "2026-07-01" not in (tmp_path / "relue.md").read_text(encoding="utf-8")
    assert "2026-07-01" in (tmp_path / "autre.md").read_text(encoding="utf-8")


def test_un_commentaire_yaml_n_est_pas_un_titre():
    annote = _charger("forge_docs_port_annotate")
    lignes = ["---\n", "# commentaire yaml\n", "type: guide\n", "---\n", "\n", "# Vrai titre\n", "corps\n"]
    assert annote._point_d_insertion(lignes) == 6


def test_sans_frontmatter_le_comportement_d_origine_reste():
    annote = _charger("forge_docs_port_annotate")
    assert annote._point_d_insertion(["# Titre\n", "corps\n"]) == 1
    assert annote._point_d_insertion(["corps sans titre\n"]) == 0
    assert annote._point_d_insertion(["---\n", "type: guide\n", "pas de fermeture\n"]) == 0
