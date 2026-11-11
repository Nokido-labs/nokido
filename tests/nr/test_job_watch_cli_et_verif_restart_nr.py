"""NR — le CLI de surveillance émet sur TOUS les chemins, et le script de vérif ne se fait pas passer pour une sonde.

Deux modules signalés par le cliquet de couverture (`test_nr_coverage_ratchet_nr`)
le 2026-09-13 : ajoutés sans aucun test. Le cliquet avait raison.

`forge_job_watch_cli` est la SEULE forme de surveillance que `bash_guard` accepte
pour `Monitor` depuis la fermeture des passe-droits. S'il reste muet sur un
chemin, le silence ressemble a « ca tourne » -- et un moniteur qui n'emet que
sur le chemin heureux laisse passer un crash sans un mot.

`forge_verif_post_restart_securite` porte un `RUNTIME_ACTIVE` ecrit EN DUR. Il
est utile comme compte rendu de chantier, mais le lire comme une sonde fait
conclure « le redemarrage a eu lieu » sans avoir rien mesure. Le NR verrouille
que cette limite reste DITE dans le module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_job_watch_cli as cli  # noqa: E402


def _capture():
    lignes: list[str] = []
    return lignes, lignes.append


def test_fin_de_job_emise_avec_son_code(tmp_path):
    (tmp_path / "job_x.log").write_text("...", encoding="utf-8")
    (tmp_path / "job_x.rc").write_text("0\n", encoding="utf-8")
    vues, ecrire = _capture()
    code = cli.surveiller("job_x", gel_s=900, max_s=4800, intervalle=0,
                          ecrire=ecrire, jobs_dir=tmp_path)
    assert code == 0
    assert any("TERMINE" in l and "rc=0" in l for l in vues), vues
    # Le rc est un SIGNAL : le module doit le dire, sinon on conclut dessus.
    assert any("SIGNAL" in l for l in vues), "le rc est presente comme un verdict"


def test_gel_emis_quand_le_journal_cesse_de_grossir(tmp_path):
    """Silence != succes : un job fige doit produire une ligne."""
    (tmp_path / "job_y.log").write_text("...", encoding="utf-8")
    faux_temps = {"t": 1000.0}

    def horloge():
        return faux_temps["t"]

    def dormir(_s):
        faux_temps["t"] += 600.0  # le journal, lui, ne bouge pas

    vues, ecrire = _capture()
    code = cli.surveiller("job_y", gel_s=900, max_s=999999, intervalle=1,
                          ecrire=ecrire, jobs_dir=tmp_path,
                          horloge=horloge, dormir=dormir)
    assert code == 0
    assert any("FIGE" in l for l in vues), vues


def test_depassement_emis_plutot_que_silence(tmp_path):
    """Ni fin ni gel : il faut quand meme une ligne, sinon on attend sans savoir."""
    log = tmp_path / "job_z.log"
    log.write_text("...", encoding="utf-8")
    faux_temps = {"t": 1000.0}

    def horloge():
        return faux_temps["t"]

    def dormir(_s):
        faux_temps["t"] += 100.0
        log.write_text("... %s" % faux_temps["t"], encoding="utf-8")  # progresse

    vues, ecrire = _capture()
    code = cli.surveiller("job_z", gel_s=900, max_s=300, intervalle=1,
                          ecrire=ecrire, jobs_dir=tmp_path,
                          horloge=horloge, dormir=dormir)
    assert code == 0
    assert any("TOUJOURS EN COURS" in l for l in vues), vues


def test_un_job_qui_est_un_chemin_est_refuse():
    """`--job` est un identifiant : un chemin ferait sortir du dossier des jobs."""
    for mauvais in ("../x", "a/b", r"a\b"):
        assert cli.main(["--job", mauvais]) == 2


def test_le_script_de_verif_dit_qu_il_n_est_pas_une_sonde():
    """Son RUNTIME_ACTIVE est ecrit en dur : le lire comme une mesure trompe."""
    src = (ROOT / "tools" / "forge_verif_post_restart_securite.py").read_text(
        encoding="utf-8", errors="replace")
    assert "PREDIT n'est PAS OBSERVE" in src, (
        "le module ne dit plus que sa sortie predite n'est pas une observation"
    )
    assert "RUNTIME_OBSERVED" in src and "RUNTIME_ACTIVE" in src, (
        "les deux qualites doivent rester distinguees dans le rapport"
    )


def test_ligne_bilan_du_producteur_lue_comme_declaree():
    """NR 10/11 : job_6841505421b8 portait `BILAN verification : archiver prouves=40 | ...` et le guet
    annoncait « rc=0 sans ligne de bilan » -- un faux silence sur un bilan ecrit."""
    for ligne in ("BILAN verification : archiver prouves=40 | a instruire=0",
                  "=== BILAN rc=0 fuites=24"):
        b = cli.lire_bilan(rc="0", texte="du bruit\n" + ligne + "\n")
        assert b["etat"] == "DECLARE", b
        assert "BILAN" in b["motif"]
    # sans bilan, le silence reste non verifie ; un Traceback apres le bilan reste un ECHEC
    assert cli.lire_bilan(rc="0", texte="rien\n")["etat"] == "TERMINE_NON_VERIFIE"
    assert cli.lire_bilan(rc="0", texte="BILAN x\nTraceback (most recent call last):\nE\n")["etat"] == "ECHEC"


def test_ci_verte_pas_etiquetee_echec_par_la_trace_d_un_gate_non_mesure():
    """11/11, job_470dcd142930 : pre-vol VERT (21 953 tests, 0 echec, « Tous les gates bloquants passent ») annonce
    « bilan ECHEC ». La trace reseau de pip-audit (gate UNKNOWN, supplee) est imprimee APRES la ligne [preuve] ;
    toute trace posterieure valait echec. Le verdict final de la CI, ecrit APRES la trace, la domine."""
    preuve = ("  [preuve] sha=455d86f5ead4  executes=21953  skipped=39  echecs=0  erreurs=0  timeouts=0  "
              "blocs_sans_preuve=0  declares_absents=0  etat=SUITE_COMPLETE")
    trace = "Traceback (most recent call last):\n  File \"x.py\", line 1, in send\nrequests.exceptions.ConnectionError: pypi"
    vert = "\x1b[1;32mTous les gates bloquants passent\x1b[0m \x1b[1;33m(1 non mesure(s), tous supplees)\x1b[0m"
    b = cli.lire_bilan(rc="0", texte="\n".join([preuve, trace, "  → UNKNOWN — le gate n'a pas pu se prononcer", vert]) + "\n")
    assert b["etat"] == "DECLARE", b
    # contre-epreuve : une trace APRES le verdict final (crash a la sortie) reste un ECHEC
    b = cli.lire_bilan(rc="0", texte="\n".join([preuve, vert, trace]) + "\n")
    assert b["etat"] == "ECHEC", b


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
