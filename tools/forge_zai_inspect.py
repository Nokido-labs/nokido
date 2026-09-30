#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspecte la STRUCTURE de la zone z.ai dans Nokido.env (zero valeur affichee).
N'imprime que: index ligne, nom (avant '='), nb de '=', longueur valeur, heuristiques.
Sert a distinguer API_KEY_ID (id) de API_KEY (vraie cle) quand la zone est malformee."""

__FORGE_COLOR__ = "immunitaire/secret : inspecte la structure de la zone z.ai sans valeur"  # organe declare le 2026-09-06 (audit de raccordement)
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = ROOT / "Nokido.env"

for i, raw in enumerate(env.read_text(encoding="utf-8", errors="replace").splitlines()):
    s = raw.strip()
    low = s.lower()
    if not ("z.ai" in low or "zhipu" in low or "api_key" in low or "api key" in low):
        continue
    if "=" in s:
        name, _, val = s.partition("=")
        v = val.strip()
        print(f"L{i}: name='{name.strip()}' eq={s.count('=')} vallen={len(v)} "
              f"dot={'.' in v} second_API_KEY_in_val={'API_KEY' in val.upper()[1:]}")
    else:
        # ligne sans '=' : peut etre une valeur brute -> on n'imprime QUE la longueur
        print(f"L{i}: (no '=') linelen={len(s)} looks_keyish={('.' in s and 20 < len(s) < 120 and ' ' not in s)}")
