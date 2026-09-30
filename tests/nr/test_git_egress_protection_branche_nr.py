# -*- coding: utf-8 -*-
"""NR — protection des branches (forge_git_egress._protection_branche).

Mesure 2026-08-19 : le gate egress Nokido ne portait AUCUNE garde de branche ; la
liste PROTEGEES vivait dans le hook du super-depot, qui ne s'execute pas quand on
pousse le depot Nokido. beta (release Codeberg) etait force-pushable sans garde.

Tests HERMETIQUES : `_git` est monkeypatche, aucun git reel n'est invoque. On
verifie l'EFFET (bloque / autorise) sur chaque forme de push.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_git_egress as E  # noqa: E402

Z = "0" * 40
A = "a" * 40
B = "b" * 40


def test_beta_est_protegee():
    assert "beta" in E._BRANCHES_PROTEGEES


def test_suppression_branche_protegee_bloquee():
    r = E._protection_branche(Z, B, "refs/heads/beta")
    assert r is not None and "suppression" in r


def test_nouvelle_branche_distante_autorisee():
    # remote_sha = zeros -> la branche n'existe pas encore cote distant.
    assert E._protection_branche(A, Z, "refs/heads/beta") is None


def test_branche_non_protegee_jamais_bloquee(monkeypatch):
    # Meme un non-fast-forward passe sur une branche non protegee.
    monkeypatch.setattr(E, "_git", lambda *a, **k: (1, "", ""))
    assert E._protection_branche(A, B, "refs/heads/redistribute") is None


def test_force_push_via_push_option_bloque(monkeypatch):
    monkeypatch.setenv("GIT_PUSH_OPTION_COUNT", "1")
    monkeypatch.setenv("GIT_PUSH_OPTION_0", "force")
    r = E._protection_branche(A, B, "refs/heads/alpha")
    assert r is not None and "force" in r.lower()


def test_non_fast_forward_bloque(monkeypatch):
    # cat-file connu (rc=0), merge-base --is-ancestor echoue (rc=1) => reecriture.
    def faux_git(args, timeout=30):
        if args[:1] == ["cat-file"]:
            return (0, "", "")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (1, "", "")   # remote n'est PAS ancetre du local
        return (0, "", "")
    monkeypatch.setattr(E, "_git", faux_git)
    r = E._protection_branche(A, B, "refs/heads/beta")
    assert r is not None and "non-fast-forward" in r


def test_fast_forward_autorise(monkeypatch):
    # cat-file connu (rc=0), merge-base --is-ancestor OK (rc=0) => avance normale.
    def faux_git(args, timeout=30):
        if args[:1] == ["cat-file"]:
            return (0, "", "")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (0, "", "")   # remote EST ancetre du local
        return (0, "", "")
    monkeypatch.setattr(E, "_git", faux_git)
    assert E._protection_branche(A, B, "refs/heads/beta") is None


def test_remote_inconnu_ne_bloque_pas(monkeypatch):
    # cat-file echoue (rc!=0) : vue distante perimee -> fail-open, pas de blocage
    # sur une non-mesure (le reste du gate egress s'applique quand meme).
    monkeypatch.setattr(E, "_git", lambda args, timeout=30: (128, "", "fatal"))
    assert E._protection_branche(A, B, "refs/heads/beta") is None
