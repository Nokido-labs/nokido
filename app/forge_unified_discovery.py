# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_unified_discovery
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_unified_discovery.py — Unified Discovery Engine
=======================================================
Remplace le simple web_search par un cycle complet :
  1. Fetch résultats web (DuckDuckGo/Brave/direct URL)
  2. Raffinage sémantique — extraction Markdown technique
  3. Ancrage local dans RAG SQLite avec tag #disco_unified
  4. Notification TUI — combien de pépites vectorisées

Usage :
  from forge_unified_discovery import unified_discovery
  result = unified_discovery("asyncio Windows SelectorEventLoopPolicy")

  # Depuis le Hub MCP :
  run(action='unified_discovery', code='query ici')
"""


import json
import re
import sqlite3
from datetime import datetime as _dt
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "embeddings.db"

# Tag de traçabilité
DISCO_TAG = "#disco_unified"


# =============================================================================
# REFINE AND ANCHOR — point d entrée depuis le Hub (résultats déjà fetchés)
# =============================================================================


def refine_and_anchor(
    query: str,
    raw_texts: list,
    collection: str = "disco",
    sources: list = None,
) -> dict:
    """
    Appelé par core.rag depuis le Hub avec des résultats déjà récupérés
    (par Claude via web_search ou autre source externe).

    raw_texts : liste de strings (snippets, paragraphes, docs)
    sources   : liste d URLs correspondantes (optionnel)
    Retourne  : {chunks_anchored, chunks_refined, tag, permanent}
    """
    sources = sources or ["disco:" + query[:40]] * len(raw_texts)
    results = []
    for i, text in enumerate(raw_texts):
        url = sources[i] if i < len(sources) else ""
        results.append(
            {
                "title": query[:60],
                "url": url,
                "snippet": str(text)[:400],
            }
        )
    chunks = _refine_to_chunks(query, results)
    anchored = _anchor_chunks(chunks, collection)

    if anchored > 0:
        try:
            from nokido_agent.app.nokido_core import get_core as _gc

            _gc().tui_notify(
                "Vectorisé " + str(anchored) + " pépite(s) RAG : " + query[:50],
                type="success",
                payload={"anchored": anchored, "collection": collection, "tag": DISCO_TAG},
            )
        except Exception:
            pass

    return {
        "query": query,
        "chunks_anchored": anchored,
        "chunks_refined": len(chunks),
        "tag": DISCO_TAG,
        "collection": collection,
        "permanent": anchored > 0,
        "message": str(anchored) + " pépite(s) ancrées." if anchored > 0 else "Aucun chunk pertinent.",
    }


# =============================================================================
# 1. WEB FETCHER — récupère le contenu brut
# =============================================================================


def _fetch_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    Fetch résultats web via DuckDuckGo API JSON (pas de clé requise).
    Fallback : Wikipedia REST API.
    Retourne liste de {title, url, snippet}.
    """
    import urllib.request, urllib.parse, json as _j

    results = []

    # Guard web search
    try:
        from nokido_agent.app.forge_web import is_web_search_enabled

        if not is_web_search_enabled({}):
            return []
    except ImportError:
        pass
    # 1. DuckDuckGo Instant Answer API
    try:
        encoded = urllib.parse.quote_plus(query)
        url = "https://api.duckduckgo.com/?q=" + encoded + "&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "LaForge/17.03"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _j.loads(r.read().decode("utf-8", errors="replace"))

        # Abstract
        if data.get("Abstract"):
            results.append(
                {
                    "title": data.get("Heading", query)[:120],
                    "url": data.get("AbstractURL", ""),
                    "snippet": data["Abstract"][:400],
                }
            )

        # Related topics
        for topic in data.get("RelatedTopics", [])[: max_results - 1]:
            if isinstance(topic, dict) and topic.get("Text"):
                url_t = topic.get("FirstURL", "")
                results.append(
                    {
                        "title": topic["Text"][:60],
                        "url": url_t,
                        "snippet": topic["Text"][:400],
                    }
                )
    except Exception:
        pass

    # 2. Fallback Wikipedia REST si peu de résultats
    if len(results) < 2:
        try:
            encoded = urllib.parse.quote(query.replace(" ", "_"))
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + encoded
            req = urllib.request.Request(url, headers={"User-Agent": "LaForge/17.03"})
            with urllib.request.urlopen(req, timeout=8) as r:
                wiki = _j.loads(r.read().decode("utf-8", errors="replace"))
            if wiki.get("extract"):
                results.append(
                    {
                        "title": wiki.get("title", "")[:120],
                        "url": wiki.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "snippet": wiki["extract"][:400],
                    }
                )
        except Exception:
            pass

    # 3. Fallback DuckDuckGo HTML simple
    if len(results) < 1:
        try:
            encoded = urllib.parse.quote_plus(query)
            url = "https://html.duckduckgo.com/html/?q=" + encoded
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="replace")
            snippets = re.findall(r'class="result__snippet">([^<]+)', html)
            titles = re.findall(r'class="result__a"[^>]*>([^<]+)', html)
            for i, snip in enumerate(snippets[:max_results]):
                results.append(
                    {
                        "title": titles[i].strip() if i < len(titles) else query,
                        "url": "",
                        "snippet": snip.strip()[:400],
                    }
                )
        except Exception:
            pass

    return results[:max_results]


