"""NR du 27/10 : le worker de veille s'importe quand il est LANCE PAR SON CHEMIN (chemin reel du superviseur).

Mesure : NokidoWatchAgent reveille 15:38 -> crash en boucle `ModuleNotFoundError: No module named 'nokido_agent'`
(ligne d'import de ChainExecutor) : lance par chemin, sys.path[0] vaut tools/, pas la racine. 8 chaines de veille
sont restees `pending` sans consommateur. Le NR rejoue ce chemin (repertoire courant etranger, sans PYTHONPATH),
sans demarrer la boucle (run_name different de __main__).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "forge_watch_agent_worker.py"


@pytest.mark.timeout(150)   # sous-processus a 120 s > borne de la suite (30 s) : borne explicite (cliquet 31/10)
def test_le_worker_s_importe_lance_par_son_chemin(tmp_path):
    code = ("import sys, runpy; sys.path.insert(0, %r); runpy.run_path(%r, run_name='nr_import')"
            % (str(SCRIPT.parent), str(SCRIPT)))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                       errors="replace", timeout=120, env=env)
    assert "No module named 'nokido_agent'" not in r.stderr, r.stderr[-800:]
    assert r.returncode == 0, r.stderr[-800:]
