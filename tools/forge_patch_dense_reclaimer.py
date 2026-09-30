#!/usr/bin/env python
"""forge_patch_dense_reclaimer.py — declare le cache dense comme RAM reclamable.

POURQUOI (mesure 2026-07-30)
    A 86-90 % de RAM, `request_resources` rendait `noop` en manquant 1.07 Go : TOUS
    les gros porteurs etaient legitimement intouchables — llama embed et reranker
    proteges par `is_critical` (piliers du RAG, endormis a tort le 24-07), qdrant
    porteur d'etat. Le corps refusait donc des spawns sans pouvoir liberer quoi que
    ce soit : il n'avait AUCUN levier.

    Or le plus gros bloc reclamable etait le cache dense du hub lui-meme : ~2.3 Go
    de vecteurs float32 dont Qdrant detient la copie sur disque, TTL 30 min. Un
    cache se rend, un organe ne s'ampute pas. `forge_resource_manager` expose
    desormais `register_reclaimer` et appelle les recuperateurs AVANT tout arret.

POURQUOI UN SCRIPT
    `app/forge_mcp_registry.py` est CRITICAL_FILE : `governed_edit` le refuse. Le
    chemin prevu est un script COMMITTE puis lance en `trusted_script` — le
    privilege qualifie la revue du code, pas le compte. Idempotent : re-lancable.
"""

from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/autoregulation-ram"

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"

ANCRE_APPEL = """                if c.get("ids") or getattr(self, "_dense_cache", None) is None:
                    self._dense_cache = c
"""
REMPLACE_APPEL = """                if c.get("ids") or getattr(self, "_dense_cache", None) is None:
                    self._dense_cache = c
                    self._declarer_cache_reclamable()
"""

ANCRE_METHODE = "    def _rag_dense_search(self, topic: str, limit: int, multi: bool = False) -> str:"
METHODE = '''    def _declarer_cache_reclamable(self) -> None:
        """Declare la matrice dense comme RAM RECLAMABLE (mesure 2026-07-30).

        ~2.3 Go de float32 dont Qdrant detient la copie sur disque : le plus gros
        bloc reclamable du corps, et il n'existait aucun levier pour le rendre. A
        86-90 % de RAM l'echelle rendait `noop` en manquant 1.07 Go, tous les gros
        porteurs etant legitimement proteges (piliers du RAG, porteurs d'etat).

        Un cache se rend, un organe ne s'ampute pas : la perte est un cout de
        RECONSTRUCTION, pas de capacite. `_rag_dense_search` leve alors
        « dense cache warming » et `handle_rag` bascule sur BM25 le temps du warm.
        """
        try:
            from forge_resource_manager import register_reclaimer
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "[rag] cache dense NON declare reclamable (%s) — le corps reste "
                "sans levier RAM", type(e).__name__)
            return

        def _rendre_cache_dense() -> float:
            cache = getattr(self, "_dense_cache", None)
            if not cache:
                return 0.0
            try:
                go = float(getattr(cache.get("mat"), "nbytes", 0)) / (1024 ** 3)
            except Exception:  # noqa: BLE001
                go = 0.0
            # Un search en cours garde SA reference locale : le GC ne libere
            # qu'apres son retour, aucune requete n'est cassee en vol.
            self._dense_cache = None
            logging.getLogger(__name__).warning(
                "[rag] cache dense RENDU sous pression RAM (~%.2f Go) — recherche "
                "en BM25 jusqu'au prochain warm", go)
            return go

        register_reclaimer("rag_dense_cache", _rendre_cache_dense)

'''


def main() -> int:
    if not CIBLE.exists():
        print(f"[patch] cible absente: {CIBLE}")
        return 1
    src = CIBLE.read_text(encoding="utf-8")
    if "_declarer_cache_reclamable" in src:
        print("[patch] deja applique — rien a faire (idempotent)")
        return 0
    if ANCRE_APPEL not in src:
        print("[patch] ANCRE D'APPEL introuvable — ABANDON (aucune ecriture)")
        return 2
    if ANCRE_METHODE not in src:
        print("[patch] ANCRE DE METHODE introuvable — ABANDON (aucune ecriture)")
        return 2
    out = src.replace(ANCRE_APPEL, REMPLACE_APPEL, 1)
    out = out.replace(ANCRE_METHODE, METHODE + ANCRE_METHODE, 1)
    try:
        ast.parse(out, filename=str(CIBLE))
    except SyntaxError as e:
        print(f"[patch] AST CASSE apres patch ({e}) — ABANDON, rien n'est ecrit")
        return 3
    CIBLE.write_text(out, encoding="utf-8")
    print(f"[patch] applique: +{len(out) - len(src)} octets, AST OK")
    print("[patch] effet: le cache dense (~2.3 Go) devient reclamable AVANT "
          "tout arret de service")
    return 0


if __name__ == "__main__":
    sys.exit(main())
