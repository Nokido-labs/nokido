"""NR : `app/forge_mesure.py` est LEGER (stdlib seule) et source unique de `_classer`."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_import_mesure_ne_charge_ni_proxy_ni_hub():
    code = ("import sys; sys.path.insert(0, %r); import app.forge_mesure; "
            "bad=[m for m in sys.modules if 'forge_agent_proxy' in m or 'nokido_hub' in m]; "
            "print('BAD', bad); sys.exit(1 if bad else 0)") % str(ROOT)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_classer_source_unique():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_cli_swarm
    from app import forge_mesure
    assert forge_cli_swarm._classer is forge_mesure._classer
