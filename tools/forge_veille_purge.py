#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_veille_purge.py - purge ciblee de chunks du RAG, par PREFIXE de source.

Anti-poison a l'origine (blogs speculatifs) ; desormais utilisable pour retirer
proprement un lot de veille identifie par le prefixe de sa source, par exemple
`github:owner/repo/sous-dossier/`.

TROIS DEFAUTS MESURES LE 2026-09-16, corriges ici. Chacun faisait que cet outil
disait avoir purge sans purger -- la pire des sorties, puisqu'elle rassure.

1. IL VISAIT LA MAUVAISE BASE. `DB = ROOT / "RAG" / "embeddings.db"` etait code
   en dur, alors que la base reelle est resolue par `forge_db_path.db_path()` et
   vaut aujourd'hui `%NOKIDO_DATA%\\embeddings.db`. Mesure : les deux chemins DIFFERENT.
   Un etat partage se lit par son interrupteur, jamais par un chemin fige.

2. IL NE PURGEAIT PAS LE LEXICAL. `DELETE FROM rag_fts WHERE source LIKE ?` :
   `rag_fts` est un FTS5 AUTONOME, il STOCKE `source` mais ne l'interroge pas de
   facon fiable -- et l'echec etait avale par un `try/except` qui imprimait un
   simple warn. Les chunks disparaissaient de `rag_chunks` en restant
   cherchables en BM25 : le lexical devenait un cache perime, ce qu'il ne doit
   JAMAIS etre. On retire donc par `chunk_id`, seule clef que cette table sache
   traiter, et en UNE passe (un `IN (SELECT ...)`), jamais un DELETE par chunk --
   `rag_fts` n'a aucun index sur `chunk_id`, donc un DELETE par chunk balaierait
   la table entiere a chaque fois (incident mesure : 5 documents en ~12 min).

3. IL BALAYAIT 1,3 M LIGNES. `WHERE source LIKE 'prefixe%'` rend
   `SCAN rag_chunks` malgre l'existence de `idx_rag_source` : SQLite n'emprunte
   pas un index pour un LIKE. La meme selection ecrite en PLAGE rend
   `SEARCH rag_chunks USING INDEX idx_rag_source` -- mesure : 8 679 chunks
   comptes en 0,001 s au lieu d'un balayage complet. D'ou `--prefixe`.

CE QUI SE FAIT TOUT SEUL, et qu'il ne faut donc pas refaire : `rag_chunks_fts`
est synchronisee par les triggers `rag_chunks_fts_ad/_ai/_au`, et
`auto_snapshot_before_delete` ARCHIVE chaque ligne supprimee -- la purge est
donc reversible. C'est `rag_fts`, l'autre table, qui n'a aucun trigger.

Usage :
    run action=run_job script=tools/forge_veille_purge.py \\
        script_args="--prefixe github:owner/repo/sous-dossier/ --apply"
DRY-RUN par defaut : sans `--apply`, rien n'est ecrit.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT en tete : le paquet-pont `nokido_agent` vit a la RACINE, pas sous app/.
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_db_path import db_path, open_writer  # noqa: E402

# Purge historique (blogs speculatifs). Conservee pour ne rien perdre, mais elle
# n'est JAMAIS appliquee sans qu'on la demande : `--historique`.
LIKE_PATTERNS = [
    "%medium.com/towards-artificial-intelligence/fable-5%",
    "%knightli.com%claude-fable-5%",
]


def bornes(prefixe: str) -> tuple[str, str]:
    """(bas, haut) d'une comparaison de PLAGE, qui emprunte `idx_rag_source`.

    Equivalent a `LIKE 'prefixe%'`, mais indexable : la borne haute incremente le
    dernier caractere du prefixe.
    """
    if not prefixe:
        raise ValueError("prefixe vide")
    return prefixe, prefixe[:-1] + chr(ord(prefixe[-1]) + 1)


def compter(con, prefixe: str) -> int:
    bas, haut = bornes(prefixe)
    return con.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE source >= ? AND source < ?",
        (bas, haut)).fetchone()[0]


def purger(con, prefixe: str, appliquer: bool) -> dict:
    """Retire un prefixe. L'ORDRE N'EST PAS COMMUTATIF.

    `rag_fts` se purge AVANT `rag_chunks` : son critere est un `chunk_id` qu'on
    lit dans `rag_chunks`. Dans l'autre sens, la sous-requete ne trouverait plus
    rien et le lexical garderait les fantomes en silence.
    """
    bas, haut = bornes(prefixe)
    avant = compter(con, prefixe)
    rapport = {"prefixe": prefixe, "chunks_avant": avant,
               "fts_retires": None, "chunks_apres": None}
    if not appliquer or not avant:
        return rapport

    t0 = time.time()
    cur = con.execute(
        "DELETE FROM rag_fts WHERE chunk_id IN ("
        "  SELECT id FROM rag_chunks WHERE source >= ? AND source < ?)",
        (bas, haut))
    rapport["fts_retires"] = cur.rowcount
    rapport["fts_secondes"] = round(time.time() - t0, 1)

    con.execute("DELETE FROM rag_chunks WHERE source >= ? AND source < ?", (bas, haut))
    rapport["chunks_apres"] = compter(con, prefixe)
    return rapport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Purge ciblee du RAG par prefixe de source.")
    ap.add_argument("--prefixe", action="append", default=[],
                    help="prefixe de source (repetable), ex: github:owner/repo/dir/")
    ap.add_argument("--historique", action="store_true",
                    help="applique aussi les LIKE_PATTERNS historiques (BALAYAGE)")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut: dry-run)")
    a = ap.parse_args(argv)

    if not a.prefixe and not a.historique:
        print("[purge] rien a faire : ni --prefixe ni --historique")
        return 2

    cible = db_path()
    print("[purge] base VISEE :", cible)
    con = open_writer()
    try:
        total = 0
        for pref in a.prefixe:
            r = purger(con, pref, a.apply)
            total += r["chunks_avant"]
            if not a.apply:
                print("[dry-run] %-46s %6d chunk(s) cible(s)" % (pref, r["chunks_avant"]))
            else:
                print("[purge  ] %-46s %6d -> %s | rag_fts: %s ligne(s) en %ss"
                      % (pref, r["chunks_avant"], r["chunks_apres"],
                         r["fts_retires"], r.get("fts_secondes")))
                # Un retrait qui laisse des restes doit le DIRE, pas se taire.
                if r["chunks_apres"]:
                    print("   [reste] %d chunk(s) NON retires : a instruire"
                          % r["chunks_apres"])
        if a.historique:
            for pat in LIKE_PATTERNS:
                rows = con.execute(
                    "SELECT id FROM rag_chunks WHERE source LIKE ?", (pat,)).fetchall()
                print("[historique] %s -> %d (BALAYAGE : LIKE n'emprunte aucun index)"
                      % (pat, len(rows)))
                total += len(rows)
                if a.apply and rows:
                    ids = [i for (i,) in rows]
                    marques = ",".join("?" * len(ids))
                    con.execute(
                        "DELETE FROM rag_fts WHERE chunk_id IN (%s)" % marques, ids)
                    con.execute("DELETE FROM rag_chunks WHERE source LIKE ?", (pat,))
        if a.apply:
            print("[ok] purge appliquee : %d chunk(s). rag_chunks_fts suit par trigger ; "
                  "auto_snapshot_before_delete a archive les lignes, le retrait est "
                  "reversible." % total)
        else:
            print("[dry-run] %d chunk(s) cible(s). Relancer avec --apply." % total)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
