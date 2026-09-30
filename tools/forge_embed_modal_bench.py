# -*- coding: utf-8 -*-
"""Bench de l'endpoint Modal sur des chunks FROIDS reels.

But : un chiffre de debit mesure (chunks/s) pour dimensionner la campagne des
~172 k chunks sans vecteur, au lieu de l'extrapoler d'un ping a 2 textes.

Le premier lot paie le COLD START du conteneur GPU (~3 s mesures) ; les suivants
donnent le regime etabli. On rapporte les deux separement : moyenner les deux
donnerait un debit qui ne decrit aucun des deux regimes.

Lecture seule par defaut. `--ecrire` persiste les vecteurs obtenus.

    run action=trusted_script path=tools/forge_embed_modal_bench.py \
        --script_args="--lots 3 --taille 64"
"""
import argparse
import os
import sqlite3
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _ROOT)

DIM = 1024


def main() -> int:
    ap = argparse.ArgumentParser(description="Bench debit Modal sur le froid")
    ap.add_argument("--lots", type=int, default=3)
    ap.add_argument("--taille", type=int, default=64)
    ap.add_argument("--ecrire", action="store_true")
    args = ap.parse_args()

    from nokido_agent.app.forge_embed_router import _modal_call, _modal_url, encode_blob
    from nokido_agent.tools.forge_tier_policy import base_rag, hot_tier_clause

    if not _modal_url():
        print("LAFORGE_MODAL_EMBED_URL introuvable (coffre + env) -- abandon")
        return 2

    db = base_rag()
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
    clause = "NOT (%s)" % hot_tier_clause(conn)
    total = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND %s" % clause).fetchone()[0]
    besoin = args.lots * args.taille
    lignes = conn.execute(
        "SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND %s LIMIT ?" % clause,
        (besoin,)).fetchall()
    conn.close()
    print("backlog FROID : %d chunks" % total)
    print("bench         : %d lots x %d = %d chunks\n" % (args.lots, args.taille, len(lignes)))

    resultats, a_ecrire = [], []
    for i in range(0, len(lignes), args.taille):
        lot = lignes[i:i + args.taille]
        textes = [(r[1] or "")[:8000] for r in lot]
        t0 = time.time()
        vecs = _modal_call(textes, timeout=120.0)
        dt = time.time() - t0
        ok = bool(vecs) and len(vecs) == len(textes)
        deb = (len(textes) / dt) if dt > 0 else 0.0
        resultats.append((ok, dt, deb, len(textes)))
        print("  lot %d : %s  %.2f s  %.1f chunks/s%s"
              % (i // args.taille + 1, "OK " if ok else "KO ", dt, deb,
                 "  (cold start)" if i == 0 else ""))
        if ok and args.ecrire:
            a_ecrire.extend((r[0], v) for r, v in zip(lot, vecs) if v and len(v) == DIM)

    bons = [r for r in resultats if r[0]]
    if not bons:
        print("\naucun lot abouti -- rien a extrapoler")
        return 3
    etabli = bons[1:] or bons          # hors cold start si possible
    debit = sum(r[3] for r in etabli) / max(1e-9, sum(r[1] for r in etabli))
    print("\n=== REGIME ETABLI ===")
    print("  debit        : %.1f chunks/s" % debit)
    reste = total
    print("  campagne %d chunks : %.1f min (%.2f h)" % (reste, reste / debit / 60, reste / debit / 3600))

    if a_ecrire:
        w = sqlite3.connect(db, timeout=30.0)
        try:
            for cid, vec in a_ecrire:
                w.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (encode_blob(vec), cid))
            w.commit()
        finally:
            w.close()
        print("\n  vecteurs ECRITS : %d" % len(a_ecrire))
    elif args.ecrire:
        print("\n  rien a ecrire")
    return 0


if __name__ == "__main__":
    sys.exit(main())
