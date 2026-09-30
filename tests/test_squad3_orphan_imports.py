"""Squad 3 — imports orphelins forge_exegol_bridge / forge_distribution (2026-07-14).

Deux modules supprimes etaient encore importes statiquement :
- app/forge_exegol_supervisor.py -> forge_exegol_bridge (fallback CLI Exegol)
- tools/autotools.py (x4) -> forge_distribution (commandes dist-*)
Les imports etaient dans des try/except (pas de crash runtime) mais restaient des
imports STATIQUES de modules fantomes (flag scan AST + code mort). Fix = import
DYNAMIQUE guarde + message explicite. Ces tests verrouillent : plus d'orphelin
statique, modules importables, commandes fail-safe (string, jamais exception).
"""

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


def test_no_static_orphan_imports():
    for rel in ("app/forge_exegol_supervisor.py", "tools/autotools.py"):
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        orphans = re.findall(r"^\s*from (forge_exegol_bridge|forge_distribution) import", text, re.M)
        assert not orphans, f"{rel} importe encore statiquement un module retire : {orphans}"


def test_modules_import_clean():
    """Les deux modules doivent s'importer (AST + runtime), sans le module fantome."""
    assert importlib.import_module("forge_exegol_supervisor")
    assert importlib.import_module("autotools")


def test_dist_commands_failsafe_when_module_absent():
    """forge_distribution absent -> les commandes dist-* retournent une STRING d'erreur
    explicite (jamais une exception qui casserait autotools)."""
    import autotools

    for fn in ("run_dist_status", "run_dist_sync", "run_dist_replica"):
        out = getattr(autotools, fn)([])
        assert isinstance(out, str) and out, f"{fn} doit retourner une string fail-safe"
        assert "dist" in out.lower() or "distribution" in out.lower()
