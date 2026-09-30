#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extrait la VRAIE cle z.ai de la ligne malformee .env (...API_KEY_ID=<id> API_KEY=<key>)
et la stocke en ZAI_API_KEY au vault DPAPI. La cle = apres le DERNIER '='.
Zero valeur affichee (longueurs + heuristiques seulement)."""

__FORGE_COLOR__ = "immunitaire/secret : extrait la vraie cle z.ai et la range au coffre"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

env = ROOT / "Nokido.env"
target = None
for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
    s = line.strip()
    if "z.ai" in s.lower() and "api_key_id" in s.lower() and "=" in s:
        target = s
        break

if not target:
    print("ligne z.ai introuvable")
    raise SystemExit(1)

# cle = segment apres le DERNIER '=' (le format z.ai 'id.secret' n'a pas de '=')
key = target.rsplit("=", 1)[1].strip()
if key:
    key = key.split()[0]  # drop tout suffixe (commentaire/espace)

print(f"extracted key_len={len(key)} dot={'.' in key} "
      f"looks_zai={('.' in key and 25 < len(key) < 80 and ' ' not in key)}")

from nokido_agent.app.forge_secrets import set_secret, get_secret

set_secret("ZAI_API_KEY", key)
chk = get_secret("ZAI_API_KEY") or ""
print(f"[vault] ZAI_API_KEY corrige (len={len(chk)} match={chk == key}) -- valeur jamais affichee")
