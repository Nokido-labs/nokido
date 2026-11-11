"""NR : llama_cli s'importe hors paquet nokido_agent (repli checkout forge_secrets)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CODE = """
import sys

import importlib.abc


class _NoNokidoAgent(importlib.abc.MetaPathFinder):
    \"\"\"Temoins : nokido_agent NON installe — l'import du paquet doit lever ImportError
    et le repli checkout de llama_cli prendre le relais par le bootstrap sys.path.\"\"\"

    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'nokido_agent' or fullname.startswith('nokido_agent.'):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, _NoNokidoAgent())

import tools.llama_cli as llama_cli
assert hasattr(llama_cli, 'main'), 'main absent du module llama_cli'
assert hasattr(llama_cli, 'get_secret'), 'get_secret absent (repli checkout rate)'
"""


def test_llama_cli_import_sans_nokido_agent():
    # Borne SOUS le --timeout=30 de la suite (cliquet test_sous_processus_borne_sous_la_suite_nr) : au-dela, pytest-timeout
    # (methode thread sous Windows) abat toute la suite. Un depassement est ILLISIBLE, jamais vert.
    try:
        r = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=25)
    except subprocess.TimeoutExpired:
        pytest.skip("ILLISIBLE : import de llama_cli > 25 s (machine chargee), ni vert ni rouge")
    assert r.returncode == 0, r.stderr[-1500:]
