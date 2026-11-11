"""NR 3/11 — les hooks git (.githooks, actifs via core.hooksPath) n'ouvrent plus de fenetre de console.

Owner 3/11 ~7 h 15 : « git n'arrete pas de faire poper rapidement des terminaux ! ». Mesure : chaque commit lance
prepare-commit-msg, pre-commit et post-commit (Python), qui appellent git (rev-parse, lfs, notes, show) et deux
Python en Popen, TOUS sans CREATE_NO_WINDOW -- une dizaine de consoles par commit.

Contrats (verification statique) :
  1. chaque hook Python de .githooks pose, sous Windows, CREATE_NO_WINDOW sur subprocess.Popen AVANT son premier
     appel de sous-processus (subprocess.run passe par Popen ; les petits-enfants heritent d'une console sans fenetre) ;
  2. un appelant qui fixe deja creationflags garde la sienne (setdefault) ;
  3. les hooks restent du Python valide.
"""
import ast
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".githooks"
PYHOOKS = [p for p in sorted(HOOKS.iterdir()) if p.is_file()
           and p.read_text(encoding="utf-8", errors="replace").startswith("#!/usr/bin/env python")]


def test_il_y_a_des_hooks_python():
    assert {p.name for p in PYHOOKS} >= {"pre-commit", "post-commit", "prepare-commit-msg"}


@pytest.mark.parametrize("hook", PYHOOKS, ids=lambda p: p.name)
def test_sans_fenetre_avant_le_premier_sous_processus(hook):
    src = hook.read_text(encoding="utf-8")
    ast.parse(src)
    i_garde = src.find("CREATE_NO_WINDOW")
    assert i_garde >= 0, "%s : aucun CREATE_NO_WINDOW" % hook.name
    assert 'setdefault("creationflags"' in src, "%s : la garde doit respecter le drapeau de l'appelant" % hook.name
    assert 'os.name == "nt"' in src, "%s : la garde ne vaut que sous Windows" % hook.name
    # Mesure 3/11 (commit 672d52764) : avec CREATE_NO_WINDOW seul, l'enfant ecrit dans SA console cachee -- les
    # messages du gate (« [OK] Nokido pre-commit », motif d'un blocage) avaient DISPARU. La sortie du hook est transmise.
    assert '("stdout", sys.stdout), ("stderr", sys.stderr)' in src, \
        "%s : la garde doit transmettre stdout/stderr du hook a l'enfant" % hook.name
    premiers = [src.find(m) for m in ("subprocess.run(", "subprocess.Popen(", "subprocess.check_output(")]
    premiers = [i for i in premiers if i >= 0]
    assert premiers and i_garde < min(premiers), "%s : la garde vient APRES un sous-processus" % hook.name
