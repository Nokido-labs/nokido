"""Le gain se mesure sur de VRAIS processus, pas sur la fonction pure seule.

`test_ci_preuve_par_bloc_nr` eprouve la CLASSIFICATION (cinq etats, agregation).
Ce fichier-ci eprouve le MECANISME : deux vrais sous-processus pytest, deux vrais
rapports JUnit, un vrai `pytest-timeout` qui tue. Sans lui on prouverait qu'une
fonction pure sait dire TIMEOUT, jamais qu'un fichier coupe cesse d'emporter la
preuve des autres -- c'est-a-dire exactement ce que le mandat demande.

LA CONTRE-EPREUVE EST LA MOITIE DU FICHIER. `test_un_seul_processus_perd_TOUT`
rejoue l'ANCIEN schema : les deux fichiers dans le meme processus. Il doit montrer
que le rapport disparait ENTIEREMENT. Sans ce cas, le premier test passerait aussi
bien si l'isolation ne servait a rien, et on croirait avoir corrige quelque chose.

Cout : ~10 s (trois runs bornes a 2 s de timeout). C'est le prix d'une preuve qui
traverse le chemin reel plutot que de le contourner.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus pytest (python) (l.102)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

# Deux fichiers de test jetables. Le second ne rend PAS la main : c'est la forme
# reduite de ce qu'Hypothesis faisait subir a la suite le 2026-09-13.
SAIN = (
    "def test_un():\n"
    "    assert True\n"
    "\n"
    "\n"
    "def test_deux():\n"
    "    assert 1 + 1 == 2\n"
)
LENT = (
    "import time\n"
    "\n"
    "\n"
    "def test_qui_ne_rend_pas_la_main():\n"
    "    time.sleep(30)\n"
)

BORNE_S = 2


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


@pytest.fixture()
def faux_depot(tmp_path):
    (tmp_path / "test_sain.py").write_text(SAIN, encoding="utf-8")
    (tmp_path / "test_lent.py").write_text(LENT, encoding="utf-8")
    return tmp_path


def _pytest(cwd, cibles, xml):
    """Lance pytest comme le fait `ci_local` : rapport JUnit + borne de duree.

    `-p pytest_timeout` N'EST PAS DECORATIF. Le gate qui execute ce fichier pose
    `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` dans l'environnement, dont ce sous-processus
    HERITE : sans chargement explicite, `--timeout` devient une option inconnue,
    pytest sort en erreur d'usage et n'ecrit AUCUN rapport. Mesure du 2026-09-14 :
    ce fichier passait en local (autoload actif) et echouait en CI sur ce seul
    motif, avec pour tout symptome un `junit_sain.xml` absent.

    Le nom vient de `entry_points.txt` -- `[pytest11] timeout = pytest_timeout`,
    donc le module de TETE porte les hooks, la ou `pytest-asyncio` exige
    `pytest_asyncio.plugin`. Lire l'entry-point AVANT tout `-p` : une montee de
    version deplace les hooks et desarme en silence un `-p` qui marchait.

    ⚠️ MAIS `-p` SEUL NE SUFFIT PAS, ET CASSE DANS L'AUTRE SENS. Mesure du
    2026-09-14, deux heures apres la premiere : sous autoload ACTIF (un pytest
    lance a la main), `pytest_timeout` est DEJA enregistre sous son nom
    d'entry-point `timeout`, et le `-p` le re-enregistre sous un second nom :

        ValueError: Plugin already registered under a different name: timeout=...

    Le correctif precedent marchait donc en CI et TUAIT le lancement local -- j'ai
    remplace un biais d'environnement par le biais symetrique, faute d'avoir
    rejoue dans les DEUX. Un sous-processus de NR ne doit donc pas DEVINER
    l'environnement herite : il le FIXE. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` rend
    le chargement explicite et identique partout, et c'est aussi ce que fait le
    gate reel -- le NR emprunte enfin le meme chemin que ce qu'il pretend
    eprouver."""
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    cmd = [sys.executable, "-m", "pytest", *cibles, "-q",
           "-p", "no:cacheprovider", "-p", "pytest_timeout",
           "--junitxml=%s" % xml, "--timeout=%d" % BORNE_S]
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       errors="replace", timeout=240, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def test_le_plugin_timeout_est_CHARGE_pas_seulement_installe(tmp_path):
    """Aptitude AVANT verdict -- et INSTALLE n'est pas CHARGE.

    La premiere version de ce test interrogeait `find_spec("pytest_timeout")` :
    elle passait donc en CI pendant que le plugin n'etait pas charge et que les
    deux vrais cas echouaient sur un rapport absent. Une sonde de PRESENCE ne dit
    rien d'une CAPACITE en conditions reelles -- c'est la meme distinction que
    `INSTALL_OK != RUNTIME_OK`, payee le 2026-09-11.

    On l'eprouve donc par un vrai run, dans le meme environnement que les autres
    cas de ce fichier."""
    (tmp_path / "test_trivial.py").write_text("def test_ok():\n    assert True\n",
                                              encoding="utf-8")
    xml = tmp_path / "junit_aptitude.xml"
    rc, out = _pytest(tmp_path, ["test_trivial.py"], xml)
    assert rc == 0, "pytest n'a pas tourne (rc=%s) :\n%s" % (rc, out[-1500:])
    assert xml.exists(), (
        "aucun rapport : l'option --timeout n'a probablement pas ete reconnue "
        "(plugin non charge sous PYTEST_DISABLE_PLUGIN_AUTOLOAD) :\n%s" % out[-1500:])


def test_le_bloc_sain_garde_son_rapport_quand_le_bloc_lent_est_tue(ci, faux_depot,
                                                                   tmp_path):
    """LE test du mandat : un bloc coupe n'emporte plus que le sien."""
    xml_sain = tmp_path / "junit_sain.xml"
    xml_lent = tmp_path / "junit_lent.xml"

    rc_sain, out_sain = _pytest(faux_depot, ["test_sain.py"], xml_sain)
    rc_lent, out_lent = _pytest(faux_depot, ["test_lent.py"], xml_lent)

    # 1. Le bloc sain a bien laisse sa preuve, malgre la mort de l'autre.
    # L'echec DIT pourquoi : un rapport absent a trop de causes possibles pour
    # qu'on laisse la suivante enqueter a partir d'un booleen.
    assert xml_sain.exists(), (
        "le bloc sain n'a pas ecrit son rapport (rc=%s) -- derniere sortie :\n%s"
        % (rc_sain, "\n".join((out_sain or "").splitlines()[-12:])))
    bilan_sain = ci._lire_junit(xml_sain)
    assert bilan_sain is not None and bilan_sain["tests"] == 2
    assert bilan_sain["problemes"] == 0

    # 2. Le bloc lent a ete TUE : rc non nul, et aucune preuve exploitable.
    assert rc_lent != 0
    bilan_lent = ci._lire_junit(xml_lent) if xml_lent.exists() else None

    # 3. Les deux verdicts, par le chemin de production.
    v_sain = ci.verdict_bloc(rc_sain, out_sain, bilan_sain)
    v_lent = ci.verdict_bloc(rc_lent, out_lent, bilan_lent)
    assert v_sain == "PASS"
    assert v_lent in ("TIMEOUT", "UNKNOWN"), v_lent
    assert v_lent != "FAIL", "un bloc coupe n'a pas mesure d'echec"

    # 4. L'agregat : incomplet, bloquant, et le verdict du bloc sain SURVIT.
    agg = ci.verdict_suite({"test_sain.py": v_sain, "test_lent.py": v_lent})
    assert agg["blocs"]["test_sain.py"] == "PASS"
    assert agg["etat"] == "SUITE_INCOMPLETE"
    assert agg["bloquant"] is True


def test_contre_epreuve_un_seul_processus_perd_TOUT(ci, faux_depot, tmp_path):
    """Ce que faisait la CI jusqu'au 2026-09-14, et qui a coute le run 34784517659.

    Les deux fichiers dans UN processus : le lent le tue, et le rapport n'est
    jamais ecrit -- donc les tests sains, pourtant passes, ne prouvent plus rien.
    Si ce cas venait a passer, l'isolation ne servirait a rien et ce fichier
    devrait etre relu, pas supprime."""
    xml = tmp_path / "junit_tout.xml"
    rc, out = _pytest(faux_depot, ["test_sain.py", "test_lent.py"], xml)

    assert rc != 0
    bilan = ci._lire_junit(xml) if xml.exists() else None
    verdict = ci.verdict_bloc(rc, out, bilan)
    assert verdict != "PASS", (
        "le processus unique aurait conclu PASS : l'isolation serait inutile")
    if bilan is not None:
        # Un rapport partiel reste possible selon la facon dont le plugin coupe :
        # on exige alors qu'il ne PRETENDE PAS avoir tout mesure.
        assert bilan["tests"] < 3, bilan
