#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_patch_lane_auto.py -- lane DEDUITE quand l'appelant n'en fournit pas.

LE DEFAUT (mesure 2026-08-29)
=============================
`run_job` accepte `lane` en OPTIONNEL. Le controle d'embolie (`check_ressources`)
s'applique bien dans tous les cas -- il a ete cable le 2026-08-02 -- mais
l'ANTI-STACKING, lui, ne s'arme que si l'appelant pense a nommer une lane. Cinq
jobs lourds ont donc ete empiles le meme jour (scan exhaustif, miroir, campagne
UI, deep_explore, checklist), sans lane ni `rss_cap_mb` : RAM saturee, hub tombe.

**Un garde optionnel n'est pas un garde** : c'est une politesse.

CE QU'IL NE FAIT PAS -- le parallelisme reste POSSIBLE
=====================================================
La lane deduite porte le NOM DU FICHIER lance (prefixe `auto:`), jamais une file
unique. Deux lancements du MEME travail s'excluent ; des fichiers DIFFERENTS
restent parallelisables, donc le swarm et le fan-out ne sont pas brides.
« Ne jamais serialiser par prudence » (RULES_SHARED) : on borne l'EMPILEMENT, pas
la concurrence.

POURQUOI UN PATCH ET PAS UN governed_edit
=========================================
`app/forge_mcp_registry.py` est un CRITICAL_FILE : l'edition gouvernee le refuse,
et la derogation `allow_critical` sur un fichier de cette taille a deja fait
tomber le hub (mesure 2026-08-27). Le chemin sur est un patch git-tracke joue en
`trusted_script`. Idempotent : relance sans effet si deja applique.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/admission-lane-par-defaut"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_patch_socle as socle  # noqa: E402

CIBLE = ROOT / "app" / "forge_mcp_registry.py"

ANCRE = '            _lane = args.get("lane")\n            _lane_acq = None\n'

AJOUT = '''            _lane = args.get("lane")
            if not _lane:
                # LANE DEDUITE (2026-08-29). Sans lane, l'anti-stacking ne s'armait
                # PAS : cinq jobs lourds empiles le meme jour ont sature la RAM et
                # fait tomber le hub. Un garde optionnel n'est pas un garde.
                # On ne serialise pour autant RIEN de plus que necessaire : la lane
                # porte le NOM DU FICHIER lance, donc deux lancements du MEME travail
                # s'excluent, tandis que des fichiers DIFFERENTS restent paralleles
                # -- swarm et fan-out intacts. « Ne jamais serialiser par prudence ».
                _src = str(args.get("script") or args.get("path") or "").replace("\\\\", "/")
                _lane = "auto:%s" % (_src.rsplit("/", 1)[-1] or "job")
                if bool(args.get("online", False)):
                    # Meme fichier, AUTRE compte (egress) : pas le meme travail. Vecu le
                    # 2026-09-27 : une mesure lancee online puis offline etait refusee
                    # (« lane occupee ») alors que les deux jobs etaient distincts.
                    _lane += "@online"
            _lane_acq = None
'''


def applique(dry_run: bool = True) -> dict:
    # Patron commun dans forge_patch_socle (ancre unique, idempotence, controle de
    # syntaxe, secours, trois etats) : ce fichier en etait l'original, le patch
    # suivant l'a recopie, et le cliquet de duplication a eu raison de le dire.
    return socle.appliquer(CIBLE, ANCRE, AJOUT, "LANE DEDUITE (2026-08-29)",
                           "avant_lane_auto", dry_run)


def main() -> int:
    return socle.rapporter(applique(dry_run="--apply" not in sys.argv))


if __name__ == "__main__":
    sys.exit(main())
