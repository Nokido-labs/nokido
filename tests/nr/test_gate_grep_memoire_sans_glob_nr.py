"""NR -- Grep sur le dossier memoire SANS glob se tait a tort.

Mesure du 2026-11-05 : `~/.claude/projects/.../memory` pointe vers `Nokido/memory`,
et `Nokido/.gitignore:511` porte `memory/`. Grep respecte le `.gitignore` : motif
`autoCompactWindow` sur l'un ou l'autre chemin, sans glob = « No files found » ; le
meme motif avec `glob=*.md` = des fiches trouvees. Une source muette a ete lue comme
une absence, sur la memoire elle-meme (owner : « attention tu perds la memoire ! »).

Trois choses verrouillees :
- la forme fautive est signalee sur les deux formes de chemin, et elle seule ;
- le rappel traverse `main()`, le point d'entree reel ;
- Grep ne passe QUE par ce verdict : l'ajouter au matcher du hook ne doit pas le
  soumettre a l'anti-polling, a l'impulsion ni au mur de depense.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("hook_capability_gate")

CHEMINS_MEMOIRE = [
    r"%USERPROFILE%\.claude\projects\C--Users-user-Script-python-IA\memory",
    "%USERPROFILE%/.claude/projects/C--Users-user-Script-python-IA/memory/",
    "~/.claude/projects/x/memory",
    r"%NOKIDO_ROOT%\memory",
    "Nokido/memory",
    "Nokido/memory/",
    "memory",
    "./memory",
]

CHEMINS_HORS_SUJET = [
    "",
    "Nokido/app",
    "Nokido/memory_bis",
    "Nokido/tools/hook_capability_gate.py",
    # Un fichier nomme explicitement : ripgrep le lit malgre le .gitignore.
    "Nokido/memory/MEMORY.md",
    r"%USERPROFILE%\.claude\projects\x\memory\fiche.md",
]


def _grep(path, **autres):
    entree = {"pattern": "autoCompactWindow", "path": path}
    entree.update(autres)
    return {"tool_name": "Grep", "tool_input": entree}


@pytest.mark.parametrize("chemin", CHEMINS_MEMOIRE)
def test_le_dossier_memoire_sans_glob_est_signale(chemin):
    touche, msg = gate.verdict_forme("Grep", {"pattern": "x", "path": chemin})
    assert touche
    assert 'glob' in msg and '*.md' in msg
    assert 'gitignore' in msg


@pytest.mark.parametrize("chemin", CHEMINS_MEMOIRE)
def test_le_dossier_memoire_avec_glob_passe(chemin):
    touche, msg = gate.verdict_forme("Grep", {"pattern": "x", "path": chemin, "glob": "*.md"})
    assert (touche, msg) == (False, "")


@pytest.mark.parametrize("chemin", CHEMINS_HORS_SUJET)
def test_les_autres_chemins_ne_declenchent_rien(chemin):
    assert gate.verdict_forme("Grep", {"pattern": "x", "path": chemin}) == (False, "")


def test_grep_sans_chemin_ne_declenche_rien():
    assert gate.verdict_forme("Grep", {"pattern": "x"}) == (False, "")


def test_un_autre_outil_sur_ce_chemin_ne_declenche_rien():
    assert gate.verdict_forme("Glob", {"pattern": "*.md", "path": "Nokido/memory"}) == (False, "")


def _passer_par_main(evenement, capsys):
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(evenement))
    try:
        rc = gate.main()
    finally:
        sys.stdin = stdin
    assert rc == 0, "un hook de nudge ne doit JAMAIS sortir non nul"
    cap = capsys.readouterr()
    return cap.out + cap.err


def test_le_point_d_entree_remonte_le_rappel(capsys):
    sortie = _passer_par_main(_grep("Nokido/memory"), capsys)
    assert "*.md" in sortie


def test_le_point_d_entree_se_tait_sur_la_bonne_forme(capsys):
    assert _passer_par_main(_grep("Nokido/memory", glob="*.md"), capsys) == ""


@pytest.mark.parametrize("verdict", ["verdict_anti_polling", "verdict_impulsion", "verdict_depense"])
def test_grep_ne_passe_pas_par_les_autres_gardes(verdict, monkeypatch, capsys):
    def interdit(*_a, **_k):
        raise AssertionError(verdict + " ne doit pas voir un Grep")

    monkeypatch.setattr(gate, verdict, interdit)
    _passer_par_main(_grep("Nokido/app"), capsys)
