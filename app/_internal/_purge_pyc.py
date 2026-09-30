"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch__purge_pyc
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""Purge les .pyc Nokido pour forcer rechargement propre."""
import os, stat, pathlib, tempfile, sys

app_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent

p = app_dir / "__pycache__"
if p.exists():
    for f in p.glob("Nokido*.pyc"):
        try:
            os.chmod(f, 0o644)
            f.unlink()
        except Exception:
            pass

e = pathlib.Path(tempfile.gettempdir()) / "nokido_pyc"
if e.exists():
    for f in e.rglob("Nokido*.pyc"):
        try:
            os.chmod(f, 0o644)
            f.unlink()
        except Exception:
            pass

print("  [OK] cache pyc purge")
