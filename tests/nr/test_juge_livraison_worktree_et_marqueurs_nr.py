"""NR 7/11 -- le juge de livraison lit le worktree de la TACHE, les marqueurs de l'EXECUTEUR, et le commit livre tout.

1. `_fichiers_non_livres` controle le repertoire de travail passe, jamais ROOT ; absent/git KO = ILLISIBLE dit.
2. Un marqueur de verdict CITE dans la prose de l'agent ne declenche aucun verdict ; le meme marqueur dans une note
   `[executeur]` si (chemins reels `_statut_livraison` et `_juger_livraison`).
3. job_bf9f3606 : un fichier suivi modifie ecarte du commit n'est pas un SUCCESS (marqueur LIVRE NON COMMITTE).
4. job_64d6f1ae : sandbox/bt_*/pytest* n'est jamais livre.
"""
import os
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402


def _git(wt, *a):
    return subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True, text=True, errors="replace").stdout


def _depot(tmp_path, fichiers=("a.py", "b.py", "c.py", "d.py")):
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "a@b.c")
    _git(wt, "config", "user.name", "t")
    for f in fichiers:
        (wt / f).write_text("V = 0\n", encoding="utf-8")
    _git(wt, "add", ".")
    _git(wt, "commit", "-qm", "init")
    return wt


# ---- defaut 1 -------------------------------------------------------------------------------------------------
def test_non_livre_porte_sur_le_worktree_de_la_tache(tmp_path):
    wt = _depot(tmp_path)
    (wt / "docs").mkdir()
    (wt / "docs" / "rendu.md").write_text("x", encoding="utf-8")   # non livre, dans le worktree de la tache
    txt = '{"intent":"OK_DONE","pointer_ref":"docs/rendu.md"}'
    assert T._fichiers_non_livres(txt, workdir=str(wt)) == [("docs/rendu.md", "non suivi")]


def test_non_livre_repertoire_absent_est_illisible_jamais_rien(tmp_path):
    txt = '{"intent":"OK_DONE","pointer_ref":"docs/rendu.md"}'
    assert T._fichiers_non_livres(txt, workdir=str(tmp_path / "absent")) == [("docs/rendu.md", "illisible")]
    assert T._fichiers_non_livres(txt) == [("docs/rendu.md", "illisible")]   # sans repertoire : pas de repli sur ROOT


def test_non_livre_git_en_echec_est_illisible(tmp_path):
    rep = tmp_path / "pas_un_depot"
    rep.mkdir()
    txt = '{"intent":"OK_DONE","pointer_ref":"docs/rendu.md"}'
    res = T._fichiers_non_livres(txt, workdir=str(rep))
    assert res and all(e == "illisible" for _c, e in res)


# ---- defaut 2 -------------------------------------------------------------------------------------------------
def test_statut_marqueur_cite_dans_la_prose_ne_juge_pas():
    effet = ("commits produits : 1 (abc) ; fichiers non commites : 0 | revue du juge : le cas "
             "« commit executeur REFUSE rc=1 » donne NEEDS_HUMAN, [RIEN PRODUIT] donne FAILURE.")
    assert T._statut_livraison(True, effet) not in ("NEEDS_HUMAN", "FAILURE")


def test_statut_marqueur_de_l_executeur_juge():
    effet = ("commits produits : 0 (-) ; fichiers non commites : 1 | prose\n"
             "[executeur] commit executeur REFUSE rc=1 : hook")
    assert T._statut_livraison(True, effet) == "NEEDS_HUMAN"


def test_juger_livraison_refus_cite_en_prose_n_est_pas_un_refus(tmp_path):
    wt = _depot(tmp_path)
    avant = T._etat_git(str(wt))
    prose = 'Revue du juge : le motif « commit executeur REFUSE rc=1 » est un refus.\n{"intent":"OK_DONE"}'
    _ok, effet, _r = T._juger_livraison(True, prose, str(wt), avant)
    assert "[COMMIT REFUSE]" not in effet


def test_juger_livraison_refus_de_l_executeur_est_un_refus(tmp_path):
    wt = _depot(tmp_path)
    avant = T._etat_git(str(wt))
    detail = "travail\n[executeur] commit executeur REFUSE rc=1 : hook"
    ok, effet, _r = T._juger_livraison(True, detail, str(wt), avant)
    assert not ok and "[COMMIT REFUSE]" in effet


# ---- defaut 3a ------------------------------------------------------------------------------------------------
def test_fichier_suivi_modifie_ecarte_du_commit_n_est_pas_un_succes(tmp_path):
    wt = _depot(tmp_path)
    for f in ("a.py", "b.py", "c.py", "d.py"):
        (wt / f).write_text("V = 1\n", encoding="utf-8")
    exclus = frozenset({"c.py", "d.py"})                       # « sales avant la tache » (reprise)
    note = T._committer_pour_agent(str(wt), "job_t", '{"commit_message":"fix: x"}', "claude_headless", exclus=exclus)
    assert note.startswith("commit executeur de 2 fichier(s)")
    assert T._LIVRE_NON_COMMITTE in note and "c.py" in note and "d.py" in note
    effet = "commits produits : 1 (abc) ; fichiers non commites : 2 | prose\n[executeur] " + note
    assert T._statut_livraison(True, effet) == "LIVRE_NON_COMMITTE"


def test_tout_livre_reste_un_succes(tmp_path):
    wt = _depot(tmp_path)
    (wt / "a.py").write_text("V = 1\n", encoding="utf-8")
    note = T._committer_pour_agent(str(wt), "job_t", '{"commit_message":"fix: x"}', "claude_headless")
    assert T._LIVRE_NON_COMMITTE not in note


# ---- defaut 3b ------------------------------------------------------------------------------------------------
def test_sandbox_bt_pytest_n_est_jamais_livre(tmp_path):
    wt = _depot(tmp_path)
    tmp = wt / "sandbox" / "bt_abc123" / "pytest-of-x" / "pytest-0"
    tmp.mkdir(parents=True)
    for i in range(5):
        (tmp / ("f%d.txt" % i)).write_text("t", encoding="utf-8")
    (wt / "a.py").write_text("V = 1\n", encoding="utf-8")
    note = T._committer_pour_agent(str(wt), "job_t", '{"commit_message":"fix: x"}', "claude_headless")
    assert note.startswith("commit executeur de 1 fichier(s)"), note
    assert "sandbox/bt_abc123" not in _git(wt, "show", "--stat", "--format=", "HEAD")
