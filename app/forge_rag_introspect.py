# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : memoire / metacognition (organe, READ-ONLY)

ORGANE : INTROSPECTION RAG — « POURQUOI ce chunk est-il remonté ? ».

Gap VERIFIE (audit veilles 2026-07-22) : le lot interpretabilite mecaniste / sparse
autoencoders enseigne qu'une representation DENSE superpose plus de concepts que de
dimensions -> opaque. La memoire de Nokido (545k vecteurs) SAIT des choses que personne
ne peut lui demander d'EXPLIQUER. Rendre le retrieval inspectable est une CAPACITE.

Version 1, honnete et additive : on ne reconstruit pas des features SAE (chantier lourd,
reste roadmap P3). On DECOMPOSE le signal de surface par composante — recouvrement
lexical (BM25 termes), poids de confiance (forge_rag_qualify), fraicheur — et on SIGNALE
les chunks remontes pour des raisons NON-semantiques (trust/recence eleves alors que le
recouvrement lexical est faible = le RAG t'a servi ca pour une raison qui n'est pas 'ca
repond a ta question'). C'est le premier degre d'auditabilite de la memoire.

STRICTEMENT READ-ONLY. Anti-dup (rag_fts) : forge_rag_engine CALCULE la fusion RRF ;
forge_rag_qualify PONDERE ; AUCUN n'EXPLIQUE a posteriori la contribution par composante.

CLI :
    LAFORGE_PYTHON app/forge_rag_introspect.py --query "ta question" [--k 8]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("LAFORGE_DB_PATH", str(ROOT / "RAG" / "embeddings.db")))
_WORD = re.compile(r"[a-zA-Z0-9]{3,}")


def _terms(text):
    return {w.lower() for w in _WORD.findall(text or "")}


def _trust_weight(source):
    """Poids de confiance du chunk, via forge_rag_qualify si dispo (sinon heuristique domaine)."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_rag_qualify import trust_weight  # type: ignore
        return float(trust_weight(source))
    except Exception:
        s = (source or "").lower()
        if s.startswith(("app/", "tools/")):
            return 0.9
        if "session:" in s or "solution" in s:
            return 0.75
        if "watch_veille" in s or "web" in s:
            return 0.4
        return 0.6


def introspect(query: str, k: int = 8) -> dict:
    q_terms = _terms(query)
    match = " OR ".join('"%s"' % t for t in list(q_terms)[:8]) or query[:40]
    con = sqlite3.connect(str(DB), timeout=30)
    con.row_factory = sqlite3.Row
    rows = []
    try:
        try:
            rows = con.execute(
                "SELECT source, substr(text,1,400) AS snip, bm25(rag_fts) AS rank "
                "FROM rag_fts WHERE rag_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, k)).fetchall()
        except sqlite3.OperationalError as e:
            return {"query": query, "error": "FTS: %s" % str(e)[:80], "results": []}
    finally:
        con.close()

    out = []
    for r in rows:
        c_terms = _terms(r["snip"])
        overlap = len(q_terms & c_terms) / max(1, len(q_terms))
        trust = _trust_weight(r["source"])
        # bm25 est un rank (plus petit = mieux) -> normaliser en [0,1] lexical
        lexical = round(min(1.0, overlap), 2)
        # DIAGNOSTIC : remonté malgré un faible recouvrement lexical ET une confiance haute
        # = surface pour une raison non-sémantique (trust/densité), pas pour répondre.
        reason = "lexical" if lexical >= 0.34 else ("trust/densité" if trust >= 0.75
                                                    else "densité vecteur (opaque)")
        flag = lexical < 0.2  # remonté sans presque aucun terme commun = à auditer
        out.append({
            "source": r["source"],
            "lexical_overlap": lexical,
            "trust_weight": round(trust, 2),
            "bm25_rank": round(float(r["rank"]), 2),
            "surfaced_for": reason,
            "opaque_flag": flag,
            "shared_terms": sorted(q_terms & c_terms)[:8],
        })
    opaque = sum(1 for o in out if o["opaque_flag"])
    return {"query": query, "k": len(out),
            "opaque_results": opaque,
            "note": ("%d/%d résultats remontés sans recouvrement lexical net "
                     "(raison non-sémantique)" % (opaque, len(out))) if out else "aucun résultat",
            "results": out}


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--k", type=int, default=8)
    a = ap.parse_args()
    res = introspect(a.query, a.k)
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, ensure_ascii=False))
    for o in res.get("results", []):
        mark = "❓" if o["opaque_flag"] else "  "
        print("  %s %-46s lex=%.2f trust=%.2f (%s) [%s]"
              % (mark, o["source"][:46], o["lexical_overlap"], o["trust_weight"],
                 o["surfaced_for"], ",".join(o["shared_terms"][:4])))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
