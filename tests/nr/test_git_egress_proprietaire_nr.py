# -*- coding: utf-8 -*-
"""NR — safe.directory et diagnostic dubious ownership dans forge_git_egress.

Mesure 2026-11-07 : sous un compte non-propriétaire du dépôt (LaForgeSbxOffline / LaForgeTrusted),
git cat-file -e <sha>^{commit} rend rc=128 "dubious ownership".
_resolve_base retombe alors sur l'arbre vide, git diff échoue avec "Could not access",
et gate() rendait RED "reconstruction impossible (fail-closed)" avec files=0.
main() affichait "PUSH BLOQUÉ par le gate souverain (secrets/chemin interdit)" : diagnostic faux.
Avec `-c safe.directory=<racine>` les appels git passent.

Vérifications :
(a) _git passe safe.directory=<racine> et pas "*" (monkeypatch subprocess.run)
(b) stderr "dubious ownership" -> gate RED avec raison "PROPRIETE : depot illisible sous ce compte"
(c) main affiche la raison du gate, pas "secrets/chemin interdit", quand la cause est la propriété.
Aucun réseau, aucun push.
"""
import io
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_git_egress as E  # noqa: E402

Z = "0" * 40
A = "a" * 40
B = "b" * 40


def test_git_passe_safe_directory_racine_et_pas_wildcard(monkeypatch):
    """(a) _git passe safe.directory=<racine> et pas "*" (monkeypatch subprocess.run)."""
    invocations = []

    def faux_run(cmd, **kwargs):
        invocations.append(cmd)
        res = subprocess.CompletedProcess(cmd, 0, stdout="dummy", stderr="")
        return res

    monkeypatch.setattr(subprocess, "run", faux_run)

    rc, out, err = E._git(["status"])
    assert rc == 0
    assert len(invocations) == 1
    cmd = invocations[0]

    # Vérifier la présence de safe.directory
    posix_root = E.ROOT.as_posix()
    expected_arg = f"safe.directory={posix_root}"

    assert "-c" in cmd
    idx = cmd.index("-c")
    assert cmd[idx + 1] == expected_arg
    # Ne doit JAMAIS utiliser "*"
    assert "safe.directory=*" not in cmd
    for arg in cmd:
        if "safe.directory" in arg:
            assert "*" not in arg


def test_dubious_ownership_gate_red_raison_propriete(monkeypatch):
    """(b) stderr 'dubious ownership' -> gate RED avec raison PROPRIETE."""
    def faux_git(args, timeout=30):
        # Simuler un échec dubious ownership sur cat-file ou diff
        return 128, "", "fatal: detected dubious ownership in repository at '...'"

    monkeypatch.setattr(E, "_git", faux_git)

    res = E.gate(A, B, "https://github.com/example/repo.git", "refs/heads/main")
    assert not res["ok"]
    assert res["status"] == "RED"
    assert res["files"] == 0
    assert "PROPRIETE : depot illisible sous ce compte" in res["reasons"]


def test_main_affiche_raison_gate_propriete_et_pas_secrets_chemin_interdit(monkeypatch, capsys):
    """(c) main affiche la raison du gate, pas 'secrets/chemin interdit', quand la cause est la propriete."""
    def faux_git(args, timeout=30):
        return 128, "", "fatal: detected dubious ownership in repository at '...'"

    monkeypatch.setattr(E, "_git", faux_git)
    # Fournir un stdin simulant le hook pre-push
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"refs/heads/main {A} refs/heads/main {B}\n"))

    rc = E.main(["pre-push", "https://github.com/example/repo.git"])
    assert rc == 1
    captured = capsys.readouterr().out

    assert "PROPRIETE : depot illisible sous ce compte" in captured
    assert "secrets/chemin interdit" not in captured
