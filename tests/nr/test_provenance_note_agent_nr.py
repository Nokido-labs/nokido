"""NR — la note de provenance `refs/notes/laforge-agent` dit AGENT|CANAL.

Test d'EFFET, pas de presence : on fait un vrai `git commit` dans un depot jetable
avec le hook du depot, puis on RELIT la note. Un test qui se contenterait de verifier
que le hook existe passerait au vert avec un hook qui n'ecrit rien -- c'est
exactement le defaut qui a laisse 219 commits sortir en `GIT:user|UNKNOWN`.

Ce qui est couvert :
  1. canal explicite (chemin hub-shell)  -> CLAUDE|HUB_SHELL
  2. agent sans canal, transport ambigu  -> CLAUDE|UNKNOWN (on ne devine pas)
  3. ni agent ni canal                   -> l'agent est resolu autrement, et un
                                            agent hors table sort en UNKNOWN

PORTEE DE CE QUE PROUVE CETTE NOTE — a ne pas surinterpreter plus tard :
c'est une TRACE LOCALE de l'identite que le hook a inscrite, pas une attestation
infalsifiable. Un shell peut poser `LAFORGE_AGENT` lui-meme ; seul le hub sait
quel appelant il a AUTHENTIFIE. Provenance operationnelle, trace locale et
attestation cryptographique sont trois choses distinctes, et seule la deuxieme
est testee ici.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (+ hook post-commit python)
#   (l.39)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".githooks" / "post-commit"
_POLLUANTS = ("LAFORGE_AGENT", "LAFORGE_AGENT_CHANNEL", "FORGE_AGENT_NAME",
              "LAFORGE_AGENT_NAME", "ANTIGRAVITY_AGENT", "GEMINI_CLI")


def _git(repo: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, env=env, errors="replace")


@pytest.fixture
def depot(tmp_path: Path) -> Path:
    """Depot jetable equipe du hook REEL du depot.

    Le hook est appele via un lanceur qui impose `sys.executable` : dependre du
    shebang `#!/usr/bin/env python` ferait echouer le test sur une machine ou
    `python` n'est pas celui qui porte les dependances -- on testerait alors
    l'installation de la machine, pas la logique du hook.
    """
    if not HOOK.is_file():
        pytest.skip("hook .githooks/post-commit absent du depot")
    repo = tmp_path / "depot"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nr@nokido.test")
    _git(repo, "config", "user.name", "NRTEST")
    hooks = repo / ".githooks"
    hooks.mkdir()
    shutil.copy2(HOOK, hooks / "post_commit_impl.py")
    (hooks / "post-commit").write_text(
        '#!/bin/sh\nexec "%s" "%s"\n' % (
            sys.executable.replace("\\", "/"),
            str(hooks / "post_commit_impl.py").replace("\\", "/")),
        encoding="utf-8", newline="\n")
    _git(repo, "config", "core.hooksPath", ".githooks")
    return repo


def _commit_et_note(repo: Path, nom: str, ajouts: dict) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _POLLUANTS}
    env["PYTHONPATH"] = str(ROOT / "tools")   # le hook importe forge_git_gate
    env.update(ajouts)
    (repo / nom).write_text("contenu\n", encoding="utf-8")
    _git(repo, "add", nom, env=env)
    c = _git(repo, "commit", "-q", "-m", "nr %s" % nom, env=env)
    assert c.returncode == 0, "commit KO: %s" % (c.stderr or c.stdout)
    n = _git(repo, "notes", "--ref=laforge-agent", "show", "HEAD", env=env)
    assert n.returncode == 0, (
        "aucune note posee — le hook n'a pas tourne ou a echoue: %s" % n.stderr)
    return n.stdout.strip()


def test_canal_explicite_prime_sur_la_table_par_agent(depot: Path) -> None:
    """Chemin hub-shell : le canal fourni gagne, sinon CLAUDE redevient STDIO."""
    note = _commit_et_note(depot, "a.txt", {"LAFORGE_AGENT": "CLAUDE",
                                            "LAFORGE_AGENT_CHANNEL": "HUB_SHELL"})
    assert note == "CLAUDE|HUB_SHELL", note


def test_claude_sans_canal_ne_ment_pas_sur_le_transport(depot: Path) -> None:
    """`CLAUDE` couvre DEUX transports : Claude Desktop passe par le pont stdio,
    Claude Code parle au hub en HTTP. Tant que `CLAUDE` figurait dans la table de
    repli, tout commit dont le chemin ne posait pas `LAFORGE_AGENT_CHANNEL` sortait
    en `STDIO_CLAUDE` -- une affirmation de transport que RIEN n'avait mesuree.
    Releve par l'owner le 2026-09-06 sur `5e8b34884` (« claude code est mcp http ! »).

    Ce test attestait AUPARAVANT l'etiquette fausse : un NR peut verrouiller un
    defaut aussi surement qu'une capacite. Il atteste desormais l'inconnu, qui se
    voit et se corrige, la ou une valeur inventee se relit comme une mesure."""
    note = _commit_et_note(depot, "b.txt", {"LAFORGE_AGENT": "CLAUDE"})
    assert note == "CLAUDE|UNKNOWN", note


def test_agent_hors_table_sort_en_canal_inconnu(depot: Path) -> None:
    """Un agent absent de la table ne doit pas heriter d'un canal au hasard."""
    note = _commit_et_note(depot, "c.txt", {"LAFORGE_AGENT": "AGENT_INEXISTANT_NR"})
    assert note == "AGENT_INEXISTANT_NR|UNKNOWN", note


def test_sans_identite_declaree_la_note_reste_structuree(depot: Path) -> None:
    """Ni agent ni canal : l'identite est resolue autrement (marqueur, identite
    git...). On n'affirme PAS quelle valeur sort — elle depend de la machine —
    seulement que la note reste au format AGENT|CANAL et n'est jamais vide."""
    note = _commit_et_note(depot, "d.txt", {})
    agent, sep, canal = note.partition("|")
    assert sep == "|", note
    assert agent.strip(), "agent vide: %r" % note
    assert canal.strip(), "canal vide: %r" % note
