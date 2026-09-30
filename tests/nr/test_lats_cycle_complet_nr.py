"""NR -- le cycle complet tourne SANS intervention, sur un vrai depot.

POURQUOI CE FICHIER. Les tests precedents verifient chaque organe isolement :
le garde refuse une troncation, le bac se retracte, le score refuse l'atrophie.
Aucun ne prouvait que les trois fonctionnent ENSEMBLE. Or c'est exactement la
question qui decide si ce moteur peut un jour tourner seul -- et une capacite
dont on n'a jamais vu le cycle entier est une capacite supposee.

CE QUI EST DEMONTRE ICI, de bout en bout et sans aucune intervention :
  1. un depot git minuscule, avec un module et sa suite de tests ;
  2. trois variantes proposees, dont une TRONQUEE et une honnete ;
  3. le bac s'ouvre en worktree, porte l'etat vivant, applique le patch ;
  4. le garde refuse la tronquee AVANT que pytest ne tourne ;
  5. le juge eprouve les autres ;
  6. le bac se retracte -- le depot d'origine est INTACT ;
  7. la selection retient la variante honnete.

CE QUI N'EST PAS DEMONTRE, et doit rester ecrit : aucune de ces etapes ne
confine l'EXECUTION (reseau, processus, ressources, secrets). Voir `ISOLATION`
dans `forge_lats`.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("app", "tools"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _lats():
    chemin = ROOT / "app" / "forge_lats.py"
    spec = importlib.util.spec_from_file_location("forge_lats", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_lats"] = mod
    sys.modules["nokido_agent.app.forge_lats"] = mod
    spec.loader.exec_module(mod)
    return mod


_MODULE = '''\
class Calcul:
    def double(self, x):
        return x * 2

    def triple(self, x):
        return x * 3
'''

_SUITE = '''\
from calcul import Calcul


def test_double():
    assert Calcul().double(2) == 4


def test_triple():
    assert Calcul().triple(2) == 6
'''


def _ecrire_lf(chemin: Path, contenu: str) -> None:
    """Ecrit en LF EXPLICITE.

    Mesure 2026-08-20, run GHA 32414071729 : `write_text` traduit `\\n` en CRLF
    sur Windows, alors que `difflib` compare les chaines telles quelles, en LF.
    Le diff produit ne correspondait donc plus aux octets du fichier, et
    `git apply` refusait : « patch failed: calcul.py:1 ». Vert chez moi parce
    que la conversion allait dans le meme sens des deux cotes, rouge ailleurs.
    Un test qui fabrique un patch doit ecrire les MEMES octets qu'il compare.
    """
    chemin.write_text(contenu, encoding="utf-8", newline="\n")


def _depot(tmp_path: Path) -> Path:
    d = tmp_path / "depot"
    d.mkdir()
    e = dict(os.environ, GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@x",
             GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@x")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True, env=e)
    # `-text` : ce depot de test ne convertit RIEN. Sans cela, le checkout du
    # worktree reintroduirait la conversion que `_ecrire_lf` vient d'eviter.
    _ecrire_lf(d / ".gitattributes", "* -text\n")
    subprocess.run(["git", "config", "core.autocrlf", "false"],
                   cwd=d, check=True, env=e)
    _ecrire_lf(d / "calcul.py", _MODULE)
    _ecrire_lf(d / "test_calcul.py", _SUITE)
    subprocess.run(["git", "add", "-A"], cwd=d, check=True, env=e)
    subprocess.run(["git", "commit", "-qm", "socle"], cwd=d, check=True, env=e)
    return d


def _diff(avant: str, apres: str, fichier: str = "calcul.py") -> str:
    """Unidiff minimal, tel que `git apply` l'accepte."""
    import difflib

    lignes = list(difflib.unified_diff(
        avant.splitlines(keepends=True), apres.splitlines(keepends=True),
        fromfile="a/" + fichier, tofile="b/" + fichier))
    return "diff --git a/%s b/%s\n" % (fichier, fichier) + "".join(lignes)


