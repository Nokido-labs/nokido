#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_rag_coverage_audit.py — P1 archeologie : que porte reellement le RAG ?

Le RAG annonce 1,16 M de chunks. La question archeologique n'est pas « combien »
mais « combien sont ATTEIGNABLES, et par quel chemin ». Trois mecanismes declares
peuvent porter zero sans que rien ne crie :

  - recherche DENSE   : un chunk sans `embedding` est stocke, jamais retrouve en
                        vectoriel. Mesure 2026-08-16 : **169 371 chunks (14,6 %)**,
                        dont des domaines ENTIERS a 100 % (`conv`, `sdk_gitingest`,
                        `mcp_result`) et `nokido_code` a 85 %.
  - dedup par HASH    : la colonne `hash` n'est remplie que sur **23 810 / 1,16 M
                        (2,1 %)**. La deduplication par empreinte ne peut donc pas
                        fonctionner : elle ne voit pas 98 % du corpus.
  - decay TEMPOREL    : il lit `meta.ingested_at` (PAS `created_at`, confusion deja
                        payee le 29/07). Ce champ est rempli sur **99 chunks**.
                        Le vieillissement s'applique a 0,008 % du RAG.

METHODE — deux regles nees d'erreurs de la maison :
  1. La couverture FTS se mesure par JOINTURE, jamais par `COUNT(*)` : `rag_fts`
     contient des FANTOMES (entrees sans chunk correspondant, mesure 2026-08-14).
     Un COUNT brut de 1 186 621 > 1 158 828 chunks "prouverait" une couverture
     de 102 %.
  2. Toute mesure est CHRONOMETREE et bornee. Les jointures sur 1,16 M lignes
     depassent le cap d'appel du hub (120 s) : ce module est fait pour
     `run_job` (detache), pas pour un appel synchrone.

    LAFORGE_PYTHON tools/forge_rag_coverage_audit.py --out rapport.json
    LAFORGE_PYTHON tools/forge_rag_coverage_audit.py --rapide   # sans les jointures
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "RAG", "embeddings.db")


def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def _mesure(con, sql, params=(), label=""):
    """Retourne (valeur, secondes). Une mesure sans son cout n'est pas reproductible."""
    t0 = time.time()
    try:
        v = con.execute(sql, params).fetchone()[0]
    except sqlite3.Error as exc:
        return {"erreur": f"{type(exc).__name__}: {exc}"[:120]}, round(time.time() - t0, 1)
    return v, round(time.time() - t0, 1)


