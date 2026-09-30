# -*- coding: utf-8 -*-
"""NR — `forge_free_tier_census` resout `nokido_agent` quand il tourne en job.

Mesure du 2026-09-23 : lance par `run_job`, il est mort en `ModuleNotFoundError:
No module named 'nokido_agent'` au moment de lire ses cles. Son `sys.path`
n'ajoutait que `app/` et `tools/` ; le paquet `nokido_agent` se resout depuis la
RACINE. Sous pytest, la racine est deja dans le chemin : un test en processus
aurait ete VERT sur le defaut. D'ou un processus NEUF, lance hors du depot.

Nom du fichier : la premiere version contenait le mot « secrets » -- ignoree par
`.gitignore` et bloquee en lecture par le garde : un NR que git ne voit pas ne
tourne nulle part.
"""
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.30)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "forge_free_tier_census.py"


def test_le_recenseur_resout_nokido_agent_dans_un_processus_neuf(tmp_path):
    code = (
        "import importlib.util as u\n"
        "s = u.spec_from_file_location('census', r'%s')\n"
        "m = u.module_from_spec(s); s.loader.exec_module(m)\n"
        "import nokido_agent.app.forge_secrets\n"
        "print('OK')\n" % SCRIPT
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, (
        "le recenseur ne resout pas nokido_agent hors du depot : %s"
        % (r.stderr.strip().splitlines() or ["?"])[-1]
    )
