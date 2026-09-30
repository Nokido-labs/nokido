"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"


async def _cmd_rag(app, args: str) -> None:
    """cmd rag."""
    import sys as _sys

    # S'assurer que _g() trouve rag_engine via __main__
    _main = _sys.modules.get("__main__")
    if _main and hasattr(app, "rag_engine") and app.rag_engine is not None:
        if getattr(_main, "rag_engine", None) is None:
            _main.rag_engine = app.rag_engine
    from nokido_agent.app.forge_handler_rag import _handle_rag

    await _handle_rag(app, args)
