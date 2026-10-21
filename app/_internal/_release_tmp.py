from app.forge_settings import _LOCK_FILE
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch__release_tmp
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)


def _release_instance_lock():
    """Libère le lock fichier et supprime nokido.lock."""
    global _LOCK_FH
    import sys

    try:
        if _LOCK_FH and not _LOCK_FH.closed:
            if sys.platform == "win32":
                import msvcrt

                try:
                    _LOCK_FH.seek(0)
                    msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/_internal/_release_tmp.py', 28, exc_info=True)
            else:
                import fcntl

                try:
                    fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_UN)
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/_internal/_release_tmp.py', 35, exc_info=True)
            _LOCK_FH.close()
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/_internal/_release_tmp.py', 38, exc_info=True)
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/_internal/_release_tmp.py', 43, exc_info=True)
