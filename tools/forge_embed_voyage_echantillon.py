# -*- coding: utf-8 -*-
"""Echantillon VOYAGE sur le froid : mesurer le COUT REEL avant d'engager le quota.

Le trial Voyage est de 200 M tokens et le backlog froid fait ~172 k chunks. On ne
devine pas : on vectorise un petit lot REEL tire du froid, on mesure les tokens
consommes (comptes par l'API elle-meme, pas estimes) et on extrapole.

DEFAUT : `--dry-run` (aucun egress, aucune ecriture) — il mesure seulement la
taille des textes. `--go` autorise l'appel reseau ; `--ecrire` autorise en plus
l'ecriture des vecteurs en base. Les trois sont volontairement separes : envoyer
172 k chunks a un tiers est un acte d'egress, il se decide, il ne se subit pas.

    run action=trusted_script path=tools/forge_embed_voyage_echantillon.py \
        script_args="--n 50 --go"
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _ROOT)

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODELE = "voyage-3"
DIM = 1024
LOT_MAX = 128  # limite dure de l'API Voyage


def _base() -> str:
    """La base qui PORTE rag_chunks — pas le premier fichier qui existe."""
    from nokido_agent.tools.forge_tier_policy import base_rag

    return base_rag()


def _froid(conn: sqlite3.Connection) -> str:
    """Clause du FROID = hors hot-tier. Le drain local ne traite que le chaud."""
    from nokido_agent.tools.forge_tier_policy import hot_tier_clause

    return "NOT (%s)" % hot_tier_clause(conn)


def main() -> int:
    ap = argparse.ArgumentParser(description="Echantillon Voyage sur le backlog froid")
    ap.add_argument("--n", type=int, default=50, help="taille de l'echantillon (defaut 50)")
    ap.add_argument("--go", action="store_true", help="autorise l'appel reseau (egress)")
    ap.add_argument("--ecrire", action="store_true", help="ecrit les vecteurs en base")
    args = ap.parse_args()
    n = max(1, min(args.n, LOT_MAX))

    db = _base()
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
    clause = _froid(conn)
    total_froid = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND %s" % clause).fetchone()[0]
    lignes = conn.execute(
        "SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND %s LIMIT ?" % clause,
        (n,)).fetchall()
    conn.close()

    textes = [(r[1] or "")[:8000] for r in lignes]
    ids = [r[0] for r in lignes]
    car = sum(len(t) for t in textes)
    print("base            : %s" % db)
    print("backlog FROID   : %d chunks" % total_froid)
    print("echantillon     : %d chunks, %d caracteres (moy %.0f car/chunk)"
          % (len(textes), car, car / max(1, len(textes))))

    if not args.go:
        print("\n[dry-run] aucun egress. Estimation grossiere (~4 car/token) :")
        est = car / 4.0
        print("  tokens echantillon ~ %.0f" % est)
        print("  extrapolation %d chunks ~ %.1f M tokens" % (total_froid, est / max(1, len(textes)) * total_froid / 1e6))
        print("  -> relancer avec --go pour la mesure REELLE (l'API compte les tokens)")
        return 0

    from nokido_agent.app.forge_secrets import get_secret

    cle = None
    for cand in ("VOYAGE_API_KEY", "VOYAGE_KEY"):
        try:
            cle = get_secret(cand)
        except Exception:  # noqa: BLE001 - candidat suivant
            cle = None
        if cle:
            break
    if not cle:
        print("AUCUNE cle Voyage lisible au coffre -- abandon")
        return 2

    payload = {"model": MODELE, "input": textes, "output_dimension": DIM}
    req = urllib.request.Request(
        VOYAGE_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % cle})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90.0) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        corps = ""
        try:
            corps = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001 - corps illisible, le code suffit
            pass
        print("HTTP %s : %s" % (e.code, corps))
        return 3
    dt = time.time() - t0

    vecs = [d.get("embedding") for d in (data.get("data") or [])]
    toks = (data.get("usage") or {}).get("total_tokens")
    print("\n=== MESURE REELLE ===")
    print("  vecteurs rendus : %d  (dim=%s)" % (len(vecs), len(vecs[0]) if vecs and vecs[0] else "?"))
    print("  latence         : %.2f s  (%.0f ms/chunk)" % (dt, dt * 1000 / max(1, len(vecs))))
    print("  tokens factures : %s" % toks)
    if toks:
        par = toks / max(1, len(textes))
        total = par * total_froid
        print("  -> %.1f tokens/chunk" % par)
        print("  -> campagne FROIDE complete : %.1f M tokens sur les 200 M du trial (%.1f %%)"
              % (total / 1e6, total / 2e6))
        print("  -> appels necessaires : %d lots de %d" % (
            (total_froid + LOT_MAX - 1) // LOT_MAX, LOT_MAX))

    if not args.ecrire:
        print("\n[lecture seule] vecteurs NON ecrits (relancer avec --ecrire).")
        return 0

    from nokido_agent.app.forge_embed_router import encode_blob

    w = sqlite3.connect(db, timeout=30.0)
    ecrits = 0
    try:
        for cid, vec in zip(ids, vecs):
            if not vec or len(vec) != DIM:
                continue
            w.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (encode_blob(vec), cid))
            ecrits += 1
        w.commit()
    finally:
        w.close()
    print("\n  vecteurs ECRITS : %d" % ecrits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
