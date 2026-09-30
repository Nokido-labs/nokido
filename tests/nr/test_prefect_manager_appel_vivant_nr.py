"""NR -- aucun site ne demande `get_prefect_manager` a forge_prefect, qui ne l'a plus.

MESURE du 2026-09-25 (journal du bridge TUI, sandbox/logs/tui_bridge.log) : une fois `__main__`
garde par la purge du demarrage, la TUI v13 mourait a forge_startup.py:205 --
    AttributeError: module 'forge_prefect' has no attribute 'get_prefect_manager'
L'accesseur vit dans forge_context (29 appelants). Tant que `get_settings()` rendait None
(`__main__` purge), le `and` court-circuitait l'appel mort : un defaut en cachait un autre.
Deux JUMEAUX portaient la meme forme dans forge_handler_patch.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app + lecture (l.23)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
APP = RACINE / "app"
APPEL_MORT = re.compile(r"""__import__\(\s*["']forge_prefect["']\s*\)\s*\.\s*get_prefect_manager""")


def test_aucun_appel_a_l_accesseur_disparu():
    fautifs = []
    for p in APP.rglob("*.py"):
        rel = p.relative_to(RACINE).as_posix()
        if "/_attic/" in rel or "/backups/" in rel:
            continue  # archives figees, jamais importees
        for n, ligne in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if APPEL_MORT.search(ligne):
                fautifs.append("%s:%d" % (rel, n))
    assert not fautifs, "appel a forge_prefect.get_prefect_manager (inexistant) : %s" % fautifs


def test_l_accesseur_vivant_existe():
    for _p in (str(RACINE), str(APP)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from nokido_agent.app import forge_context

    assert callable(getattr(forge_context, "get_prefect_manager", None))
