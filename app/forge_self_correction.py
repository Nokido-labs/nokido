"""Ancre erreurs et solutions dans rag_chunks/rag_fts et les retrouve avant une action.

Entrees : anchor_error, anchor_solution, preflight_check, preflight_check_verbose,
session_summary, read_lessons, rebuild_fts_index, rebuild_chunks_fts_index,
purge_rag_fts_fantomes. preflight_check cherche via RAGEngine, puis FTS5 rag_fts,
puis LIKE, et ne retient que les sources du corps (session:, memory:, lesson...).
Effets : ecrit RAG/embeddings.db (rag_chunks, rag_fts, archive rag_fts_fantomes),
ajoute a logs/lessons_learned.md, reveille l'embedder via forge_nudge_embed.
Appele par forge_circadian (maintenance FTS), forge_dsl, forge_grounder,
forge_guarded_change et nokido_core (learn_from_error, apply_smart_patch).
"""
from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : time.time() L760.
import time

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_self_correction_hybrid_retrieval
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]
CONTRAINTE: preflight_check branche sur la vraie stack RAG (RAGEngine.search + FTS5 fallback), au lieu du SQL LIKE primitif
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]"
"""
forge_self_correction.py — Protocole Self-Correction RAG
=========================================================
Implémente le protocole de mémoire persistante pour Claude (et tout LLM).

Fonctions principales :
  preflight_check(action, context)   — vérif pré-vol (HYBRID RAG)
  anchor_error(error, context)       — ancrage immédiat d'une erreur
  anchor_solution(problem, solution) — ancrage d'une solution validée
  session_summary(commits, tests)    — résumé fin de session
  read_lessons(n)                    — lecture lessons_learned.md

Usage type :
  from forge_self_correction import preflight_check, anchor_error

  warnings = preflight_check("apply_smart_patch", "modifier forge_settings.py")
  if warnings: print(warnings)

  except SyntaxError as e:
      anchor_error(str(e), context="apply_smart_patch sur forge_settings.py")

Fix 2026-04-24 : preflight_check utilisait un SQL LIKE brut sur 20 rows
avec filtre len(kw)>3. Rappel catastrophique. Maintenant :

  1. Essaie RAGEngine.search() (FAISS + BM25 + RRF k=60 + rerank) si l engine
     est charge en memoire (__main__.rag_engine ou forge_context)
  2. Sinon fallback FTS5 SQLite natif (rag_fts table, tokenize porter unicode61)
  3. Sinon ultime fallback SQL LIKE (comportement originel preserve)

Les ancrages (anchor_error, anchor_solution) synchronisent aussi rag_fts
pour que les lecons fraichement ancrees soient immediatement retrouvables.
"""


import hashlib
import os as _os
import sqlite3
import json
import re
import time as _time
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional


def _make_id(text: str, source: str) -> str:
    """ID deterministe pour rag_chunks (evite les NULL).
    Compatible avec RAGEngine.make_chunk_id : sha256(source|text)[:16]."""
    key = source + "|" + (text[:500] if text else "")
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]


_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "embeddings.db"
_LESSONS = _ROOT / "logs" / "lessons_learned.md"


def _zmq_nudge_brain(n_chunks: int = 1) -> None:
    """Reveille le daemon d'embedding — via le helper qui VERIFIE l'ecouteur.

    L'ancienne version poussait en fire-and-forget sur :5557 et se croyait sure
    d'elle. Mesure du 2026-08-05 : un PUSH ZMQ vers un port FERME est ACCEPTE sans
    exception, donc le `except: pass` ne se declenchait jamais et le reveil paraissait
    reussir. Le port est ferme depuis juin — les chunks attendaient un signal qui
    n'atteignait personne, sans qu'aucune trace ne l'indique.
    """
    try:
        from nokido_agent.app.forge_nudge_embed import nudge_embed

        nudge_embed(n_chunks, source="forge_self_correction")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[self_correction] reveil d'embedding impossible (%s: %s) | consequence: "
            "les chunks corriges resteront sans vecteur jusqu'au prochain drain",
            type(e).__name__, str(e)[:90])


# =============================================================================
# RETRIEVAL HELPERS — 3 niveaux de fallback
# =============================================================================


def _clean_query(q: str) -> str:
    """Nettoie la query pour FTS5 : supprime tokens speciaux, garde mots utiles."""
    # Retire caracteres qui cassent FTS5 : : . ( ) " etc.
    cleaned = re.sub(r"[^\w\s\-]", " ", q, flags=re.UNICODE)
    # Filtre mots >= 3 chars (minimum utile, plus permissif que l ancien >3)
    words = [w for w in cleaned.split() if len(w) >= 3]
    return " ".join(words[:12])  # max 12 termes pour garder la requete rapide


def _fts5_search(query: str, limit: int = 10) -> list:
    """
    Recherche via rag_fts (FTS5 natif SQLite avec BM25).
    Retourne liste de (bm25_score, text, source).
    Plus rapide que SQL LIKE et gere tokenization porter/unicode61.
    """
    cleaned = _clean_query(query)
    if not cleaned:
        return []

    # Construit une query OR entre les termes (meilleur rappel que AND)
    terms = cleaned.split()
    # Escape tokens qui pourraient etre interpretes (keywords FTS5)
    fts_keywords = {"AND", "OR", "NOT", "NEAR"}
    safe_terms = ['"' + t + '"' if t.upper() in fts_keywords else t for t in terms]
    fts_query = " OR ".join(safe_terms)

    try:
        conn = sqlite3.connect(str(_DB))
        cur = conn.cursor()
        # bm25() retourne negatif (plus proche de 0 = meilleur), on trie ASC
        cur.execute(
            "SELECT bm25(rag_fts) as rank, text, source, chunk_id "
            "FROM rag_fts "
            "WHERE rag_fts MATCH ? "
            "  AND (source LIKE 'session:%' OR source LIKE '%error%' OR source LIKE '%lesson%' OR source LIKE '%rule%') "
            "ORDER BY rank "
            "LIMIT ?",
            (fts_query, limit),
        )
        results = cur.fetchall()
        conn.close()
        # Transforme en format uniforme (score positif = meilleur)
        return [(-r[0], r[1], r[2]) for r in results]
    except Exception:
        return []


