# test_red_retroactif_nr.py
"""RED retroactif NR.

Ce test demontre qu'on peut voir un RED sur HEAD et un GREEN sur l'arbre
courant avec forge_red_retroactif.py. Le depot temporaire est construit de
facon autonome : tmp_path, git init, config locale, et config globale/systeme
neutralisee (le hook ou le gpgsign d'une machine hote ne doivent pas decider
de l'issue de ce test).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


OUTIL = Path(__file__).resolve().parents[2] / "tools" / "forge_red_retroactif.py"


def _git_env():
    """Environnement git hermetique : ni config globale, ni config systeme."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ADVICE_DETACHEDHEAD"] = "0"
    return env


def _git(repo, *args, env):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


# borne propre > timeout du sous-processus (300 s) : sous --timeout=30 la reference 63a63a812 abattait le worker (20/10)
@pytest.mark.timeout(330)
def test_red_retroactif_bilan_has_red_and_green(tmp_path):
    env = _git_env()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)],
        check=True, capture_output=True, env=env,
    )
    _git(repo, "config", "user.name", "test", env=env)
    _git(repo, "config", "user.email", "test@test.local", env=env)

    tools_dir = repo / "tools"
    tools_dir.mkdir(parents=True)
    mod = tools_dir / "dummy_mod.py"
    mod.write_text("# v1\n", encoding="utf-8")

    _git(repo, "add", ".", env=env)
    _git(repo, "commit", "-m", "v1", env=env)

    mod.write_text("# v2\ndef need():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".", env=env)
    _git(repo, "commit", "-m", "v2", env=env)

    # HEAD repart sur v1 : la version de HEAD n'a pas `need` -> le test est ROUGE
    # sur HEAD, et VERT sur l'arbre courant, ou le fichier a ete re-ecrit en v2.
    _git(repo, "checkout", "HEAD~1", env=env)
    mod.write_text("# v2\ndef need():\n    return 1\n", encoding="utf-8")

    test = repo / "tests" / "nr" / "test_need_nr.py"
    test.parent.mkdir(parents=True)
    test.write_text(
        "from dummy_mod import need\n\n\ndef test_need():\n    assert need() == 1\n",
        encoding="utf-8",
    )

    assert OUTIL.is_file(), "outil absent : %s" % OUTIL

    res = subprocess.run(
        [
            sys.executable,
            str(OUTIL),
            "--test",
            "tests/nr/test_need_nr.py",
            "--module",
            "tools/dummy_mod.py",
            "--depot",
            str(repo),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=env,
    )
    out = res.stdout + "\n" + res.stderr
    assert "BILAN" in out, out
    m = re.search(r"BILAN red=(\d+) green=(\d+)", out)
    assert m, out
    assert int(m.group(1)) != 0, "le test devait etre ROUGE sur HEAD : %s" % out
    assert int(m.group(2)) == 0, "le test devait etre VERT sur l'arbre : %s" % out
