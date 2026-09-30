#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_embed_lot_commun.py - le socle partage des outils de drain BORNE d'embedding.

__FORGE_COLOR__ = "vegetatif/embedding : selection indexee et rapport communs aux mesures de drain"

Deux outils ecrits le 2026-09-06 (`forge_embed_8099_mesure_bornee`, mesure de la RAM du
pilier local ; `forge_embed_cloudflare_lot`, mesure du quota Cloudflare) faisaient la
MEME chose deux fois : choisir des chunks sans vecteur par une requete indexee, refuser
de travailler si le plan balaye la base, et ecrire un rapport JSON avec un verdict. Le
cliquet de duplication de la CI les a designes comme clones -- il avait raison. Ce
module porte la partie commune ; les outils gardent ce qui les distingue (ce qu'ils
mesurent et quand ils s'arretent).

Pourquoi le refus de plan est ICI : c'est la garde qui empeche un outil de mesure de
devenir le 4e balayeur de `%NOKIDO_DATA%\\embeddings.db` (motif paye trois fois : 41 min a 98 % de
CPU pour zero resultat le 2026-09-03). Une garde partagee ne peut pas etre oubliee dans
la copie suivante.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)


class PlanNonIndexe(RuntimeError):
    """Le plan d'execution balaye `rag_chunks` : on refuse, en DISANT le plan lu."""


def candidats_sans_vecteur(conn, n: int, dire=print) -> list[tuple[str, str]]:
    """`n` chunks (id, text) sans vecteur, par la selection indexee du drain reel.

    Meme clause que `forge_embed_auto_trigger.run_pass` (`embedding IS NULL` +
    `hot_tier_clause`), plan VERIFIE avant la premiere lecture. Leve `PlanNonIndexe`
    si le planificateur choisit un balayage : mieux vaut ne pas mesurer que scanner
    24,9 Go pour un echantillon.
    """
    from nokido_agent.tools.forge_tier_policy import hot_tier_clause  # type: ignore

    sql = f"SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND {hot_tier_clause(conn)} LIMIT ?"
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, (n,)))
    dire(f"[plan] {plan}")
    if "SCAN rag_chunks" in plan and "USING" not in plan:
        raise PlanNonIndexe(f"selection NON indexee, refus de balayer la base : {plan}")
    return conn.execute(sql, (n,)).fetchall()


def ouvrir_lecture():
    """Connexion LECTURE SEULE a la base du RAG (une mesure n'ecrit pas par megarde)."""
    import sqlite3

    from nokido_agent.app.forge_db_path import db_path  # type: ignore

    return sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)


def ecrire_rapport(chemin: Path, rapport: dict, verdict: str, raison: str = "",
                   sans: tuple[str, ...] = ()) -> dict:
    """Complete, ecrit et imprime le rapport. `sans` = cles trop volumineuses pour stdout.

    Le fichier garde TOUT (les echantillons servent a refaire le calcul de pente) ;
    stdout n'en montre que le resume, pour qu'un job long reste lisible.
    """
    rapport["verdict"] = verdict
    rapport["raison"] = raison
    rapport["fin"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(rapport, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[verdict] {verdict} {raison}".strip(), flush=True)
    print(json.dumps({k: v for k, v in rapport.items() if k not in sans},
                     indent=1, ensure_ascii=False), flush=True)
    return rapport


def cos(a, b) -> float:
    """Cosinus de deux vecteurs, tronque a la plus courte longueur.

    Remonte ici le 2026-09-06 : deux outils de mesure en portaient une copie et le
    cliquet de duplication les a attrapes. Une primitive partagee par deux mesures
    appartient a la brique commune, pas a chacune d'elles.
    """
    import math

    n = min(len(a), len(b))
    num = sum(a[i] * b[i] for i in range(n))
    da = math.sqrt(sum(x * x for x in a[:n])) or 1e-9
    db = math.sqrt(sum(x * x for x in b[:n])) or 1e-9
    return num / (da * db)


def echantillon_vectorise(n: int, dire=print,
                          lu_max: int = 400) -> list[tuple[str, str, list[float]]]:
    """Chunks DEJA vectorises : (id, texte, vecteur en base). Selection INDEXEE et bornee.

    LECTURE BORNEE PAR ROWID, filtrage en Python. `LENGTH(text) BETWEEN ...` n'est pas
    indexable : le planificateur balayait `rag_chunks` (24,9 Go) pour trouver six lignes.
    Ici on lit un nombre FINI de lignes consecutives et on DIT combien on en a lues --
    une mesure de demonstration n'a aucune raison de parcourir la base.
    """
    import sqlite3
    import struct

    from nokido_agent.app.forge_db_path import db_path  # type: ignore

    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
    try:
        sql = "SELECT id, text, embedding FROM rag_chunks WHERE rowid > ? LIMIT ?"
        plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, (0, 1)))
        dire(f"[plan] {plan}")
        out, lues = [], 0
        for cid, txt, blob in conn.execute(sql, (0, lu_max)):
            lues += 1
            if not blob or len(blob) != 4096 or not txt or not (200 <= len(txt) <= 1200):
                continue
            out.append((cid, txt, list(struct.unpack("1024f", blob))))
            if len(out) >= n:
                break
        dire(f"[lecture] {lues} ligne(s) lues (cap {lu_max}) -> {len(out)} exploitable(s)")
        return out
    finally:
        conn.close()


def chrono(journal: list[dict], nom: str, fn, rss=None):
    """Enveloppe `fn` en notant duree et delta RSS dans `journal`.

    Utilise par le profil d'organe : mesurer une phase ne doit pas etre reecrit a
    chaque phase (c'est ce qui avait fait deux enveloppes jumelles dans le profil
    d'Homeostasis).
    """
    def _rss_defaut() -> float:
        import psutil

        return round(psutil.Process().memory_info().rss / 2**30, 3)

    lire = rss or _rss_defaut

    def _enveloppe(*a, **kw):
        r0, t0 = lire(), time.time()
        try:
            return fn(*a, **kw)
        finally:
            r1 = lire()
            journal.append({"phase": nom, "s": round(time.time() - t0, 2),
                            "rss_avant_go": r0, "rss_apres_go": r1,
                            "delta_go": round(r1 - r0, 3)})

    return _enveloppe
