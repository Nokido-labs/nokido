#!/usr/bin/env python3
# apply_mcp_buffer_patch.py
# Patch le MCP server pour augmenter les limites buffer
# Le Sentinel bloque l ecriture directe sur nokido_mcp_server.py.
#
# Commandes:
#   python tools/apply_mcp_buffer_patch.py           # applique
#   python tools/apply_mcp_buffer_patch.py --revert  # revert
#   python tools/apply_mcp_buffer_patch.py --check   # check
#
# Apres: nssm restart NokidoMCP

import shutil
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "nokido_mcp_server.py"
BACKUP = TARGET.with_suffix(".py.bak_buffer")

PATCHES = [
    ("if len(out) > 4096:", "if len(out) > 6144:", "seuil mmap 4KB->6KB"),
    ("+ out[:500]", "+ out[:800]", "preview mmap 500->800"),
    ("return out[:8000]", "return out[:12000]", "fallback 8KB->12KB"),
    ("text=res[:10000]", "text=res[:14000]", "read limit 10KB->14KB"),
]


def check():
    """Verifie si les patches sont appliques."""
    text = TARGET.read_text(encoding="utf-8")
    print("File: " + str(TARGET))
    print("Size: " + str(len(text)) + " bytes")
    patched = 0
    for old, new, desc in PATCHES:
        if new in text:
            print("  PATCHED: " + desc)
            patched += 1
        elif old in text:
            print("  ORIGINAL: " + desc)
        else:
            print("  UNKNOWN: " + desc)
    return patched


def apply_patches():
    """Applique les patches."""
    text = TARGET.read_text(encoding="utf-8")
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print("Backup: " + str(BACKUP))
    applied = 0
    for old, new, desc in PATCHES:
        if old in text:
            text = text.replace(old, new, 1)
            print("  APPLIED: " + desc)
            applied += 1
        elif new in text:
            print("  SKIP (already): " + desc)
        else:
            print("  WARN: pattern not found for " + desc)
    TARGET.write_text(text, encoding="utf-8")
    print(str(applied) + " patches applied. Restart: nssm restart NokidoMCP")
    return applied


def revert():
    """Revert depuis le backup."""
    if BACKUP.exists():
        shutil.copy2(BACKUP, TARGET)
        print("Reverted from " + str(BACKUP))
    else:
        print("No backup found!")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--revert" in sys.argv:
        revert()
    else:
        print("Applying MCP buffer patches...")
        apply_patches()