# =============================================================================
# 2. MARKDOWN REFINER — transforme en chunks techniques
# =============================================================================


def _refine_to_chunks(query: str, results: List[Dict]) -> List[Dict]:
    """
    Transforme les résultats bruts en chunks Markdown techniques.
    Filtre le bruit (pub, nav, boilerplate).
    Retourne liste de {text, source, score}.
    """
    chunks = []
    keywords = set(query.lower().split())

    for r in results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        url = r.get("url", "")

        # Score de pertinence — mots-clés présents
        combined = (title + " " + snippet).lower()
        score = sum(1 for kw in keywords if kw in combined and len(kw) > 3)

        if score == 0 or len(snippet) < 30:
            continue

        # Formater en Markdown technique propre
        text = (
            "## "
            + title[:100]
            + chr(10)
            + "**Source:** "
            + url[:100]
            + chr(10)
            + "**Query:** `"
            + query[:80]
            + "` "
            + DISCO_TAG
            + chr(10)
            + chr(10)
            + snippet.strip()
        )

        chunks.append(
            {
                "text": text,
                "source": url or "disco:" + query[:40],
                "score": score,
            }
        )

    # Trier par pertinence
    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks


# =============================================================================
# 3. RAG ANCHOR — insère dans SQLite avec déduplication
# =============================================================================


def _anchor_chunks(chunks: List[Dict], collection: str = "disco") -> int:
    """
    Insère les chunks dans rag_chunks avec tag #disco_unified.
    Déduplique par source URL.
    Retourne le nombre de chunks insérés.
    """
    if not chunks:
        return 0

    try:
        conn = sqlite3.connect(str(_DB))
        conn.execute("PRAGMA journal_mode=WAL")
        # index PARTIEL sur les chunks disco (role_hint='disco', qq centaines) : sert
        # le snapshot et _check_rag_cache SANS full-scan `source LIKE '%disco%'` (qui
        # matchait surtout du bruit incidentel : forge_agents.py#discover, etc.).
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_disco "
                         "ON rag_chunks(role_hint) WHERE role_hint='disco'")
        except Exception:
            pass

        # Récupérer les sources déjà présentes
        # Déduplique toutes les sources — pas seulement disco
        _sources_to_check = [c["source"] for c in chunks if c.get("source")]
        if _sources_to_check:
            placeholders = ",".join("?" * len(_sources_to_check))
            existing = {
                row[0]
                for row in conn.execute(
                    f"SELECT source FROM rag_chunks WHERE source IN ({placeholders})", _sources_to_check
                ).fetchall()
            }
        else:
            existing = set()

        inserted = 0
        inserted_sources = []
        for chunk in chunks:
            if chunk["source"] in existing:
                continue  # Déduplique

            meta = json.dumps(
                {
                    "ring": 2,
                    "trust_score": min(0.5 + chunk["score"] * 0.1, 0.9),
                    "consensus_level": "disco_unified",
                    "collection": collection,
                    "tags": [DISCO_TAG, "web", collection],
                    "disco_date": _dt.now().strftime("%Y-%m-%d"),
                }
            )

            # 2026-09-12 : sans `id` (TEXT PRIMARY KEY) la clef restait NULLE et
            # la deduplication ne pouvait pas operer.
            from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

            conn.execute(
                "INSERT INTO rag_chunks (id, text, source, domain, role_hint, meta) "
                "VALUES (?,?,?,?,?,?)",
                (_cid(chunk["source"], chunk["text"]), chunk["text"],
                 chunk["source"], "general", "disco", meta),
            )
            inserted += 1
            inserted_sources.append(chunk["source"])
            existing.add(chunk["source"])

        conn.commit()

        # Auto-snapshot : on snapshot EXACTEMENT les chunks qu'on vient d'inserer
        # (source IN, indexe par idx_rag_source), au lieu d'un `source LIKE '%disco%'
        # ORDER BY id DESC` qui full-scannait 1.17M lignes, matchait du bruit
        # incidentel, et triait par id=HASH (ordre non chronologique).
        if inserted > 0 and inserted_sources:
            try:
                seq = (conn.execute("SELECT COALESCE(MAX(sequence_id),0) FROM rag_snapshots").fetchone()[0] or 0) + 1
                ph = ",".join("?" * len(inserted_sources))
                conn.execute(
                    "INSERT INTO rag_snapshots (timecode, session_id, agent_id, chunk_id, text, source, domain, meta, op, sequence_id) "
                    "SELECT datetime('now'), 'disco', 'unified_discovery', id, text, source, domain, meta, 'disco_anchor', ? "
                    f"FROM rag_chunks WHERE source IN ({ph})",
                    [seq] + inserted_sources,
                )
                conn.commit()
            except Exception:
                pass

        conn.close()
        return inserted

    except Exception as e:
        return 0