def auditer(rapide: bool = False) -> dict:
    con = _con()
    rap: dict = {"db": DB, "genere_par": "tools/forge_rag_coverage_audit.py", "couts_s": {}}

    total, c = _mesure(con, "SELECT COUNT(*) FROM rag_chunks")
    rap["total_chunks"], rap["couts_s"]["total"] = total, c

    for cle, sql in (
        ("sans_embedding", "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"),
        ("hash_rempli", "SELECT COUNT(*) FROM rag_chunks WHERE hash IS NOT NULL AND hash!=''"),
        ("sources_distinctes", "SELECT COUNT(DISTINCT source) FROM rag_chunks"),
        ("superseded_by_rempli", "SELECT COUNT(*) FROM rag_chunks WHERE superseded_by IS NOT NULL AND superseded_by!=''"),
    ):
        v, c = _mesure(con, sql)
        rap[cle], rap["couts_s"][cle] = v, c

    # decay : le champ REELLEMENT lu est meta.ingested_at (json), pas created_at.
    v, c = _mesure(con, "SELECT COUNT(*) FROM rag_chunks WHERE json_extract(meta,'$.ingested_at') IS NOT NULL")
    rap["decay_champ_lu"] = "meta.ingested_at"
    rap["decay_rempli"], rap["couts_s"]["decay"] = v, c

    t0 = time.time()
    rap["sans_embedding_par_domaine"] = [
        {"domaine": d, "sans_embedding": n}
        for d, n in con.execute(
            "SELECT COALESCE(domain,'(NULL)'), COUNT(*) c FROM rag_chunks "
            "WHERE embedding IS NULL GROUP BY 1 ORDER BY c DESC LIMIT 15")
    ]
    rap["couts_s"]["ventilation"] = round(time.time() - t0, 1)

    if rapide:
        rap["jointures"] = "SAUTEES (--rapide) : ABSENT n'est pas ZERO"
    else:
        # Couverture FTS : par ENSEMBLES, pas par jointure SQL.
        # `rag_fts` est une table FTS5 — `chunk_id` n'y est PAS un index B-tree.
        # Mesure 2026-08-16 : UN lookup `WHERE chunk_id = ?` coute **2,27 s**, donc
        # un `NOT EXISTS` sur 169 371 chunks demanderait ~**107 HEURES**. Le premier
        # jet a tourne 12 minutes sans ecrire une ligne avant que le calcul du cout
        # ne le condamne. Deux scans lineaires + une difference en memoire rendent
        # le meme resultat en quelques secondes.
        t0 = time.time()
        ids_fts = {r[0] for r in con.execute("SELECT chunk_id FROM rag_fts") if r[0]}
        rap["couts_s"]["scan_fts"] = round(time.time() - t0, 1)
        t0 = time.time()
        ids_chunks = set()
        sans_emb_absents = 0
        for cid, emb in con.execute("SELECT id, embedding IS NULL FROM rag_chunks"):
            ids_chunks.add(cid)
            if emb and cid not in ids_fts:
                sans_emb_absents += 1
        rap["sans_embedding_ET_absents_du_fts"] = sans_emb_absents
        rap["fantomes_fts"] = len(ids_fts - ids_chunks)
        # Le chiffre qui compte vraiment : quelle PART du corpus l'index texte
        # couvre-t-il ? `rag_fts` affiche plus de lignes que `rag_chunks` n'a de
        # chunks, ce qui suggere 102 % de couverture. Mesure 2026-08-16 : 39 % de
        # ses identifiants pointent vers des chunks DISPARUS (`beir_*`,
        # `lesson_sol_*`), verifies un par un par cle primaire. La couverture
        # reelle se lit donc a l'INTERSECTION, jamais au volume de l'index.
        inter = len(ids_chunks & ids_fts)
        rap["chunks_dans_fts"] = inter
        rap["couverture_fts_pct"] = round(100.0 * inter / max(len(ids_chunks), 1), 1)
        rap["couts_s"]["scan_chunks"] = round(time.time() - t0, 1)
        v, c = _mesure(con,
            "SELECT COALESCE(SUM(n),0) FROM (SELECT COUNT(*) n FROM rag_chunks "
            "GROUP BY source, text HAVING COUNT(*)>1)")
        rap["lignes_en_doublon_exact"], rap["couts_s"]["doublons"] = v, c

    tot = rap.get("total_chunks") or 1
    if isinstance(tot, int) and tot:
        rap["taux"] = {
            "sans_embedding_pct": round(100.0 * (rap.get("sans_embedding") or 0) / tot, 1),
            "hash_rempli_pct": round(100.0 * (rap.get("hash_rempli") or 0) / tot, 2),
            "decay_rempli_pct": round(100.0 * (rap.get("decay_rempli") or 0) / tot, 4),
        }
    rap["angles_morts"] = [
        "Sans embedding != introuvable : le FTS peut rattraper. C'est la jointure "
        "`sans_embedding_ET_absents_du_fts` qui dit l'invisibilite REELLE.",
        "`rag_fts` porte des fantomes : ne jamais lire sa couverture au COUNT(*).",
        "Le decay lit meta.ingested_at ; created_at n'est PAS la date d'ingestion "
        "(verdict artefactuel deja paye le 2026-07-29).",
    ]
    con.close()
    return rap


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit de couverture du RAG (P1 archeologie)")
    ap.add_argument("--rapide", action="store_true", help="sans les jointures lourdes")
    ap.add_argument("--out", default="", help="ecrire le JSON ici")
    ns = ap.parse_args()
    rap = auditer(rapide=ns.rapide)
    txt = json.dumps(rap, ensure_ascii=False, indent=1)
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"[rag-coverage] ecrit -> {ns.out}")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
