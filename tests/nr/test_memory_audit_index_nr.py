"""NR -- audit de l'index memoire : taille, fiches atteignables a 2 sauts, orphelines.

L'index charge a chaque session a un plafond de taille, et une fiche hors de portee
est une fiche perdue (owner 5/11 : « tu perds la memoire »). Lecture seule : l'audit
ne supprime rien. Les fiches se citent de deux facons, pointeur markdown et [[lien]],
ce dernier par nom de fichier OU par `name:` du frontmatter (tirets ou soulignes).
"""
from __future__ import annotations

import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

compacteur = pytest.importorskip("forge_memory_compactor")


@pytest.fixture
def memoire(tmp_path):
    (tmp_path / "MEMORY.md").write_text("- [A](a.md) x\n- [Mort](absent.md) y\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("voir [[b]] et [[lien_mort]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("---\nname: b\n---\nvoir [[fiche-c]]\n", encoding="utf-8")
    (tmp_path / "c_fichier.md").write_text("---\nname: fiche_c\n---\nfin\n", encoding="utf-8")
    (tmp_path / "orpheline.md").write_text("cite [[a]] mais personne ne la cite\n", encoding="utf-8")
    return tmp_path


def test_taille_de_l_index(memoire):
    r = compacteur.audit_index(memoire)
    assert r["index_lignes"] == 2
    assert r["index_octets"] == (memoire / "MEMORY.md").stat().st_size


def test_portee_par_sauts(memoire):
    r = compacteur.audit_index(memoire)
    assert r["fiches"] == 4
    assert r["a_1_saut"] == ["a.md"]
    assert r["a_2_sauts"] == ["b.md"]
    assert r["au_dela"] == ["c_fichier.md"]
    assert r["orphelines"] == ["orpheline.md"]


def test_les_liens_morts_sont_nommes(memoire):
    r = compacteur.audit_index(memoire)
    assert r["liens_morts_index"] == ["absent.md"]
    assert r["crochets_morts"] == ["lien_mort"]


def test_lecture_seule(memoire):
    avant = {p.name: p.read_bytes() for p in memoire.iterdir()}
    compacteur.audit_index(memoire)
    assert {p.name: p.read_bytes() for p in memoire.iterdir()} == avant


def test_strict_resout_comme_obsidian_par_nom_de_fichier(memoire):
    """`[[fiche-c]]` ne vise que `name: fiche_c` : Obsidian n'y voit aucun fichier."""
    r = compacteur.audit_index(memoire, strict=True)
    assert r["a_2_sauts"] == ["b.md"]
    assert r["au_dela"] == []
    assert r["orphelines"] == ["c_fichier.md", "orpheline.md"]
    assert r["crochets_morts"] == ["fiche-c", "lien_mort"]
    assert r["crochets_reparables"] == {"fiche-c": "c_fichier.md"}


def test_strict_accepte_alias_section_et_casse(tmp_path):
    (tmp_path / "MEMORY.md").write_text("- [A](a.md)\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("[[B|alias]] [[c#section]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "c.md").write_text("x", encoding="utf-8")
    r = compacteur.audit_index(tmp_path, strict=True)
    assert r["a_2_sauts"] == ["b.md", "c.md"]
    assert r["crochets_morts"] == []


def test_une_cible_ambigue_n_est_pas_reparable(tmp_path):
    (tmp_path / "MEMORY.md").write_text("- [A](a.md)\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("[[g_h]]\n", encoding="utf-8")
    (tmp_path / "g-h.md").write_text("x", encoding="utf-8")
    (tmp_path / "autre.md").write_text("---\nname: g_h\n---\n", encoding="utf-8")
    r = compacteur.audit_index(tmp_path, strict=True)
    assert r["crochets_morts"] == ["g_h"]
    assert r["crochets_reparables"] == {}


def test_reparer_en_dry_run_n_ecrit_rien(memoire):
    avant = {p.name: p.read_bytes() for p in memoire.iterdir()}
    r = compacteur.reparer_crochets(memoire, dry_run=True)
    assert r["liens_repares"] == 1 and r["fiches"] == 1
    assert {p.name: p.read_bytes() for p in memoire.iterdir()} == avant


def test_reparer_ecrit_le_nom_de_fichier_et_garde_alias_et_section(memoire, monkeypatch):
    monkeypatch.setattr(compacteur, "_synchroniser_ledger", lambda _d: None)
    (memoire / "b.md").write_text("[[fiche-c]] [[fiche-c|vu]] [[fiche-c#s]] [[lien_mort]]\n", encoding="utf-8")
    index_avant = (memoire / "MEMORY.md").read_bytes()
    compacteur.reparer_crochets(memoire, dry_run=False)
    assert (memoire / "b.md").read_text(encoding="utf-8") == (
        "[[c_fichier]] [[c_fichier|vu]] [[c_fichier#s]] [[lien_mort]]\n")
    assert (memoire / "MEMORY.md").read_bytes() == index_avant
    assert compacteur.audit_index(memoire, strict=True)["crochets_reparables"] == {}


def test_sans_ledger_rien_n_est_reecrit(memoire, monkeypatch):
    def panne(_d):
        raise OSError("ledger")

    monkeypatch.setattr(compacteur, "_synchroniser_ledger", panne)
    avant = (memoire / "b.md").read_bytes()
    r = compacteur.reparer_crochets(memoire, dry_run=False)
    assert "ARRET" in r
    assert (memoire / "b.md").read_bytes() == avant


def test_l_alarme_sonne_avant_le_cap_de_chargement():
    """Choix owner 5/11 : plafond 25 Ko (= cap 24,4 Kio), alarme a 22 Ko pour replier avant la perte."""
    assert compacteur._SEUIL_DEFAUT_KB == 22.0
    assert compacteur._CAP_CHARGEMENT_KB - compacteur._SEUIL_DEFAUT_KB >= 2


def test_index_absent_est_illisible_pas_vide(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    r = compacteur.audit_index(tmp_path)
    assert r["etat"] == "ILLISIBLE"
    assert "orphelines" not in r
