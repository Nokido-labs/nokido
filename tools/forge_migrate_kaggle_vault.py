# -*- coding: utf-8 -*-
"""One-shot : migre KAGGLE_API_TOKEN de Nokido.env vers le coffre DPAPI,
verifie la lecture coffre, PUIS re-commente la ligne du .env (clef en clair
inerte). Appels de fonctions uniquement, AUCUNE valeur affichee.
Miroir du pattern migration OpenRouter 2026-07-04.

Run : run action=trusted_script path=tools/forge_migrate_kaggle_vault.py
(si ACL coffre refuse -> session owner via !)
"""
import sys
from pathlib import Path

# Chemins DERIVES du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
_RACINE = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE))

from nokido_agent.app.forge_secrets import _dotenv
from nokido_agent.app.forge_machine_vault import vault_set, vault_get

key = _dotenv("KAGGLE_API_TOKEN")
if not key:
    print("ABORT: KAGGLE_API_TOKEN absent/commente dans Nokido.env")
    sys.exit(2)

vault_set("KAGGLE_API_TOKEN", key)
back = vault_get("KAGGLE_API_TOKEN")
if back != key:
    print("ABORT: relecture coffre != valeur migree — .env INTACT")
    sys.exit(3)
print(f"coffre: OK (len={len(back)}, valeur non affichee)")

# Re-commente la ligne (octets intacts), idempotent.
# NB: `LaForge.env` est un NOM DE FICHIER reel sur le disque, il n'est pas renomme ici.
envp = _RACINE / "LaForge.env"
raw = envp.read_bytes()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
lines = raw.split(nl)
hits = 0
for i, line in enumerate(lines):
    if line.startswith(b"KAGGLE_API_TOKEN="):
        lines[i] = b"# " + line
        hits += 1
if hits:
    envp.write_bytes(nl.join(lines))
print(f"OK: migration coffre + {hits} ligne(s) re-commentee(s)")
