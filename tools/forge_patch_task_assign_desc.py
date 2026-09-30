"""`task action=assign` perdait l'enonce de la tache : lecture d'une clé absente.

Le schema du tool expose le parametre `task` ; le handler ne lisait QUE
`args.get("description")`. Un appel CONFORME au schema creait donc une tache au
corps vide, sans erreur nulle part — mesure 24-07 : `job_d168f5c8` stocke
`description` de longueur 0, `_relay_to_agy` poste un corps vide, AGY repond
« le message est vide ou absent dans la transmission », et la tache revient
malgre tout `OK_DONE`. Le relais etait hors de cause depuis le debut.

`forge_mcp_registry.py` etant CRITICAL_FILE, `governed_edit` le refuse a juste
titre : le patch passe par `run action=trusted_script`, ou le gate le revoit.

Idempotent. N'ecrit que si le resultat compile. Sauvegarde horodatee a cote.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

ANCRE = '        desc = args.get("description", "")\n'

PATCH = '''        # Le schema du tool expose `task` ; ce handler ne lisait QUE `description`.
        # Un appel CONFORME au schema creait donc une tache au corps VIDE, en
        # silence (mesure 24-07 : job_d168f5c8, description len=0 -> AGY repond
        # « le message est vide ou absent dans la transmission », et la tache
        # revient quand meme OK_DONE). On accepte les trois noms rencontres, en
        # commencant par celui que le schema annonce.
        desc = (args.get("task") or args.get("description") or args.get("message") or "").strip()
'''


def main() -> int:
    if not CIBLE.exists():
        print(f"CIBLE INTROUVABLE: {CIBLE}")
        return 2
    src = CIBLE.read_text(encoding="utf-8")

    if 'args.get("task") or args.get("description")' in src:
        print("DEJA PATCHE — aucune modification (idempotent).")
        return 0
    if ANCRE not in src:
        print("ANCRE ABSENTE — le code a bouge, rien n'est ecrit.")
        return 3

    n = src.count(ANCRE)
    if n != 1:
        print(f"ANCRE AMBIGUE ({n} occurrences) — rien n'est ecrit.")
        return 4

    patched = src.replace(ANCRE, PATCH, 1)
    try:
        compile(patched, str(CIBLE), "exec")
    except SyntaxError as e:
        print(f"SYNTAXE KO apres patch ({e}) — rien n'est ecrit.")
        return 5

    sauvegarde = CIBLE.with_suffix(f".py.bak_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(CIBLE, sauvegarde)
    CIBLE.write_text(patched, encoding="utf-8")
    print(f"PATCH APPLIQUE ({len(src)} -> {len(patched)} octets)")
    print(f"sauvegarde: {sauvegarde.name}")
    print("Redemarrer le hub pour charger le nouveau code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
