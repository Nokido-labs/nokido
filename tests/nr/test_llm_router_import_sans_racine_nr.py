"""NR 24/10 : `forge_llm_router` s'importe avec SEULEMENT `app/` dans sys.path.

Mesure 24/10 : `palier_ollama_cloud_ok` (3e3ce9f0e) importait
`nokido_agent.tools.forge_provider_catalogue` sans repli, et il est appele AU
CHARGEMENT du module (filtre du catalogue Ollama Cloud). Un script ou un job qui ne
mettait que `app/` dans son chemin mourait en `ModuleNotFoundError: nokido_agent`
avant la premiere ligne utile -- le routeur entier, pas seulement Ollama Cloud.
Chemin reel : un interpreteur NEUF, sans PYTHONPATH, lance hors du depot.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Borne pytest (cliquet test_sous_processus_borne_sous_la_suite_nr) : le sous-interpreteur a timeout=240 > 30 s de
# la suite ; sans borne propre, pytest-timeout (methode thread, Windows) abattrait toute la session.
pytestmark = pytest.mark.timeout(300)

RACINE = Path(__file__).resolve().parents[2]


def test_le_routeur_s_importe_avec_app_seul(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSTARTUP")}
    env["PYTHONNOUSERSITE"] = "1"
    code = (
        "import sys; sys.path.insert(0, %r); import forge_llm_router as R; "
        "print('OK', R.palier_ollama_cloud_ok('openai/gpt-oss:120b'))" % str(RACINE / "app")
    )
    p = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    assert p.returncode == 0, (p.stderr or "")[-600:]
    assert "OK True" in p.stdout, p.stdout[-300:]
