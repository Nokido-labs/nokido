"""Un worker de la suite pure qui meurt doit dire QUEL test et, si c'est os._exit, QUELLE pile.

Owner 5/11 : la CI tombe sur le meme test depuis des semaines. Le worker meurt « Not properly terminated », sans evenement
Windows ni trace : pytest-timeout (methode thread) et tout autre appelant de os._exit ne laissent rien dans le rapport.
Chemin reel : un vrai pytest en sous-processus, avec tests/conftest.py charge, puis le rapporteur que ci_local appelle.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_vol_worker_nr", RACINE / "tools" / "forge_vol_worker.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _pytest(tmp_path, corps, env):
    (tmp_path / "test_cible.py").write_text(corps, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = dict(env, PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("NOKIDO_CI_LISTE", None)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.conftest", "--rootdir", str(tmp_path), "-c", str(tmp_path / "pytest.ini"),
                           str(tmp_path / "test_cible.py")], cwd=RACINE, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=25)


def test_os_exit_laisse_le_test_et_la_pile(tmp_path):
    dossier = tmp_path / "fh"
    r = _pytest(tmp_path, "import os\n\n\ndef test_meurt():\n    os._exit(3)\n", dict(os.environ, NOKIDO_FAULTHANDLER_DIR=str(dossier)))
    assert r.returncode == 3, r.stdout[-500:]
    vols = list(dossier.glob("vol_*.log"))
    assert len(vols) == 1
    t = vols[0].read_text(encoding="utf-8")
    assert "START" in t and "test_meurt" in t
    assert "OS_EXIT code=3" in t
    assert "test_cible.py" in t  # la pile nomme l'appelant


def test_le_verdict_du_test_ne_change_pas(tmp_path):
    dossier = tmp_path / "fh"
    r = _pytest(tmp_path, "def test_vert():\n    assert True\n", dict(os.environ, NOKIDO_FAULTHANDLER_DIR=str(dossier)))
    assert r.returncode == 0, r.stdout[-500:]
    t = next(dossier.glob("vol_*.log")).read_text(encoding="utf-8")
    assert "FIN" in t and "OS_EXIT" not in t


def test_sans_dossier_aucun_journal_et_os_exit_intact(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "NOKIDO_FAULTHANDLER_DIR"}
    r = _pytest(tmp_path, "import os\n\n\ndef test_x():\n    assert getattr(os._exit, '_vol_worker', False) is False\n", env)
    assert r.returncode == 0, r.stdout[-500:]
    assert not list(tmp_path.glob("**/vol_*.log"))


def test_le_rapporteur_nomme_le_test_du_worker_mort(tmp_path, capsys):
    d = tmp_path
    (d / "vol_gw1_11.log").write_text("10:00:00 START a::t1\n10:00:01 FIN a::t1\n10:00:01 START b::mort\n", encoding="utf-8")
    (d / "vol_gw2_12.log").write_text("10:00:00 START c::t2\n10:00:01 FIN c::t2\n", encoding="utf-8")
    (d / "vol_gw3_13.log").write_text("10:00:00 START e::t3\n10:00:31 OS_EXIT code=1 fil=pytest_timeout\n--- fil MainThread\n  File x.py\n", encoding="utf-8")
    (d / "vol_principal_14.log").write_text("10:00:00 START f::sous_processus\n", encoding="utf-8")
    morts = _module().rapporter(d)
    sortie = capsys.readouterr().out
    assert {m["worker"] for m in morts} == {"gw1", "gw3"}
    assert "b::mort" in sortie and "OS_EXIT code=1" in sortie and "File x.py" in sortie
    assert "gw2" not in sortie
    assert "f::sous_processus" not in sortie  # un sous-processus de test tue expres n'est pas un worker mort
    assert "1 sous-processus" in sortie


def test_rapporteur_sans_journal_le_dit(tmp_path, capsys):
    assert _module().rapporter(tmp_path / "absent") == []
    assert "aucun journal" in capsys.readouterr().out


def test_ci_local_appelle_le_rapporteur():
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    i = src.find("_rapporter_faulthandler(_fh_dir)")
    assert i > 0 and "forge_vol_worker" in src[i:i + 400]