# =============================================================================
# 4. UNIFIED DISCOVERY — point d'entrée principal
# =============================================================================


def unified_discovery(
    query: str,
    collection: str = "disco",
    max_results: int = 5,
    notify_core: bool = True,
) -> Dict:
    """
    Cycle complet : fetch → refine → anchor → notify.

    Retourne un JSON avec statut vectorisation :
    {
      "query": str,
      "results_fetched": int,
      "chunks_anchored": int,
      "top_chunks": [...],
      "collection": str,
      "tag": "#disco_unified",
      "permanent": bool,
    }
    """
    # 1. Vérifier si déjà dans RAG (évite requête web inutile)
    existing = _check_rag_cache(query)
    if existing:
        return {
            "query": query,
            "from_cache": True,
            "results_fetched": 0,
            "chunks_anchored": 0,
            "top_chunks": existing[:3],
            "collection": collection,
            "tag": DISCO_TAG,
            "permanent": True,
            "message": "Déjà dans le RAG local — pas de requête web.",
        }

    # 2. Fetch web
    raw_results = _fetch_web(query, max_results)

    # 3. Raffinage → chunks Markdown
    chunks = _refine_to_chunks(query, raw_results)

    # 4. Ancrage RAG
    anchored = _anchor_chunks(chunks, collection)

    # 5. Notification TUI
    if notify_core and anchored > 0:
        try:
            from nokido_agent.app.nokido_core import get_core as _gc

            _gc().tui_notify(
                "Vectorisé " + str(anchored) + " pépite(s) RAG : " + query[:50],
                type="success",
                payload={"anchored": anchored, "collection": collection, "tag": DISCO_TAG},
            )
        except Exception:
            pass

    # 6. Résultat
    return {
        "query": query,
        "from_cache": False,
        "results_fetched": len(raw_results),
        "chunks_anchored": anchored,
        "chunks_refined": len(chunks),
        "top_chunks": [c["text"][:200] for c in chunks[:3]],
        "collection": collection,
        "tag": DISCO_TAG,
        "permanent": anchored > 0,
        "message": (
            str(anchored) + " pépite(s) vectorisée(s) dans RAG local."
            if anchored > 0
            else "Aucun chunk pertinent extrait."
        ),
    }


# =============================================================================
# 5. RAG CACHE CHECK — priorité locale avant web
# =============================================================================


def _check_rag_cache(query: str, min_score: int = 2) -> Optional[List[str]]:
    """
    Cherche dans le RAG si la query a déjà été indexée.
    Retourne les chunks pertinents ou None.
    """
    try:
        conn = sqlite3.connect(str(_DB))
        # role_hint='disco' (index partiel idx_rag_disco) = les VRAIS chunks de
        # discovery, au lieu de `source LIKE '%disco%'` qui full-scannait 1.17M lignes
        # et matchait surtout du bruit incidentel (forge_agents.py#discover, etc.).
        rows = conn.execute("SELECT text FROM rag_chunks WHERE role_hint='disco' LIMIT 50").fetchall()
        conn.close()

        keywords = set(query.lower().split())
        scored = []
        for (text,) in rows:
            score = sum(1 for kw in keywords if kw in text.lower() and len(kw) > 3)
            if score >= min_score:
                scored.append((score, text[:300]))

        if not scored:
            return None

        scored.sort(reverse=True)
        return [t for _, t in scored[:3]]

    except Exception:
        return None
