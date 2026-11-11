# -*- coding: utf-8 -*-
"""NR (owner 3/11 23 h 30, suite de l'autopsie du RSI) : apres c2421ab73 + 96561a13a, le cycle 0 traitait encore chaque
proposition en ~40 ms sans rejeu visible, alors que 4 des 5 tests REL sont DEJA VERTS (rejeu en job : 1 passed).
_rel_deja_vert lisait rc=1 comme « rouge » meme quand pytest n'avait rien execute (« No module named pytest », erreur de
collecte) : un INCONNU lu NON. Desormais : rc 0 -> vert ; rc 1 avec un test reellement echoue -> rouge ; rc 1 sans
execution, ou tout autre rc -> None (illisible), et le code + la fin de sortie sont journalises. L'interpreteur retenu
est le premier candidat qui sait IMPORTER pytest."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_self_patcher as sp  # noqa: E402


def _faux_run(rc, sortie):
    return lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], rc, stdout=sortie, stderr="")


def test_pytest_absent_est_illisible_pas_rouge(monkeypatch):
    monkeypatch.setattr(sp.subprocess, "run", _faux_run(1, "C:\\x\\python.exe: No module named pytest\n"))
    assert sp._rel_deja_vert("tests/nr/test_a_nr.py::t") is None


def test_erreur_de_collecte_est_illisible(monkeypatch):
    monkeypatch.setattr(sp.subprocess, "run", _faux_run(1, "ImportError while loading conftest\n1 error in 0.2s\n"))
    assert sp._rel_deja_vert("tests/nr/test_a_nr.py::t") is None


def test_un_vrai_echec_est_rouge(monkeypatch):
    monkeypatch.setattr(sp.subprocess, "run", _faux_run(1, "F\nFAILED tests/nr/test_a_nr.py::t\n1 failed in 0.3s\n"))
    assert sp._rel_deja_vert("tests/nr/test_a_nr.py::t") is False


def test_vert_et_autres_codes(monkeypatch):
    monkeypatch.setattr(sp.subprocess, "run", _faux_run(0, "1 passed in 0.2s\n"))
    assert sp._rel_deja_vert("tests/nr/test_a_nr.py::t") is True
    monkeypatch.setattr(sp.subprocess, "run", _faux_run(4, "ERROR: usage\n"))
    assert sp._rel_deja_vert("tests/nr/test_a_nr.py::t") is None


def test_l_interpreteur_retenu_sait_importer_pytest(monkeypatch, tmp_path):
    sans = tmp_path / "sans_pytest.exe"
    sans.write_text("x")
    monkeypatch.setattr(sp, "_candidats_interpreteur", lambda: [str(sans), sys.executable])
    monkeypatch.setattr(sp, "_a_pytest", lambda exe: exe == sys.executable)
    assert sp._interpreteur() == sys.executable
