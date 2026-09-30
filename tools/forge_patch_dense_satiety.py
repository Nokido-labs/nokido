#!/usr/bin/env python
"""forge_patch_dense_satiety.py — satiete sur la construction du cache dense.

LE MANQUE (avis biomimetique AGY 2026-07-30, mesure le meme jour)
    AGY : « Signal de SATIETE PREVENTIF (feedback negatif) : manquant. Necessaire
    d'introduire un watermark superieur bloquant les nouvelles allocations avant de
    declencher la purge d'urgence. »

    Verifie plutot que suppose : `should_throttle()` rend bien True a 79,2 % de RAM,
    donc les SPAWNS sont freines. Mais `_dense_refresh_bg` n'a AUCUNE garde : le hub
    reconstruit ses ~2,2 Go de matrice dense quelle que soit la pression. Combine a la
    periode refractaire posee le meme jour, cela produit le pire cas : construire a
    90 %, puis interdiction de rendre pendant 120 s.

    Le frein manquait donc la ou le corps se sert LUI-MEME, pas sur les spawns.

LE SEUIL N'EST PAS INVENTE
    On reprend `_SUPERVISOR_SLEEP_RAM_THRESHOLD = 78.0`, deja declare par le corps
    comme le point ou il commence a endormir des services : batir 2,2 Go pendant qu'il
    endort des organes est incoherent. S'y ajoute une marge en Go pour que la
    construction ne soit pas ce qui fait basculer la machine. Inventer un seuil quand
    le systeme en declare un est le motif `seuil_invente` de RULES_SHARED.

    Fail-open : si la mesure RAM est indisponible, on CONSTRUIT (un cache absent
    degrade la recherche en BM25 ; un frein sur mesure aveugle serait pire).

POURQUOI UN SCRIPT
    `app/forge_mcp_registry.py` est CRITICAL_FILE, refuse a `governed_edit`. Script
    committe puis lance en `trusted_script`. Idempotent, verifie ancre et AST, et
    n'ecrit RIEN s'il doute.
"""

from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/autoregulation-ram"

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"

ANCRE = """        def _work():
            try:
                c = self._load_dense_cache()
"""
REMPLACE = '''        def _work():
            try:
                # SATIETE (avis AGY 2026-07-30) : ne pas batir ~2,2 Go de matrice
                # dense quand le corps manque de place. Le seuil vient du corps
                # lui-meme (_SUPERVISOR_SLEEP_RAM_THRESHOLD : le point ou il endort
                # des services), pas d'un chiffre choisi ici. Fail-open : mesure
                # indisponible -> on construit, car un cache absent degrade en BM25
                # alors qu'un frein aveugle bloquerait le RAG sans raison.
                try:
                    import psutil as _ps

                    from forge_resource_manager import (
                        _SUPERVISOR_SLEEP_RAM_THRESHOLD as _SEUIL,
                    )

                    _vm = _ps.virtual_memory()
                    _libre = _vm.available / (1024 ** 3)
                    if _vm.percent >= _SEUIL or _libre < 3.5:
                        logging.getLogger(__name__).warning(
                            "[rag] warm dense REFUSE (satiete) : RAM %.1f%% >= %.1f%% "
                            "ou libre %.2f Go < 3.5 — recherche en BM25, "
                            "reconstruction au prochain cycle",
                            _vm.percent, _SEUIL, _libre,
                        )
                        return
                except Exception as _e:
                    logging.getLogger(__name__).debug(
                        "[rag] satiete non mesurable (%s) — on construit",
                        type(_e).__name__,
                    )
                c = self._load_dense_cache()
'''


def main() -> int:
    if not CIBLE.exists():
        print(f"[patch] cible absente: {CIBLE}")
        return 1
    src = CIBLE.read_text(encoding="utf-8")
    if "warm dense REFUSE (satiete)" in src:
        print("[patch] deja applique — rien a faire (idempotent)")
        return 0
    if ANCRE not in src:
        print("[patch] ANCRE introuvable — ABANDON, rien n'est ecrit")
        return 2
    out = src.replace(ANCRE, REMPLACE, 1)
    try:
        ast.parse(out, filename=str(CIBLE))
    except SyntaxError as e:
        print(f"[patch] AST CASSE apres patch ({e}) — ABANDON, rien n'est ecrit")
        return 3
    CIBLE.write_text(out, encoding="utf-8")
    print(f"[patch] applique: +{len(out) - len(src)} octets, AST OK")
    print("[patch] effet: le hub ne batit plus 2,2 Go de cache dense sous pression ;")
    print("        le frein agit AVANT la purge d'urgence, la ou il manquait.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
