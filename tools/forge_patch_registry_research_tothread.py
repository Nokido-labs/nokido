# -*- coding: utf-8 -*-
"""One-shot patcher: handle_research_agent hors event-loop (Fix 3 RCA wedge).

forge_research_agent.research_agent = SearXNG HTTP + _ollama (urllib sync,
timeout 30s) x max_rounds — appele SYNC dans la coroutine = gele l'event-loop
du hub pendant des minutes (coupable liste loop_lag RCA 2026-07-02).
Fix = await asyncio.to_thread au site d'appel (asyncio deja importe top-level).

CRITICAL_FILE -> owner trusted_script, garanties habituelles (count==1,
idempotence, compile() avant ecriture, newline preserve).

Run : run action=trusted_script path=tools/forge_patch_registry_research_tothread.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

OLD = (
    '        return str(\n'
    '            research_agent(\n'
)
NEW = (
    '        # Fix 3 RCA wedge : SearXNG+ollama sync x rounds -> JAMAIS sur l\'event-loop.\n'
    '        return str(\n'
    '            await asyncio.to_thread(\n'
    '                research_agent,\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "to_thread(\n                research_agent," in text:
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
print(f"OK: handle_research_agent offloade (to_thread) + AST valid. newline={nl!r}")
