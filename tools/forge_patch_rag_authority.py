"""Porte l'autorite de source dans le moteur REELLEMENT utilise par le tool `rag`.

`forge_mcp_registry._rag_dense_search` refait sa propre recherche hybride (dense
:8099 + BM25 FTS5, union, rerank :8100) — elle n'emprunte PAS `RAGEngine.search()`.
Les correctifs poses cote `forge_rag_engine` sont donc restes sans effet sur le tool.
Ce fichier etant CRITICAL_FILE, `governed_edit` le refuse a juste titre : le patch
passe par `run action=trusted_script`, ou le gate le revoit.

Deux modifications, idempotentes :
  1. ecarter `session:auto_*` (tool_calls indexes VERBATIM, requete comprise) du jeu
     de candidats, AVANT le rerank ;
  2. ponderer le tri post-rerank par l'autorite de la source.

Le fichier n'est ecrit que si le resultat compile. Sauvegarde horodatee a cote.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

ANCRE_FILTRE = """        cand = cand[:80]
        try:
            docs = [(meta[ids[i]]["text"] or "")[:512] for i in cand]
"""

PATCH_FILTRE = '''        # TRACE BRUTE hors du canal de connaissance. `session:auto_*` indexe les
        # tool_calls VERBATIM, requete comprise : la recherche retrouvait en tete
        # l'appel d'outil ou la question figurait mot pour mot — le RAG rendait son
        # propre echo. Sa pertinence lexicale est maximale par construction, donc
        # aucun prior d'autorite ne la renverse ; il faut l'ecarter des candidats.
        # Filtre AVANT le rerank : autant ne pas payer le cross-encoder pour ca.
        cand = [i for i in cand if not str(meta[ids[i]].get("source") or "").startswith("session:auto_")]
        cand = cand[:80]
        try:
            docs = [(meta[ids[i]]["text"] or "")[:512] for i in cand]
'''

ANCRE_TRI = """            if res and len(res) == len(cand):
                res = sorted(res, key=lambda x: -x.get("relevance_score", 0.0))
                cand = [cand[x["index"]] for x in res]
                mode += "+rerank"
"""

PATCH_TRI = '''            if res and len(res) == len(cand):
                # AUTORITE DE LA SOURCE. Le cross-encoder ne repond qu'a « est-ce
                # pertinent ? », jamais a « qui parle ? » : 504k chunks de docsets
                # tiers contre 99 de doctrine souveraine, il n'a aucun moyen de
                # savoir lesquels font foi sur Nokido. Ponderation DELIBEREMENT
                # moderee (x1.0 doctrine, x0.78 docset) : elle departage a
                # pertinence comparable, elle n'ecrase pas un tiers tres pertinent.
                try:
                    from forge_rag_qualify import trust_weight as _tw
                except Exception:  # noqa: BLE001 - jamais degrader la recherche
                    def _tw(_s):
                        return 0.5

                def _autorite(x):
                    src = meta[ids[cand[x["index"]]]].get("source") or ""
                    return x.get("relevance_score", 0.0) * (0.6 + 0.4 * _tw(src))

                res = sorted(res, key=lambda x: -_autorite(x))
                cand = [cand[x["index"]] for x in res]
                mode += "+rerank+autorite"
'''


def main() -> int:
    if not CIBLE.exists():
        print(f"CIBLE INTROUVABLE: {CIBLE}")
        return 2
    src = CIBLE.read_text(encoding="utf-8")
    deja = 'mode += "+rerank+autorite"' in src
    if deja:
        print("DEJA PATCHE — aucune modification (idempotent).")
        return 0

    manquantes = [n for n, a in (("filtre", ANCRE_FILTRE), ("tri", ANCRE_TRI)) if a not in src]
    if manquantes:
        # Une ancre absente = le code a bouge. Ne PAS deviner sur un CRITICAL_FILE.
        print(f"ANCRE(S) ABSENTE(S): {manquantes} — abandon, rien n'est ecrit.")
        return 3

    patched = src.replace(ANCRE_FILTRE, PATCH_FILTRE, 1).replace(ANCRE_TRI, PATCH_TRI, 1)
    if patched == src:
        print("REMPLACEMENT SANS EFFET — abandon.")
        return 4

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
