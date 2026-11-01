"""NR -- le pre-commit SIGNALE un jeton de caviardage ajoute a un fichier (P1_gate_jetons_de_caviardage_20261026).

Vecu 26/10 : OPENCODE_NEMOTRON a recopie le jeton du pare-feu dans SECURITY.md a la place d'une adresse
(livraison 2584d3d70, rejetee a la relecture). Un jeton [IP_INTERNAL_n] / [PATH_WIN_n] / [SECRET_n] n'est
JAMAIS une valeur. Le garde vit dans le pre-commit, pas dans governed_write : les executeurs ecrivent en
natif dans leur worktree, et c'est le commit qu'ils passent tous. OBSERVATION : un avertissement, jamais un
refus, le temps de mesurer son bruit. Un jeton deja present (ligne deplacee) n'est pas compte.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_git_gate as gg  # noqa: E402

J = "[" + "IP_INTERNAL_1" + "]"  # assemble : ce test ne doit pas se signaler lui-meme

DIFF = "\n".join([
    "diff --git a/SECURITY.md b/SECURITY.md",
    "+++ b/SECURITY.md",
    "@@ -1,0 +1,1 @@",
    "+the hub binds " + J + " only",
    "diff --git a/docs/x.md b/docs/x.md",
    "+++ b/docs/x.md",
    "@@ -3,1 +3,1 @@",
    "-ancienne ligne " + J,
    "+ligne deplacee " + J,
    "diff --git a/tools/y.py b/tools/y.py",
    "+++ b/tools/y.py",
    "+x = tableau[i]  # crochets ordinaires",
])


def test_un_jeton_ajoute_est_signale_par_fichier():
    assert gg.jetons_ajoutes(DIFF) == {"SECURITY.md": [J]}


def test_le_regex_est_celui_du_detecteur_existant():
    import forge_ordres_bureau as ob
    assert ob.texte_caviarde("a " + J) and gg.jetons_ajoutes is not None
    assert gg._RE_JETON.pattern == ob.RE_JETON_CAVIARDAGE.pattern


def test_l_avertissement_ne_bloque_jamais(monkeypatch, capsys):
    monkeypatch.setattr(gg, "_git", lambda args: SimpleNamespace(stdout=DIFF, returncode=0))
    assert gg._jetons_caviardage_warn(["SECURITY.md"]) is None
    sortie = capsys.readouterr().out
    assert "[gate][caviardage][warn]" in sortie and "SECURITY.md" in sortie
