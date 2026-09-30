#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Liste les NOMS de variables de Nokido.env (JAMAIS les valeurs).

Diagnostic sûr : ne lit que la partie avant '=' de chaque ligne -> aucune valeur
de secret n'entre dans la sortie/contexte. Filtre optionnel par substring sur le nom.
Usage: trusted_script path=tools/forge_env_key_names.py script_args="zai"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
flt = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
env = ROOT / "Nokido.env"

names = []
for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    names.append(s.split("=", 1)[0].strip())  # NOM seul, jamais la valeur

pats = ("zai", "z_ai", "zhipu", "glm", "bigmodel")
match = [n for n in names if any(p in n.lower() for p in pats)]
print("MATCH z.ai/glm/zhipu :", match)
print("LAST 6 vars         :", names[-6:])
print("TOTAL vars          :", len(names))
