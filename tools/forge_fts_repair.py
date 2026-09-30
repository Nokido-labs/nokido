#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reparation de l'index lexical du moteur (`rag_chunks_fts`) — a lancer DEPORTE.

Pourquoi un outil et pas un appel direct : un rebuild FTS5 sur 700k+ lignes depasse le
cap d'un appel hub, et un rebuild inline dans l'event-loop du hub a deja provoque un
wedge de plus de 120 s (2026-06-16). Il se lance donc par `run_job`.

Ce qu'il repare, mesure le 2026-07-30 : 214 entrees de l'index designaient des lignes
DISPARUES de `rag_chunks`, si bien que toute recherche les touchant echouait par
`fts5: missing row N from content table`. Cause de la derive : le seul chemin de
reconstruction etait DEAD CODE — `forge_mcp_registry` importait `rebuild_fts_index`
depuis `forge_self_correction`, ou la fonction n'existait pas, et l'ImportError etait
avale par un `except: pass`. L'option `rebuild` n'a donc jamais rien reconstruit.

Precaution NON negociable : ne PAS reconstruire pendant une ingestion. Le 2026-07-25
une resynchronisation FTS lancee pendant un backfill a fait echouer des ecritures
(`database is locked`) et PERDU une source. On refuse donc de partir si une ingestion
ecrit, et on le DIT au lieu de passer outre.

Usage :
    POST /admin/run_job  script=tools/forge_fts_repair.py
    LAFORGE_PYTHON tools/forge_fts_repair.py --forcer   # ignore la garde d'ingestion
