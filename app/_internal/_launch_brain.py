"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch__launch_brain
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""Lance brain_worker.py en arrière-plan sans fenêtre console."""
import subprocess, sys, pathlib, os

brain = pathlib.Path(__file__).parent / "brain_worker.py"
if not brain.exists():
    sys.exit(0)

# Lit la version Nokido pour nommer le processus
try:
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from nokido_agent.app.forge_version import get as _fvg

    _ver = _fvg()
except Exception:
    _ver = "?"

# Script wrapper qui nomme le processus avant de lancer brain_worker
_wrapper = (
    "import setproctitle, sys, runpy; "
    f"setproctitle.setproctitle('LaForge-Brain v{_ver}'); "
    "sys.argv = [sys.argv[0]] + sys.argv[1:]; "
    f"runpy.run_path(r'{brain}', run_name='__main__')"
)

kwargs = dict(
    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    env={**os.environ, "LAFORGE_PROC_NAME": f"LaForge-Brain v{_ver}"},
)

port = sys.argv[1] if len(sys.argv) > 1 else "5557"

# Tente avec setproctitle, fallback sans si non installé
try:
    import importlib

    importlib.import_module("setproctitle")
    proc = subprocess.Popen(
        [sys.executable, "-c", _wrapper, "--port", port, "--no-generator", "--close-delay", "5"], **kwargs
    )
except Exception:
    # Fallback direct sans nommage
    proc = subprocess.Popen(
        [sys.executable, str(brain), "--port", port, "--no-generator", "--close-delay", "5"], **kwargs
    )

print(f"brain_worker lance sur port {port} (PID {proc.pid})")
