"""NR : coupe des vieux journaux de sandbox/jobs (décision owner 2026-11-05).

Un job terminé depuis plus de 30 jours et non cité ne garde que la fin de son journal (64 Ko) : job_status lit
la fin, le verdict y est. Essai à blanc sans LAFORGE_JOBS_REGISTRE_PURGE=applique, interrupteur distinct de
celui de laforge_jobs. Une fiche, un .rc, un .err ne bougent jamais. Ce qu'on ne peut pas lire est gardé.
"""
import importlib.util
import json
import os
import pathlib
import time

import pytest

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_log_retention.py"
_spec = importlib.util.spec_from_file_location("flr_registre_nr", _CHEMIN)
flr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flr)

JOUR = 86400
ID = "job_0123456789ab"


def _vieillir(chemin, age_j):
    t = time.time() - age_j * JOUR
    os.utime(chemin, (t, t))
    return chemin


def _job(registre, jid=ID, age_j=40, octets=200_000, rc=True, statut="done"):
    """Un job complet. Le journal finit par FIN_<jid> pour prouver que la fin survit."""
    ligne = b"ligne de journal\n"
    corps = ligne * (octets // len(ligne)) + b"FIN_" + jid.encode() + b"\n"
    log = registre / f"{jid}.log"
    log.write_bytes(corps)
    (registre / f"{jid}.json").write_text(json.dumps({"status": statut}), encoding="utf-8")
    (registre / f"{jid}.err").write_text("erreur", encoding="utf-8")
    if rc:
        (registre / f"{jid}.rc").write_text("0", encoding="utf-8")
    _vieillir(log, age_j)
    return log


@pytest.fixture
def reg(tmp_path, monkeypatch):
    registre = tmp_path / "jobs"
    memoire = tmp_path / "memory"
    registre.mkdir()
    memoire.mkdir()
    (memoire / "fiche.md").write_text("rien", encoding="utf-8")
    monkeypatch.setattr(flr, "JOBS_REGISTRE_DIR", registre)
    monkeypatch.setattr(flr, "MEMOIRE_AGENT_DIR", memoire)
    monkeypatch.setattr(flr, "_registre_citations_depot", lambda: set())
    monkeypatch.setenv("LAFORGE_JOBS_REGISTRE_PURGE", "applique")
    monkeypatch.delenv("LAFORGE_JOBS_PURGE", raising=False)
    return type("Reg", (), {"dir": registre, "memoire": memoire})


def test_vieux_journal_coupe_garde_la_fin_et_le_dit(reg):
    log = _job(reg.dir)
    avant = log.stat()
    r = flr._couper_journaux_registre(False)
    apres = log.read_bytes()
    assert r["registre_mode"] == "applique" and r["registre_coupes"] == 1
    assert len(apres) <= flr.JOBS_REGISTRE_QUEUE + 256
    assert apres.endswith(b"FIN_" + ID.encode() + b"\n")
    assert apres.startswith(b"[coupe par forge_log_retention")
    assert r["registre_octets_liberes"] == avant.st_size - len(apres)


def test_coupe_commence_a_une_ligne_entiere(reg):
    log = _job(reg.dir)
    flr._couper_journaux_registre(False)
    lignes = log.read_bytes().split(b"\n")
    assert lignes[1] == b"ligne de journal"


def test_la_date_du_journal_est_conservee(reg):
    log = _job(reg.dir)
    avant = log.stat().st_mtime
    flr._couper_journaux_registre(False)
    assert abs(log.stat().st_mtime - avant) < 2


def test_fiche_rc_err_ne_bougent_pas(reg):
    _job(reg.dir)
    avant = {p.name: p.read_bytes() for p in reg.dir.iterdir() if p.suffix != ".log"}
    flr._couper_journaux_registre(False)
    assert {p.name: p.read_bytes() for p in reg.dir.iterdir() if p.suffix != ".log"} == avant
    assert sorted(p.name for p in reg.dir.iterdir()) == sorted([f"{ID}.log"] + list(avant))


def test_seconde_passe_ne_recoupe_pas(reg):
    log = _job(reg.dir)
    flr._couper_journaux_registre(False)
    contenu = log.read_bytes()
    r = flr._couper_journaux_registre(False)
    assert log.read_bytes() == contenu and r["registre_coupes"] == 0 and r["registre_courts"] == 1


def test_journal_recent_intact(reg):
    log = _job(reg.dir, age_j=29)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_recents"] == 1 and r["registre_coupes"] == 0


def test_journal_court_intact(reg):
    log = _job(reg.dir, octets=1000)
    contenu = log.read_bytes()
    r = flr._couper_journaux_registre(False)
    assert log.read_bytes() == contenu and r["registre_courts"] == 1


def test_job_sans_rc_intact(reg):
    log = _job(reg.dir, rc=False)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_gardes_vivants"] == 1


def test_fiche_running_intacte(reg):
    log = _job(reg.dir, statut="running")
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_gardes_vivants"] == 1


@pytest.mark.parametrize("casse", ["absente", "tronquee"])
def test_fiche_illisible_garde_le_journal(reg, casse):
    log = _job(reg.dir)
    fiche = reg.dir / f"{ID}.json"
    if casse == "absente":
        fiche.unlink()
    else:
        fiche.write_text("{ tronqué", encoding="utf-8")
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_gardes_illisibles"] == 1


def test_journal_cite_en_memoire_intact(reg):
    log = _job(reg.dir)
    (reg.memoire / "fiche.md").write_text(f"preuve dans {ID}, voir", encoding="utf-8")
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_gardes_cites"] == 1


def test_journal_cite_dans_le_depot_intact(reg, monkeypatch):
    log = _job(reg.dir)
    monkeypatch.setattr(flr, "_registre_citations_depot", lambda: {ID})
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_gardes_cites"] == 1


@pytest.mark.parametrize("muet", ["memoire", "depot"])
def test_citations_illisibles_gardent_tout(reg, monkeypatch, muet):
    log = _job(reg.dir)
    if muet == "memoire":
        (reg.memoire / "fiche.md").unlink()
    else:
        monkeypatch.setattr(flr, "_registre_citations_depot", lambda: None)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille
    assert r["registre_eligibles"] == 0 and r["registre_illisible"]


def test_a_blanc_sans_interrupteur_chiffre_le_gain(reg, monkeypatch):
    monkeypatch.delenv("LAFORGE_JOBS_REGISTRE_PURGE")
    log = _job(reg.dir)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille
    assert r["registre_mode"] == "dry-run" and r["registre_eligibles"] == 1 and r["registre_coupes"] == 0
    assert r["registre_octets_liberables"] == taille - flr.JOBS_REGISTRE_QUEUE
    assert r["registre_octets_liberes"] == 0


def test_interrupteur_de_laforge_jobs_ne_suffit_pas(reg, monkeypatch):
    monkeypatch.delenv("LAFORGE_JOBS_REGISTRE_PURGE")
    monkeypatch.setenv("LAFORGE_JOBS_PURGE", "applique")
    log = _job(reg.dir)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(False)
    assert log.stat().st_size == taille and r["registre_mode"] == "dry-run"


def test_dry_de_l_appelant_prime(reg):
    log = _job(reg.dir)
    taille = log.stat().st_size
    r = flr._couper_journaux_registre(True)
    assert log.stat().st_size == taille and r["registre_mode"] == "dry-run"


def test_journal_agy_jamais_touche(reg):
    agy = reg.dir / "agy_job_0123456789ab.log"
    agy.write_bytes(b"x" * 200_000)
    _vieillir(agy, 90)
    r = flr._couper_journaux_registre(False)
    assert agy.stat().st_size == 200_000 and r["registre_vus"] == 0


def test_remplacement_refuse_laisse_l_original_et_se_nomme(reg, monkeypatch):
    log = _job(reg.dir)
    contenu = log.read_bytes()

    def refus(_src, _dst):
        raise PermissionError("tenu")

    monkeypatch.setattr(flr.os, "replace", refus)
    r = flr._couper_journaux_registre(False)
    assert log.read_bytes() == contenu and r["registre_coupes"] == 0 and r["registre_echecs"] == 1
    assert ID in " ".join(r["registre_illisible"])
    assert not list(reg.dir.glob("*.coupe"))


def test_registre_absent_dit(reg, monkeypatch, tmp_path):
    monkeypatch.setattr(flr, "JOBS_REGISTRE_DIR", tmp_path / "absent")
    assert flr._couper_journaux_registre(False)["registre_zone"] == "absente"


def test_run_retention_appelle_la_coupe():
    import inspect

    assert "_couper_journaux_registre(dry)" in inspect.getsource(flr.run_retention)
