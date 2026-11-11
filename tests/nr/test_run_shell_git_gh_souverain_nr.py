# -*- coding: utf-8 -*-
"""NR RED -- `run action=shell` n'est plus une porte derobee vers git push, gh en ecriture ou l'injection.

Owner 2026-11-08 : « gh ne doit pas echapper au push sovereign ! » puis « le run action=shell ne
doit pas aussi laisser passer des tentatives d'injection ! ». Mesure du meme jour : le hub a
EXECUTE `gh pr create --help` par `run action=shell` ; bash_guard l'aurait refuse. Le filtre
git/gh ne vivait que dans tools/bash_guard.py, qui s'execute a l'import (stdin, sys.exit) et
ne peut donc pas etre reutilise par le hub.

Contrat (source UNIQUE, aucun systeme parallele) :
  app/forge_git_shell_guard.py (pur, sans import lourd, __FORGE_COLOR__ declare) porte
    refus_git_gh(seg), split_segments(cmd)   DEPLACES de bash_guard (memes regles)
    refus_commande_shell(cmd) -> str | None  pour TOUT texte de shell du hub :
      - normalise AVANT l'analyse : caret de cmd (`g^h`), guillemets colles (`g"h"`),
        chemin complet ou `.exe` (`C:\\x\\git.exe`), casse ;
      - descend dans les shells imbriques (`cmd /c`, `powershell -c`, `pwsh -Command`,
        `start`, `call`) et dans chaque segment (`&`, `&&`, `||`, `|`, `;`, saut de ligne) ;
      - refuse git/gh accompagnes d'une injection : `$(`, backtick, `%VAR%`, `!VAR!`,
        `-c alias.` / `core.sshCommand` / `core.hooksPath` / `core.fsmonitor` /
        `protocol.ext`, `ext::`, `--upload-pack`, `--receive-pack`, `--exec` ;
      - applique refus_git_gh a chaque segment (push, --no-verify, gh hors lecture) ;
      - texte inanalysable qui nomme git/gh = REFUS (fail-closed).
  tools/bash_guard.py importe refus_git_gh/split_segments de ce module (plus de copie).
  app/forge_mcp_registry.py, branche `act == "shell"`, appelle refus_commande_shell sur
  `code` et sur chaque entree de `commands` AVANT toute execution ; module illisible et
  commande qui nomme git/gh = refus.
"""
import importlib
import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

D = '"%NOKIDO_ROOT%"'


def _g():
    return importlib.import_module("nokido_agent.app.forge_git_shell_guard")


REFUSES = [
    "gh pr create --title x --body y",
    "gh pr create --help",
    "gh api -X POST repos/o/r/issues -f title=x",
    "gh release create v1",
    f"git -c safe.directory=* -C {D} push origin alpha",
    f"git -c safe.directory=* -C {D} commit --no-verify -m x",
    f"git -C {D} commit -nm x",
    "dir & gh pr merge 1",
    "echo ok && git push",
    "g^h pr create --title x",
    'g"i"t push origin alpha',
    r"C:\Program Files\Git\cmd\git.exe push",
    'cmd /c "gh pr merge 1"',
    'powershell -NoProfile -Command "gh release create v1"',
    "git -c core.sshCommand=calc.exe fetch",
    "git -c alias.x=!calc x",
    "git -c core.hooksPath=NUL commit -m x",
    "git clone ext::cmd.exe",
    "git fetch --upload-pack=calc origin",
    "git log $(calc)",
    "git log `calc`",
    "git log %COMSPEC%",
    "gh run list --repo !R!",
    'git log "non ferme',
    # Relecture Claude 2026-11-08 : la liste NOIRE de -c laissait passer tout executeur ;
    # -c est en liste BLANCHE (safe.directory seul). Variables GIT_*/GH_* posees avant git.
    "git -c core.pager=calc log",
    "git -c credential.helper=!calc fetch",
    "git -c diff.external=calc diff",
    'git -c "core.editor=calc" commit',
    "set GIT_SSH_COMMAND=calc & git fetch",
    "$env:GIT_SSH_COMMAND='calc'; git fetch",
    "set GH_TOKEN=x && gh pr view 1",
    # Sous-commandes qui executent un programme arbitraire.
    "git rebase -x calc HEAD~1",
    "git difftool --extcmd=calc",
    "git submodule foreach calc",
    "git bisect run calc",
    "git filter-branch --tree-filter calc",
]

PERMIS = [
    f"git -c safe.directory=* -C {D} log --oneline -2",
    f"git -c safe.directory=* -C {D} status --short",
    f"git -c safe.directory=* -C {D} push --dry-run origin alpha",
    "gh run list --repo Nokido-labs/nokido --limit 1",
    "gh pr view 12",
    "gh api repos/o/r/actions/runs",
    "tasklist /FI \"IMAGENAME eq agy.exe\"",
    'type "C:/x/.git/HEAD" & dir .gitignore',
    "echo %DATE%",
]


@pytest.mark.parametrize("cmd", REFUSES)
def test_refuse(cmd):
    assert _g().refus_commande_shell(cmd), cmd


@pytest.mark.parametrize("cmd", PERMIS)
def test_permis(cmd):
    assert _g().refus_commande_shell(cmd) is None, cmd


def test_source_unique_bash_guard_importe_le_module():
    src = (ROOT / "tools" / "bash_guard.py").read_text(encoding="utf-8")
    assert "forge_git_shell_guard" in src
    assert not re.search(r"^def (refus_git_gh|_refus_gh|_refus_git|split_segments)\b", src, re.M), \
        "copie restee dans bash_guard : deux sources divergeront"


def test_hub_shell_appelle_le_filtre_avant_execution():
    reg = importlib.import_module("nokido_agent.app.forge_mcp_registry")
    # Le corps reel est _handle_run_brut (handle_run l'enrobe du bornage) : inspecter le
    # mauvais nom a pousse un delegue a restructurer handle_run (relecture 2026-11-08).
    src = inspect.getsource(reg.ToolRegistry._handle_run_brut)
    i_shell = src.index('if act == "shell":')
    i_filtre = src.find("refus_commande_shell", i_shell)
    i_exec = src.find("_exec_sandboxed", i_shell)
    assert i_filtre != -1 and i_filtre < i_exec, "le filtre n'est pas avant la premiere execution"


def test_forge_color_declare():
    assert "__FORGE_COLOR__" in (ROOT / "app" / "forge_git_shell_guard.py").read_text(encoding="utf-8")
