"""Un axe NON MESURABLE sort du denominateur -- il ne vaut pas zero.

PREMIER TEST DU JUGE CANONIQUE (2026-09-07). `forge_scorecard` est designe par le
MANIFESTO comme l'arbitre de la voie critique (declaration 2, §3.4 : « LLM-draft ->
forge_scorecard 6 axes deterministes -> GOAP routing »). Mesure du jour : ses trois
evaluateurs avaient ZERO appelant, et le module n'avait AUCUN test. Ce fichier est
le premier.

LE DEFAUT MESURE. `evaluate_symbolic` attribue 0.20 a l'axe pylint. Quand pylint est
absent de l'environnement -- ce qui est le cas ici, `No module named pylint` --
l'exception est avalee et l'axe reste a `0.0`, note « skipped ». Trois fichiers reels
du depot sortent alors a 0.669, 0.746 et 0.751 : tous PARTIAL, et le grade OPTIMAL
(>= 0.9) devient **mathematiquement inatteignable**, quelle que soit la qualite du
code, puisque le maximum possible tombe a 0.80.

C'est `UNKNOWN` lu comme `NO`, dans un instrument de CERTIFICATION : precisement ce
que la constitution semantique interdit, et ce que le contrat pip-audit du meme jour
a deja tranche -- MESURE+sain -> PASS, MESURE+probleme -> FAIL, PAS MESURE ->
NON_MESURE, exclu du verdict et NOMME.

Le remede n'est donc pas d'installer pylint (ce serait toucher l'environnement pour
faire taire un instrument) : c'est que le juge cesse de confondre « mauvais » et
« pas vu ». Le calcul devrait porter sur les axes REELLEMENT mesures et dire sa
couverture (`axes=5/6`), comme le fait deja `ci_local` pour pip-audit.

⚠️ POURQUOI CES TESTS SONT EN `xfail` ET NON CORRIGES. La tentative d'edition a ete
REFUSEE, a juste titre :

    SECURITY: Separation of powers violation: Agent 'CLAUDE' (ring 4) is forbidden
    from editing judge module 'app/forge_scorecard.py'

`forge_separation` interdit a un agent de modifier le module qui le JUGE. C'est la
separation des pouvoirs du manifesto, et la contourner viderait de son sens tout ce
que ce fichier defend. Le garde fonctionne, et sa reponse prouve au passage que
`forge_scorecard` est bien enregistre comme juge.

La correction releve donc d'un geste OWNER (ou d'un agent de ring habilite). Ces
tests restent ici, EXECUTES et `xfail(strict=True)` : la dette est portee par la CI
au lieu de dormir dans une note, et le jour ou le juge est corrige ils passeront en
`xpass`, ce qui fera echouer la suite et forcera a retirer ce marqueur. Un defaut
connu doit rester bruyant aux deux extremites.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_DETTE = pytest.mark.xfail(
    strict=True,
    reason="juge canonique a corriger par l'owner : un axe non mesurable est compte "
           "zero (pylint absent -> plafond 0.80, OPTIMAL inatteignable). Edition "
           "refusee par forge_separation, ring 4 ne modifie pas son juge.",
)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_PROPRE = "def f(x):\n    return x + 1\n"


def _sans_pylint(monkeypatch):
    """pylint introuvable -- l'etat REEL de cet environnement."""
    import forge_scorecard as fs  # noqa: PLC0415

    vrai = subprocess.run

    def _faux(cmd, *a, **k):
        if any("pylint" in str(c) for c in (cmd if isinstance(cmd, (list, tuple)) else [cmd])):
            raise FileNotFoundError("No module named pylint")
        return vrai(cmd, *a, **k)

    monkeypatch.setattr(fs.__dict__.get("subprocess", subprocess), "run", _faux,
                        raising=False)
    monkeypatch.setattr(subprocess, "run", _faux)


@_DETTE
def test_un_axe_NON_MESURABLE_est_NOMME_dans_la_critique(monkeypatch, tmp_path):
    """PROPRIETE 1. Dit, jamais avale. Un axe muet doit se voir dans le verdict."""
    import forge_scorecard as fs  # noqa: PLC0415

    f = tmp_path / "propre.py"
    f.write_text(_PROPRE, encoding="utf-8")
    _sans_pylint(monkeypatch)

    sc = fs.evaluate_symbolic(str(f))
    assert "NON_MESURE" in sc.critique, (
        "un axe qu'on n'a pas pu mesurer doit etre NOMME comme tel ; « skipped(0.00) » "
        "se lit comme une note nulle et penalise le fichier en silence : %r"
        % sc.critique)


@_DETTE
def test_un_axe_NON_MESURABLE_sort_du_DENOMINATEUR(monkeypatch, tmp_path):
    """PROPRIETE 2. Le coeur : sans pylint, un fichier propre peut encore etre OPTIMAL.

    Sinon le maximum atteignable tombe a 0.80 et le grade haut est hors d'atteinte
    par construction -- l'instrument mesure alors son propre environnement, pas le
    code qu'on lui soumet.
    """
    import forge_scorecard as fs  # noqa: PLC0415

    f = tmp_path / "propre.py"
    f.write_text(_PROPRE, encoding="utf-8")
    _sans_pylint(monkeypatch)

    sc = fs.evaluate_symbolic(str(f))
    assert sc.confidence_score > 0.80, (
        "score %.3f : l'axe non mesurable est encore compte ZERO, donc OPTIMAL est "
        "inatteignable quel que soit le code" % sc.confidence_score)
    assert sc.grade.value == "OPTIMAL", (
        "un fichier trivialement propre doit pouvoir atteindre le grade haut "
        "(grade rendu : %s, score %.3f)" % (sc.grade.value, sc.confidence_score))


@_DETTE
def test_le_juge_DIT_sa_couverture(monkeypatch, tmp_path):
    """PROPRIETE 3. Un verdict porte le denominateur qui l'a produit.

    « Imprimer le denominateur » : sans lui, 0.75 sur 5 axes ne se distingue pas de
    0.75 sur 6, et deux verdicts non comparables se comparent quand meme.
    """
    import forge_scorecard as fs  # noqa: PLC0415

    f = tmp_path / "propre.py"
    f.write_text(_PROPRE, encoding="utf-8")
    _sans_pylint(monkeypatch)

    sc = fs.evaluate_symbolic(str(f))
    assert "axes=" in sc.critique, (
        "la critique doit dire sur COMBIEN d'axes le score porte : %r" % sc.critique)


def test_un_AST_casse_reste_un_VETO(monkeypatch, tmp_path):
    """PROPRIETE 4. Non-regression : normaliser ne doit pas amnistier un veto.

    L'axe AST est le seul veto du juge. Un fichier qui ne parse pas doit rester
    CRASHED / REJECTED, quelle que soit la couverture des autres axes.
    """
    import forge_scorecard as fs  # noqa: PLC0415

    f = tmp_path / "casse.py"
    f.write_text("def f(:\n    pass\n", encoding="utf-8")
    _sans_pylint(monkeypatch)

    sc = fs.evaluate_symbolic(str(f))
    assert sc.state.value == "CRASHED" and sc.grade.value == "REJECTED", (
        "un AST casse reste un veto : etat %s grade %s"
        % (sc.state.value, sc.grade.value))
