"""Purge les sauvegardes laissees par les scripts de patch (`*.py.bak_*`).

Chaque patch d'un CRITICAL_FILE depose une copie horodatee a cote du fichier.
Utile sur le moment, jamais nettoye ensuite : quatre copies de
`forge_mcp_registry.py` (~360 Ko piece) trainaient dans `app/` le 24-07, dont
deux du jour meme. Le compte du bac a sable n'a pas le droit de supprimer dans
`app/` — d'ou le passage par `run action=trusted_script`.

git porte deja l'historique : ces copies sont une ceinture de courte duree, pas
une archive. On garde donc les `GARDE` plus recentes PAR FICHIER (le temps de
constater qu'un patch tient) et on supprime le reste.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZONES = ("app", "tools", "proxy_deno")
GARDE = 2


def main() -> int:
    par_cible: dict[str, list[Path]] = collections.defaultdict(list)
    for zone in ZONES:
        d = ROOT / zone
        if not d.is_dir():
            continue
        for p in d.glob("*.bak_*"):
            par_cible[p.name.split(".bak_")[0]].append(p)

    if not par_cible:
        print("Aucune sauvegarde de patch — rien a faire.")
        return 0

    supprimes = octets = 0
    for cible, fichiers in sorted(par_cible.items()):
        # mtime plutot que le nom : deux formats d'horodatage coexistent
        # (epoch et AAAAMMJJ_HHMMSS), un tri lexical melangerait les deux.
        fichiers.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        gardes, a_purger = fichiers[:GARDE], fichiers[GARDE:]
        print(f"{cible}: {len(fichiers)} sauvegarde(s), {len(gardes)} gardee(s)")
        for p in a_purger:
            taille = p.stat().st_size
            try:
                p.unlink()
            except OSError as e:
                print(f"   REFUS {p.name}: {e}")
                continue
            supprimes += 1
            octets += taille
            print(f"   purge {p.name} ({taille / 1e6:.1f} Mo)")

    print(f"\n{supprimes} fichier(s) supprime(s), {octets / 1e6:.1f} Mo liberes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
