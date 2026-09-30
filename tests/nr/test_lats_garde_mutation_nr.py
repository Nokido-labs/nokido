"""NR -- le garde de mutation precede le juge, et un refus ne gagne jamais.

POURQUOI. `lats_search` selectionnait ses variantes sur « les tests passent ».
Une variante qui TRONQUE un fichier obtient pourtant un score parfait des lors
que la partie supprimee n'est pas couverte -- et le depot a mesure des surfaces
a 8,3 % de mutants tues. Une telle pression ne selectionne pas l'amelioration,
elle selectionne l'ATROPHIE : la branche gagnante est celle qui supprime le
plus de code non teste.

`MutationGuard` refuse precisement ce que pytest ne voit pas. Ces tests
verrouillent deux choses, par l'EFFET :
  1. le garde s'applique AVANT le juge (une variante refusee ne consomme pas
     un run de tests) ;
  2. un refus rend un score NUL, donc ne peut jamais remporter la selection.

Le troisieme etat compte autant : `guard_ok=None` signifie « le garde n'a pas
pu se prononcer ». Ce n'est ni un succes ni un refus, et le motif est conserve.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Des tests de ce fichier lancent un VRAI git (init / add / commit) : sous charge, un seul
# sous-processus peut depasser les 30 s du timeout par test, et le thread de pytest-timeout
# tue alors TOUTE la suite pure (paye le 2026-09-29 par un voisin de meme forme,
# test_veille_clone_chemins_windows_nr). Meme borne que les autres tests a vrai git.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("app", "tools"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _lats():
    chemin = ROOT / "app" / "forge_lats.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_lats", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_lats"] = mod
    sys.modules["nokido_agent.app.forge_lats"] = mod
    spec.loader.exec_module(mod)
    return mod


_DIFF = (
    "diff --git a/cible.py b/cible.py\n"
    "--- a/cible.py\n"
    "+++ b/cible.py\n"
    "@@ -1,2 +1,1 @@\n"
)


def _paire(tmp_path: Path, avant: str, apres: str) -> tuple[Path, Path]:
    """Deux arbres : la source d'origine, et le bac a sable deja patche."""
    src, sbx = tmp_path / "src", tmp_path / "sbx"
    src.mkdir()
    sbx.mkdir()
    (src / "cible.py").write_text(avant, encoding="utf-8")
    (sbx / "cible.py").write_text(apres, encoding="utf-8")
    return src, sbx


# --------------------------------------------------------------------------
# Le garde REFUSE ce que pytest ne verrait pas
# --------------------------------------------------------------------------

def test_une_troncation_est_refusee(tmp_path):
    m = _lats()
    avant = "def f():\n" + "    x = 1\n" * 50
    apres = "def f():\n" + "    x = 1\n" * 5
    src, sbx = _paire(tmp_path, avant, apres)
    ok, motif = m.garde_mutation(src, sbx, _DIFF)
    assert ok is False
    assert "troncation" in motif.lower()


def test_une_classe_disparue_est_refusee_et_nommee(tmp_path):
    m = _lats()
    avant = "class A:\n    pass\n\n\nclass B:\n    pass\n"
    apres = "class A:\n    pass\n"
    src, sbx = _paire(tmp_path, avant, apres)
    ok, motif = m.garde_mutation(src, sbx, _DIFF)
    assert ok is False
    assert "B" in motif, "le motif doit NOMMER ce qui a disparu"


def test_une_mutation_honnete_passe(tmp_path):
    """Le garde ne doit pas tout refuser : sinon la recherche ne cherche plus."""
    m = _lats()
    corps = "    # padding\n" * 30
    avant = "def f(x):\n" + corps + "    return x\n"
    apres = "def f(x: int) -> int:\n" + corps + "    return x\n"
    src, sbx = _paire(tmp_path, avant, apres)
    ok, motif = m.garde_mutation(src, sbx, _DIFF)
    assert ok is True, motif


