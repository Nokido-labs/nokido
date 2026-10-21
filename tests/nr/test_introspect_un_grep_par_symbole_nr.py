"""NR -- passe native d'introspect, suite (GO owner 18/10, point 1) : un seul `git grep` par symbole, `rg` absent
sonde une seule fois.

Constat de lecture (forge_callgraph_jit, 18/10) : `definitions(nom)` greppait `"def nom"` et `callers(nom)` greppait
`nom` -- les fichiers du premier motif sont INCLUS dans ceux du second, et l'index AST par fichier distingue deja
definitions et appels. Et `_grep_files` relancait `rg` a CHAQUE appel alors qu'il est absent du poste (un processus
cree pour rien sous Windows). Ces tests comptent les sous-processus, sans rien executer de reel.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import forge_callgraph_jit as cg  # noqa: E402


class _Faux:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


def _espion(monkeypatch, rg_absent=True):
    appels = []

    def run(cmd, *a, **k):
        appels.append(list(cmd))
        if cmd[0] == "rg":
            if rg_absent:
                raise FileNotFoundError("rg")
            return _Faux("", 1)
        if cmd[0] == "git" and "grep" in cmd:
            return _Faux("", 1)
        return _Faux("", 0)

    monkeypatch.setattr(cg.subprocess, "run", run)
    monkeypatch.setattr(cg, "_est_racine_depot", lambda _r: True)
    for nom in ("_RG_ABSENT", "_GREP_MEMO"):
        if hasattr(cg, nom):
            monkeypatch.setattr(cg, nom, type(getattr(cg, nom))())
    return appels


def test_callers_et_definitions_du_meme_nom_font_un_seul_git_grep(monkeypatch):
    appels = _espion(monkeypatch)
    cg.callers("fonction_temoin_xyz")          # appelle aussi definitions() via ambiguite()
    greps = [c for c in appels if c[0] == "git" and "grep" in c]
    assert len(greps) == 1, greps


def test_rg_absent_n_est_sonde_qu_une_fois(monkeypatch):
    appels = _espion(monkeypatch, rg_absent=True)
    cg._grep_files("a_temoin")
    cg._grep_files("b_temoin")
    assert sum(1 for c in appels if c[0] == "rg") == 1


def test_les_mots_candidats_sont_prefiltres_en_un_seul_git_grep(monkeypatch):
    """Mesure du 18/10 (job_38a1e6d83854) : 6 a 9 git grep par appel introspect, ~0,9 s -- UN `def <mot>` par mot
    CANDIDAT de la question, alors que la plupart ne sont pas des symboles. Chemin reel : `_code`."""
    import forge_introspect as fi

    appels = _espion(monkeypatch)
    fi._code("alpha_temoin beta_temoin gamma_temoin delta_temoin epsilon_temoin", [], jit=cg)
    greps = [c for c in appels if c[0] == "git" and "grep" in c]
    assert len(greps) == 1, ["%d motifs" % c.count("-e") for c in greps]


def test_definitions_reste_exacte_sur_un_vrai_fichier(tmp_path, monkeypatch):
    """Le grep elargi (`nom` au lieu de `def nom`) ne change pas le resultat : l'AST trie."""
    f = tmp_path / "m.py"
    f.write_text("def cible():\n    return 1\n\n\ndef autre():\n    return cible()\n", encoding="utf-8")
    monkeypatch.setattr(cg, "_grep_files", lambda needle: [str(f)])
    monkeypatch.setattr(cg, "ROOT", tmp_path)
    assert [d["line"] for d in cg.definitions("cible")] == [1]
