"""tools/forge_env_backup_relocate.py

Deplace les backups plaintext laisses par forge_vault_migrate dans
_backups/secrets/ (gitignore). Idempotent. Necessaire pour les runs
anterieurs ou BACKUP atterrissait a la racine du repo (sous compte
LaForgeTrusted dont Path.home() = C:/Users/Default).

Run via : hub run action=trusted_script path=tools/forge_env_backup_relocate.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "_backups" / "secrets"
PATTERNS = ("nokido_env_backup*.txt", "nokido_env_prep_backup*.txt")


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    moved = 0
    for pat in PATTERNS:
        for src in ROOT.glob(pat):
            if not src.is_file():
                continue
            dst = TARGET / src.name
            try:
                shutil.move(str(src), str(dst))
                print(f"[relocate] {src.name} -> {dst}")
                moved += 1
            except OSError as e:
                print(f"[relocate] FAIL {src.name}: {e}")
    print(f"[relocate] {moved} backup(s) deplace(s) vers {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