def test_un_fichier_neuf_est_une_ABSTENTION_pas_une_validation(tmp_path):
    """Sans version d'origine, il n'y a rien a comparer -- et pretendre le
    contraire fabriquerait un verdict sans mesure.

    Le code rendait `True` ici alors que son propre commentaire disait « ce
    n'est pas non plus une validation ». Corrige le 2026-08-20 : c'est `None`,
    le troisieme etat que ce module pretend offrir.
    """
    m = _lats()
    src, sbx = tmp_path / "src", tmp_path / "sbx"
    src.mkdir()
    sbx.mkdir()
    (sbx / "cible.py").write_text("def neuf():\n    return 1\n", encoding="utf-8")
    ok, motif = m.garde_mutation(src, sbx, _DIFF)
    assert ok is None, "aucun fichier comparable = abstention"
    assert "comparable" in motif


# --------------------------------------------------------------------------
# Un refus ne peut pas gagner la selection
# --------------------------------------------------------------------------

def test_un_refus_du_garde_donne_un_score_nul():
    m = _lats()
    r = m.SandboxResult(passed=10, total=10, apply_ok=True, guard_ok=False,
                        guard_motif="troncation")
    assert r.score == 0.0, "une variante refusee ne doit JAMAIS gagner"


def test_un_succes_complet_garde_son_score():
    m = _lats()
    r = m.SandboxResult(passed=10, total=10, apply_ok=True, guard_ok=True)
    assert r.score == 1.0


def test_le_garde_non_prononce_ne_penalise_pas_le_score():
    """`None` n'est pas un refus : bloquer la recherche parce que le garde est
    indisponible serait pire que la laisser avancer en le DISANT."""
    m = _lats()
    r = m.SandboxResult(passed=8, total=10, apply_ok=True, guard_ok=None,
                        guard_motif="garde indisponible (ImportError)")
    assert r.score == 0.8
    assert r.guard_motif


# --------------------------------------------------------------------------
# L'ordre : garde AVANT juge
# --------------------------------------------------------------------------

def test_le_garde_est_appele_avant_pytest():
    """CONTRAT STRUCTUREL, assume : lancer un vrai cycle demanderait un depot
    git et une suite pytest. Ce qui est verrouille, c'est l'ORDRE -- le refus
    doit sortir avant que la commande pytest ne soit seulement construite."""
    src = (ROOT / "app" / "forge_lats.py").read_text(encoding="utf-8", errors="replace")
    i_garde = src.find("sb.guard_ok, sb.guard_motif = garde_mutation")
    i_pytest = src.find('"-m", "pytest"')
    assert i_garde > 0 and i_pytest > 0
    assert i_garde < i_pytest, "le garde doit preceder la construction du run pytest"


# --------------------------------------------------------------------------
# PAS 2 -- des tests verts qui ne tuent aucun mutant ne valent pas 1.0
# --------------------------------------------------------------------------

def test_mutation_non_mesuree_laisse_le_score_des_tests():
    """`mutants_total = 0` veut dire NON MESURE. Melanger une mesure absente a
    une mesure faite fabriquerait un chiffre ininterpretable."""
    m = _lats()
    r = m.SandboxResult(passed=10, total=10, apply_ok=True, guard_ok=True)
    assert r.score_mutation is None
    assert r.score == 1.0


def test_des_tests_verts_sans_aucun_mutant_tue_valent_moitie():
    """LE COEUR DU PAS 2. Sans cette ponderation, une variante qui supprime du
    code non couvert obtient 1.0 et remporte l'arbre : la recherche apprend
    l'atrophie."""
    m = _lats()
    r = m.SandboxResult(passed=10, total=10, apply_ok=True, guard_ok=True,
                        mutants_tues=0, mutants_total=12)
    assert r.score == 0.5


def test_tests_verts_et_mutants_tous_tues_valent_un():
    m = _lats()
    r = m.SandboxResult(passed=10, total=10, apply_ok=True, guard_ok=True,
                        mutants_tues=12, mutants_total=12)
    assert r.score == 1.0


def test_la_mutation_departage_deux_variantes_toutes_vertes():
    """Deux branches passent tous les tests ; seule celle qui PROTEGE gagne."""
    m = _lats()
    fragile = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=True,
                              mutants_tues=1, mutants_total=10)
    solide = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=True,
                             mutants_tues=9, mutants_total=10)
    assert solide.score > fragile.score
    assert fragile.score_tests == solide.score_tests == 1.0


# --------------------------------------------------------------------------
# PAS 3 -- le bac est borne, et il se retracte
# --------------------------------------------------------------------------

