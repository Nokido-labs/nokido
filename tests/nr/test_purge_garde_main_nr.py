"""NR -- la purge de cache du demarrage ne retire JAMAIS `__main__` de sys.modules.

MESURE du 2026-09-25 (journal du bridge TUI, sandbox/logs/tui_bridge.log) : la TUI v13 lancee
par le bridge :7440 (`python app/Nokido.py`) mourait dans `DevOpsApp(...)` :
    textual/_path.py:70  inspect.getfile(obj.__class__)
    OSError: source code not available
`forge_startup._purge_pycache` retire de sys.modules TOUT module dont le fichier est dans app/ --
donc `__main__`, puisque le script lance EST app/Nokido.py. `inspect.getfile` d'une classe de
`__main__` sans module enregistre leve cette erreur ; textual-serve gardait alors le websocket
ouvert, et le navigateur attendait sans fin (« la TUI ne finit jamais de s'afficher »).

Sous-processus : la purge agit sur sys.modules et sur app/__pycache__ (un cache, recree a la
demande) ; rien ne fuit dans la suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.45)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]

SONDE = """
import json, sys, types
from pathlib import Path
sys.path.insert(0, {racine!r})
from nokido_agent.app.forge_startup import _purge_pycache
app = Path({app!r})
# Comme `python app/Nokido.py` : le script lance vit dans app/.
sys.modules["__main__"].__file__ = str(app / "Nokido.py")
faux = types.ModuleType("faux_module_app")
faux.__file__ = str(app / "faux_module_app.py")
sys.modules["faux_module_app"] = faux
_purge_pycache()
print("RESULTAT " + json.dumps({{
    "main_garde": "__main__" in sys.modules,
    "faux_purge": "faux_module_app" not in sys.modules,
}}))
"""


def test_purge_garde_main_et_purge_le_reste():
    code = SONDE.format(racine=str(RACINE), app=str(RACINE / "app"))
    r = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120)
    ligne = next((l for l in r.stdout.splitlines() if l.startswith("RESULTAT ")), None)
    assert ligne, "sonde muette (rc=%s) :\n%s" % (r.returncode, r.stderr[-1500:])
    etat = json.loads(ligne[len("RESULTAT "):])
    assert etat["main_garde"], "__main__ retire de sys.modules : Textual ne retrouve plus la classe"
    assert etat["faux_purge"], "la purge ne purge plus les modules de app/"
