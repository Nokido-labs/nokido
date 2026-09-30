"""NR -- aucun outil du depot ne passe `--no-verify` a git (veille lot_C_03, 24/09).

Patron arXiv 2608.26183 : « un verificateur jamais force a refuser n'est pas prouve ». Le
pre-commit de Nokido porte le scan de SECRETS : un `git commit --no-verify` l'ENJAMBE. La
propriete « aucun --no-verify » etait ecrite dans la docstring de `forge_push_sovereign` et
gardee par rien -- la mutation qui compte est qu'une edition future l'y ajoute.
Mesure a la creation (3 111 fichiers de app/ et tools/) : 1 site suivi par git, nomme ci-dessous
(worktree ephemere) ; 4 scripts `tools/tmp_commit_*.py` NON suivis committaient en --no-verify.
La prose (docstrings) n'est pas un appel : elle est ignoree.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files; parcours du depot :
#   rglob app+tools (repli) (l.34)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
_SHELL = re.compile(r"\bgit\b[^\n]*--no-verify")

# Contournements VOULUS, avec leur preuve. Une exception qui ne sert plus fait rougir.
EXCEPTIONS = {
    "tools/nokido_historical_consolidation.py":
        "commit de TEST dans un worktree EPHEMERE (forge_worktree), reinitialise ensuite, jamais pousse",
    # (24/09) L'exception `forge_git_gate.py` -- le gate conseillait lui-meme `--no-verify` comme
    # soupape anti-perte -- est RETIREE : decision owner, soupape etroite par controle nomme
    # (test_git_gate_soupape_etroite_nr). Le cliquet interdit desormais son retour.
}


def _fichiers() -> tuple[list[str], str]:
    """Fichiers SUIVIS de app/ et tools/ ; repli glob si git est illisible, et le DIT."""
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "ls-files", "--", "app", "tools"],
                           cwd=str(ROOT), capture_output=True, text=True, errors="replace", timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return [l for l in r.stdout.splitlines() if l.endswith(".py") and "_attic" not in l], "git"
    except (OSError, subprocess.SubprocessError):
        pass
    tous = [p.relative_to(ROOT).as_posix() for d in ("app", "tools") for p in (ROOT / d).rglob("*.py")
            if "_attic" not in p.parts]
    garde = [f for f in tous if not Path(f).name.startswith("tmp_")]
    return garde, "glob (git ILLISIBLE) : %d fichier(s) tmp_* NON suivis ecartes" % (len(tous) - len(garde))


def sites(src: str) -> list[int]:
    """Lignes ou un appel passe --no-verify (argument litteral ou commande shell)."""
    arbre = ast.parse(src)
    prose = {id(n.value) for n in ast.walk(arbre)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    out = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose:
            if n.value.strip() == "--no-verify" or _SHELL.search(n.value):
                out.append(n.lineno)
    return out


def test_aucun_outil_ne_contourne_les_hooks_git():
    fichiers, mode = _fichiers()
    assert len(fichiers) > 500, "trop peu de fichiers lus (%d, mode %s) : le lecteur ne voit plus le depot" % (
        len(fichiers), mode)
    fautes, servies = [], set()
    for rel in fichiers:
        try:
            src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            lignes = sites(src)
        except (OSError, SyntaxError):
            continue
        if not lignes:
            continue
        if rel in EXCEPTIONS:
            servies.add(rel)
        else:
            fautes.append("%s:%s" % (rel, lignes))
    assert not fautes, ("--no-verify ENJAMBE le pre-commit (scan de secrets) [%s] :\n  %s"
                        % (mode, "\n  ".join(fautes)))
    perimees = sorted(set(EXCEPTIONS) - servies)
    assert not perimees, "exception(s) qui ne servent plus -- les retirer : %s" % perimees


def test_garde_du_garde():
    assert sites('import subprocess\nsubprocess.run(["git", "commit", "--no-verify", "-m", "x"])\n') == [2]
    assert sites('import os\nos.system("git commit --no-verify -m x")\n') == [2]
    assert sites('"""Jamais git commit --no-verify : le scan de secrets doit tourner."""\n') == []
    assert sites('x = ["git", "commit", "-m", "--no-verify dans un message ne passe pas"]\n') == []
