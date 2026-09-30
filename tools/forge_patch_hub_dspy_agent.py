# -*- coding: utf-8 -*-
"""One-shot patcher: ajoute DSPY_ROUTER a _AGENT_LIST de tools/nokido_hub.py.

CRITICAL_FILE -> applique via owner trusted_script (chemin officiel, miroir
forge_patch_mcpsec_fix3) en repliquant les garanties governed_edit :
exact-match (count==1), garde d'idempotence, compile() AVANT ecriture,
style de newline preserve. Aucune ecriture si le moindre mismatch.

Contexte : identite DSPY_ROUTER au registre ring 3 (commit 1320b59c) + token
vault frappe (forge_provision_clients) ; sans l'entree _AGENT_LIST le loader
_load_agent_tokens ne charge pas le token -> 401. Reload hub requis apres.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "tools", "nokido_hub.py")

OLD = '    "ANTIGRAVITY",\n)'
NEW = '    "ANTIGRAVITY",\n    "DSPY_ROUTER",\n)'

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if '"DSPY_ROUTER"' in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

n = text.count(OLD)
if n != 1:
    print(f"ABORT: anchor found {n} times (expected exactly 1) -> no write")
    sys.exit(2)

text = text.replace(OLD, NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: DSPY_ROUTER ajoute a _AGENT_LIST + AST valid. newline={nl!r}")
print("SUITE: reload hub (restart_hub.ps1) pour charger le token.")
