"""NR 10/11 -- un faux agent `faux.py` laisse vivant par un test est tue au teardown.

Mesure job_b486a06b80ae (C:/tmp/fuite_faux_par_test_20261110.py) : 24 tests de 8 fichiers ACP laissaient
un `python <tmp_path>/faux.py` vivant apres leur teardown ; sous un worker xdist longue vie ils
s'accumulaient (21 orphelins tues a la main le 10/11). Le rejeu « 0 fuite » comptait APRES la sortie de
pytest -- quand les enfants meurent avec leur parent : une mesure au mauvais moment.
"""
from __future__ import annotations

import subprocess
import sys
import time

import importlib.util
from pathlib import Path

import psutil

# par son CHEMIN : `import conftest` attrape tests/conftest.py ou tests/nr/conftest.py selon le lot (7215316e0)
_SPEC = importlib.util.spec_from_file_location("_nr_conftest_faux", Path(__file__).with_name("conftest.py"))
conftest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conftest)


def _tuer(dossier) -> int:
    """La fonction du conftest, appelee par son attribut (absente -> AttributeError = rouge)."""
    return conftest._tuer_faux_orphelins(dossier)  # pylint: disable=protected-access


def test_fonction_existe():
    """Le conftest NR porte la fonction de nettoyage."""
    assert callable(getattr(conftest, "_tuer_faux_orphelins", None))


def test_faux_vivant_tue(tmp_path):
    """Un faux.py vivant sous tmp_path est tue, et compte."""
    f = tmp_path / "faux.py"
    f.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    with subprocess.Popen([sys.executable, str(f)]) as p:
        try:
            time.sleep(0.3)
            assert _tuer(tmp_path) == 1
            p.wait(timeout=5)
            assert not psutil.pid_exists(p.pid) or psutil.Process(p.pid).status() == psutil.STATUS_ZOMBIE
        finally:
            if p.poll() is None:
                p.kill()


def test_sans_faux_rien_tue(tmp_path):
    """Sans faux.py, rien n'est tue."""
    assert not _tuer(tmp_path)


def test_fixture_autouse_branchee():
    """La fixture de teardown est bien autouse."""
    src = Path(conftest.__file__).read_text(encoding="utf-8")
    avant = src.split("def _faux_orphelins_au_teardown")[0]
    assert "def _faux_orphelins_au_teardown" in src and "autouse=True" in avant[-120:]
