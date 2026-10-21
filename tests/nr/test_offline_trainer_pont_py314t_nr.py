"""NR -- OfflineTrainer demarre sous son VRAI interpreteur (PY314T, canari sans GIL) : `nokido_agent` y est importable.

Mesure 19/10 02:21 (journal logs/supervisor/NokidoOfflineTrainer.log) : premier tir NREM3 reussi apres le correctif
circadien, NightTrainer vivant, mais OfflineTrainer `exited code=1 after 0s` x5 puis QUARANTAINE --
`ModuleNotFoundError: No module named 'nokido_agent'` a tools/forge_offline_trainer.py:317. Le script, lance par son
chemin, ne pose que app/ sur sys.path ; sous l'interpreteur principal la racine vient d'ailleurs, pas sous PY314T.
Le NR emprunte le CHEMIN REEL : l'interpreteur du service, un repertoire courant neutre (sinon '' masque le defaut).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# L'interpreteur du service, lu a sa SOURCE (services.toml) : `~` designe le profil du compte qui lance pytest.
_m = re.search(r'^PY314T\s*=\s*"([^"]+)"', (ROOT / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"),
               re.M)
PY314T = Path(_m.group(1)) if _m else Path("introuvable")


def test_le_pont_nokido_agent_existe_sous_l_interpreteur_du_service(tmp_path):
    try:
        lisible = PY314T.exists()
    except OSError:
        lisible = False
    if not lisible:
        pytest.skip("interpreteur PY314T ILLISIBLE depuis ce compte : chemin reel non verifiable")
    code = ("import runpy; runpy.run_path(r'%s'); import nokido_agent.app.forge_guarded_change; print('PONT_OK')"
            % (ROOT / "tools" / "forge_offline_trainer.py"))
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env.update(PYTHONNOUSERSITE="1", PYTHON_GIL="0")
    r = subprocess.run([str(PY314T), "-c", code], cwd=str(tmp_path), capture_output=True, text=True,
                       errors="replace", timeout=120, env=env)
    assert "PONT_OK" in r.stdout, (r.stdout + r.stderr)[-800:]
