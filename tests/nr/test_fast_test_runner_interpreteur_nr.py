"""fast_test_runner sous un compte bac a sable (bug_fast_test_runner_interpreteur_profil_sbx_20261022).

Mesure 22/10 : sous run_job (compte LaForgeSbx*), `~\\miniforge3\\python.exe` se resout sur le profil du compte qui
lance -> FileNotFoundError (job_b0cd5902b0e4) ; et plusieurs cibles positionnelles -> rc=2 (job_ede89ead1edc).
Contrat : l'interpreteur est celui qui fait tourner le runner ; plusieurs cibles sont acceptees (chemin reel main()).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import fast_test_runner as F  # noqa: E402


def test_interpreteur_independant_du_profil():
    assert "~" not in F.PYTHON and F.PYTHON == sys.executable, F.PYTHON


def test_plusieurs_cibles_positionnelles(monkeypatch):
    vues = {}

    def _faux(target, extra_args=None, timeout_per_test=None, parallel=True, last_failed=False, stream=False):
        vues["target"] = target
        return {"duration_s": 0, "failed": 0, "rc": 0}

    monkeypatch.setattr(F, "run_tests", _faux)
    monkeypatch.setattr(sys, "argv", ["fast_test_runner.py", "tests/nr/a_nr.py", "tests/nr/b_nr.py", "--no-parallel"])
    with pytest.raises(SystemExit) as fin:
        F.main()
    assert fin.value.code == 0
    assert list(vues["target"]) == ["tests/nr/a_nr.py", "tests/nr/b_nr.py"], vues
