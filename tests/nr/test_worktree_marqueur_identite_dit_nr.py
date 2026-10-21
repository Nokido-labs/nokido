"""
tests/nr/test_worktree_marqueur_identite_dit_nr.py — Non-régression : marqueur d'identité .nokido.agent.

Dette « chemin d'erreur muet » (commit f2cf7daf8) :
Un marqueur .nokido.agent non écrit fait que forge_git_gate n'attribue plus les commits
du worktree à l'agent.
Ce test vérifie :
- Échec d'écriture (PermissionError) -> "marqueur_identite" contient "NON ECRIT (PermissionError)"
  et avertissement consigné via logging.getLogger("Nokido.Worktree").
- Succès d'écriture -> "marqueur_identite" vaut "ecrit".
- Aucun sous-processus git réel n'est exécuté (git doublé).
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import forge_worktree


def test_marqueur_identite_non_ecrit_signale_erreur(monkeypatch, tmp_path, caplog):
    """Quand Path.write_text lève PermissionError, create() renvoie NON ECRIT et loggue un warning."""
    monkeypatch.setattr(forge_worktree, "WT_ROOT", tmp_path)

    # Doubler git : aucun vrai worktree créé
    def fake_git(args, cwd=None):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(forge_worktree, "_git", fake_git)

    # Doubler Path.write_text pour lever PermissionError
    def fail_write_text(self, *args, **kwargs):
        raise PermissionError("Access is denied: .nokido.agent")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with caplog.at_level(logging.WARNING, logger="Nokido.Worktree"):
        res = forge_worktree.create("gemini")

    assert res["status"] == "created"
    assert "marqueur_identite" in res
    assert res["marqueur_identite"].startswith("NON ECRIT (PermissionError)")
    assert "forge_git_gate n'attribuera pas les commits de ce worktree a GEMINI" in res["marqueur_identite"]
    assert res["marqueur_identite"] == (
        "NON ECRIT (PermissionError) : forge_git_gate n'attribuera pas les commits de ce worktree a GEMINI"
    )

    # Vérification du warning journalisé
    warnings = [r for r in caplog.records if r.name == "Nokido.Worktree" and r.levelno == logging.WARNING]
    assert len(warnings) >= 1
    assert "PermissionError" in warnings[0].getMessage()


def test_marqueur_identite_ecrit_succes(monkeypatch, tmp_path):
    """Quand l'écriture réussit, create() renvoie 'ecrit' et dépose le marqueur."""
    monkeypatch.setattr(forge_worktree, "WT_ROOT", tmp_path)

    # Doubler git : simule la création du dossier de worktree par git worktree add
    def fake_git(args, cwd=None):
        if "add" in args:
            (tmp_path / "gemini").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(forge_worktree, "_git", fake_git)

    res = forge_worktree.create("gemini")

    assert res["status"] == "created"
    assert res.get("marqueur_identite") == "ecrit"
    marker = tmp_path / "gemini" / ".nokido.agent"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "agent=GEMINI\n"


def test_marqueur_identite_autre_oserror(monkeypatch, tmp_path, caplog):
    """Vérifie que le type d'exception OSError est dynamique (ex: OSError générique)."""
    monkeypatch.setattr(forge_worktree, "WT_ROOT", tmp_path)

    def fake_git(args, cwd=None):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(forge_worktree, "_git", fake_git)

    def fail_write_text(self, *args, **kwargs):
        raise OSError("Disque plein")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with caplog.at_level(logging.WARNING, logger="Nokido.Worktree"):
        res = forge_worktree.create("claude")

    assert res["status"] == "created"
    assert res["marqueur_identite"] == (
        "NON ECRIT (OSError) : forge_git_gate n'attribuera pas les commits de ce worktree a CLAUDE"
    )
    warnings = [r for r in caplog.records if r.name == "Nokido.Worktree" and r.levelno == logging.WARNING]
    assert len(warnings) >= 1
    assert "OSError" in warnings[0].getMessage()
