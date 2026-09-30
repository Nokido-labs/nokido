# -*- coding: utf-8 -*-
"""forge_docs_chemins_morts.py — une page de doc ne renvoie pas vers du vide.

POURQUOI (mesure 2026-09-17, owner : « le wiki porte des informations fausses ou
des chemins absents desormais »). Sur `docs/wiki/` : **2465 references de chemin
distinctes, 24 MORTES** reparties sur 14 pages. Un lecteur qui suit
`app/forge_jepa.py` depuis `12-AMI-Cognitive-Stack` tombe sur rien.

CE QUI EXISTE DEJA ET N'EST PAS REFAIT ICI :
  - `forge_docs_relink.py --verifier` couvre les LIENS RELATIFS markdown
    (`[x](../y.md)`) — 227 verifies, 0 mort. Autre famille, deja saine.
  - `forge_docs_port_annotate.py` couvre les PORTS arretes cites.
Ce gate couvre la troisieme famille : les CHEMINS DE CODE cites en texte.

⚠️ IL CLASSE, IL NE SE CONTENTE PAS DE DETECTER. Un detecteur binaire crierait
sur `tools/your_tool.py` -- un placeholder pedagogique parfaitement legitime
dans la doc des lanceurs -- et se ferait desarmer au premier agacement. Quatre
etats, mesures sur le corpus reel :

  MORT       le fichier n'existe nulle part        -> a instruire
  DEPLACE    meme nom ailleurs (`tools/x` -> `app/x`, ou migration de
             namespace : `2fd348209` a migre la famille `app`, 2106
             transformations) -> repointer, surtout pas supprimer la mention
  COQUILLE   un voisin au nom presque identique (`sandbox/snn.wante` pour
             `snn.wanted`) -> corriger la frappe
  EXEMPLE    placeholder reconnu (`your_`, `mon_`, `<...>`) -> jamais signale

Sans ce tri, on « corrige » une doc juste en supprimant une mention utile.

Usage :
    LAFORGE_PYTHON tools/forge_docs_chemins_morts.py [--dossier docs] [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Organe declare a la creation (2026-09-17). Le gate `anatomie` est BLOQUANT
# depuis le 2026-09-06 et il m'a arrete des le premier run : un module non
# classe est un module dont personne ne surveille la regulation. Meme organe
# que `forge_docs_relink`, qui verifie l'autre famille de liens.
__FORGE_COLOR__ = "qualite/quality : classe les chemins de code cites par la doc (mort, coquille, deplace, exemple)"

ROOT = Path(__file__).resolve().parent.parent

# Zones du depot qu'une doc peut citer. Hors de cette liste, on ne juge pas :
# un chemin systeme ou un chemin d'exemple n'a pas a etre resolu ici.
ZONES = ("app", "tools", "tests", "config", "docs", "proxy_deno",
         "forge_desktop", "RAG", "sandbox", "scripts", ".github")

_RE_CHEMIN = re.compile(
    r"(?<![\w/.-])((?:%s)/[A-Za-z0-9_./*-]+\.[A-Za-z0-9]{1,5})" % "|".join(ZONES))

# Placeholders PEDAGOGIQUES. Liste volontairement COURTE et issue du corpus
# reel (`tools/your_tool.py`, doc des lanceurs) : inventer des motifs ici
# reviendrait a se rendre aveugle a de vrais chemins morts.
_EXEMPLES = ("your_", "mon_", "ton_", "<", "exemple_", "example_")

# Ou chercher un fichier deplace. `nokido_agent/` : la famille `app` y a ete
# migree (commit 2fd348209, 2106 transformations) -- un chemin `app/x.py` cite
# avant cette migration n'est pas mort, il a bouge.
_ZONES_RECHERCHE = ("app", "tools", "tests", "sandbox", "RAG", "docs",
                    "nokido_agent/app", "nokido_agent/tools")


def _est_exemple(chemin: str) -> bool:
    nom = chemin.rsplit("/", 1)[-1]
    return any(m in nom or chemin.startswith(m) for m in _EXEMPLES)


def classer(chemin: str, racine: Path = None) -> tuple:
    """(etat, precision) pour un chemin cite. N'invente jamais un remede."""
    racine = racine or ROOT
    if "*" in chemin:
        return ("GLOB", "motif, non resolvable")      # ni vivant ni mort
    if (racine / chemin).exists():
        return ("VIVANT", "")
    if _est_exemple(chemin):
        return ("EXEMPLE", "placeholder pedagogique")
    base = chemin.rsplit("/", 1)[-1]
    for z in _ZONES_RECHERCHE:
        if (racine / z / base).exists():
            return ("DEPLACE", "%s/%s" % (z, base))
    dossier = (racine / chemin).parent
    if dossier.exists():
        prefixe = base[:max(4, len(base) - 3)]
        voisins = sorted(f.name for f in dossier.iterdir()
                         if f.name.startswith(prefixe) and f.name != base)
        if voisins:
            return ("COQUILLE", ", ".join(voisins[:3]))
    return ("MORT", "")


def scanner(dossier: Path, racine: Path = None) -> dict:
    racine = racine or ROOT
    par_etat: dict = {}
    pages, illisibles = 0, []
    for p in sorted(dossier.rglob("*.md")):
        try:
            texte = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # ILLISIBLE != PROPRE : une page qu'on n'a pas pu lire ne prouve
            # pas qu'elle est saine. On la compte et on la nomme.
            illisibles.append("%s (%s)" % (p.name, type(exc).__name__))
            continue
        pages += 1
        for chemin in sorted(set(_RE_CHEMIN.findall(texte))):
            etat, precision = classer(chemin, racine)
            if etat in ("VIVANT", "GLOB"):
                continue
            par_etat.setdefault(etat, []).append((p.name, chemin, precision))
    return {"pages": pages, "illisibles": illisibles, "par_etat": par_etat}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossier", default="docs")
    ap.add_argument("--check", action="store_true",
                    help="rc=1 si des chemins MORTS subsistent")
    a = ap.parse_args(argv)

    cible = ROOT / a.dossier
    if not cible.exists():
        print("[chemins] dossier ABSENT : %s — NON MESURE, pas un succes" % cible)
        return 0
    res = scanner(cible)
    ordre = ("MORT", "COQUILLE", "DEPLACE", "EXEMPLE")
    total = sum(len(res["par_etat"].get(e, ())) for e in ordre)
    print("[chemins] %d page(s) lue(s), %d illisible(s), %d reference(s) a instruire"
          % (res["pages"], len(res["illisibles"]), total))
    for nom in res["illisibles"]:
        print("   ILLISIBLE %s" % nom)
    for etat in ordre:
        lot = res["par_etat"].get(etat) or []
        if not lot:
            continue
        print("  -- %s : %d --" % (etat, len(lot)))
        for page, chemin, precision in lot:
            print("     %-34s %-44s %s" % (page, chemin, precision))

    morts = res["par_etat"].get("MORT") or []
    if not morts:
        print("[chemins] aucun chemin MORT — les autres etats sont instruisibles, "
              "pas des pannes.")
        return 0
    print("[chemins] %d chemin(s) MORT(S) : la doc envoie le lecteur vers du vide."
          % len(morts))
    return 1 if a.check else 0


if __name__ == "__main__":
    sys.exit(main())
