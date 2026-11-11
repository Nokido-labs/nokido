"""NR : rotation par âge de C:/tmp/laforge_jobs (décision owner 2026-11-05).

Sorties (.out, .xml) après 7 jours, scripts (.py) après 30 jours sans usage. Essai à blanc tant que
l'owner n'a pas validé. Ce qu'on ne peut pas lire ne vaut jamais « sans usage » : une source muette
garde le fichier. Tout ce que la décision ne couvre pas (.db, autres dossiers, autres suffixes) reste en place.

Extension décidée par l'owner le même jour : dossiers bt_*, fouille_*, essai_* et fichiers .log, .txt après
30 jours, sauf s'ils sont cités. L'âge d'un dossier est celui de son contenu le plus récent. invsqrt,
ctx_kickmix, wheels_bm25 restent intacts.
"""
import importlib.util
import json
import os
import pathlib
import time

import pytest

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_log_retention.py"
_spec = importlib.util.spec_from_file_location("flr_rotation_nr", _CHEMIN)
flr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flr)

JOUR = 86400


def _ecrire(chemin, age_j, texte="x"):
    chemin.write_text(texte, encoding="utf-8")
    t = time.time() - age_j * JOUR
    os.utime(chemin, (t, t))
    return chemin


@pytest.fixture
def bac(tmp_path, monkeypatch):
    bac = tmp_path / "laforge_jobs"
    registre = tmp_path / "jobs"
    memoire = tmp_path / "memory"
    for d in (bac, registre, memoire):
        d.mkdir()
    _ecrire(registre / "job_temoin.json", 1, json.dumps({"script": "C:\\tmp\\autre\\temoin.py"}))
    _ecrire(memoire / "fiche.md", 1, "rien")
    monkeypatch.setattr(flr, "JOBS_TMP_DIR", bac)
    monkeypatch.setattr(flr, "JOBS_REGISTRE_DIR", registre)
    monkeypatch.setattr(flr, "MEMOIRE_AGENT_DIR", memoire)
    monkeypatch.setattr(flr, "_jobs_citations_depot", lambda: set())
    monkeypatch.setenv("LAFORGE_JOBS_PURGE", "applique")
    bac_ns = type("Bac", (), {"bac": bac, "registre": registre, "memoire": memoire})
    return bac_ns


def test_sortie_vieille_purgee_recente_gardee(bac):
    vieux = [_ecrire(bac.bac / "a.out", 8), _ecrire(bac.bac / "b.xml", 8)]
    recents = [_ecrire(bac.bac / "c.out", 6), _ecrire(bac.bac / "d.xml", 6)]
    r = flr._purge_laforge_jobs(False)
    assert not any(p.exists() for p in vieux)
    assert all(p.exists() for p in recents)
    assert r["jobs_mode"] == "applique" and r["jobs_fichiers_purges"] == 2


def test_sans_interrupteur_rien_n_est_supprime(bac, monkeypatch):
    monkeypatch.delenv("LAFORGE_JOBS_PURGE")
    vieux = _ecrire(bac.bac / "a.out", 40)
    r = flr._purge_laforge_jobs(False)
    assert vieux.exists()
    assert r["jobs_mode"] == "dry-run"
    assert r["jobs_fichiers_eligibles"] == 1 and r["jobs_fichiers_purges"] == 0


def test_dry_de_l_appelant_prime_sur_l_interrupteur(bac):
    vieux = _ecrire(bac.bac / "a.out", 40)
    r = flr._purge_laforge_jobs(True)
    assert vieux.exists() and r["jobs_mode"] == "dry-run"


def test_script_sans_usage_purge_seulement_apres_30_jours(bac):
    vieux = _ecrire(bac.bac / "vieux.py", 31)
    recent = _ecrire(bac.bac / "recent.py", 29)
    flr._purge_laforge_jobs(False)
    assert not vieux.exists() and recent.exists()


def test_script_lance_par_un_job_recent_est_garde(bac):
    utilise = _ecrire(bac.bac / "utilise.py", 60)
    _ecrire(bac.registre / "job_a.json", 2, json.dumps({"script": f"C:\\tmp\\laforge_jobs\\{utilise.name}"}))
    r = flr._purge_laforge_jobs(False)
    assert utilise.exists() and r["jobs_gardes_usage"] == 1


def test_job_ancien_ne_vaut_pas_usage(bac):
    oublie = _ecrire(bac.bac / "oublie.py", 60)
    _ecrire(bac.registre / "job_a.json", 40, json.dumps({"script": f"C:\\tmp\\laforge_jobs\\{oublie.name}"}))
    flr._purge_laforge_jobs(False)
    assert not oublie.exists()


