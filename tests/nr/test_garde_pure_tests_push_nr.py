"""tests/nr/test_garde_pure_tests_push_nr.py — Non-regression du garde PURE_TESTS au push.

Verifie:
(a) NR neuf present seulement en commentaire dans ci_local.py -> RED (l'AST ne prend pas les commentaires)
(b) present dans une autre liste que PURE_TESTS -> RED (l'AST cible l'Assign de PURE_TESTS)
(c) PURE_TESTS non litteral -> ILLISIBLE (ast.literal_eval echoue)
(d) ILLISIBLE bloque dans main (code retour != 0, pas de vert par defaut)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import forge_push_sovereign as fps


def test_nr_neuf_present_seulement_en_commentaire_est_red():
    """(a) NR neuf present seulement en commentaire dans ci_local.py -> RED."""
    contenu_fake_ci_local = '''
# tests/nr/test_nouveau_nr.py
PURE_TESTS = [
    "tests/nr/test_ancien_nr.py",
]
'''
    tests, err = fps.extraire_pure_tests(contenu_fake_ci_local)
    assert err is None
    assert tests == ["tests/nr/test_ancien_nr.py"]
    assert "tests/nr/test_nouveau_nr.py" not in tests

    def fake_git(*args, **kwargs):
        cmd = list(args)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="fake_base_sha\n", stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="tests/nr/test_nouveau_nr.py\n", stderr="")
        if "show" in cmd:
            return MagicMock(returncode=0, stdout=contenu_fake_ci_local, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(fps, "git", side_effect=fake_git):
        res = fps.verifier_pure_tests_ajoutes("alpha", "fake_head_sha")
        assert res["etat"] == "RED"
        assert "tests/nr/test_nouveau_nr.py" in res["manquants"]


def test_nr_present_dans_une_autre_liste_que_pure_tests_est_red():
    """(b) present dans une autre liste que PURE_TESTS -> RED."""
    contenu_fake_ci_local = '''
AUTRE_LISTE = [
    "tests/nr/test_autre_nr.py",
]
PURE_TESTS = [
    "tests/nr/test_ancien_nr.py",
]
'''
    tests, err = fps.extraire_pure_tests(contenu_fake_ci_local)
    assert err is None
    assert tests == ["tests/nr/test_ancien_nr.py"]
    assert "tests/nr/test_autre_nr.py" not in tests

    def fake_git(*args, **kwargs):
        cmd = list(args)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="fake_base_sha\n", stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="tests/nr/test_autre_nr.py\n", stderr="")
        if "show" in cmd:
            return MagicMock(returncode=0, stdout=contenu_fake_ci_local, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(fps, "git", side_effect=fake_git):
        res = fps.verifier_pure_tests_ajoutes("alpha", "fake_head_sha")
        assert res["etat"] == "RED"
        assert "tests/nr/test_autre_nr.py" in res["manquants"]


def test_pure_tests_non_litteral_est_illisible():
    """(c) PURE_TESTS non litteral -> ILLISIBLE."""
    contenu_fake_ci_local = '''
def generer_tests():
    return ["tests/nr/test_dyn.py"]

PURE_TESTS = generer_tests()
'''
    tests, err = fps.extraire_pure_tests(contenu_fake_ci_local)
    assert tests is None
    assert err is not None
    assert "literal_eval" in err

    def fake_git(*args, **kwargs):
        cmd = list(args)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="fake_base_sha\n", stderr="")
        if "diff" in cmd:
            return MagicMock(returncode=0, stdout="tests/nr/test_dyn.py\n", stderr="")
        if "show" in cmd:
            return MagicMock(returncode=0, stdout=contenu_fake_ci_local, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(fps, "git", side_effect=fake_git):
        res = fps.verifier_pure_tests_ajoutes("alpha", "fake_head_sha")
        assert res["etat"] == "ILLISIBLE"
        assert "literal_eval" in res["motif"]


def test_illisible_bloque_dans_main():
    """(d) ILLISIBLE bloque dans main (pas de vert par defaut)."""
    with patch.object(sys, "argv", ["forge_push_sovereign.py", "--branch", "alpha"]), \
         patch.object(fps, "git") as mock_git, \
         patch.object(fps, "verifier_pure_tests_ajoutes") as mock_verif, \
         patch.object(fps, "say") as mock_say:

        def fake_git(*args, **kwargs):
            cmd = list(args)
            if "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="fakehead123\n", stderr="")
            if "merge-base" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_git.side_effect = fake_git
        mock_verif.return_value = {
            "etat": "ILLISIBLE",
            "ajoutes": [],
            "manquants": [],
            "pure_tests": [],
            "motif": "base distante introuvable",
        }

        rc = fps.main()
        assert rc == 6
        # Verifier qu'aucun push n'a ete tente
        for call_args in mock_git.call_args_list:
            assert "push" not in call_args[0]
