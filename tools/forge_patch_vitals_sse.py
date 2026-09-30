#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_patch_vitals_sse.py -- borner le flux SSE des vitaux.

LE DEFAUT (mesure 2026-08-29)
=============================
Le webhub :7400 cesse de repondre apres quelques parcours complets de l'interface.
Signature : LISTENING intact, `/health` qui expire, et les sockets qui s'empilent
en CLOSE_WAIT -- CINQ apres une passe, VINGT ET UN apres trois.

Ce n'est PAS un gel de la boucle asyncio : `forge_loop_sentinel`, armee cote
webhub le meme jour, n'a rien capte pendant que le service etait mort (les seuls
dumps du journal viennent du hub :8766). La boucle tourne ; ce sont les GENERATEURS
qui ne finissent pas.

Pourquoi. `/api/vitals/sse` alimente le fond ambiant du Design System : il s'ouvre
des qu'une page est affichee. Son generateur fait, dans cet ordre :

    v = await asyncio.to_thread(all_vitals)   # 5 a 50 s selon la charge
    yield ...
    await asyncio.sleep(5)
    if await request.is_disconnected(): break

Le test de deconnexion arrive donc APRES le calcul couteux. Un onglet ferme pendant
`to_thread` n'est vu qu'au tour suivant, soit jusqu'a une minute plus tard -- et
`all_vitals` occupe pendant tout ce temps un worker du ThreadPoolExecutor par
defaut, dont la taille est bornee (min(32, cpu+4)). Assez de flux ouverts puis
abandonnes, et le pool est plein : toute requete qui a besoin d'un thread attend,
le service parait muet, et les connexions restent en CLOSE_WAIT faute d'un
generateur qui se termine.

CE QUE LE PATCH FAIT
====================
1. Le test de deconnexion passe EN TETE de boucle, avant le calcul : on n'entre
   plus dans `all_vitals` pour un client deja parti.
2. Un semaphore borne le nombre de flux SIMULTANES (`LAFORGE_VITALS_SSE_MAX`,
   defaut 8). Au-dela, le flux rend un evenement `sature` et se termine
   proprement au lieu de prendre un worker de plus. Une borne qui se DIT vaut
   mieux qu'une saturation qui se decouvre au silence.

POURQUOI UN PATCH ET PAS UN governed_edit
=========================================
`app/web_hub/app.py` est un CRITICAL_FILE ; la derogation `allow_critical` sur un
fichier de cette taille a deja fait tomber le hub (mesure 2026-08-27). Le chemin
sur est un patch git-tracke joue en `trusted_script`. Idempotent : relance sans
effet si deja applique.
"""

from __future__ import annotations

__FORGE_COLOR__ = "interface/flux-vitaux-borne"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_patch_socle as socle  # noqa: E402

CIBLE = ROOT / "app" / "web_hub" / "app.py"

ANCRE = """    async def _gen():
        import sys
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from forge_vitals_tools import all_vitals
        while True:
            try:
"""

AJOUT = '''    import os as _os

    # BORNE DES FLUX SIMULTANES (2026-08-29). Chaque flux occupe un worker du
    # ThreadPoolExecutor par defaut pendant `all_vitals` (5 a 50 s) ; le pool est
    # borne a min(32, cpu+4). Assez de flux ouverts puis abandonnes et il est
    # plein : le service parait muet, LISTENING intact, sockets en CLOSE_WAIT
    # (5 apres une passe de l'UI, 21 apres trois). Une borne qui se DIT vaut mieux
    # qu'une saturation qui se decouvre au silence.
    global _VITALS_SSE_SEM
    try:
        _VITALS_SSE_SEM
    except NameError:
        _VITALS_SSE_SEM = asyncio.Semaphore(
            int(_os.environ.get("LAFORGE_VITALS_SSE_MAX", "8")))

    async def _gen():
        import sys
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from forge_vitals_tools import all_vitals
        if _VITALS_SSE_SEM.locked():
            yield "data: " + _json.dumps({"type": "sature", "max": int(
                _os.environ.get("LAFORGE_VITALS_SSE_MAX", "8"))}) + "\\n\\n"
            return
        async with _VITALS_SSE_SEM:
          while True:
            # EN TETE, avant le calcul. Le test etait APRES `to_thread` : un onglet
            # ferme pendant les 5 a 50 s du calcul n'etait vu qu'au tour suivant,
            # et `all_vitals` tenait un worker tout ce temps POUR PERSONNE.
            if await request.is_disconnected():
                break
            try:
'''


def applique(dry_run: bool = True) -> dict:
    # Le patron (ancre unique, idempotence, controle de syntaxe, secours, trois
    # etats) vit dans forge_patch_socle : le cliquet de duplication a signale --
    # a raison -- que je l'avais recopie depuis forge_patch_lane_auto.
    return socle.appliquer(CIBLE, ANCRE, AJOUT,
                           "BORNE DES FLUX SIMULTANES (2026-08-29)",
                           "avant_vitals_sse", dry_run)


def main() -> int:
    return socle.rapporter(applique(dry_run="--apply" not in sys.argv))


if __name__ == "__main__":
    sys.exit(main())