def test_fichier_cite_en_memoire_ou_dans_le_depot_est_garde(bac, monkeypatch):
    cite_memoire = _ecrire(bac.bac / "lire_commit.py", 90)
    sortie_citee = _ecrire(bac.bac / "rapport.xml", 90)
    cite_depot = _ecrire(bac.bac / "doc.py", 90)
    _ecrire(bac.memoire / "fiche.md", 1, "voir C:/tmp/laforge_jobs/lire_commit.py et laforge_jobs\\rapport.xml")
    monkeypatch.setattr(flr, "_jobs_citations_depot", lambda: {"doc.py"})
    r = flr._purge_laforge_jobs(False)
    assert cite_memoire.exists() and sortie_citee.exists() and cite_depot.exists()
    assert r["jobs_gardes_cites"] == 3


def test_script_appele_par_un_script_garde_est_garde_transitivement(bac):
    tete = _ecrire(bac.bac / "tete.py", 1, "import milieu\n")
    milieu = _ecrire(bac.bac / "milieu.py", 90, "subprocess.run(['python', 'feuille.py'])\n")
    feuille = _ecrire(bac.bac / "feuille.py", 90)
    orphelin = _ecrire(bac.bac / "orphelin.py", 90)
    flr._purge_laforge_jobs(False)
    assert tete.exists() and milieu.exists() and feuille.exists()
    assert not orphelin.exists()


def test_registre_muet_garde_les_scripts_mais_pas_les_sorties(bac):
    (bac.registre / "job_temoin.json").unlink()
    script = _ecrire(bac.bac / "s.py", 90)
    sortie = _ecrire(bac.bac / "s.out", 90)
    r = flr._purge_laforge_jobs(False)
    assert script.exists() and not sortie.exists()
    assert "registre" in " ".join(r["jobs_illisible"])


def test_job_illisible_garde_les_scripts(bac):
    _ecrire(bac.registre / "job_b.json", 1, "{ tronqué")
    script = _ecrire(bac.bac / "s.py", 90)
    r = flr._purge_laforge_jobs(False)
    assert script.exists() and r["jobs_illisible"]


@pytest.mark.parametrize("muet", ["memoire", "depot"])
def test_citations_illisibles_gardent_tout(bac, monkeypatch, muet):
    if muet == "memoire":
        (bac.memoire / "fiche.md").unlink()
    else:
        monkeypatch.setattr(flr, "_jobs_citations_depot", lambda: None)
    script = _ecrire(bac.bac / "s.py", 90)
    sortie = _ecrire(bac.bac / "s.out", 90)
    r = flr._purge_laforge_jobs(False)
    assert script.exists() and sortie.exists()
    assert r["jobs_fichiers_eligibles"] == 0 and r["jobs_illisible"]


def test_hors_decision_jamais_touche_mais_compte(bac):
    db = _ecrire(bac.bac / "copie.db", 400, "base")
    autre = _ecrire(bac.bac / "note.json", 400)
    dossier = _dossier(bac.bac / "invsqrt", 400)
    r = flr._purge_laforge_jobs(False)
    assert db.exists() and autre.exists() and (dossier / "a.out").exists()
    assert r["jobs_hors_decision_fichiers"] == 2
    assert r["jobs_hors_decision_octets"] == len("base") + 1
    assert r["jobs_hors_decision_dossiers"] == ["invsqrt"]


def _dossier(chemin, age_j, contenu=("a.out", "sous/b.txt")):
    """Arbre dont fichiers et dossiers ont le même âge, racine comprise."""
    chemin.mkdir()
    for rel in contenu:
        f = chemin / rel
        f.parent.mkdir(exist_ok=True)
        _ecrire(f, age_j)
    t = time.time() - age_j * JOUR
    for d in [p for p in chemin.rglob("*") if p.is_dir()] + [chemin]:
        os.utime(d, (t, t))
    return chemin


@pytest.mark.parametrize("nom", ["bt_x", "fouille_x", "essai_x"])
def test_dossier_jetable_vieux_retire_entier(bac, nom):
    d = _dossier(bac.bac / nom, 31)
    r = flr._purge_laforge_jobs(False)
    assert not d.exists()
    assert r["jobs_dossiers_eligibles"] == 1 and r["jobs_dossiers_purges"] == 1
    assert r["jobs_octets_liberes"] == 2


def test_dossier_jetable_garde_a_29_jours(bac):
    d = _dossier(bac.bac / "bt_x", 29)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_dossiers_eligibles"] == 0 and r["jobs_gardes_recents"] == 1


def test_age_du_dossier_est_celui_de_son_contenu_le_plus_recent(bac):
    d = _dossier(bac.bac / "bt_x", 90, ("a.out", "sous/b.txt"))
    _ecrire(d / "sous" / "b.txt", 2)
    t = time.time() - 90 * JOUR
    os.utime(d / "sous", (t, t))
    flr._purge_laforge_jobs(False)
    assert (d / "a.out").exists()


