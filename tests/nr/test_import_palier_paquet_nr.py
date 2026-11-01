"""NR : forge_task_executor s'importe par le chemin de paquet SANS tools/ dans sys.path."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CODE = """
import os, sys
sys.path[:] = [p for p in sys.path if os.path.basename(os.path.normpath(p)) != 'tools']
sys.path.insert(0, %r)
import nokido_agent.tools.forge_task_executor as m
assert m._palier.__name__.endswith('forge_palier_effort')
import nokido_agent.tools.nokido_headless
"""


def test_import_paquet_sans_tools_dans_syspath():
    r = subprocess.run([sys.executable, "-c", CODE % str(ROOT)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
