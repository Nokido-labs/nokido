"""tools/rag_sources_fantomes.py -- desactive les chunks des fichiers de Nokido DISPARUS (A BLANC par defaut).

Mesure du 20/10 (par plage sur idx_rag_source, sans LIKE) : 204 fichiers .py de Nokido indexes n'existent plus
(app/LaForge.py renomme, app/backups/*, anciens agents, tools/ctf...) et leurs 1 886 chunks etaient ACTIFS. Decision
owner (AskUserQuestion) : les desactiver par `forge_rag_truth.retirer_versions_anterieures` -- rien n'est supprime.
Logique dans app/forge_rag_truth.py (`sources_fantomes`, `retirer_sources_fantomes`) ; ici le seul point d'entree.

    LAFORGE_PYTHON tools/rag_sources_fantomes.py                 # a blanc : compte, n'ecrit rien
    LAFORGE_PYTHON tools/rag_sources_fantomes.py --appliquer     # desactive (active=0, superseded_by)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _verite():
    try:
        from nokido_agent.app import forge_rag_truth
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        import forge_rag_truth
    return forge_rag_truth


def main() -> int:
    ap = argparse.ArgumentParser(description="Chunks des fichiers de Nokido disparus : a blanc, ou --appliquer.")
    ap.add_argument("--base", default=None, help="base RAG (defaut : forge_tier_policy.base_rag())")
    ap.add_argument("--racine", default=str(RACINE), help="racine du depot ou se verifie l'existence des fichiers")
    ap.add_argument("--prefixes", nargs="+", default=["app/", "tools/", "tests/", "proxy_deno/"])
    ap.add_argument("--appliquer", action="store_true", help="desactiver (sinon : compter seulement)")
    args = ap.parse_args()

    if args.base:
        base = Path(args.base)
    else:
        import forge_tier_policy
        base = Path(forge_tier_policy.base_rag())
    v = _verite()
    conn = (sqlite3.connect(str(base), timeout=30) if args.appliquer
            else sqlite3.connect("file:%s?mode=ro" % base.as_posix(), uri=True, timeout=30))
    try:
        fantomes = v.sources_fantomes(conn, Path(args.racine), tuple(args.prefixes))
        n = v.retirer_sources_fantomes(conn, fantomes, appliquer=args.appliquer)
        if args.appliquer:
            conn.commit()
    finally:
        conn.close()
    print("[fantomes] %d fichier(s) disparu(s), %d source(s), %d chunk(s) %s"
          % (len(fantomes), sum(len(s) for s in fantomes.values()), n,
             "DESACTIVE(S)" if args.appliquer else "actif(s) -- a blanc, rien d'ecrit (--appliquer pour agir)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