@pytest.mark.parametrize("nom", ["invsqrt", "ctx_kickmix", "wheels_bm25"])
def test_dossier_non_jetable_jamais_touche(bac, nom):
    d = _dossier(bac.bac / nom, 400)
    r = flr._purge_laforge_jobs(False)
    assert (d / "a.out").exists() and r["jobs_hors_decision_dossiers"] == [nom]


@pytest.mark.parametrize("citation", ["laforge_jobs/essai_pub", "voir laforge_jobs\\essai_pub.", "laforge_jobs/essai_pub/a.out"])
def test_dossier_jetable_cite_est_garde(bac, citation):
    d = _dossier(bac.bac / "essai_pub", 90)
    _ecrire(bac.memoire / "fiche.md", 1, citation)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_gardes_cites"] == 1


def test_dossier_jetable_a_blanc_sans_interrupteur(bac, monkeypatch):
    monkeypatch.delenv("LAFORGE_JOBS_PURGE")
    d = _dossier(bac.bac / "bt_x", 90)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_dossiers_eligibles"] == 1 and r["jobs_dossiers_purges"] == 0
    assert r["jobs_octets_eligibles"] == 2 and r["jobs_octets_liberes"] == 0


def test_journal_et_texte_retires_apres_30_jours_sauf_cites(bac):
    vieux = [_ecrire(bac.bac / "a.log", 31), _ecrire(bac.bac / "b.txt", 31)]
    recents = [_ecrire(bac.bac / "c.log", 29), _ecrire(bac.bac / "d.txt", 29)]
    cite = _ecrire(bac.bac / "e.log", 90)
    _ecrire(bac.memoire / "fiche.md", 1, "laforge_jobs/e.log")
    flr._purge_laforge_jobs(False)
    assert not any(p.exists() for p in vieux)
    assert all(p.exists() for p in recents) and cite.exists()


def test_dossier_ou_journal_nomme_par_un_script_garde_est_garde(bac):
    _ecrire(bac.bac / "tete.py", 1, "OUT = 'bt_vivant'\nLOG = 'trace.log'\n")
    d = _dossier(bac.bac / "bt_vivant", 90)
    journal = _ecrire(bac.bac / "trace.log", 90)
    autre = _dossier(bac.bac / "bt_oublie", 90)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and journal.exists() and not autre.exists()
    assert r["jobs_gardes_usage"] == 2


def test_citations_illisibles_gardent_les_dossiers(bac, monkeypatch):
    monkeypatch.setattr(flr, "_jobs_citations_depot", lambda: None)
    d = _dossier(bac.bac / "bt_x", 90)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_dossiers_eligibles"] == 0 and r["jobs_gardes_illisibles"] == 1


def test_registre_muet_garde_les_dossiers(bac):
    (bac.registre / "job_temoin.json").unlink()
    d = _dossier(bac.bac / "bt_x", 90)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_gardes_illisibles"] == 1


def test_contenu_illisible_garde_le_dossier(bac, monkeypatch):
    d = _dossier(bac.bac / "bt_x", 90)

    def refus(_chemin):
        raise PermissionError("refus")

    monkeypatch.setattr(flr, "_jobs_poids_dossier", refus)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_dossiers_eligibles"] == 0 and r["jobs_illisibles"] == 1
    assert "bt_x" in " ".join(r["jobs_illisible"])


def test_poids_dossier_lit_toute_la_profondeur(tmp_path):
    d = _dossier(tmp_path / "bt_x", 90)
    _ecrire(d / "sous" / "b.txt", 2, "abc")
    t = time.time() - 90 * JOUR
    os.utime(d / "sous", (t, t))
    recent, octets = flr._jobs_poids_dossier(d)
    assert octets == 4
    assert time.time() - recent < 3 * JOUR


def test_retrait_incomplet_compte_comme_echec(bac, monkeypatch):
    d = _dossier(bac.bac / "bt_x", 90)
    monkeypatch.setattr(flr, "_supprimer_arbre", lambda chemin: None)
    r = flr._purge_laforge_jobs(False)
    assert d.exists() and r["jobs_dossiers_purges"] == 0 and r["jobs_illisibles"] == 1
    assert r["jobs_octets_liberes"] == 0


def test_racine_absente_dite(bac, monkeypatch, tmp_path):
    monkeypatch.setattr(flr, "JOBS_TMP_DIR", tmp_path / "absente")
    assert flr._purge_laforge_jobs(False)["jobs_zone"] == "absente"


def test_run_retention_appelle_la_rotation():
    import inspect

    assert "_purge_laforge_jobs(dry)" in inspect.getsource(flr.run_retention)