def test_le_plafond_de_bacs_existe_et_est_petit():
    """Chaque bac materialise ~4455 fichiers suivis. Un arbre sans plafond
    sature le disque avant d'ameliorer quoi que ce soit."""
    m = _lats()
    assert 0 < m.PLAFOND_BACS <= 8


def test_un_bac_git_est_un_worktree_et_se_retracte(tmp_path):
    """EFFET, sur un vrai depot minuscule : le bac s'ouvre, il est bien un
    worktree (pas une copie du `.git`), et la retraction ne laisse rien."""
    import subprocess

    depot = tmp_path / "depot"
    depot.mkdir()
    env = {"GIT_AUTHOR_NAME": "nr", "GIT_AUTHOR_EMAIL": "nr@x",
           "GIT_COMMITTER_NAME": "nr", "GIT_COMMITTER_EMAIL": "nr@x"}
    import os as _os

    e = dict(_os.environ, **env)
    subprocess.run(["git", "init", "-q"], cwd=depot, check=True, env=e)
    (depot / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=depot, check=True, env=e)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=depot, check=True, env=e)

    m = _lats()
    avant = m._bacs_ouverts()
    bac, retracter, genre, etat = m._ouvrir_bac(depot)
    try:
        assert genre.startswith("worktree"), "un depot git doit donner un worktree"
        assert (bac / "a.py").exists()
        assert m._bacs_ouverts() == avant + 1
        assert etat.complet, "depot propre : rien ne manque, donc COMPLET"
        assert etat.mode == m.HEAD_ONLY
        assert etat.base_head, "le sha de base doit etre nomme"
    finally:
        retracter()
    assert not bac.exists(), "la retraction doit ne rien laisser"
    assert m._bacs_ouverts() == avant, "le semaphore doit revenir a son etat"


def test_le_bac_porte_les_modifications_NON_COMMITEES(tmp_path):
    """P0. `git worktree add HEAD` materialise HEAD ; l'ancien `copytree`
    transportait le working tree. Remplacer l'un par l'autre sans compenser
    changeait la BASE EVALUEE en silence -- l'arbre jugeait un patch contre un
    depot d'il y a quelques commits."""
    import os as _os
    import subprocess

    depot = tmp_path / "depot2"
    depot.mkdir()
    e = dict(_os.environ, GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@x",
             GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@x")
    subprocess.run(["git", "init", "-q"], cwd=depot, check=True, env=e)
    (depot / "a.py").write_text("VERSION = 'commitee'\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=depot, check=True, env=e)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=depot, check=True, env=e)
    # Modification VIVANTE, non commitee
    (depot / "a.py").write_text("VERSION = 'vivante'\n", encoding="utf-8")

    m = _lats()
    bac, retracter, genre, etat = m._ouvrir_bac(depot)
    try:
        lu = (bac / "a.py").read_text(encoding="utf-8")
        assert "vivante" in lu, (
            "le bac evalue HEAD au lieu de l'etat courant : %s" % lu)
        assert etat.mode == m.LIVE_COMPLETE, etat.resume()
        assert "a.py" in etat.suivis_modifies
        assert etat.complet
    finally:
        retracter()


def test_les_fichiers_non_suivis_sont_comptes_et_annonces(tmp_path):
    """Un patch ne peut pas les transporter. On ne les cache donc pas : le
    genre du bac dit combien manquent."""
    import os as _os
    import subprocess

    depot = tmp_path / "depot3"
    depot.mkdir()
    e = dict(_os.environ, GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@x",
             GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@x")
    subprocess.run(["git", "init", "-q"], cwd=depot, check=True, env=e)
    (depot / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=depot, check=True, env=e)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=depot, check=True, env=e)
    (depot / "jamais_suivi.py").write_text("y = 2\n", encoding="utf-8")

    m = _lats()
    bac, retracter, genre, etat = m._ouvrir_bac(depot)
    try:
        assert "jamais_suivi.py" in etat.non_suivis_absents, etat.resume()
        # REGLE DURE : un vivant incomplet interdit la promotion. Le dire dans
        # un log ne suffisait pas -- le moteur pouvait promouvoir un candidat
        # juge sur une realite amputee.
        assert etat.mode == m.LIVE_PARTIAL
        assert etat.complet is False
        r = m.SandboxResult(passed=9, total=9, apply_ok=True, guard_ok=True,
                            mutants_tues=9, mutants_total=9,
                            etat_vivant=etat.mode, etat_detail=etat.resume())
        ok, motif = r.promouvable
        assert ok is False and "PARTIEL" in motif, motif
        assert r.score == 1.0, "le CLASSEMENT reste possible : c'est la PROMOTION qui est bloquee"
    finally:
        retracter()


def test_un_depot_propre_reste_promouvable():
    """HEAD_ONLY n'est pas une amputation : un depot sans modification locale
    n'a rien de plus a porter. Le confondre avec PARTIEL bloquerait tout."""
    m = _lats()
    r = m.SandboxResult(passed=9, total=9, apply_ok=True, guard_ok=True,
                        mutants_tues=9, mutants_total=9,
                        etat_vivant=m.HEAD_ONLY)
    assert r.promouvable[0] is True


# --------------------------------------------------------------------------
# Le score CLASSE, le seuil AUTORISE -- deux questions distinctes
# --------------------------------------------------------------------------

def test_une_suite_qui_ne_tue_presque_rien_n_est_pas_promouvable():
    """0.5 au classement ne doit pas valoir un droit de promotion : le depot a
    mesure des surfaces a 8,3 % de mutants tues."""
    m = _lats()
    r = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=True,
                        mutants_tues=1, mutants_total=12)
    ok, motif = r.promouvable
    assert ok is False
    assert "seuil" in motif


def test_une_suite_solide_est_promouvable():
    m = _lats()
    r = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=True,
                        mutants_tues=9, mutants_total=10)
    assert r.promouvable[0] is True


