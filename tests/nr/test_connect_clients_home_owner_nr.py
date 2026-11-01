"""NR -- l'installeur gouverne le profil de l'OWNER, jamais celui d'un compte de service.

Mesure 2026-10-24 : `forge_connect_clients.py --govern --dry-run` lance sous ps_clm (SYSTEM) a lu
C:/Windows/system32/config/systemprofile/.gemini/... : le diff AGY montrait un settings.json SANS
permissions alors que celui de l'owner les portait depuis le matin. HOME = Path.home() fige au
chargement : un installeur lance par un compte de service gouvernait le mauvais profil en silence.
Convention reprise de forge_remediation._owner_home : variable LAFORGE_OWNER_HOME.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_connect_clients as C  # noqa: E402

SYSTEME = Path("C:/Windows/system32/config/systemprofile")


def test_home_explicite_par_argument_prime():
    h = C.resoudre_home(["x", "--govern", "--home", "C:/Users/owner"], {"LAFORGE_OWNER_HOME": "C:/Users/autre"}, SYSTEME)
    assert h == Path("C:/Users/owner")


def test_home_par_variable_d_environnement():
    h = C.resoudre_home(["x"], {"LAFORGE_OWNER_HOME": "C:/Users/owner"}, Path("C:/Users/LaForgeSbx"))
    assert h == Path("C:/Users/owner")


def test_profil_systeme_refuse_sans_home_explicite():
    assert C.resoudre_home(["x"], {}, SYSTEME) is None


def test_compte_de_service_laforge_refuse_sans_home_explicite():
    assert C.resoudre_home(["x"], {}, Path("C:/Users/LaForgeSbx")) is None
    assert C.resoudre_home(["x"], {}, Path("C:/Users/LaForgeTrusted")) is None


def test_profil_owner_courant_accepte():
    assert C.resoudre_home(["x"], {}, Path("%USERPROFILE%")) == Path("%USERPROFILE%")


def test_drapeau_home_sans_valeur_ne_plante_pas():
    assert C.resoudre_home(["x", "--home"], {}, Path("%USERPROFILE%")) == Path("%USERPROFILE%")


def test_main_refuse_sous_compte_de_service(monkeypatch, capsys):
    monkeypatch.setattr(C, "HOME", SYSTEME)
    monkeypatch.delenv("LAFORGE_OWNER_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["forge_connect_clients.py", "--govern", "--dry-run"])
    assert C.main() == 2
    assert "LAFORGE_OWNER_HOME" in capsys.readouterr().out
