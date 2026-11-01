# -*- coding: utf-8 -*-
"""NR (31/10, owner « c'est quoi toutes ces fenetres que tu fais poper ? ») : l'executeur ne fait plus surgir de consoles.

Mesure 31/10 14:04-14:13 (chaine de parente prouvee) : services.exe -> nssm -> deno (superviseur) -> python (lanceur)
-> python (executeur OpenCode) -> cmd.exe -> opencode.exe, plus 5 conhost.exe sous des python.exe et un git.exe avec
OpenConsole : l'executeur tourne SANS console, donc chaque sous-processus console (git, cmd, opencode, pytest) ouvre
SA fenetre. Une seule ligne sur ~30 sous-processus de forge_task_executor portait CREATE_NO_WINDOW. Interrupteur
global (patron owner 06/09) : au demarrage, sous Windows, tout Popen sans creationflags explicite recoit
CREATE_NO_WINDOW ; un drapeau explicite est respecte ; NOKIDO_EXECUTEUR_FENETRES=1 rend le comportement d'avant.
"""
# pylint: disable=missing-function-docstring,protected-access
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_task_executor as T  # noqa: E402

pytestmark = pytest.mark.skipif(not hasattr(subprocess, "CREATE_NO_WINDOW"), reason="Windows seulement")


@pytest.fixture()
def espion(monkeypatch):
    vus = []

    def faux_init(self, *a, **k):  # remplace le VRAI lancement : aucun processus n'est cree
        vus.append(dict(k))
    monkeypatch.setattr(subprocess.Popen, "__init__", faux_init)
    monkeypatch.setattr(subprocess.Popen, "_nokido_sans_fenetre", False, raising=False)
    monkeypatch.delenv("NOKIDO_EXECUTEUR_FENETRES", raising=False)
    return vus


def test_tout_sous_processus_sans_drapeau_part_sans_fenetre(espion):
    assert T._sans_fenetre_par_defaut() is True
    subprocess.Popen(["git", "status"])
    assert espion[-1]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_un_drapeau_explicite_est_respecte(espion):
    T._sans_fenetre_par_defaut()
    subprocess.Popen(["x"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    assert espion[-1]["creationflags"] == subprocess.CREATE_NEW_CONSOLE


def test_idempotent_et_interrupteur(espion, monkeypatch):
    assert T._sans_fenetre_par_defaut() is True
    assert T._sans_fenetre_par_defaut() is False  # deja pose : jamais d'enveloppe double
    monkeypatch.setattr(subprocess.Popen, "_nokido_sans_fenetre", False, raising=False)
    monkeypatch.setenv("NOKIDO_EXECUTEUR_FENETRES", "1")
    assert T._sans_fenetre_par_defaut() is False


def test_le_point_d_entree_le_pose():
    assert "_sans_fenetre_par_defaut()" in inspect.getsource(T.main)