def test_une_mutation_non_mesuree_autorise_sans_prouver():
    """Interdire sur une mesure absente punirait l'ignorance, pas la faiblesse.
    Mais le motif doit le DIRE."""
    m = _lats()
    r = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=True)
    ok, motif = r.promouvable
    assert ok is True
    assert "non prouvee" in motif


def test_un_refus_du_garde_interdit_la_promotion():
    m = _lats()
    r = m.SandboxResult(passed=8, total=8, apply_ok=True, guard_ok=False,
                        mutants_tues=10, mutants_total=10)
    assert r.promouvable[0] is False


def test_une_source_sans_git_retombe_sur_la_copie_et_le_dit(tmp_path, monkeypatch):
    """Le repli existe, mais il NOMME son genre : un repli muet empecherait de
    comprendre pourquoi un run coute soudain dix fois plus de disque.

    L'hypothese « sans git » est CONSTRUITE, pas supposee (2026-09-02).
    `_ouvrir_bac` appelle `git rev-parse --git-dir`, qui REMONTE LES PARENTS :
    le resultat dependait donc de l'endroit ou pytest pose son `tmp_path`.
    Sans `--basetemp`, il va au TEMP du systeme -- hors depot -- et le test
    passait ; la CI, elle, ancre le basetemp DANS le checkout, si bien que la
    source etait vue comme un depot et que le genre sortait `worktree/...`.
    Un test vert chez son auteur et rouge en CI, pour une raison qui n'est pas
    dans le code teste.

    `GIT_CEILING_DIRECTORIES` arrete cette remontee : l'isolement est alors une
    propriete du test, plus une propriete de la machine.
    """
    m = _lats()
    src = tmp_path / "brut"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    bac, retracter, genre, etat = m._ouvrir_bac(src)
    try:
        assert genre == "copie"
        assert (bac / "a.py").exists()
        # La copie transporte le working tree TEL QUEL : rien ne manque, donc
        # rien n'interdit la promotion de ce cote.
        assert etat.complet is True
    finally:
        retracter()


def test_les_fichiers_du_diff_sont_extraits_des_entetes():
    m = _lats()
    diff = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
        "diff --git a/doc.md b/doc.md\n--- a/doc.md\n+++ b/doc.md\n"
        "--- /dev/null\n+++ b/neuf.py\n"
    )
    trouves = m._fichiers_python_du_diff(diff)
    assert "x.py" in trouves
    assert "neuf.py" in trouves
    assert "doc.md" not in trouves, "seuls les .py passent par le garde AST"