"""

from __future__ import annotations

__FORGE_COLOR__ = "memoire/reparation-lexicale"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# Motifs de process qui ECRIVENT dans la base : reconstruire pendant leur travail fait
# perdre leurs ecritures.
ECRIVAINS = ("veille_run", "curriculum_ingest", "embed_backfill", "clone_ingest",
             "embed_auto_trigger", "gitingest", "forge_hot_ingest")


def ingestion_active() -> list[str]:
    """Qui ecrit en ce moment. Liste vide = personne, ou cmdline illisible (angle mort)."""
    try:
        import psutil
    except Exception:
        return ["psutil indisponible — impossible de verifier, garde INEFFICACE"]
    vus = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue  # cmdline d'un autre compte : angle mort connu, 331/339 process
        for k in ECRIVAINS:
            if k in cl:
                vus.append("%s(pid %s)" % (k, p.info["pid"]))
    return vus


# Pattern OFFICIEL FTS5 a contenu externe : sans ces trois declencheurs, l'index
# NE PEUT PAS suivre sa table source -- il derive par construction.
#
# POURQUOI ILS MANQUAIENT (mesure 2026-09-01). `rag_chunks` portait DEJA cinq
# triggers : deux snapshots, un garde de palier, et surtout DEUX pour la file de
# synchronisation Qdrant (`qdrant_sync_on_embed_insert` / `_on_embed_update`).
# Le canal VECTORIEL etait donc tenu a jour automatiquement, et le canal LEXICAL
# laisse a des ecritures manuelles dispersees (13 sites dans 9 modules pour
# `rag_fts`, zero pour `rag_chunks_fts`). D'ou 702 180 chunks manquants dans
# l'index que lit `forge_rag_engine._lexical()` : le lexical etait traite comme
# un substitut du vectoriel, pas comme un moteur de memoire a part entiere.
#
# LE `OF text, source, domain` N'EST PAS COSMETIQUE. Un `AFTER UPDATE` nu se
# declencherait a CHAQUE ecriture d'embedding -- or la vectorisation ne fait que
# cela, par millions -- et reindexerait le document pour une colonne que l'index
# ne contient meme pas. On ne reagit qu'aux colonnes reellement indexees.
#
# LE QUATRIEME DECLENCHEUR (`_bi`) N'EST PAS UNE PRECAUTION, C'EST UN CORRECTIF PAYE.
# Les trois declencheurs officiels ont ete poses en production le 2026-09-01 a 18:07 ;
# vingt minutes plus tard la base rendait un ecart NEGATIF (index 2 030 596 pour
# 2 030 595 lignes, sur un snapshot coherent). Cause : le DELETE implicite d'un
# `INSERT OR REPLACE` NE DECLENCHE PAS les triggers DELETE, sauf
# `PRAGMA recursive_triggers = ON` -- OFF par defaut, et reglable seulement PAR
# CONNEXION, donc ingarantissable : `INSERT OR REPLACE INTO rag_chunks` est ecrit sur
# 17 sites actifs. Chaque remplacement laissait donc l'ancienne version indexee.
# Et un FANTOME est pire qu'un manquant : il fausse les frequences documentaires de
# BM25, donc le classement de TOUTES les recherches (501 255 entrees mortes mesurees
# en juillet, 27 % de l'index). `_bi` purge l'entree de la ligne de meme `id` AVANT
# l'insertion, quel que soit le verbe employe par l'ecrivain.
_TRIGGERS = {
    "rag_chunks_fts_bi": (
        "CREATE TRIGGER rag_chunks_fts_bi BEFORE INSERT ON rag_chunks BEGIN\n"
        "  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)\n"
        "  SELECT 'delete', rowid, text, source, domain FROM rag_chunks\n"
        "  WHERE id = new.id;\n"
        "END"),
    "rag_chunks_fts_ai": (
        "CREATE TRIGGER rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN\n"
        "  INSERT INTO rag_chunks_fts(rowid, text, source, domain)\n"
        "  VALUES (new.rowid, new.text, new.source, new.domain);\n"
        "END"),
    "rag_chunks_fts_ad": (
        "CREATE TRIGGER rag_chunks_fts_ad AFTER DELETE ON rag_chunks BEGIN\n"
        "  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)\n"
        "  VALUES ('delete', old.rowid, old.text, old.source, old.domain);\n"
        "END"),
    "rag_chunks_fts_au": (
        "CREATE TRIGGER rag_chunks_fts_au AFTER UPDATE OF text, source, domain\n"
        "ON rag_chunks BEGIN\n"
        "  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)\n"
        "  VALUES ('delete', old.rowid, old.text, old.source, old.domain);\n"
        "  INSERT INTO rag_chunks_fts(rowid, text, source, domain)\n"
        "  VALUES (new.rowid, new.text, new.source, new.domain);\n"
        "END"),
}


def triggers_etat(conn=None) -> dict:
    """Quels declencheurs de synchronisation lexicale sont POSES."""
    import sqlite3

    from nokido_agent.app.forge_db_path import db_path

    propre = conn is None
    if propre:
        conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=20)
    try:
        poses = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'rag_chunks_fts_%'")}
    finally:
        if propre:
            conn.close()
    return {"poses": sorted(poses), "manquants": sorted(set(_TRIGGERS) - poses),
            "synchronise": not (set(_TRIGGERS) - poses)}


def poser_triggers(retirer: bool = False) -> dict:
    """Pose (ou retire) les declencheurs. Idempotent, et REVERSIBLE par `retirer`.

    Ne touche a AUCUNE donnee : uniquement au schema. Un `DROP TRIGGER` remet
    exactement l'etat d'avant -- c'est ce qui rend ce geste sur.
    """
    from nokido_agent.app.forge_db_path import write_retry

    avant = triggers_etat()

    def _op(cx):
        faits = []
        for nom, ddl in _TRIGGERS.items():
            if retirer:
                cx.execute(f"DROP TRIGGER IF EXISTS {nom}")
                faits.append("drop:" + nom)
            elif nom in avant["manquants"]:
                cx.execute(ddl)
                faits.append("create:" + nom)
        return faits

    faits = write_retry(_op)
    return {"ok": True, "action": "retire" if retirer else "pose",
            "faits": faits, "avant": avant, "apres": triggers_etat()}


def _ecart_moteur(conn) -> tuple:
    """(lignes source, lignes indexees) pour `rag_chunks_fts`."""
    return (conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0],
            conn.execute("SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0])


def rattraper_incremental(taille_lot: int = 20_000, budget_s: float = 900.0,
                          dry_run: bool = False, journal=print) -> dict:
    """Complete `rag_chunks_fts` par LOTS, sans jamais prendre de verrou long.

    POURQUOI cette voie plutot que le rebuild (mesure 2026-09-01, demande owner
    « les veilles doivent etre servies en lexical en attendant la vectorisation »).

    Le rebuild complet est correct, mais il exige un verrou d'ecriture PROLONGE :
    lance de jour, il est reste bloque 6 minutes a 0,9 s de CPU pendant qu'un autre
    ecrivain tenait la base (WAL a 982 Mo). C'est precisement pour cela qu'il n'est
    arme qu'en phase NREM3. Seulement NREM3 n'avait pas tire depuis 3,4 jours, et
    l'ecart avait atteint 702 180 chunks sur 2 030 594 : le moteur
    (`forge_rag_engine._lexical()`) ignorait donc TOUTE la veille non vectorisee.
    Sans vecteur et sans entree lexicale, ces chunks n'etaient atteignables par
    aucun des deux etages de la recherche hybride.

    Ce rattrapage NE REMPLACE PAS le rebuild : lui seul purge les entrees ORPHELINES
    (un `DELETE` ne le peut pas, le texte d'origine est perdu). Celui-ci n'ajoute que
    les MANQUANTS -- les deux index derivent en sens opposes, c'est documente.

    Trois gardes, chacune pour une raison payee :
      * transaction COURTE par plage de rowid, on rend la main entre les lots ;
      * `ingestion_active()` RE-CONSULTEE entre chaque lot, pas une seule fois au
        depart : une ingestion qui demarre en cours de route doit nous arreter
        (une source a ete perdue ainsi le 2026-07-25) ;
      * `write_retry` sur chaque lot : un verrou tenu par un voisin fait ATTENDRE,
        il ne doit pas faire perdre le lot.
    """
    import sqlite3
    import time

    from nokido_agent.app.forge_db_path import db_path, open_writer, write_retry

    debut = time.time()
    conn = open_writer()
    try:
        src0, idx0 = _ecart_moteur(conn)
        lo, hi = conn.execute("SELECT min(rowid), max(rowid) FROM rag_chunks").fetchone()
        journal("[fts-inc] source %d | indexe %d | manquants %d | rowid %d..%d"
                % (src0, idx0, src0 - idx0, lo, hi))

        borne, inseres, lots, arret = (lo or 1) - 1, 0, 0, "termine"
        while borne < hi:
            if time.time() - debut > budget_s:
                arret = "budget de temps atteint (%.0f s)" % budget_s
                break
            actifs = ingestion_active()
            if actifs:
                arret = "ingestion demarree : " + ", ".join(actifs[:3])
                break
            fin = min(borne + taille_lot, hi)
            sql_where = ("FROM rag_chunks c WHERE c.rowid > ? AND c.rowid <= ? "
                         "AND NOT EXISTS (SELECT 1 FROM rag_chunks_fts_docsize d "
                         "WHERE d.id = c.rowid)")
            if dry_run:
                n = conn.execute("SELECT count(*) " + sql_where, (borne, fin)).fetchone()[0]
            else:
                # `write_retry` fournit LUI-MEME la connexion (`op(conn)`) et la
                # renouvelle a chaque tentative : l'operation doit donc l'accepter en
                # premier argument. La lier a la connexion de lecture ci-dessus ferait
                # perdre le benefice de la reprise -- et le test NR l'a attrape.
                def _op(cx, _a=borne, _b=fin, _w=sql_where):
                    return cx.execute(
                        "INSERT INTO rag_chunks_fts(rowid, text, source, domain) "
                        "SELECT c.rowid, c.text, c.source, c.domain " + _w,
                        (_a, _b)).rowcount
                n = write_retry(_op)
            inseres += max(int(n or 0), 0)
            lots += 1
            borne = fin
            if lots % 20 == 0:
                journal("[fts-inc] lot %d | rowid <= %d | cumul %d" % (lots, borne, inseres))

        src1, idx1 = _ecart_moteur(conn)
    finally:
        conn.close()

    ecart = src1 - idx1
    return {
        "ok": True, "dry_run": dry_run, "lots": lots, "inseres": inseres,
        "arret": arret, "duree_s": round(time.time() - debut, 1),
        "ecart_avant": src0 - idx0, "ecart_apres": ecart,
        # Le verdict ne se lit PAS sur l'absence d'erreur : un rattrapage qui laisse
        # l'ecart intact a echoue sans le dire. Il ne se lit pas non plus sur un SEUIL
        # absolu : la premiere version reprenait les 20 000 du circadien et declarait
        # donc RESORBE apres un arret qui laissait des manquants -- le seuil du
        # circadien dit quand DECLENCHER, jamais si on a REUSSI (test NR a l'appui).
        "verdict": ("DRY_RUN" if dry_run
                    else "RESORBE" if ecart == 0
                    else "PARTIEL" if ecart < (src0 - idx0) else "SANS EFFET"),
        "db": db_path() if not dry_run else None,
    }


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Reconstruit un index FTS5 du RAG (rag_fts par defaut).")
    ap.add_argument("--forcer", action="store_true",
                    help="reconstruire meme si une ingestion ecrit (deconseille)")
    # Le 2026-08-14, `rebuild_fts_index` etait defini DEUX fois dans
    # forge_self_correction : la seconde ecrasait la premiere depuis le 30/07 et
    # visait une AUTRE table. Ce script appelait donc `rag_chunks_fts` en croyant
    # nommer l'index du RAG. Les deux existent et derivent en sens opposes
    # (rag_fts : +35 961 fantomes ; rag_chunks_fts : -29 075 manquants), d'ou ce
    # choix EXPLICITE plutot qu'un defaut implicite.
    ap.add_argument("--table", choices=("rag_fts", "rag_chunks_fts"),
                    default="rag_fts",
                    help="index a reconstruire (defaut: rag_fts, interroge par "
                         "67 modules)")
    ap.add_argument("--incremental", action="store_true",
                    help="completer rag_chunks_fts par lots courts au lieu du rebuild "
                         "complet : praticable de JOUR, aucun verrou long, reprend ou "
                         "il s'arrete (le rebuild, lui, exige la fenetre NREM3)")
    ap.add_argument("--lot", type=int, default=20_000,
                    help="taille d'une plage de rowid par transaction (defaut 20000)")
    ap.add_argument("--budget-s", type=float, default=900.0,
                    help="duree maximale avant arret propre (defaut 900 s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compter les manquants sans rien ecrire")
    ap.add_argument("--triggers", choices=("etat", "poser", "retirer"),
                    help="declencheurs de synchronisation lexicale : sans eux une FTS5 "
                         "a contenu externe DERIVE par construction (702 180 manquants "
                         "mesures le 2026-09-01)")
    args = ap.parse_args(argv)

    if args.triggers:
        if args.triggers == "etat":
            res = triggers_etat()
        else:
            res = poser_triggers(retirer=(args.triggers == "retirer"))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.incremental:
        # La garde d'ingestion est re-consultee A CHAQUE LOT dans la fonction : on ne
        # se contente pas du controle d'entree ci-dessous, qui ne vaut qu'a l'instant t.
        res = rattraper_incremental(taille_lot=args.lot, budget_s=args.budget_s,
                                    dry_run=args.dry_run)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    actifs = ingestion_active()
    if actifs and not args.forcer:
        print(json.dumps({"ok": False, "refus": "ingestion active", "process": actifs,
                          "pourquoi": "un rebuild pendant une ingestion fait perdre ses "
                                      "ecritures (source perdue le 2026-07-25)"},
                         ensure_ascii=False, indent=2))
        return 2
    if actifs:
        print("[fts] ATTENTION forcage demande alors que %d ecrivain(s) tournent : %s"
              % (len(actifs), ", ".join(actifs)))

    if args.table == "rag_fts":
        from nokido_agent.app.forge_self_correction import rebuild_fts_index as _rebuild
    else:
        from nokido_agent.app.forge_self_correction import rebuild_chunks_fts_index as _rebuild
    print(f"[fts] reconstruction de {args.table} ...", flush=True)
    res = _rebuild()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
