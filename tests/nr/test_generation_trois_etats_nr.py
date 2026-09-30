"""La PREUVE ne convertit jamais une absence de mesure en succes.

CE QUE CE FICHIER DEFEND. Le certificateur possede trois etats -- PASS, FAIL,
NON_MESURE -- et il n'en utilisait que deux au moment d'ecrire la preuve. Un gate
qui n'avait RIEN pu mesurer y entrait comme PASS.

    _run()                 -> (nom, True)      « pas un echec du CODE »
    _INCONCLUS             -> (nom, ...)        « n'a pas pu se prononcer »
    generation (AVANT)     -> "PASS"            <- les deux se contredisent

Le resume, lui, disait honnetement « non mesure, supplee par... ». Deux
representations du meme verdict coexistaient, et c'est la plus flatteuse qui
partait dans l'artefact de preuve.

POURQUOI CE DEFAUT A VECU. La traduction vivait au milieu d'une chaine
d'entrees-sorties -- worktree de preuve, ACL, capture de sha -- qu'aucun test ne
pouvait traverser. Rien ne le signalait, et il a fallu un audit EXTERNE lisant le
code du sha b3ed1cc50d5c pour le voir (2026-09-14). La fonction est desormais PURE
et eprouvable : c'est la moitie du correctif.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


def test_un_gate_NON_MESURE_n_entre_jamais_en_PASS(ci):
    """LE test de ce fichier."""
    resultats = [("pip-audit", True), ("pytest (suite pure)", True)]
    inconclus = [("pip-audit", False, "pip_audit_2026-09-09.json")]
    verdicts = ci.verdicts_pour_generation(resultats, inconclus)
    assert verdicts["pip-audit"] == "NON_MESURE", (
        "un gate qui n'a rien mesure est inscrit %r dans la PREUVE"
        % verdicts["pip-audit"])
    assert verdicts["pytest (suite pure)"] == "PASS"


def test_un_SUPPLEANT_ne_vaut_pas_une_MESURE(ci):
    """Un suppleant dit qu'on accepte de ne pas mesurer ici -- pas que la mesure
    a eu lieu. Les confondre est exactement le defaut qu'on ferme."""
    avec = ci.verdicts_pour_generation([("g", True)], [("g", False, "rapport.json")])
    sans = ci.verdicts_pour_generation([("g", True)], [("g", True, None)])
    assert avec["g"] == "NON_MESURE"
    assert sans["g"] == "NON_MESURE", (
        "l'etat ne doit pas dependre de l'existence d'un suppleant")


def test_les_verdicts_REELS_sont_preserves(ci):
    """Contre-epreuve : sans elle, une fonction qui rendrait NON_MESURE partout
    passerait le premier test sans rien prouver."""
    verdicts = ci.verdicts_pour_generation(
        [("vert", True), ("rouge", False)], [])
    assert verdicts == {"vert": "PASS", "rouge": "FAIL"}


def test_aucun_inconclus_laisse_le_resultat_inchange(ci):
    for vide in ([], None):
        assert ci.verdicts_pour_generation([("g", True)], vide) == {"g": "PASS"}


def test_le_format_de_generation_CONNAIT_les_trois_etats(ci):
    """Le vocabulaire existait : c'est le certificateur qui ne s'en servait pas.

    Si `forge_generation` cessait un jour de documenter `NON_MESURE`, la
    correction ci-dessus ecrirait un etat que la preuve ne sait pas lire -- et le
    defaut reviendrait par l'autre bout.
    """
    source = (RACINE / "app" / "forge_generation.py").read_text(
        encoding="utf-8", errors="replace")
    assert "NON_MESURE" in source, (
        "le format de generation ne connait plus l'etat NON_MESURE : la traduction "
        "de ci_local ecrirait un etat non lu")


def test_l_inscription_PASSE_par_la_fonction_pure(ci):
    """Pas de seconde traduction recopiee dans la chaine d'ecriture.

    Deux traductions du meme verdict, c'est precisement le defaut d'origine.
    """
    import inspect

    src = inspect.getsource(ci._inscrire_generation)
    assert "verdicts_pour_generation(" in src, (
        "l'inscription ne passe plus par la fonction eprouvee")
    assert '"PASS" if ok else "FAIL"' not in src, (
        "une traduction a deux etats est revenue dans la chaine d'ecriture")
