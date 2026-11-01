"""NR 30/10 -- la mesure du profil client ne touche ni l'arbre ni les bases du hub vivant.

Le script d'AGY (62d8481ea) faisait `pip install -e <depot>` (egg-info ecrit dans l'arbre de travail) et demarrait
un second hub sur les MEMES bases que le hub vivant. Desormais : copie `git archive HEAD` dans le dossier temporaire,
installation non editable depuis la copie, LAFORGE_DB vers une base JETABLE (lu par forge_db_path.py:550),
NOKIDO_DATA_DIR sous le dossier temporaire (forge_db_path.py:446).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("mesure_profil_client", RACINE / "tools/bench/mesure_profil_client.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _g(d, *a):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=NUL",
                           "-c", "safe.directory=*", "-C", str(d), *a], capture_output=True, text=True,
                          errors="replace", env=env)


def test_env_isole_vise_une_base_jetable_sous_le_dossier_temporaire(tmp_path):
    env = M.env_isole(tmp_path, 8799)
    assert Path(env["LAFORGE_DB"]).parent == tmp_path and Path(env["LAFORGE_DB"]).exists()
    assert Path(env["NOKIDO_DATA_DIR"]).parent == tmp_path
    assert env["LAFORGE_HUB_PORT"] == "8799" and env["LAFORGE_HUB_HOST"] == "127.0.0.1"


def test_la_copie_n_ecrit_rien_dans_le_depot_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _g(src, "init", "-q")
    (src / "a.txt").write_text("a")
    _g(src, "add", "a.txt")
    assert _g(src, "commit", "-q", "-m", "a").returncode == 0
    avant = sorted(p.name for p in src.iterdir())
    copie = M.copier_depot(src, tmp_path / "copie")
    assert (copie / "a.txt").read_text() == "a"
    assert sorted(p.name for p in src.iterdir()) == avant
