"""forge_log_rotation.py — Centralized rotating log handlers for Nokido.

Incident 2026-05-25 : `mcp_audit.log` a atteint **83 MB** sans rotation. Plus
des dizaines de `.err`/`.log` NSSM crash-loop (~290 bytes chacun) saturent
inode cache NTFS. Sans cap, le disque finit par etre engorge et l'I/O
contention degrade tout.

Politique : RotatingFileHandler maxBytes=10MB, backupCount=5 par defaut.
Override via env vars `LAFORGE_LOG_MAX_BYTES` / `LAFORGE_LOG_BACKUP_COUNT`.

Usage minimal dans un module :

    from forge_log_rotation import get_rotating_logger
    log = get_rotating_logger("forge_my_module")
    log.info("hello")

Usage avec path explicite :

    log = get_rotating_logger("hub_audit", path=ROOT/"logs/mcp_audit.log")

Migration des handlers existants (drop-in pour FileHandler) :

    from forge_log_rotation import migrate_to_rotating
    migrate_to_rotating(logging.getLogger("Nokido"))
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = ROOT / "logs"

MAX_BYTES = int(os.environ.get("LAFORGE_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
BACKUP_COUNT = int(os.environ.get("LAFORGE_LOG_BACKUP_COUNT", "5"))
DEFAULT_FMT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"


def get_rotating_logger(
    name: str,
    *,
    path: Path | str | None = None,
    level: int = logging.INFO,
    fmt: str = DEFAULT_FMT,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
) -> logging.Logger:
    """Return a configured logger with a RotatingFileHandler.

    Idempotent : si le logger a deja un RotatingFileHandler pointant vers le
    meme fichier, on ne duplique pas.
    """
    if path is None:
        path = DEFAULT_LOG_DIR / f"{name}.log"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger(name)
    log.setLevel(level)

    abs_path = str(path.resolve())
    for h in log.handlers:
        if isinstance(h, RotatingFileHandler) and str(Path(h.baseFilename).resolve()) == abs_path:
            return log  # deja configure

    handler = RotatingFileHandler(
        str(path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter(fmt))
    log.addHandler(handler)
    log.propagate = False
    return log


def migrate_to_rotating(logger: logging.Logger, *, max_bytes: int = MAX_BYTES, backup_count: int = BACKUP_COUNT) -> int:
    """Replace tous les FileHandler non-rotating sur ce logger par des
    RotatingFileHandler equivalents (meme fichier, meme format, meme level).
    Retourne le nombre de handlers migres."""
    migrated = 0
    new_handlers: list[logging.Handler] = []
    for h in list(logger.handlers):
        if isinstance(h, logging.FileHandler) and not isinstance(h, RotatingFileHandler):
            try:
                base = h.baseFilename
                fmt = h.formatter
                level = h.level
                logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
                new_h = RotatingFileHandler(
                    base,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                    delay=True,
                )
                if fmt:
                    new_h.setFormatter(fmt)
                new_h.setLevel(level)
                new_handlers.append(new_h)
                migrated += 1
            except Exception:
                logger.addHandler(h)  # restore en cas d'echec
        else:
            new_handlers.append(h)
    for h in new_handlers:
        if h not in logger.handlers:
            logger.addHandler(h)
    return migrated


def cap_existing_log(path: Path | str, *, keep_last_bytes: int = MAX_BYTES) -> bool:
    """Tronque immediatement un fichier de log qui a deja explose, en gardant
    les `keep_last_bytes` derniers octets. Usage one-shot pour rattraper les
    logs deja > 10 MB (ex: mcp_audit.log 83 MB en 2026-05-25)."""
    path = Path(path)
    if not path.exists():
        return False
    size = path.stat().st_size
    if size <= keep_last_bytes:
        return False
    try:
        with path.open("rb") as f:
            f.seek(size - keep_last_bytes)
            tail = f.read()
        # garde a partir du prochain '\n' pour eviter de couper au milieu
        nl = tail.find(b"\n")
        if 0 <= nl < 4096:
            tail = tail[nl + 1 :]
        backup = path.with_suffix(path.suffix + ".pretruncate")
        try:
            backup.write_bytes(b"")  # marker, sans copier 83 MB
        except Exception:
            pass
        path.write_bytes(tail)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # CLI : truncate mcp_audit.log + autres logs > 10MB de logs/
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--cap-large":
        for p in DEFAULT_LOG_DIR.glob("*.log"):
            if p.stat().st_size > MAX_BYTES:
                ok = cap_existing_log(p)
                print(f"  {'capped' if ok else 'skip'} {p.name} (size {p.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print(__doc__)
