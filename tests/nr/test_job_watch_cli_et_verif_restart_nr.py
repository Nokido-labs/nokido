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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
