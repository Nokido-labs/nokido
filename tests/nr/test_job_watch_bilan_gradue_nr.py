"""NR — la fin d'un job se dit GRADUEE, jamais par le seul `rc` (fiche de veille V2, 2026-09-23).

Ecrit ROUGE avant correctif.

LE DEFAUT. `forge_job_watch_cli` annoncait « TERMINE rc=0 — le rc est un SIGNAL, le
verdict se lit sur l'artefact », puis s'arretait : il rappelait la regle sans
l'appliquer. Payes le meme jour : la vague 5 finie `rc=0` sans aucune ligne de
bilan (silence lu comme reussite), un job `rc=0` a 0 chunk, un arret de garde
disque `rc=5` qu'il fallait aller relire a la main.

CE QUE LE GRADER DIT, ET CE QU'IL NE DIT PAS. Il lit le BILAN que le producteur a
ecrit dans son journal. `DECLARE(N)` est donc l'affirmation du producteur — PAS
`VERIFIED`, qui exige une preuve independante (compte en base par source), hors de
portee d'un notifieur en lecture seule. Un grader qui ecrirait VERIFIED sur la foi
du producteur fabriquerait exactement le faux calme qu'il doit empecher.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

cli = pytest.importorskip("forge_job_watch_cli")


def _bilan(texte, rc):
    if not hasattr(cli, "lire_bilan"):
        pytest.fail("lire_bilan absent : la fin d'un job n'est toujours jugee que par son rc")
    return cli.lire_bilan(texte, rc)


def test_rc_zero_sans_bilan_n_est_pas_une_reussite():
    b = _bilan("ingest a.txt: +10 chunks\n", "0")
    assert b["etat"] == "TERMINE_NON_VERIFIE", b


def test_rc_zero_a_zero_chunk_est_vide():
    assert _bilan("TOTAL 0 chunks\n", "0")["etat"] == "VIDE"


def test_rc_zero_avec_bilan_est_declare_jamais_verified():
    b = _bilan("...\n  TOTAL 2790 chunks\n", "0")
    assert b["etat"] == "DECLARE" and b["chunks"] == 2790, b
    assert b["etat"] != "VERIFIED"


def test_bilan_de_l_ingesteur_de_depots():
    b = _bilan("=== RAG : +49503 chunks (domain=sdk_gitingest), 4279 skip ===\n", "0")
    assert b["etat"] == "DECLARE" and b["chunks"] == 49503, b


def test_arret_de_garde_est_nomme():
    log = ("=== ARRET PENDANT x.txt : 29.0 Go libres < seuil 30 Go sur le volume de C:\\RAG "
           "-- 28/316 depot(s) complets, +360398 chunks ===\n")
    b = _bilan(log, "5")
    assert b["etat"] == "ARRET_GARDE", b
    assert "29.0 Go libres" in b["motif"]


def test_un_arret_imprime_par_un_test_au_milieu_du_journal_n_est_pas_la_fin_du_job():
    # Mesure 2026-09-26 : la CI job_ab829f9d4715 (12 462 tests, 0 echec, SUITE_COMPLETE) a ete
    # annoncee « ARRET_GARDE : refus DEFINITIF de la lane : unauthorized » -- une ligne IMPRIMEE
    # par un NR de ci-attente qui simule des admissions (job_x pid=1 sur le sha abc1234), au
    # milieu d'un journal de 2 750 lignes.
    log = ("[ci-attente] ARRET — refus DEFINITIF de la lane : unauthorized.\n"
           + "".join("tests/nr/test_%03d_nr.py ....\n" % i for i in range(200))
           + "  [preuve] sha=abc  executes=12462  echecs=0  etat=SUITE_COMPLETE\n")
    assert _bilan(log, "0")["etat"] != "ARRET_GARDE"


def test_un_vrai_arret_en_queue_de_journal_reste_nomme():
    log = ("".join("[%d/316] depot ok\n" % i for i in range(200))
           + "=== ARRET PENDANT x.txt : 29.0 Go libres < seuil 30 Go ===\n")
    b = _bilan(log, "5")
    assert b["etat"] == "ARRET_GARDE" and "29.0 Go" in b["motif"], b


def test_une_ci_verte_qui_imprime_des_traceback_n_est_pas_un_echec():
    # Mesure 2026-09-26 : la CI de reference job_e073b2edba52 (12 496 executes, 0 echec,
    # SUITE_COMPLETE) a ete annoncee « bilan ECHEC » -- 13 Traceback IMPRIMES par des tests qui
    # passent (handlers de logging, threads) et aucun bilan d'ingestion : le premier suffisait.
    # Le bilan d'une CI est sa ligne `[preuve]`, telle que ci_local l'ecrit (couleurs ANSI comprises).
    log = ("Traceback (most recent call last):\n  File \"handlers.py\", line 81, in emit\n"
           "PermissionError: [WinError 32]\n"
           + "".join("tests/nr/test_%03d_nr.py ....\n" % i for i in range(200))
           + "\x1b[90m  [preuve] sha=d62be24b4868  executes=12496  skipped=22  echecs=0  erreurs=0  "
             "timeouts=0  etat=SUITE_COMPLETE\x1b[0m\n"
           + "Tous les gates bloquants passent.\n")
    b = _bilan(log, "0")
    assert b["etat"] == "DECLARE" and "SUITE_COMPLETE" in b["motif"], b


def test_une_preuve_ci_avec_des_echecs_est_un_echec():
    b = _bilan("  [preuve] sha=abc  executes=10  echecs=1  erreurs=0  timeouts=0  etat=SUITE_COMPLETE\n", "0")
    assert b["etat"] == "ECHEC" and "echecs=1" in b["motif"], b


def test_une_preuve_ci_incomplete_n_est_pas_une_reussite():
    b = _bilan("  [preuve] sha=abc  executes=10  echecs=0  erreurs=0  etat=SUITE_PARTIELLE\n", "0")
    assert b["etat"] == "TERMINE_NON_VERIFIE", b


def test_un_traceback_apres_la_preuve_reste_un_echec():
    log = ("  [preuve] sha=abc  executes=10  echecs=0  etat=SUITE_COMPLETE\n"
           "Traceback (most recent call last):\n  File x\nOSError: disque plein\n")
    b = _bilan(log, "0")
    assert b["etat"] == "ECHEC" and "OSError" in b["motif"], b


def test_traceback_est_un_echec_meme_a_rc_zero():
    b = _bilan("Traceback (most recent call last):\n  File x\nValueError: boom\n", "0")
    assert b["etat"] == "ECHEC", b
    assert "ValueError" in b["motif"]


def test_rc_non_nul_sans_motif_est_un_echec():
    assert _bilan("rien\n", "1")["etat"] == "ECHEC"


def test_rc_illisible_n_est_pas_un_succes():
    assert _bilan("TOTAL 5 chunks\n", "ILLISIBLE (OSError)")["etat"] == "INCONNU"


def test_le_motif_d_echec_vient_aussi_du_stderr(tmp_path):
    """Controle du 2026-09-23 sur 6 vrais jobs : les Traceback sont dans `.err`, et
    `surveiller` ne lisait que `.log` — l'echec etait note, sans son motif."""
    (tmp_path / "job_e.log").write_text("", encoding="utf-8")
    (tmp_path / "job_e.err").write_text("Traceback (most recent call last):\n  x\nIndexError: list index\n",
                                        encoding="utf-8")
    (tmp_path / "job_e.rc").write_text("1", encoding="utf-8")
    vues = []
    cli.surveiller("job_e", gel_s=900, max_s=60, intervalle=0, ecrire=vues.append,
                   jobs_dir=tmp_path, dormir=lambda s: None)
    ligne = next(l for l in vues if "TERMINE" in l)
    assert "ECHEC" in ligne and "IndexError" in ligne, ligne


def test_la_ligne_terminee_porte_le_bilan(tmp_path):
    """Chemin REEL : `surveiller` sur un job temoin, pas seulement la fonction pure."""
    (tmp_path / "job_t.log").write_text("  TOTAL 12 chunks\n", encoding="utf-8")
    (tmp_path / "job_t.rc").write_text("0", encoding="utf-8")
    vues = []
    cli.surveiller("job_t", gel_s=900, max_s=60, intervalle=0, ecrire=vues.append,
                   jobs_dir=tmp_path, dormir=lambda s: None)
    ligne = next(l for l in vues if "TERMINE" in l)
    assert "rc=0" in ligne and "DECLARE" in ligne and "12" in ligne, ligne
