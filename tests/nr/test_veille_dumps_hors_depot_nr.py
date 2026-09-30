# -*- coding: utf-8 -*-
"""NR 2026-09-23 — les dumps de veille peuvent vivre HORS du depot (E:).

Mesure du jour : sous `run_job online`, le compte `LaForgeSbxOnline` clone
enfin (commit obtenu), mais n'a pas le droit d'ecrire dans `docs/` ; il ecrit
sur `E:\\nokido_veille_dumps`, et `LaForgeSbxOffline` (l'ingestion) y relit.

Deplacer l'ECRIVAIN seul fabriquerait des faux ABSENT : trois lecteurs codaient
`ROOT/docs` en dur (clone_ingest --ingest-only, le backlog, le capteur GitHub).
Un seul resolveur, un seul interrupteur (`sandbox/veille_dumps.dir`) lu a chaque
appel — jamais site par site.
"""
from pathlib import Path

from nokido_agent.tools.forge_veille_registre import (
    chemin_dump,
    dossier_ecriture_dumps,
    dossiers_dumps,
    noms_dumps,
)


def _racine(tmp_path, *secondaires):
    (tmp_path / "docs").mkdir()
    if secondaires:
        (tmp_path / "sandbox").mkdir()
        (tmp_path / "sandbox" / "veille_dumps.dir").write_text(
            "# dossiers de dumps hors depot\n\n" + "\n".join(str(s) for s in secondaires),
            encoding="utf-8")
    return tmp_path


def _dump(dossier: Path, nom: str) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    p = dossier / ("gitingest_veille_%s.txt" % nom)
    p.write_text("x", encoding="utf-8")
    return p


def test_sans_interrupteur_seul_docs(tmp_path):
    r = _racine(tmp_path)
    assert dossiers_dumps(r) == [r / "docs"]


def test_interrupteur_ajoute_les_dossiers_et_ignore_commentaires(tmp_path):
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    assert dossiers_dumps(r) == [r / "docs", e]


def test_lecture_la_copie_la_plus_recente_gagne(tmp_path):
    import os
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    ds = dossiers_dumps(r)
    sec = _dump(e, "seul_sur_e")
    assert chemin_dump("seul_sur_e", ds) == sec
    # FILTRE_VERSION 2 (2026-09-23) : un dump PERIME de docs/ est re-dumpe sur E: ;
    # la copie neuve doit masquer l'ancienne, gelee (jamais supprimee).
    vieux = _dump(r / "docs", "double")
    os.utime(vieux, (1_000_000, 1_000_000))
    neuf = _dump(e, "double")
    assert chemin_dump("double", ds) == neuf
    os.utime(neuf, (500_000, 500_000))
    assert chemin_dump("double", ds) == vieux
    assert chemin_dump("absent", ds) is None


def test_ecriture_premier_dossier_inscriptible_hors_depot_d_abord(tmp_path):
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    ds = dossiers_dumps(r)
    _dump(r / "docs", "historique")
    # Mesure 2026-09-23 : le compte online NE PEUT PAS ecrire dans docs/. Ecrire
    # « la ou le dump existe » faisait mourir le job sur le 1er dump perime.
    assert dossier_ecriture_dumps("historique", ds) == e
    assert dossier_ecriture_dumps("neuf", ds) == e
    # sans interrupteur : comportement d'avant, docs/
    assert dossier_ecriture_dumps("neuf", [r / "docs"]) == r / "docs"


def test_ecriture_repli_sur_docs_si_hors_depot_non_inscriptible(tmp_path):
    bloque = tmp_path / "pas_un_dossier"
    bloque.write_text("fichier, pas dossier", encoding="utf-8")
    r = _racine(tmp_path, bloque)
    assert dossier_ecriture_dumps("x", dossiers_dumps(r)) == r / "docs"


def test_noms_dumps_couvre_tous_les_dossiers(tmp_path):
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    _dump(r / "docs", "a")
    _dump(e, "b")
    _dump(e, "a")
    assert sorted(noms_dumps(dossiers_dumps(r))) == ["a", "b"]


def test_ecrivain_atomique_en_flux_tout_ou_rien(tmp_path):
    """Mesure 2026-09-23 : dump construit en memoire -> job tue a 6 151 Mo.
    L'ecriture en flux garde le contrat : rien de visible avant `valider`."""
    from nokido_agent.tools.forge_veille_registre import EcrivainAtomique
    cible = tmp_path / "d" / "dump.txt"
    e = EcrivainAtomique(cible)
    e.write("a")
    e.write("b\n")
    assert not cible.exists()                       # rien avant validation
    assert e.valider() == cible and cible.read_text(encoding="utf-8") == "ab\n"
    e.abandonner()                                  # apres valider : sans effet
    assert cible.exists()
    e2 = EcrivainAtomique(cible)
    e2.write("tronque")
    e2.abandonner()
    assert cible.read_text(encoding="utf-8") == "ab\n"   # l'ancien intact
    assert [p.name for p in cible.parent.iterdir()] == ["dump.txt"]  # 0 .tmp


def test_capteur_github_voit_un_dump_hors_depot(tmp_path):
    from nokido_agent.app.forge_autonomous_loops import _gh_cibles_suivies
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    _dump(e, "org_depot")
    doc = {"cibles": {"org_depot": {"url": "https://github.com/org/depot",
                                     "target_id": "t1"}}}
    suivies, sans = _gh_cibles_suivies(doc, dossiers=dossiers_dumps(r))
    assert [c["slug"] for c in suivies] == ["org_depot"] and sans == 0


def test_clone_ingest_resout_lecture_et_ecriture_via_interrupteur(tmp_path):
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    e = tmp_path / "E"
    r = _racine(tmp_path, e)
    sec = _dump(e, "foo")
    assert ci._chemin_dump("foo", racine=r) == sec
    assert ci._chemin_dump("inconnu", racine=r) == r / "docs" / "gitingest_veille_inconnu.txt"
    assert ci._sortie_dump("bar", racine=r) == e / "gitingest_veille_bar.txt"
    _dump(r / "docs", "perime")
    assert ci._sortie_dump("perime", racine=r) == e / "gitingest_veille_perime.txt"
