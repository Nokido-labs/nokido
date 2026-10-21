# -*- coding: utf-8 -*-
"""NR -- le scorecard juge le DIFF livre, et un diff casse n'est jamais committe (decision owner 19/10).

Mesure du 19/10 00:36 : la 1re livraison de Mistral (ead32585b) committait un `print` mal indente
(IndentationError) dans tools/forge_roadmap_keeper.py ; l'executeur l'a committe sans compiler, et le scorecard de la
tache disait « det: aucun bloc de code a verifier -- non note » : il ne lit que les blocs ```python du TEXTE de la
reponse, jamais les fichiers livres. Owner : « une methode ... avec scorecard cadre » -> scorecard du diff pour TOUS
les executeurs (choix multiple).

Contrats :
  1. scorecard_de_livraison : un .py livre qui ne compile pas -> REJECTED (fichier:ligne dans la critique) ;
  2. .py qui compilent, aucun NR livre -> PARTIAL (on n'a pas prouve le comportement) ;
  3. NR livres qui passent -> OPTIMAL ; NR livres qui echouent -> REJECTED ;
  4. rien de verifiable (docs seules) -> UNRATED, jamais OPTIMAL ;
  5. _committer_pour_agent REFUSE de committer une livraison REJECTED, le dit, et consigne REJETEE au registre de
     recompense (forge_motivation), sans relecteur humain.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_scorecard as S  # noqa: E402

pytestmark = pytest.mark.timeout(120)

CASSE = "def f():\n    try:\n        pass\n    except Exception:\n    print('x')\n        pass\n"
BON = "def f():\n    return 1\n"


def _ecrire(wt, rel, texte):
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte, encoding="utf-8")


def test_un_py_qui_ne_compile_pas_est_rejete(tmp_path):
    _ecrire(tmp_path, "tools/a.py", CASSE)
    sc = S.scorecard_de_livraison(tmp_path, ["tools/a.py"])
    assert sc.grade == S.QualityGrade.REJECTED
    assert "tools/a.py" in sc.critique


def test_compile_sans_nr_livre_est_partiel(tmp_path):
    _ecrire(tmp_path, "tools/a.py", BON)
    assert S.scorecard_de_livraison(tmp_path, ["tools/a.py"]).grade == S.QualityGrade.PARTIAL


def test_nr_livres_verts_optimal_rouges_rejetes(tmp_path):
    _ecrire(tmp_path, "tools/a.py", BON)
    _ecrire(tmp_path, "tests/nr/test_a_nr.py", "def test_ok():\n    assert True\n")
    # la critique dans le message (20/10) : rouge en CI de reference seulement, vert seul -- le prochain echec dira pourquoi
    sc0 = S.scorecard_de_livraison(tmp_path, ["tools/a.py", "tests/nr/test_a_nr.py"])
    assert sc0.grade == S.QualityGrade.OPTIMAL, sc0.critique
    _ecrire(tmp_path, "tests/nr/test_b_nr.py", "def test_ko():\n    assert False\n")
    sc = S.scorecard_de_livraison(tmp_path, ["tools/a.py", "tests/nr/test_b_nr.py"])
    assert sc.grade == S.QualityGrade.REJECTED and "test_b_nr.py" in sc.critique


def test_rien_de_verifiable_n_est_jamais_optimal(tmp_path):
    _ecrire(tmp_path, "docs/x.md", "# titre\n")
    assert S.scorecard_de_livraison(tmp_path, ["docs/x.md"]).grade == S.QualityGrade.UNRATED


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(cwd), *args], capture_output=True, text=True,
                          errors="replace", check=True).stdout.strip()


def test_l_executeur_refuse_de_committer_un_diff_rejete(tmp_path, monkeypatch):
    from nokido_agent.app import forge_motivation as M  # meme nom d'import que l'executeur : une seule instance
    import forge_task_executor as X
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q", "-b", "alpha")
    _git(wt, "config", "user.email", "nr@test")
    _git(wt, "config", "user.name", "nr")
    _ecrire(wt, "README.md", "x\n")
    _git(wt, "add", "README.md")
    _git(wt, "commit", "-q", "-m", "base")
    avant = _git(wt, "rev-parse", "HEAD")
    _ecrire(wt, "tools/a.py", CASSE)
    monkeypatch.setattr(M, "RESULTATS", tmp_path / "r.jsonl")
    monkeypatch.setenv("NOKIDO_MOTIVATION_SANS_CORPS", "1")
    note = X._committer_pour_agent(str(wt), "t1", '{"intent":"OK_DONE"}', "OPENCODE_DEFAUT2")
    assert note and "REFUSE par le scorecard" in note, note
    assert _git(wt, "rev-parse", "HEAD") == avant
    lignes = (tmp_path / "r.jsonl").read_text(encoding="utf-8")
    assert "REJETEE" in lignes and "OPENCODE_DEFAUT2" in lignes