def _ragengine_search(query: str, limit: int = 10) -> list:
    """
    Tente d utiliser RAGEngine en memoire (FAISS + BM25 + RRF + rerank).
    Retourne [] si l engine n est pas charge ou search async non executable sync.
    """
    try:
        import sys as _sys

        main_mod = _sys.modules.get("__main__")
        engine = getattr(main_mod, "rag_engine", None) if main_mod else None

        if engine is None:
            try:
                from nokido_agent.app.forge_context import get_rag_engine

                engine = get_rag_engine()
            except Exception:
                return []

        if engine is None or not hasattr(engine, "search"):
            return []

        # RAGEngine.search est async — on tente un run synchrone si possible.
        # Si on est deja dans une event loop, on skip (preflight_check reste sync).
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Deja dans une loop -> impossible d appeler async sync sans blocking
            return []
        except RuntimeError:
            pass

        # Pas de loop active : on peut creer une temporaire
        try:
            docs = asyncio.run(engine.search(query, k=limit, rerank=True, compress=False))
            return [
                (d.get("rerank_score", d.get("score", 0.0)), d.get("content", ""), d.get("source", ""))
                for d in docs
                if isinstance(d, dict)
            ]
        except Exception:
            return []

    except Exception:
        return []


def _like_fallback(query: str, limit: int = 20) -> list:
    """
    Fallback SQL LIKE sur role_hint='rule' + sources lesson/error/session.
    Plus permissif que l ancien : accepte len(kw) >= 3 au lieu de > 3.
    """
    cleaned = _clean_query(query)
    keywords = cleaned.split()
    if not keywords:
        return []

    try:
        conn = sqlite3.connect(str(_DB))
        rows = conn.execute(
            "SELECT text, source FROM rag_chunks "
            "WHERE (role_hint='rule' "
            "   OR source LIKE '%error%' "
            "   OR source LIKE '%lesson%' "
            "   OR source LIKE 'session:%') "
            "  AND LENGTH(text) > 20 "
            "ORDER BY id DESC LIMIT ?",
            (limit * 3,),  # triple pour avoir du choix
        ).fetchall()
        conn.close()

        results = []
        for text, source in rows:
            text_lower = text.lower()
            # Score = nombre de keywords presents (pas juste 2+)
            score = sum(1 for kw in keywords if kw in text_lower)
            if score >= 1:  # assouplissement : 1 match suffit
                results.append((score, text, source))

        results.sort(key=lambda x: -x[0])
        return results[:limit]
    except Exception:
        return []


# =============================================================================
# 1. PREFLIGHT CHECK — version hybride RAG
# =============================================================================


# LISTE BLANCHE des ancrages du corps. Prefixes MESURES le 2026-09-20 sur les
# chunks portant une solution ancree : session: 7 370 · mcp_result: 384 ·
# memory: 36. Les autres prefixes rencontres (github:, qdrant_docs:, https:,
# docset:, gitingest:) designent de la documentation ou du code EXTERIEUR.
#
# POURQUOI UNE LISTE BLANCHE, ET PAS UNE LISTE NOIRE -- je me suis trompe une
# premiere fois ici. Ma version precedente ecartait les prefixes « gitingest% »,
# en reprenant le critere de la colonne generee `origin` de rag_chunks. Mesure :
#
#     origin='laforge'      gemini_cli/CONTRIBUTING.md     31 416 chunks
#     origin='cold-legacy'  gemini_cli/.prettierrc.json     6 080 chunks
#
# La regle CASE de `origin` ne classe `external-lib` que `source LIKE
# 'gitingest%'` et verse TOUT LE RESTE dans son `ELSE 'laforge'`. Le corps compte
# donc 31 416 chunks de code Google comme etant les siens, et une liste noire
# calquee dessus laisse passer exactement ce qu'elle devait bloquer.
#
# RULES_SHARED le dit : « on classe par liste BLANCHE -- n'est sain que ce qui
# est PROUVE sain. Une liste NOIRE laisse toute valeur inattendue tomber dans le
# sain par defaut. » C'est le cas ici, mot pour mot.
_PREFIXES_DU_CORPS = ("session:", "memory:", "anchor", "lesson", "git:")


def _est_source_du_corps(source: str | None) -> bool:
    """Vrai si ce chunk est un ancrage produit par le corps lui-meme.

    Une source ILLISIBLE (None, vide) n'est PAS reconnue comme du corps : on
    n'accorde pas la confiance sur une absence d'information. C'est l'asymetrie
    volontaire d'une liste blanche -- le doute exclut, il n'inclut pas.
    """
    if not source:
        return False
    s = str(source).lstrip().lower()
    return s.startswith(_PREFIXES_DU_CORPS)


