# -*- coding: utf-8 -*-
"""One-shot : re-commente la ligne OPENROUTER_API_KEY de Nokido.env.

Contexte (memoire swebench 2026-07-04) : la cle a ete migree au coffre DPAPI
(prioritaire) ; la ligne en clair decommentee pendant la migration est INERTE
mais doit redevenir commentee. Aucune valeur lue/extraite/affichee : operation
de prefixe de ligne uniquement, octets intacts. Idempotent.

Run : run action=trusted_script path=tools/forge_env_recomment_openrouter.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "Nokido.env")

raw = open(TARGET, "rb").read()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
lines = raw.split(nl)

hits = 0
for i, line in enumerate(lines):
    if line.startswith(b"OPENROUTER_API_KEY="):
        lines[i] = b"# " + line
        hits += 1

if hits == 0:
    print("no-op: aucune ligne active OPENROUTER_API_KEY (deja commentee ?)")
    sys.exit(0)

open(TARGET, "wb").write(nl.join(lines))
print(f"OK: {hits} ligne(s) re-commentee(s) dans Nokido.env (octets valeur intacts)")
