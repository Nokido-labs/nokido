"""Garde d'EFFET pour `tools/forge_ci_profil.py` (instrument de mesure de la CI).

Un instrument qui ment sur la CI est pire que pas d'instrument : il oriente des
decisions d'architecture. Deux proprietes sont figees ici, et une seule des deux
saute aux yeux en relecture.

1. **Le mode parallele ne doit JAMAIS porter `--capture=no`.** xdist exige la
   capture ; l'y laisser fait echouer le run pour une raison etrangere a la suite,
   ce qui se lirait comme « la parallelisation casse les tests ». Or `--capture=no`
   est present dans la commande de `ci_local` (mesure 2026-08-26 : le process
   mourait au shutdown sans imprimer « N passed »), donc la tentation de recopier
   la commande telle quelle est reelle.

2. **`bilan_junit` distingue ABSENT de ZERO ECHEC.** Rendre `{"echecs": 0}` quand le
   rapport n'existe pas transformerait « je n'ai pas pu lire » en « tout va bien » —
   le defaut le plus cher de ce projet, paye trois fois le 2026-09-04 (scan de drift
   muet, `exists()` sur acces refuse, `_git` rendant None).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _mod():
    import forge_ci_profil  # noqa: PLC0415

    return forge_ci_profil


def test_selection_lit_la_liste_reelle_de_la_ci():
    """La selection doit venir de `ci_local.PURE_TESTS`, pas d'un glob invente.

    Mesurer une AUTRE selection que celle de la CI rendrait la comparaison
    sequentiel/parallele sans valeur : on optimiserait un run qui n'existe pas.
    """
    tests = _mod().selection_pure()
    assert isinstance(tests, list) and len(tests) > 100, (
        "selection anormalement petite (%d) — la lecture AST de PURE_TESTS a du casser"
        % len(tests))
    assert all(t.startswith("tests/") for t in tests), "chemins inattendus dans la selection"
    assert all((ROOT / t).exists() for t in tests), "la selection contient des fichiers absents"


def test_le_mode_parallele_ne_passe_pas_capture_no(tmp_path):
    """xdist EXIGE la capture : `--capture=no` en parallele casse le run."""
    m = _mod()
    par = m.construire("par", 4, ["tests/nr/x.py"], tmp_path / "j.xml")
    assert "--capture=no" not in par, (
        "le mode parallele passe --capture=no : xdist va echouer pour une raison "
        "etrangere a la suite, et ce faux negatif se lira comme « xdist casse tout »")
    assert "-n" in par and "4" in par, "workers non transmis a xdist"
    assert "-p" in par and "xdist" in par, (
        "xdist doit etre charge EXPLICITEMENT : la CI tourne avec "
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, donc -n seul serait refuse")


def test_le_mode_sequentiel_demande_bien_les_durees(tmp_path):
    """Sans `--durations`, le mode seq ne mesure rien : c'est tout son objet."""
    seq = _mod().construire("seq", 0, ["tests/nr/x.py"], tmp_path / "j.xml")
    assert any(a.startswith("--durations=") for a in seq), "profil sans --durations"
    assert "-n" not in seq, "le mode sequentiel ne doit pas paralleliser"


def test_bilan_junit_distingue_absent_de_zero_echec(tmp_path):
    """ABSENT rend None, jamais un bilan a zero echec."""
    m = _mod()
    assert m.bilan_junit(tmp_path / "inexistant.xml") is None, (
        "un rapport absent rend un bilan : « je n'ai pas pu lire » deviendrait "
        "« 0 echec »")

    illisible = tmp_path / "casse.xml"
    illisible.write_text("<testsuite><<<pas du xml", encoding="utf-8")
    assert m.bilan_junit(illisible) is None, "un XML illisible doit rendre None"


def test_bilan_junit_compte_echecs_et_erreurs(tmp_path):
    """Une `error` compte autant qu'un `failure` — sinon un crash de setup passe."""
    x = tmp_path / "j.xml"
    x.write_text(
        '<testsuites><testsuite tests="10" failures="2" errors="3" skipped="1">'
        "</testsuite></testsuites>", encoding="utf-8")
    b = _mod().bilan_junit(x)
    assert b == {"tests": 10, "echecs": 5, "skips": 1}, (
        "les erreurs doivent s'ajouter aux echecs : un test qui CRASHE au setup "
        "n'est pas un test qui passe (bilan obtenu : %r)" % (b,))
