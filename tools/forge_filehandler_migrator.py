"""forge_filehandler_migrator.py — Audit + migrate FileHandler -> RotatingFileHandler.

Phase 23 durcissement : tous les logs Nokido doivent utiliser
RotatingFileHandler pour eviter logs unbounded (memory: skill_enricher
heartbeat 29j sans rotation = log GB).

Audit-only par defaut. --apply pour modifier sources.
Backup .bak avant modification.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns
IMPORT_RE = re.compile(r"^(\s*)from\s+logging\s+import\s+(.+)$", re.M)
FH_USE_RE = re.compile(r"\blogging\.FileHandler\s*\(")
ROTATING_IMPORT = "from logging.handlers import RotatingFileHandler"

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 5


SKIP_PATHS = ("_attic", "__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache")


def audit() -> list[dict]:
    """Scan tools/ + app/ for FileHandler non-rotating usage.
    Skip _attic (archived code), __pycache__, etc."""
    out = []
    for fp in list((ROOT / "tools").rglob("*.py")) + list((ROOT / "app").rglob("*.py")):
        rel = str(fp.relative_to(ROOT))
        if any(skip in rel for skip in SKIP_PATHS):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "logging.FileHandler" not in text:
            continue
        has_rotating = "RotatingFileHandler" in text
        n_fh = len(FH_USE_RE.findall(text))
        out.append(
            {
                "path": rel,
                "filehandler_count": n_fh,
                "has_rotating_import": has_rotating,
                "size_lines": len(text.splitlines()),
            }
        )
    return out


def migrate_file(
    fp: Path, max_bytes: int = DEFAULT_MAX_BYTES, backup_count: int = DEFAULT_BACKUP_COUNT
) -> dict:
    """Migrate a single file. Add RotatingFileHandler import +
    replace logging.FileHandler( -> RotatingFileHandler( with maxBytes/backupCount.
    Backup .bak."""
    text = fp.read_text(encoding="utf-8", errors="replace")
    if "logging.FileHandler" not in text:
        return {"skip": "no FileHandler", "path": str(fp)}

    # 1. Add import if missing
    if "RotatingFileHandler" not in text:
        # Find a good insertion point: after "import logging" or top
        m = re.search(r"^(\s*)import\s+logging.*$", text, re.M)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + "\n" + ROTATING_IMPORT + text[insert_at:]
        else:
            # Insert at top after future imports
            lines = text.splitlines(keepends=True)
            insert_idx = 0
            for i, l in enumerate(lines):
                if l.startswith("from __future__") or l.startswith("#") or l.strip() == "":
                    insert_idx = i + 1
                else:
                    break
            lines.insert(insert_idx, ROTATING_IMPORT + "\n")
            text = "".join(lines)

    # 2. Replace logging.FileHandler( -> RotatingFileHandler( + add kwargs
    # NB: this is naive, only handles simple cases. Complex calls (multi-line)
    # left to manual review.
    def _replace(m):
        return "RotatingFileHandler("

    # Replace primary occurrence
    new_text = FH_USE_RE.sub(_replace, text)

    # Add maxBytes/backupCount in calls if not present (best effort line-by-line)
    def _augment(line):
        if "RotatingFileHandler(" in line and "maxBytes" not in line:
            # Insert kwargs before closing paren of THIS call (basic match)
            i = line.find("RotatingFileHandler(")
            # find matching close paren
            depth = 1
            j = i + len("RotatingFileHandler(")
            while j < len(line) and depth > 0:
                if line[j] == "(":
                    depth += 1
                elif line[j] == ")":
                    depth -= 1
                j += 1
            if depth == 0:
                # j-1 is closing paren
                inner = line[i + len("RotatingFileHandler(") : j - 1]
                if inner.strip():
                    new_inner = (
                        f"{inner.rstrip(', ')}, maxBytes={max_bytes}, backupCount={backup_count}"
                    )
                else:
                    new_inner = f"maxBytes={max_bytes}, backupCount={backup_count}"
                line = line[:i] + f"RotatingFileHandler({new_inner}" + line[j - 1 :]
        return line

    new_text = "".join(
        _augment(l + ("" if l.endswith("\n") else "\n")) for l in new_text.splitlines()
    )

    # 3. Backup + write
    bak = fp.with_suffix(fp.suffix + ".filehandler.bak")
    shutil.copy(fp, bak)
    fp.write_text(new_text, encoding="utf-8")

    return {"path": str(fp), "backup": str(bak), "ok": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply", action="store_true", help="Modify files in place (default audit-only)"
    )
    ap.add_argument("--limit", type=int, default=10, help="Max files to migrate per run (safety)")
    args = ap.parse_args()

    found = audit()
    print("=== FileHandler audit ===")
    print(f"  files using logging.FileHandler: {len(found)}")
    non_rotating = [f for f in found if not f["has_rotating_import"]]
    print(f"  non-rotating: {len(non_rotating)}")
    for f in non_rotating[:20]:
        print(f"    {f['path']:60} fh_count={f['filehandler_count']}")

    if not args.apply:
        print("\n  Use --apply to migrate (will create .filehandler.bak files)")
        print("  --limit caps migrations per run (default 10)")
        return

    print(f"\n=== Migrating (limit={args.limit}) ===")
    migrated = []
    for f in non_rotating[: args.limit]:
        try:
            r = migrate_file(ROOT / f["path"])
            migrated.append(r)
            print(f"  + {f['path']}")
        except Exception as e:
            print(f"  ! {f['path']}: ERR {e}")
    print(f"\nDONE: {len(migrated)} files migrated. Backups *.filehandler.bak")


if __name__ == "__main__":
    main()