def preflight_check(action: str, context: str = "", limit: int = 5) -> Optional[str]:
    """
    Cherche dans le RAG des erreurs connues et solutions liees a cette action.
    Retourne un avertissement si trouve, None sinon.

    Appele AVANT chaque action critique (write, subprocess, creation module, etc.)

    Pipeline 3 niveaux :
      1. RAGEngine.search() si l engine est charge (FAISS+BM25+RRF+rerank)
      2. Sinon rag_fts (FTS5 BM25 natif SQLite, tokenize porter unicode61)
      3. Sinon SQL LIKE permissif (fallback ultime, toujours disponible)
    """
    query = (action + " " + context).strip()
    if not query:
        return None

    # Niveau 1 : RAGEngine complet (ideal mais souvent pas dispo en contexte preflight)
    results = _ragengine_search(query, limit=limit)

    # Niveau 2 : FTS5 natif (rapide, toujours exploitable, bon rappel)
    if not results:
        results = _fts5_search(query, limit=limit)

    # Niveau 3 : LIKE fallback
    if not results:
        results = _like_fallback(query, limit=limit)

    if not results:
        return None

    # PROVENANCE AVANT PERTINENCE (2026-09-20).
    #
    # MESURE, sur une erreur REELLE tiree de network_log (ERR:401 agent=RESCUE,
    # 8 occurrences en 3 h) :
    #
    #   [PREFLIGHT] Match pour '401 unauthorized agent RESCUE ring -1 ad'
    #   (source=gitingest:gemini_cli/.../a2a-client.ts, score=26.35)
    #   : //example.com/card'
    #
    # Le raffineur a repondu avec du CODE TIERS a une question sur le hub. Le
    # corps indexe 509 016 chunks de depots en veille (`origin='external-lib'`)
    # et le retrieval de lecons ne les distinguait pas de ses propres ancrages.
    #
    # Ce n'est pas un accident : `preflight_check` ne rend `None` que sur une
    # liste VIDE, et son pipeline se termine par `_like_fallback` -- decrit plus
    # haut comme « fallback ultime, toujours disponible ». Il etait donc construit
    # pour TOUJOURS repondre, donc pour ne presque jamais dire « je ne sais pas ».
    # Un retrieval qui ne rend jamais vide transforme UNKNOWN en affirmation.
    #
    # ON N INTRODUIT AUCUN SEUIL DE SCORE, et c'est un choix DIT : les trois
    # niveaux (RAGEngine, FTS5 BM25, LIKE) rendent des scores d'ECHELLES
    # DIFFERENTES -- un seuil unique serait faux par construction, et leurs
    # distributions n'ont pas ete mesurees. On corrige ce qui est FACTUEL : une
    # lecon du corps ne nait pas d'un depot tiers.
    _du_corps = [r for r in results if _est_source_du_corps(r[2])]
    if not _du_corps:
        # Tout ce qu'on a trouve vient de l'exterieur : c'est une ABSENCE de lecon,
        # pas une lecon faible. Rendre le meilleur chunk tiers « faute de mieux »
        # fabriquerait une reponse affirmative a partir d'un vide.
        return None
    results = _du_corps

    # Meilleure correspondance : extraire SOLUTION ou snippet utile
    best_score, best_text, best_source = results[0]

    # Prioriser le champ SOLUTION si present (anchor_solution format)
    snippet = ""
    for tag in ("SOLUTION :", "SOLUTION:", "Solution :", "Solution:"):
        idx = best_text.find(tag)
        if idx >= 0:
            snippet = best_text[idx + len(tag) :].strip().split("\n")[0][:300]
            break

    if not snippet:
        # Fallback : premiere ligne non vide du chunk
        for line in best_text.split("\n"):
            line = line.strip()
            if line and not line.startswith(("#", "---", "===")):
                snippet = line[:300]
                break
        if not snippet:
            snippet = best_text[:250]

    # Source compactee pour trace
    src_short = best_source[:40] if best_source else "rag"

    return (
        "[PREFLIGHT] Match pour '"
        + action[:40]
        + "' "
        + "(source="
        + src_short
        + ", score="
        + str(round(best_score, 2))
        + ") : "
        + snippet
    )


def preflight_check_verbose(action: str, context: str = "", limit: int = 5) -> dict:
    """
    Version verbose : retourne le dict complet des matches pour inspection.
    Utile pour debug et pour les scenarios ou on veut montrer plusieurs lecons.
    """
    query = (action + " " + context).strip()
    if not query:
        return {"results": [], "tier": "none"}

    tier = "ragengine"
    results = _ragengine_search(query, limit=limit)
    if not results:
        tier = "fts5"
        results = _fts5_search(query, limit=limit)
    if not results:
        tier = "like"
        results = _like_fallback(query, limit=limit)
    if not results:
        tier = "none"

    # LE CORPS D'ABORD (2026-09-20). Mesure des appelants reels :
    #
    #   preflight_check_verbose  ->  10 sites (forge_dsl, forge_epistemic_veille,
    #       forge_extern_patterns, forge_grounder, forge_debate_job,
    #       forge_rag_llama_query, forge_rescue, forge_self_patcher,
    #       nokido_hub:4245, bench_rag)
    #   preflight_check          ->   1 site (app/nokido_core.py:1458)
    #
    # Le corps passe par CETTE fonction. Avoir filtre la provenance dans
    # `preflight_check` seul, c'etait corriger le jumeau mort -- meme motif que
    # le circadien le 2026-09-20, paye deux fois dans la journee.
    #
    # ON TRIE, ON NE FILTRE PAS, et c'est un choix DIT : cette sortie sert aussi a
    # `bench_rag`, qui mesure le RAPPEL -- y supprimer des lignes fausserait la
    # mesure. Le tri est STABLE (`not` -> False avant True), donc l'ordre relatif
    # a l'interieur de chaque groupe est conserve : on remonte le corps, on ne
    # rebat pas les cartes. Et chaque resultat porte `du_corps`, pour que
    # l'appelant decide sans avoir a redeviner le prefixe lui-meme.
    results = sorted(results, key=lambda r: not _est_source_du_corps(r[2]))

    return {
        "query": query,
        "tier": tier,
        "results": [{"score": round(s, 3), "source": src, "preview": text[:250],
                     "du_corps": _est_source_du_corps(src)}
                    for s, text, src in results],
    }


# =============================================================================
# 2. ANCHOR ERROR — ancrage immediat d une erreur
# =============================================================================