@pytest.mark.timeout(120)
def test_cycle_complet_garde_bac_juge_et_retraction(tmp_path):
    m = _lats()
    depot = _depot(tmp_path)
    empreinte_avant = (depot / "calcul.py").read_text(encoding="utf-8")

    # 1. VARIANTE TRONQUEE : elle supprime la classe... non, elle supprime une
    #    methode ET la moitie du fichier. Les tests survivants passeraient si on
    #    ne regardait qu'eux -- c'est precisement le piege.
    tronquee = "class Calcul:\n    def double(self, x):\n        return x * 2\n"
    r_tronquee = m.default_apply_and_test(
        depot, _diff(_MODULE, tronquee), pytest_targets=["test_calcul.py"], timeout_s=60)

    assert r_tronquee.apply_ok, "le patch doit s'appliquer, c'est le garde qui juge"
    assert r_tronquee.guard_ok is False, "la troncation doit etre REFUSEE"
    assert "REFUS DU GARDE" in r_tronquee.error_log
    assert r_tronquee.total == 0, "le juge ne doit PAS avoir tourne : refus en amont"
    assert r_tronquee.score == 0.0, "une variante refusee ne peut pas gagner"

    # 2. VARIANTE HONNETE : une annotation, rien de perdu.
    honnete = _MODULE.replace("def double(self, x):", "def double(self, x: int) -> int:")
    r_honnete = m.default_apply_and_test(
        depot, _diff(_MODULE, honnete), pytest_targets=["test_calcul.py"], timeout_s=60)

    assert r_honnete.guard_ok is True, r_honnete.guard_motif
    assert r_honnete.apply_ok
    assert r_honnete.passed == 2 and r_honnete.total == 2, r_honnete.error_log[:400]
    assert r_honnete.score == 1.0

    # 3. LE DEPOT D'ORIGINE EST INTACT. C'est la promesse de la retraction :
    #    deux cycles ont tourne, rien n'a bouge hors du bac.
    assert (depot / "calcul.py").read_text(encoding="utf-8") == empreinte_avant
    reste = subprocess.run(["git", "-C", str(depot), "worktree", "list"],
                           capture_output=True, text=True, errors="replace").stdout
    assert reste.count("\n") <= 1, "aucun worktree ne doit survivre : %s" % reste
    assert m._bacs_ouverts() == 0, "tous les bacs doivent etre rendus"


@pytest.mark.timeout(120)
def test_la_selection_retient_la_variante_qui_PROTEGE(tmp_path):
    """L'arbre entier, avec un juge et une mesure de mutation simules.

    Deux variantes passent TOUS les tests. Seule la mutation les separe -- et
    c'est le point 9 : sans mesure sur les deux, l'arbre choisirait la premiere
    venue et l'objectif reel resterait « pytest ».
    """
    m = _lats()
    depot = _depot(tmp_path)

    fragile = m.PatchProposal(diff="d-fragile", provider="a")
    solide = m.PatchProposal(diff="d-solide", provider="b")

    def propose(_probleme, _contexte):
        return [fragile, solide]

    def juge(_wd, diff):
        # Les deux sont vertes : pytest ne sait pas les departager.
        return m.SandboxResult(passed=2, total=2, apply_ok=True, guard_ok=True)

    def mutation(_wd, diff):
        return (1, 10) if diff == "d-fragile" else (9, 10)

    res = m.lats_search("ameliorer", depot, propose, test_fn=juge,
                        n_initial=2, max_depth=1, beam_width=2,
                        mutation_fn=mutation)

    gagnant = res["best"]
    assert gagnant is not None
    assert gagnant.patch.diff == "d-solide", (
        "l'arbre a retenu la variante qui ne protege rien")
    assert res["mutation_mesuree"] is True
    ok, motif = gagnant.result.promouvable
    assert ok is True, motif


def test_la_variante_fragile_n_est_pas_promouvable(tmp_path):
    """Meme gagnante, une suite qui ne tue presque rien ne doit pas promouvoir."""
    m = _lats()
    r = m.SandboxResult(passed=2, total=2, apply_ok=True, guard_ok=True,
                        mutants_tues=1, mutants_total=10)
    ok, motif = r.promouvable
    assert ok is False and "seuil" in motif


def test_l_isolation_est_declaree_et_honnete():
    """Le mot « sandbox » recouvre deux choses : la table doit dire laquelle."""
    m = _lats()
    assert m.ISOLATION["git"] is True
    for volet in ("reseau", "processus", "ressources", "secrets"):
        assert m.ISOLATION[volet] is False, (
            "ne jamais pretendre confiner %s : ce bac ne le fait pas" % volet)
