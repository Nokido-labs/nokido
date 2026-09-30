# -*- coding: utf-8 -*-
"""One-shot patcher fix1: NameError `re` dans _compact_tools (forge_mcp_registry).

Le `import re` module-level du fichier est tardif (apres la classe) / non
disponible dans les globals au call-time -> import local dans la methode.
Memes garanties que le patcher parent : exact-match count==1, idempotence,
compile() avant ecriture, newline preserve.

Run : run action=trusted_script path=tools/forge_patch_registry_compact_fix1.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

OLD = (
    '        du canonique (copie par tool)."""\n'
    '        out: List[Dict[str, Any]] = []\n'
)
NEW = (
    '        du canonique (copie par tool)."""\n'
    '        import re  # local : le `import re` module-level du fichier est tardif\n'
    '        out: List[Dict[str, Any]] = []\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "import re  # local" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

n = text.count(OLD)
if n != 1:
    print(f"ABORT: block found {n} times (expected exactly 1) -> no write")
    sys.exit(2)

text = text.replace(OLD, NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: fix1 import re local applied + AST valid. newline={nl!r}")
