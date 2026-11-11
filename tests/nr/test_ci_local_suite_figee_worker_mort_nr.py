"""NR 10/11 -- une suite figee par un worker xdist MORT s'arrete et NOMME le coupable.

Mesure 10/11 (enregistreur de vol) : gw2 tue par pytest-timeout (os._exit) pendant
test_admission_mesure_vs_sentinelle_nr.py::test_le_refus_est_journalise ; le controleur xdist a
attendu a vie (« 99 % »), le pre-vol a ete tue a la main sans verdict. `_run(veilleur=...)` coupe
quand la sortie est immobile ET qu'un diagnostic nomme un worker mort : FAIL mesure, pas UNKNOWN.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ci_local  # noqa: E402

DORMEUR = "import time\nprint('debut', flush=True)\ntime.sleep(3600)\n"


def _cmd(tmp_path):
    f = tmp_path / "dormeur.py"
    f.write_text(DORMEUR, encoding="utf-8")
    return [sys.executable, str(f)]


def test_worker_mort_arrete_et_nomme(tmp_path, capsys):
    """Sortie immobile + diagnostic -> processus tue, FAIL, coupable nomme, en moins de 20 s."""
    t0 = time.time()
    nom, ok = ci_local._run("pytest (suite pure) NR", _cmd(tmp_path), blocking=True,  # pylint: disable=protected-access
                            veilleur=(1, lambda: "gw2 test_x"), veille_periode_s=0.2, timeout_s=60)
    sortie = capsys.readouterr().out
    assert time.time() - t0 < 20
    assert ok is False and nom == "pytest (suite pure) NR"
    assert "SUITE FIGEE" in sortie and "test_x" in sortie


def test_sans_diagnostic_le_veilleur_ne_tue_pas(tmp_path, capsys):
    """Diagnostic None -> on attend ; seule la borne existante coupe (UNKNOWN, pas FAIL)."""
    _nom, ok = ci_local._run("pytest (suite pure) NR2", _cmd(tmp_path), blocking=True,  # pylint: disable=protected-access
                             veilleur=(1, lambda: None), veille_periode_s=0.2, timeout_s=3)
    sortie = capsys.readouterr().out
    assert ok is True and "SUITE FIGEE" not in sortie and "UNKNOWN" in sortie


def test_diag_worker_mort_lit_l_enregistreur(tmp_path, capsys):
    """Le diagnostic branche sur la suite pure nomme le worker tue et son test, sans rien imprimer."""
    (tmp_path / "vol_gw0_11.log").write_text("19:20:00 START a.py::t\n19:20:01 FIN a.py::t\n", encoding="utf-8")
    (tmp_path / "vol_gw2_3524.log").write_text(
        "19:21:11 START tests/nr/x_nr.py::test_le_refus\n19:21:44 OS_EXIT pytest_timeout\n", encoding="utf-8")
    d = ci_local._diag_worker_mort(tmp_path)  # pylint: disable=protected-access
    assert d and "gw2" in d and "test_le_refus" in d and "os._exit" in d
    assert capsys.readouterr().out == ""
    vide = tmp_path / "vide"
    vide.mkdir()
    assert ci_local._diag_worker_mort(vide) is None  # pylint: disable=protected-access


def test_vols_des_runs_precedents_ranges_avant_la_suite(tmp_path):
    """11/11 (pre-vol job_0d40c2f333e5) : le veilleur a nomme gw1/test_admission... lu dans un vol du pre-vol 2
    (72 des 81 fichiers du dossier venaient d'anciens runs) ; le vrai coupable etait gw0/test_generation_differee.
    Avant la suite, les journaux anterieurs sont RANGES (jamais supprimes) : le diagnostic ne voit que le run."""
    (tmp_path / "vol_gw1_18208.log").write_text(
        "22:05:00 START tests/nr/vieux_nr.py::test_perime\n22:05:40 OS_EXIT pytest_timeout\n", encoding="utf-8")
    (tmp_path / "faulthandler_gw1_18208.log").write_text("vieille pile\n", encoding="utf-8")
    assert ci_local._diag_worker_mort(tmp_path)  # pylint: disable=protected-access
    n = ci_local._ranger_vols_precedents(tmp_path)  # pylint: disable=protected-access
    assert n == 2
    assert ci_local._diag_worker_mort(tmp_path) is None  # pylint: disable=protected-access
    gardes = sorted(p.name for p in (tmp_path / "precedents").rglob("*.log"))
    assert gardes == ["faulthandler_gw1_18208.log", "vol_gw1_18208.log"]
    assert ci_local._ranger_vols_precedents(tmp_path) == 0  # idempotent  # pylint: disable=protected-access
    assert ci_local._ranger_vols_precedents(tmp_path / "absent") == 0  # pylint: disable=protected-access


def _faux_lanceur(scenario):
    """Rend (lancer, lire_dernier, cmds) : chaque passe consomme une entree de `scenario` (diag ou None)."""
    cmds, etat = [], {"dernier": {}}

    def lancer(cmd):
        cmds.append(list(cmd))
        diag = scenario[len(cmds) - 1]
        etat["dernier"] = {"suite_figee": diag} if diag else {}
        return "pytest (suite pure)", diag is None

    return lancer, (lambda: etat["dernier"]), cmds


def test_reprise_auto_un_run_nomme_tous_les_coupables(capsys):
    """11/11 (choix owner) : 5 pre-vols de 50 min, UN coupable par run. Desormais, worker mort -> la suite est
    relancee SANS le fichier coupable, jusqu'a une passe complete ; verdict FAIL, tous les coupables nommes."""
    lancer, dernier, cmds = _faux_lanceur([
        "gw1 tests/nr/test_a_nr.py::test_x (os._exit)", "gw0 tests\\nr\\test_b_nr.py::test_y (os._exit)", None])
    rangements = []
    nom, ok, coupables = ci_local._suite_avec_reprise(  # pylint: disable=protected-access
        lancer, ["pytest", "@liste"], dernier, avant=lambda: rangements.append(1))
    assert coupables == ["tests/nr/test_a_nr.py", "tests/nr/test_b_nr.py"]
    assert ok is False and nom == "pytest (suite pure)"
    assert cmds[0] == ["pytest", "@liste"]
    assert cmds[2][-4:] == ["--deselect", "tests/nr/test_a_nr.py", "--deselect", "tests/nr/test_b_nr.py"]
    assert len(rangements) == 3, "les journaux de vol sont ranges avant CHAQUE passe"
    sortie = capsys.readouterr().out
    assert "test_a_nr.py" in sortie and "test_b_nr.py" in sortie and "REPRISE" in sortie


def test_reprise_aussi_quand_xdist_plante_au_lieu_de_se_figer():
    """Epreuve reelle du 11/11 (job_56f59932a8d5) : apres la mort d'un worker, xdist loadfile ne s'est pas fige,
    il a plante en INTERNALERROR (rc=3, scheduler loadscope._reschedule). Meme cause, autre forme : sans gel,
    le veilleur ne dit rien -- c'est le diagnostic des journaux de vol qui nomme le coupable."""
    passes = []

    def lancer(cmd):
        passes.append(list(cmd))
        return "pytest (suite pure)", len(passes) > 1

    def dernier():
        return {"rc": 3} if len(passes) == 1 else {"rc": 0}

    def diag():
        return "gw2 tests/nr/test_c_nr.py::test_z (os._exit)" if len(passes) == 1 else None

    _n, ok, coupables = ci_local._suite_avec_reprise(lancer, ["p"], dernier, diag_mort=diag)  # pylint: disable=protected-access
    assert coupables == ["tests/nr/test_c_nr.py"] and ok is False and len(passes) == 2
    # un simple rouge (rc=1, tests en echec) ne declenche JAMAIS de reprise, meme si un vieux diagnostic traine
    passes.clear()
    _n, ok, coupables = ci_local._suite_avec_reprise(  # pylint: disable=protected-access
        lambda c: (passes.append(c) or ("s", False)), ["p"], lambda: {"rc": 1}, diag_mort=lambda: "gw0 tests/nr/x_nr.py::t")
    assert coupables == [] and len(passes) == 1


def test_reprise_bornee_et_sans_effet_sur_une_suite_saine():
    """Suite saine : une seule passe, verdict intact. Gel repete : borne a max_reprises, jamais une boucle."""
    lancer, dernier, cmds = _faux_lanceur([None])
    assert ci_local._suite_avec_reprise(lancer, ["p"], dernier) == ("pytest (suite pure)", True, [])  # pylint: disable=protected-access
    assert len(cmds) == 1
    gels = ["gw0 tests/nr/test_%d_nr.py::t (os._exit)" % i for i in range(9)]
    lancer, dernier, cmds = _faux_lanceur(gels)
    _n, ok, coupables = ci_local._suite_avec_reprise(lancer, ["p"], dernier, max_reprises=2)  # pylint: disable=protected-access
    assert ok is False and len(cmds) == 3 and len(coupables) == 3
    # diagnostic sans fichier lisible : on ne boucle pas, on ne devine pas
    lancer, dernier, cmds = _faux_lanceur(["gw0 (hors test) (sans os._exit)", None])
    _n, ok, coupables = ci_local._suite_avec_reprise(lancer, ["p"], dernier)  # pylint: disable=protected-access
    assert ok is False and len(cmds) == 1 and coupables == []


def test_marge_de_timeout_sur_les_fichiers_lents_mesures():
    """Mesure job_da23217046a2 (21 716 tests sous charge CI) : une vingtaine de fichiers SAINS durent 15 a 26 s
    pour un timeout de 30 s -> un rien de charge tue le worker. Marge explicite, sauf marqueur deja pose."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_nr_conftest_marge", Path(__file__).with_name("conftest.py"))
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)

    class Item:
        def __init__(self, fichier, marque=None):
            self.fspath, self._m, self.ajoutes = fichier, marque, []

        def get_closest_marker(self, nom):
            return self._m if nom == "timeout" else None

        def add_marker(self, m):
            self.ajoutes.append(m)

    lent = Item("x/tests/nr/test_flux_etats_nr.py")
    deja = Item("x/tests/nr/test_pouls_canon_nr.py", marque=object())
    autre = Item("x/tests/nr/test_quelconque_nr.py")
    cf.pytest_collection_modifyitems(None, [lent, deja, autre])
    assert len(lent.ajoutes) == 1 and lent.ajoutes[0].args[0] >= 3 * 26
    assert not deja.ajoutes and not autre.ajoutes
    assert "test_introspect_memoire_active_nr.py" in cf._FICHIERS_LENTS_MESURES  # pylint: disable=protected-access


def test_diagnostic_qui_leve_vaut_none(tmp_path, capsys):
    """Une exception du diagnostic ne tue rien et ne casse pas le gate."""
    def _boum():
        raise RuntimeError("diag casse")
    _nom, ok = ci_local._run("pytest (suite pure) NR3", _cmd(tmp_path), blocking=True,  # pylint: disable=protected-access
                             veilleur=(1, _boum), veille_periode_s=0.2, timeout_s=3)
    assert ok is True and "SUITE FIGEE" not in capsys.readouterr().out
