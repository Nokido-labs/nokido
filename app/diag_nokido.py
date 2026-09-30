"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
import sys, traceback, pathlib

# Racine DERIVEE du fichier. Le dossier "Nokido" vise ici n'existe pas (sequelle du
# cutover du 2026-07-09) : ce journal de diagnostic n'a jamais pu etre ecrit.
log_path = pathlib.Path(__file__).resolve().parent.parent / "logs" / "diag_import.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Patch Textual pour intercepter compose
    import textual.app as _ta

    _orig_run = _ta.App.run_async

    async def _patched_run(self, *a, **kw) -> object:
        """patched run."""
        try:
            return await _orig_run(self, *a, **kw)
        except Exception as e:
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            raise

    _ta.App.run_async = _patched_run

    import asyncio

    # Import Nokido et run main
    from nokido_agent.app import Nokido

    asyncio.run(Nokido.main())

except SystemExit:
    pass
except Exception as e:
    msg = traceback.format_exc()
    log_path.write_text(msg, encoding="utf-8")
    print(msg)
