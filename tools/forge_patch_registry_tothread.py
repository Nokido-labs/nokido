# -*- coding: utf-8 -*-
"""One-shot patcher: to_thread sur _archive_long_args dans forge_mcp_registry.dispatch.

Dernier trigger wedge connu (RCA 2026-07-02/03) : _archive_long_args fait du SQLite
SYNC (connect+INSERT+commit par long-arg) DANS async def dispatch (L496) = sur
l'event-loop unique du hub, a CHAQUE appel d'outil. Fix = await asyncio.to_thread
(import asyncio module-level L52 ; meme idiome que les fixes to_thread precedents).

CRITICAL_FILE -> applique via owner trusted_script (miroir de
forge_patch_mcpsec_fix3.py) : exact-match assert count==1, garde idempotence,
compile() AST AVANT ecriture, style newline preserve. Abort sans ecrire au
moindre ecart. Re-run sur.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

OLD = "                    args_preview = self._archive_long_args(args, agent, name)"
NEW = (
    "                    # Offload SQLite sync hors event-loop (wedge trigger #2, RCA 2026-07-02/03)\n"
    "                    args_preview = await asyncio.to_thread(self._archive_long_args, args, agent, name)"
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "await asyncio.to_thread(self._archive_long_args" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

n = text.count(OLD)
if n != 1:
    print(f"ABORT: target found {n} times (expected exactly 1) -> no write")
    sys.exit(2)

text = text.replace(OLD, NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: to_thread applique sur _archive_long_args + AST valide. newline={nl!r}")