def anchor_error(
    error_msg: str,
    context: str = "",
    solution: str = "",
    domain: str = "systeme",
) -> dict:
    """
    Ancre une erreur dans le RAG au moment ou elle se produit.
    Met aussi a jour logs/lessons_learned.md et synchronise rag_fts.

    A appeler dans chaque except, IMMEDIATEMENT apres l erreur.
    """
    # DLP log Tier 1 : scrub PII/secrets AVANT ancrage RAG (indexé rag_fts = searchable)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_str_for_log as _scrub

        error_msg, context, solution = _scrub(error_msg), _scrub(context), _scrub(solution)
    except Exception:
        pass
    date_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    text = (
        "ERREUR RECURRENTE : "
        + error_msg[:300]
        + chr(10)
        + "CONTEXTE : "
        + context[:200]
        + chr(10)
        + ("SOLUTION : " + solution[:300] + chr(10) if solution else "")
        + "DATE : "
        + date_str
    )
    source = "session:" + _dt.now().strftime("%Y-%m-%d") + ":error_learning"
    try:
        from nokido_agent.app.forge_trace_context import get_trace_id

        _tid = get_trace_id()
    except Exception:
        _tid = "system"
    meta = json.dumps(
        {
            "ring": 1,
            "trust_score": 0.85,
            "auto_learned": True,
            "tags": ["erreur", "auto_correction"],
            "trace_id": _tid,
        }
    )

    try:
        # Ecriture gouvernee sur `_DB` : cf. la note de `anchor_solution` -- ne PAS
        # passer par `open_writer()`, qui ouvre `db_path()` et court-circuiterait la
        # redirection des tests.
        conn = sqlite3.connect(str(_DB), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        from nokido_agent.app.forge_db_path import busy_ms
        conn.execute(f"PRAGMA busy_timeout={busy_ms()}")
        cur = conn.cursor()

        # 1. Insert dans rag_chunks. L'EMPREINTE est deterministe ; l'identifiant, non —
        # il porte un suffixe temporel (lu par `forge_skill_enricher` pour dater), ce qui
        # rendait l'`INSERT OR IGNORE` ci-dessous inoperant : chaque ecriture creait une
        # clef neuve. Meme defaut, meme remede que `anchor_solution` (mesure 2026-08-26).
        _empreinte = _make_id(text, source)
        chunk_id = "lesson_err_" + _empreinte + "_" + str(int(_time.time()))
        # GLOB et non LIKE : jumeau exact du defaut mesure dans `anchor_solution` le
        # 2026-09-04. Ici le plan etait `SCAN rag_chunks` NU -- le pire cas, la table
        # de 24,9 Go lue en entier a chaque ancrage d'erreur. `LIKE` est insensible a
        # la casse, ce qui interdit l'usage de l'index de la cle primaire ; `GLOB` est
        # sensible a la casse, donc convertible en bornes. Plan apres :
        # `SEARCH rag_chunks USING INDEX sqlite_autoindex_rag_chunks_1`.
        _deja = cur.execute(
            "SELECT id FROM rag_chunks WHERE id GLOB ? AND text = ? LIMIT 1",
            ("lesson_err_" + _empreinte + "_*", text),
        ).fetchone()
        if _deja:
            conn.commit()
            conn.close()
            return {"ok": True, "anchored": error_msg[:60], "chunk_id": _deja[0],
                    "deja_connue": True,
                    "note": "erreur identique deja ancree — non dupliquee"}
        cur.execute(
            "INSERT OR IGNORE INTO rag_chunks (id, text, source, domain, role_hint, meta) SELECT ?,?,?,?,?,? "
            "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
            (chunk_id, text, source, domain, "rule", meta, chunk_id),
        )
        new_id = chunk_id

        # 2. Synchroniser rag_fts (lecon searchable immediatement)
        try:
            cur.execute(
                "INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                (chunk_id, text, source, domain),
            )
        except Exception:
            pass

        conn.commit()
        conn.close()
        _zmq_nudge_brain(1)

        # 3. Markdown trace humaine
        _append_to_lessons(
            "### ["
            + date_str
            + "] AUTO - "
            + error_msg[:60]
            + chr(10)
            + "**Contexte :** "
            + context[:150]
            + chr(10)
            + ("**Solution :** " + solution[:200] + chr(10) if solution else "")
            + chr(10)
        )

        return {"ok": True, "anchored": error_msg[:60], "chunk_id": new_id}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# 3. ANCHOR SOLUTION — ancrage d une solution validee
# =============================================================================


def anchor_solution(
    problem: str,
    solution: str,
    example: str = "",
    domain: str = "systeme",
) -> dict:
    """
    Ancre une solution validee. Renforce la memoire positive (pas juste erreurs).
    Synchronise rag_fts pour retrieval immediat via preflight_check.
    """
    # DLP log Tier 1 : scrub PII/secrets AVANT ancrage RAG (indexé rag_fts = searchable)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_str_for_log as _scrub

        problem, solution, example = _scrub(problem), _scrub(solution), _scrub(example)
    except Exception:
        pass
    date_str = _dt.now().strftime("%Y-%m-%d")
    text = (
        "SOLUTION VALIDEE : "
        + problem[:200]
        + chr(10)
        + "SOLUTION : "
        + solution[:400]
        + chr(10)
        + ("EXEMPLE : " + example[:300] + chr(10) if example else "")
        + "DATE : "
        + date_str
    )
    source = "session:" + date_str + ":solution"
    try:
        from nokido_agent.app.forge_trace_context import get_trace_id

        _tid = get_trace_id()
    except Exception:
        _tid = "system"
    meta = json.dumps(
        {
            "ring": 1,
            "trust_score": 0.95,
            "auto_learned": True,
            "tags": ["solution", "pattern_correct"],
            "trace_id": _tid,
        }
    )

    # P2a memory gate : rejeter bruit/placeholder/contenu trivial AVANT consolidation
    # (anti-confabulation). Gate sur le contenu BRUT (pas le text prefixe). Fail-open.
    try:
        from nokido_agent.tools.forge_memory_gate import should_ingest as _mem_gate

        _g = _mem_gate((problem + " :: " + solution).strip(), source=source, domain=domain, author="anchor_solution")
        if not _g.get("ok"):
            return {"ok": False, "rejected": _g.get("reason"), "anchored": None}
    except Exception:
        pass

    try:
        # Reglages d'ecriture gouvernee (autocommit + WAL + busy_timeout) poses ICI, et
        # NON via `forge_db_path.open_writer()`. Raison mesuree le 2026-09-04 : ce
        # helper ouvre `db_path()`, alors que `_DB` est le point de REDIRECTION des
        # tests. Les deux designent bien le meme fichier en fonctionnement normal
        # (junction V: -> C:, verifie), mais des qu'un test monkeypatche `_DB` vers une
        # base temporaire, `open_writer` continue d'ecrire dans la base de PRODUCTION :
        # `test_ancrage_sans_redite_nr` comptait alors 0 chunk dans sa base a lui.
        # L'egalite de deux chemins a l'instant t ne dit rien du point d'indirection.
        #
        # `isolation_level=None` (autocommit) est ce qui compte vraiment : un connect()
        # nu ouvre une transaction implicite qui tient le verrou d'ecriture pendant
        # toute la fonction -- le « database is locked » du voisin.
        conn = sqlite3.connect(str(_DB), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        from nokido_agent.app.forge_db_path import busy_ms
        conn.execute(f"PRAGMA busy_timeout={busy_ms()}")
        cur = conn.cursor()

        _empreinte = _make_id(text, source)
        chunk_id = "lesson_sol_" + _empreinte + "_" + str(int(_time.time()))

        # ANTI-REDITE. Mesure 2026-08-26 : `domain='autonomous'` portait 5132 chunks pour
        # 566 textes distincts, soit 9,1 COPIES par lecon — une seule d'entre elles
        # repetee 35 fois dans la journee. La cause est ici : l'id porte un suffixe
        # temporel, donc chaque ecriture cree une clef NEUVE et l'`INSERT OR IGNORE`
        # ci-dessous ne pouvait JAMAIS se declencher. Un garde present, et contourne par
        # la ligne qui le precede.
        #
        # Le suffixe est CONSERVE : `forge_skill_enricher` le parse pour dater les lecons
        # (fallback L124). On ne change donc pas le format d'id — on empeche l'ecriture
        # redondante en amont, sur l'empreinte (source + texte), qui est stable.
        # GLOB, et surtout PAS `LIKE`. Mesure 2026-09-04 : `id LIKE 'prefixe%'` donne
        # le plan `SCAN rag_chunks`, soit 24,9 Go balayes A CHAQUE ancrage de lecon.
        # C'est ce qui faisait expirer le timeout de 30 s et tuait la suite pytest
        # SANS verdict (gate rouge, aucune ligne d'echec). La table est pourtant bien
        # indexee : c'est la REQUETE qui neutralisait son index, `LIKE` etant
        # INSENSIBLE a la casse par defaut -- SQLite ne peut alors pas le convertir en
        # bornes. `GLOB` est sensible a la casse, donc indexable. Plan mesure apres :
        # `SEARCH rag_chunks USING INDEX sqlite_autoindex_rag_chunks_1`, 0,002 s.
        #
        # Gain de PRECISION au passage : en LIKE, '_' est un JOKER (jamais echappe
        # ici), donc le motif matchait aussi des identifiants etrangers ; en GLOB il
        # est litteral. Verifie sur les 6936 ancrages en base : tous en hexadecimal
        # minuscule, aucun n'est rate par le passage a GLOB.
        _deja = cur.execute(
            "SELECT id FROM rag_chunks WHERE id GLOB ? AND text = ? LIMIT 1",
            ("lesson_sol_" + _empreinte + "_*", text),
        ).fetchone()
        if _deja:
            # La lecon EXISTE : on ne la re-ecrit pas. Une redite n'apporte aucune
            # information et degrade la recherche, qui remonterait N fois la meme chose.
            conn.commit()
            conn.close()
            # Meme forme de retour que le chemin nominal (`anchored` = le probleme,
            # `chunk_id` = l'identifiant) : un appelant ne doit pas avoir a savoir
            # laquelle des deux branches l'a servi. `deja_connue` le DIT quand meme,
            # pour qui veut compter les redites evitees.
            return {"ok": True, "anchored": problem[:60], "chunk_id": _deja[0],
                    "deja_connue": True,
                    "note": "lecon identique deja ancree — non dupliquee"}

        cur.execute(
            "INSERT OR IGNORE INTO rag_chunks (id, text, source, domain, role_hint, meta) SELECT ?,?,?,?,?,? "
            "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
            (chunk_id, text, source, domain, "rule", meta, chunk_id),
        )
        new_id = chunk_id

        # Sync rag_fts
        try:
            cur.execute(
                "INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                (chunk_id, text, source, domain),
            )
        except Exception:
            pass

        conn.commit()
        conn.close()
        _zmq_nudge_brain(1)

        _append_to_lessons(
            "### ["
            + date_str
            + "] SOLUTION - "
            + problem[:60]
            + chr(10)
            + "**Solution :** "
            + solution[:200]
            + chr(10)
            + (("**Exemple :** `" + example[:100] + "`" + chr(10)) if example else "")
            + chr(10)
        )

        return {"ok": True, "anchored": problem[:60], "chunk_id": new_id}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# 4. SESSION SUMMARY
# =============================================================================


def session_summary(commits: list, tests: str, notes: str = "") -> dict:
    """Ancre le resume de la session dans lessons_learned.md."""
    date_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    summary = (
        chr(10)
        + "---"
        + chr(10)
        + "## SESSION "
        + date_str
        + chr(10)
        + "**Tests NR :** "
        + tests
        + chr(10)
        + "**Commits :**"
        + chr(10)
        + chr(10).join("- " + c for c in commits)
        + chr(10)
        + ("**Notes :** " + notes + chr(10) if notes else "")
        + chr(10)
    )
    _append_to_lessons(summary)
    return {"ok": True, "date": date_str}


# =============================================================================
# 5. REBUILD FTS INDEX — utilitaire de maintenance
# =============================================================================


_FTS_LOCK = _DB.parent / "fts_rebuild.lock"
_FTS_BATCH = 500  # rows per commit — keeps write-lock window to ~50ms


def rebuild_fts_index() -> dict:
    """Resynchronise rag_fts depuis rag_chunks — shadow table swap (stratégie 5).

    Pipeline sans lock production :
    1. Construit rag_fts_build (shadow) en batches → lock uniquement sur shadow
    2. Swap atomique: DROP fts_old, RENAME rag_fts→fts_old, RENAME shadow→rag_fts
    3. Lock production = quelques ms (le RENAME final)
    Advisory lock file + busy_timeout pour coordination inter-process.
    """
    # Le verrou etait ECRIT sans jamais etre LU : deux reconstructions
    # simultanees pouvaient se marcher dessus, et un process tue laissait un
    # fichier trompeur que personne n'interrogeait. Un garde qu'on ne consulte
    # pas ne garde rien — motif recurrent corrige le 2026-08-14.
    if _FTS_LOCK.exists():
        try:
            _pid_tenu = int(_FTS_LOCK.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            _pid_tenu = 0
        _vivant = False
        if _pid_tenu:
            try:
                import psutil as _ps

                _vivant = _ps.pid_exists(_pid_tenu)
            except ImportError:
                # Sans psutil on ne PEUT pas trancher : refuser plutot que de
                # supposer le verrou orphelin et ecraser un rebuild en cours.
                return {"ok": False, "refus": "verrou present, vivacite "
                        "indeterminee (psutil absent)", "pid": _pid_tenu}
        if _vivant:
            return {"ok": False, "refus": "reconstruction deja en cours",
                    "pid": _pid_tenu}
        # Orphelin : le process est mort sans passer par son `finally` (kill).
        _FTS_LOCK.unlink(missing_ok=True)

    _FTS_LOCK.write_text(str(_os.getpid()))
    try:
        conn = sqlite3.connect(str(_DB), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        from nokido_agent.app.forge_db_path import busy_ms
        conn.execute(f"PRAGMA busy_timeout={busy_ms()}")
        cur = conn.cursor()

        # 1. Récupère tous les chunks manquants dans rag_fts
        cur.execute("""
            SELECT rc.id, rc.text, rc.source, rc.domain
            FROM rag_chunks rc
            LEFT JOIN rag_fts f ON f.chunk_id = rc.id
            WHERE f.chunk_id IS NULL
              AND rc.id IS NOT NULL
              AND rc.text IS NOT NULL
              AND LENGTH(rc.text) > 20
        """)
        missing = cur.fetchall()

        if not missing:
            conn.close()
            return {"ok": True, "synced": 0}

        # 2. Si peu de chunks (<= batch), insert direct sur rag_fts (pas besoin de shadow)
        if len(missing) <= _FTS_BATCH:
            cur.executemany(
                "INSERT OR IGNORE INTO rag_fts (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                [(str(r[0]), r[1], r[2] or "", r[3] or "general") for r in missing],
            )
            conn.commit()
            conn.close()
            return {"ok": True, "synced": len(missing)}

        # 3. Shadow table : construction en batches sans toucher rag_fts
        cur.execute("DROP TABLE IF EXISTS rag_fts_build")
        # `source` et `domain` sont INDEXES depuis le 2026-09-03. En UNINDEXED,
        # FTS5 les STOCKE mais refuse de les interroger : un `MATCH 'source:rfc'`
        # y rend 0 — mesure faite ce jour-la, alors que la meme requete rendait
        # 58 sources sur `rag_chunks_fts`, qui les declare indexees. Ce zero a ete
        # lu comme « aucune RFC ingeree » alors que 2 582 chunks etaient en base.
        # Les indexer rend possible le PREFILTRAGE lexical (par source, par
        # domaine) avant meme le calcul BM25. Cout : un index un peu plus gros.
        # `chunk_id` reste UNINDEXED : c'est une clef de jointure, jamais un terme
        # de recherche — et l'indexer gonflerait le vocabulaire pour rien.
        cur.execute("""
            CREATE VIRTUAL TABLE rag_fts_build
            USING fts5(chunk_id UNINDEXED, text, source, domain)
        """)
        conn.commit()

        # Copier les entrées existantes — SEULEMENT celles dont le chunk vit
        # encore. Le `SELECT ... FROM rag_fts` sans jointure recopiait TOUT,
        # fantômes compris : la reconstruction ajoutait les manquants sans
        # jamais retirer les morts, et l'index ne pouvait que gonfler.
        # Mesure du 2026-08-14 : 1 186 356 entrées d'index pour 1 150 407
        # chunks — 35 949 références vers des chunks supprimés, que toute
        # recherche RAG pouvait ramener.
        cur.execute("""
            INSERT INTO rag_fts_build (chunk_id, text, source, domain)
            SELECT f.chunk_id, f.text, f.source, f.domain
            FROM rag_fts f
            JOIN rag_chunks rc ON rc.id = f.chunk_id
        """)
        conn.commit()
        reprises = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        cur.execute("SELECT count(*) FROM rag_fts")
        avant = cur.fetchone()[0]
        fantomes = max(0, avant - reprises) if reprises else 0

        # Ajouter les nouvelles en batches
        synced = 0
        _t0 = time.time()
        _lots = (len(missing) + _FTS_BATCH - 1) // _FTS_BATCH
        # `print` et non un logger : ce module n'importe pas `logging` et sort
        # deja par print. Un `_log` inexistant aurait leve un NameError DANS la
        # boucle — le chemin d'alerte aurait tue la tache qu'il devait suivre.
        print("[fts] %d chunks a indexer en %d lots ; %d fantome(s) ecarte(s)"
              % (len(missing), _lots, fantomes), flush=True)
        for i in range(0, len(missing), _FTS_BATCH):
            batch = missing[i : i + _FTS_BATCH]
            cur.executemany(
                "INSERT OR IGNORE INTO rag_fts_build (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                [(str(r[0]), r[1], r[2] or "", r[3] or "general") for r in batch],
            )
            conn.commit()
            synced += len(batch)
            # JALON : sans lui, une reconstruction de plusieurs heures est
            # indiscernable d'un blocage — constate le 2026-08-14, 30 min sans
            # savoir si l'on etait a 5 % ou a 90 %.
            _lot = i // _FTS_BATCH + 1
            if _lot % 10 == 0 or _lot == _lots:
                _ecoule = time.time() - _t0
                _reste = (_ecoule / synced) * (len(missing) - synced) if synced else 0
                print("[fts] lot %d/%d — %d/%d chunks (%.1f %%) — "
                      "ecoule %.0f s, reste ~%.0f s"
                      % (_lot, _lots, synced, len(missing),
                         100.0 * synced / len(missing), _ecoule, _reste),
                      flush=True)

        # 4. Swap atomique — lock production = quelques ms
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS rag_fts_old")
        cur.execute("ALTER TABLE rag_fts RENAME TO rag_fts_old")
        cur.execute("ALTER TABLE rag_fts_build RENAME TO rag_fts")
        cur.execute("COMMIT")
        cur.execute("DROP TABLE IF EXISTS rag_fts_old")
        conn.commit()

        conn.close()
        return {"ok": True, "synced": synced, "fantomes_ecartes": fantomes,
                "duree_s": round(time.time() - _t0, 1)}

    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        _FTS_LOCK.unlink(missing_ok=True)


# =============================================================================
# HELPERS
# =============================================================================


def _append_to_lessons(text: str) -> None:
    """Ajoute du contenu a lessons_learned.md."""
    try:
        _LESSONS.parent.mkdir(parents=True, exist_ok=True)
        if _LESSONS.exists():
            current = _LESSONS.read_text(encoding="utf-8")
        else:
            current = "# Nokido - Lessons Learned\n\n"
        _LESSONS.write_text(current + text, encoding="utf-8")
    except Exception:
        pass


def rebuild_chunks_fts_index(verbeux: bool = True) -> dict:
    """Reconstruit l'index lexical du moteur (`rag_chunks_fts`) depuis son contenu.

    RENOMMEE le 2026-08-14. Elle s'appelait `rebuild_fts_index` — comme la
    fonction definie 100 lignes plus haut, qu'elle ECRASAIT silencieusement a
    l'import depuis le 2026-07-30. Sa note d'origine dit « CETTE FONCTION
    MANQUAIT » : elle ne manquait pas, elle n'a pas ete trouvee. La chercher
    aurait evite de la recreer pour une AUTRE table et de tuer l'originale.

    Les deux existent et servent, mais elles ne reconstruisent pas le meme
    index : celle-ci vise `rag_chunks_fts` (16 modules l'interrogent), l'autre
    `rag_fts` (67 modules). Mesure du 2026-08-14, source `rag_chunks` a
    1 150 371 lignes : `rag_fts` en compte 1 186 332 (35 961 FANTOMES) et
    `rag_chunks_fts` 1 121 296 (29 075 MANQUANTS). Les deux derivent, en sens
    opposes — d'ou l'importance que chacune garde un nom qui dit sa table.

    CETTE FONCTION MANQUAIT (mesure 2026-07-30). `forge_mcp_registry` l'IMPORTE et
    l'APPELLE derriere son option `rebuild`, dans un `try/except: pass` — donc son
    absence etait avalee en silence et l'option n'a JAMAIS rien reconstruit. C'est le
    motif de la journee : un consommateur branche sur quelque chose qui n'existe pas.
    Consequence constatee : 214 entrees de l'index designent des lignes DISPARUES de
    `rag_chunks`, et toute recherche qui les touche echoue par
    `fts5: missing row N from content table`.

    On visé `rag_chunks_fts` et non `rag_fts` : c'est la table que
    `forge_rag_engine._lexical()` interroge (gotcha du 29/07 — deux tables FTS
    coexistent, alimenter la mauvaise n'indexe rien pour le moteur). `rag_chunks_fts`
    est a CONTENU EXTERNE, donc la commande `'rebuild'` de FTS5 est le remede propre :
    elle re-derive tout l'index depuis la table source et fait disparaitre les entrees
    orphelines, ce qu'un `DELETE` ne peut pas faire (il exige le texte d'origine, perdu).

    LOURD par nature (700k+ lignes) : a lancer DEPORTE, jamais dans l'event-loop du hub
    — un rebuild inline y a deja provoque un wedge de plus de 120 s le 2026-06-16.
    """
    # Imports LOCAUX : le module ne garantit pas `sys` ni `Path` a ce niveau, et le
    # premier essai est mort sur un NameError — le hook AST valide la syntaxe, JAMAIS
    # les noms non definis (lecon deja consignee le 28/07 sur ce meme module).
    import sys as _sys
    import time as _t
    from pathlib import Path as _Path

    t0 = _t.time()
    try:
        _sys.path.insert(0, str(_Path(__file__).resolve().parent))
        from nokido_agent.app.forge_db_path import open_writer
    except Exception as exc:
        return {"ok": False,
                "raison": "writer gouverne injoignable: %s: %s"
                          % (type(exc).__name__, str(exc)[:160])}

    try:
        with open_writer() as cx:
            avant = cx.execute(
                "SELECT COUNT(*) FROM rag_chunks_fts_docsize d "
                "LEFT JOIN rag_chunks r ON r.rowid = d.id WHERE r.rowid IS NULL"
            ).fetchone()[0]
            cx.execute("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')")
            apres = cx.execute(
                "SELECT COUNT(*) FROM rag_chunks_fts_docsize d "
                "LEFT JOIN rag_chunks r ON r.rowid = d.id WHERE r.rowid IS NULL"
            ).fetchone()[0]
            lignes = cx.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    except Exception as exc:
        return {"ok": False, "raison": "%s: %s" % (type(exc).__name__, str(exc)[:200])}

    res = {"ok": apres == 0, "orphelins_avant": avant, "orphelins_apres": apres,
           "lignes": lignes, "duree_s": round(_t.time() - t0, 1),
           "table": "rag_chunks_fts"}
    if verbeux:
        print("[fts] rebuild %s : %d orphelins -> %d, %d lignes, %.1f s"
              % ("OK" if res["ok"] else "INCOMPLET", avant, apres, lignes, res["duree_s"]))
    return res


def purge_rag_fts_fantomes(limite: int = 200_000, verbeux: bool = False) -> dict:
    """Archive PUIS supprime les entrees de `rag_fts` qui ne joignent plus a rien.

    POURQUOI CETTE FONCTION EXISTE. Supprimer un chunk de `rag_chunks` ne supprime
    PAS son entree lexicale : `rag_fts` est un index AUTONOME, personne ne le
    previent. La fuite est lente et silencieuse, et elle avait accumule 501 255
    entrees mortes au 2026-08-23 pour 1 328 447 chunks — soit 27 % de l'index. Un
    index gonfle de mort fausse les frequences documentaires de BM25, donc degrade
    le classement de TOUTES les recherches, pas seulement celles qui touchent un
    fantome. Le stock a ete purge ce jour-la ; SANS CETTE PASSE, il repart.

    Elle ne fait pas doublon avec `rebuild_fts_index` : celle-la RECOPIE les entrees
    existantes sans jointure, donc elle preserve les fantomes au lieu de les enlever
    (piege mesure le 2026-08-14). Ni avec `rebuild_chunks_fts_index`, qui vise
    l'AUTRE table et s'appuie sur la commande 'rebuild' de FTS5 — impossible ici,
    `rag_fts` n'etant pas a contenu externe : son texte n'existe QUE dans l'index.

    C'est aussi pourquoi on ARCHIVE avant de supprimer. Ces entrees portent le texte
    de chunks disparus de `rag_chunks` : pour certaines, c'est la derniere copie.
    Regle owner : rien ne se supprime dans la base. La suppression n'a lieu QUE si
    l'archive est complete — sinon on abandonne sans rien toucher.

    BORNEE, et elle le DIT. Au-dela de `limite` entrees, la passe s'arrete et rend
    `plafonne: True` : une troncature silencieuse se lirait comme un travail fini.
    """
    import time as _t

    t0 = _t.time()
    try:
        from nokido_agent.app.forge_db_path import db_path, open_writer
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "raison": "writer gouverne injoignable: %s: %s"
                                       % (type(exc).__name__, str(exc)[:160])}

    archive = "rag_fts_fantomes"

    # DETECTER EN LECTURE, N'ECRIRE QUE S'IL Y A A FAIRE (mesure 2026-08-23).
    # Le balayage de detection coute ~78 s et ne trouve RIEN la plupart des nuits.
    # Le faire depuis une connexion d'ECRITURE revenait a tenir un writer pendant
    # 78 s chaque nuit sur une base partagee avec le hub — un cout impose aux
    # voisins pour un travail qui n'existe pas. La sonde passe donc en mode=ro ; le
    # writer n'est ouvert que si la sonde a trouve quelque chose. La nuit rare ou il
    # y a du travail paie le balayage deux fois : c'est le bon sens du compromis.
    try:
        _sonde = sqlite3.connect("file:%s?mode=ro" % db_path(), uri=True, timeout=30)
        try:
            n_vus = _sonde.execute(
                "SELECT COUNT(*) FROM rag_fts f LEFT JOIN rag_chunks c "
                "ON c.id = f.chunk_id WHERE c.id IS NULL").fetchone()[0]
        finally:
            _sonde.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "raison": "sonde illisible: %s: %s"
                                       % (type(exc).__name__, str(exc)[:160]),
                "duree_s": round(_t.time() - t0, 1)}
    if n_vus == 0:
        return {"ok": True, "mortes": 0, "supprimees": 0,
                "duree_s": round(_t.time() - t0, 1)}

    try:
        with open_writer() as cx:
            cx.execute("PRAGMA temp_store=FILE")
            cx.execute("PRAGMA cache_size=-16000")
            cx.execute("DROP TABLE IF EXISTS temp.fts_morts")
            cx.execute(
                "CREATE TEMP TABLE fts_morts AS "
                "SELECT f.rowid AS rid, "
                "       CASE WHEN f.chunk_id IS NULL OR f.chunk_id = '' "
                "            THEN 'cle_absente' ELSE 'id_disparu' END AS motif "
                "FROM rag_fts f LEFT JOIN rag_chunks c ON c.id = f.chunk_id "
                "WHERE c.id IS NULL LIMIT %d" % int(limite))
            n = cx.execute("SELECT COUNT(*) FROM temp.fts_morts").fetchone()[0]
            if n == 0:
                return {"ok": True, "mortes": 0, "supprimees": 0,
                        "duree_s": round(_t.time() - t0, 1)}

            cx.execute("CREATE TABLE IF NOT EXISTS %s ("
                       " chunk_id TEXT, text TEXT, source TEXT, domain TEXT,"
                       " motif TEXT, archived_at TEXT)" % archive)
            avant = cx.execute("SELECT COUNT(*) FROM %s" % archive).fetchone()[0]
            cx.execute(
                "INSERT INTO %s(chunk_id, text, source, domain, motif, archived_at) "
                "SELECT f.chunk_id, f.text, f.source, f.domain, m.motif, datetime('now') "
                "FROM temp.fts_morts m JOIN rag_fts f ON f.rowid = m.rid" % archive)
            archivees = cx.execute("SELECT COUNT(*) FROM %s" % archive).fetchone()[0] - avant

            # GARDE : pas d'archive complete, pas de suppression.
            if archivees < n:
                return {"ok": False, "raison": "archive incomplete", "mortes": n,
                        "archivees": archivees, "supprimees": 0,
                        "duree_s": round(_t.time() - t0, 1)}

            rmin, rmax = cx.execute(
                "SELECT MIN(rid), MAX(rid) FROM temp.fts_morts").fetchone()
            supprimees, cur = 0, rmin
            while cur <= rmax:
                hi = cur + 50_000
                supprimees += cx.execute(
                    "DELETE FROM rag_fts WHERE rowid IN "
                    "(SELECT rid FROM temp.fts_morts WHERE rid >= ? AND rid < ?)",
                    (cur, hi)).rowcount or 0
                cur = hi
            par_motif = dict(cx.execute(
                "SELECT motif, COUNT(*) FROM temp.fts_morts GROUP BY motif").fetchall())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "raison": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                "duree_s": round(_t.time() - t0, 1)}

    res = {"ok": supprimees == n, "mortes": n, "archivees": archivees,
           "supprimees": supprimees, "par_motif": par_motif,
           "plafonne": n >= int(limite), "archive": archive,
           "duree_s": round(_t.time() - t0, 1)}
    if res["plafonne"]:
        # Mesure 2026-09-19 : cette ligne appelait `logger`, nom inexistant -> et
        # elle ne s'execute QUE dans le cas `plafonne`, c'est-a-dire exactement
        # quand il y a quelque chose a signaler. Le garde mourait sur son propre
        # journal (motif du 06/09).
        #
        # ⚠️ Premiere correction FAUSSE, gardee en memoire ici : j'ai ecrit `_lg`
        # parce que ce nom apparait L95 -- mais cet import est LOCAL a une autre
        # fonction, donc invisible d'ici. Voir un nom DANS LE FICHIER ne dit pas
        # qu'il est lie DANS LA PORTEE. On importe donc ici, ou l'on s'en sert.
        import logging as _journal  # noqa: PLC0415

        _journal.getLogger(__name__).warning(
            "[fts] purge PLAFONNEE a %d entrees : il en reste — "
            "la prochaine passe continuera", limite)
    if verbeux:
        print("[fts] purge fantomes : %d archivees, %d supprimees, %.1f s"
              % (archivees, supprimees, res["duree_s"]))
    return res


def read_lessons(last_n_chars: int = 3000) -> str:
    """Lit les dernieres lecons markdown - a appeler au debut d une session."""
    try:
        if _LESSONS.exists():
            content = _LESSONS.read_text(encoding="utf-8")
            return content[-last_n_chars:]
        return "Aucune lecon enregistree."
    except Exception as e:
        return "Erreur lecture lessons: " + str(e)


# =============================================================================
# SELF-TEST
# =============================================================================


if __name__ == "__main__":
    print("=== Test preflight_check hybride ===\n")

    tests = [
        ("creer module PII", "ajouter detection email telephone"),
        ("anonymize cloud", "avant envoi LLM externe"),
        ("creer forge_pii_detector", "nouveau module Python"),
        ("SemanticFirewall usage", "pre_flight redact"),
        ("nouvelle action random xyz", "rien de prevu"),
    ]

    for action, ctx in tests:
        print(f"> preflight_check('{action}', '{ctx}')")
        r = preflight_check(action, ctx)
        if r:
            print(f"  -> {r[:250]}")
        else:
            print("  -> (pas de warning)")
        print()

    # Test verbose sur une requete pointue
    print("=== Test preflight_check_verbose ===\n")
    v = preflight_check_verbose("creer module PII", "detection email")
    print(f"Tier utilise : {v['tier']}")
    for i, r in enumerate(v["results"][:3]):
        print(f"  #{i + 1} score={r['score']} source={r['source'][:40]}")
        print(f"       {r['preview'][:150]}")
        print()

    # Rebuild FTS pour les entrees non synchronisees
    print("=== Rebuild FTS ===")
    r = rebuild_fts_index()
    print(f"  {r}")
