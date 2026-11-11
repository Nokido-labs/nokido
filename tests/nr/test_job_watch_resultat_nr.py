"""NR 5/11 (owner : plus possible de gacher les tokens) : la notification de fin d'un job porte ses lignes RESULTAT.

Sans elles, chaque job coutait un tour de plus (`job_status`) pour lire son verdict, avec toute la queue du journal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_job_watch_cli as W  # noqa: E402


def _fin(tmp_path, journal):
    (tmp_path / "job_x.log").write_text(journal, encoding="utf-8")
    (tmp_path / "job_x.rc").write_text("0", encoding="utf-8")
    sortie = []
    W.surveiller("job_x", 900, 60, 1, ecrire=sortie.append, jobs_dir=tmp_path, activite=lambda _pid: None)
    assert len(sortie) == 1
    return sortie[0]


def test_la_fin_porte_les_lignes_resultat_et_pas_le_bruit(tmp_path):
    message = _fin(tmp_path, "bruit\nRESULTAT a: 1\nautre bruit\nRESULTAT b: 2\n")
    assert "TERMINE" in message
    assert "RESULTAT a: 1" in message and "RESULTAT b: 2" in message
    assert "bruit" not in message


def test_le_volume_est_plafonne_et_la_troncature_est_dite(tmp_path):
    journal = "".join("RESULTAT ligne %03d %s\n" % (i, "x" * 90) for i in range(60))
    message = _fin(tmp_path, journal)
    assert "RESULTAT ligne 000" in message
    assert "RESULTAT ligne 059" not in message
    assert "tronque" in message
    assert len(message.split("\n", 1)[1]) <= W.PLAFOND_RESULTAT + 80


def test_un_journal_sans_resultat_ne_fabrique_rien(tmp_path):
    message = _fin(tmp_path, "bruit\n")
    assert "RESULTAT" not in message
    assert "\n" not in message
