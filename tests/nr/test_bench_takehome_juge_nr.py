"""NR du juge du banc take-home (tools/forge_bench_takehome.py, pilote du cycle conseil 24/10).

Le juge est la seule verite du pilote : s'il se laisse tromper, tout le classement est faux.
La reference est COPIEE dans tmp_path (l'originale n'est jamais touchee) ; sans clone local, le test
saute (le clone vit dans sandbox/workspace/bench, hors depot).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N / "tools"))
import forge_bench_takehome as J  # noqa: E402

pytestmark = pytest.mark.skipif(not (J.REF / "perf_takehome.py").is_file(),
                                reason="clone de reference absent (sandbox/workspace/bench)")


@pytest.fixture
def ref(tmp_path, monkeypatch):
    copie = tmp_path / "ref"
    shutil.copytree(J.REF, copie, ignore=shutil.ignore_patterns(".git"))
    monkeypatch.setattr(J, "REF", copie)
    return copie


def _candidat(tmp_path, texte):
    c = tmp_path / "cand" / "perf_takehome.py"
    c.parent.mkdir(exist_ok=True)
    c.write_text(texte, encoding="utf-8")
    return c


def test_la_baseline_officielle_vaut_147734_cycles(ref):
    v = J.juger(ref / "perf_takehome.py", graines=1)
    assert v["statut"] == "VALEUR", v
    assert v["correct"] is True
    assert v["cycles"] == J.BASELINE
    # contrat strict (27/10) : la baseline ecrit indices ET valeurs et ne touche pas l'arbre
    assert v["indices_exacts"] is True and v["arbre_intact"] is True


def test_un_candidat_qui_altere_la_reference_est_refuse(ref, tmp_path):
    cible = (ref / "tests" / "frozen_problem.py").as_posix()
    texte = (ref / "perf_takehome.py").read_text(encoding="utf-8")
    texte += f"\nopen({cible!r}, 'a', encoding='utf-8').write('\\n# triche\\n')\n"
    v = J.juger(_candidat(tmp_path, texte), graines=1)
    assert v["statut"] == "REFUS"
    assert "PAR le candidat" in v["raison"]


def test_une_sortie_fausse_est_un_echec_metier_pas_une_valeur(ref, tmp_path):
    texte = ("class KernelBuilder:\n"
             "    def build_kernel(self, *a):\n"
             "        self.instrs = [{'alu': [('+', 0, 0, 0)]}]\n")
    v = J.juger(_candidat(tmp_path, texte), graines=1)
    assert v["statut"] == "ECHEC_METIER"
    assert v["correct"] is False
    # boucle du 24/10 : sans diagnostic de l'ecart, l'executant a stagne 5 tours a 28 950 cycles faux
    e = v["ecart"]
    assert e["faux"] == 256 and e["inchanges"] == 256  # aucun store : tout est reste a l'entree
    assert e["premier"]["indice"] == 0 and e["premier"]["attendu"] != e["premier"]["obtenu"]
    # indices jamais ecrits : mesures FAUX a part, sans etre confondus avec le verdict des valeurs
    assert v["indices_exacts"] is False and v["arbre_intact"] is True


def test_un_programme_vide_est_refuse(ref, tmp_path):
    texte = ("class KernelBuilder:\n"
             "    def build_kernel(self, *a):\n"
             "        self.instrs = []\n")
    v = J.juger(_candidat(tmp_path, texte), graines=1)
    assert v["statut"] == "REFUS"


def test_une_reference_deja_alteree_refuse_avant_d_executer(ref, tmp_path):
    (ref / "problem.py").write_text("# altere\n", encoding="utf-8")
    v = J.juger(ref / "perf_takehome.py", graines=1)
    assert v["statut"] == "REFUS"
    assert "avant execution" in v["raison"]
