#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Migre un secret de Nokido.env vers le vault DPAPI sous un nom PROPRE.

Cas d'usage : une clé collée avec un nom malformé (espaces/URL) dans .env ->
la relire et la stocker sous un nom canonique au vault. La VALEUR ne sort JAMAIS
(ni stdout ni contexte) : on n'imprime que la longueur + un bool de cohérence.

Usage: trusted_script path=tools/forge_migrate_env_secret.py
       script_args="'<nom source dans .env>' <NOM_CIBLE_VAULT>"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if len(sys.argv) < 3:
    print("usage: forge_migrate_env_secret.py '<source_name>' <TARGET_NAME> [--commentee]")
    raise SystemExit(2)

src, tgt = sys.argv[1], sys.argv[2]
# LIGNE COMMENTEE : jamais par defaut. Dans ce fichier, un `#` devant une clef signifie
# le plus souvent « perimee, remplacee, ou migree ailleurs » -- la lire sans le vouloir
# ressusciterait un secret mort et ferait diagnostiquer un `401` pendant des heures.
# Le drapeau rend l'intention EXPLICITE, et la provenance est imprimee.
commentee_ok = "--commentee" in sys.argv[3:]
env = ROOT / "Nokido.env"

val, provenance = None, ""
for num, line in enumerate(env.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
    s = line.strip()
    est_commentee = s.startswith("#")
    if est_commentee:
        if not commentee_ok:
            continue
        s = s.lstrip("#").strip()
    if "=" not in s:
        continue
    name, _, v = s.partition("=")
    if name.strip() == src and v.strip():
        val = v.strip()
        provenance = f"ligne {num}" + (" (COMMENTEE -- lue sur demande explicite)"
                                       if est_commentee else "")
        break

if not val:
    print(f"source '{src}' introuvable dans Nokido.env"
          + ("" if commentee_ok else " (lignes commentees ignorees : ajouter --commentee)"))
    raise SystemExit(1)
print(f"[source] {src} <- {provenance}, longueur {len(val)} (valeur jamais affichee)")

from nokido_agent.app.forge_secrets import set_secret, get_secret

set_secret(tgt, val)
chk = get_secret(tgt) or ""
print(f"[vault] {tgt} stocke (len={len(chk)} match={chk == val}) -- valeur jamais affichee")
