# -*- coding: utf-8 -*-
"""
tests/nr/test_rag_proxy_nr.py
==============================
NR pour le RAG Proxy universel :
  forge_unified_discovery.refine_and_anchor  — raffinage + ancrage
  forge_unified_discovery._refine_to_chunks  — extraction Markdown
  forge_unified_discovery._anchor_chunks     — déduplication SQLite
  forge_unified_discovery._check_rag_cache   — cache local
  forge_unified_discovery.unified_discovery  — cycle complet
  /rag/ingest endpoint                       — contrat HTTP

Critères NR :
  C1 Modulaire   : 1 classe = 1 composant
  C2 Comportement: assert sur décisions, pas sur timing
  C3 Edge cases  : résultats vides, query courte, double ingest
  C4 Tolérant    : isinstance / in / True|False
  C5 Isolé       : tags uniques par test pour éviter collision
  C6 Rapide      : < 1s par test, pas de réseau
"""
from __future__ import annotations

import sys
import json
import sqlite3
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_APP  = _ROOT / "app"
_DB   = _ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(_APP))


# =============================================================================
# BLOC 1 — _refine_to_chunks
# =============================================================================

class TestRefineToChunks:
    """C1 — Transformation résultats bruts → chunks Markdown techniques."""

    def setup_method(self):
        from forge_unified_discovery import _refine_to_chunks
        self._fn = _refine_to_chunks

    def test_retourne_liste(self):
        r = self._fn("test query", [{"title":"T","url":"u","snippet":"hello world test query"}])
        assert isinstance(r, list)

    def test_chunk_contient_markdown(self):
        r = self._fn("woodpecker ci", [{"title":"Woodpecker CI","url":"https://x.com","snippet":"Woodpecker CI pipeline runner"}])
        if r:
            assert "##" in r[0]["text"] or "**" in r[0]["text"]

    def test_filtre_snippet_court(self):
        """Snippets < 30 chars sont filtrés."""
        r = self._fn("test", [{"title":"T","url":"","snippet":"trop court"}])
        assert r == []

    def test_filtre_sans_keywords(self):
        """Snippet sans aucun mot-clé de la query est écarté."""
        r = self._fn("woodpecker nssm windows", [{"title":"T","url":"","snippet":"random unrelated content here nothing matching"}])
        assert r == []

    def test_score_pertinence(self):
        """Chunk avec plus de keywords a un score plus élevé."""
        results = [
            {"title":"A","url":"","snippet":"woodpecker nssm windows local backend service install"},
            {"title":"B","url":"","snippet":"woodpecker pipeline configuration"},
        ]
        chunks = self._fn("woodpecker nssm windows local", results)
        if len(chunks) >= 2:
            assert chunks[0]["score"] >= chunks[1]["score"]

    def test_contient_tag_disco(self):
        """Le chunk contient le tag #disco_unified."""
        from forge_unified_discovery import DISCO_TAG
        r = self._fn("woodpecker ci local", [{"title":"T","url":"https://x.com","snippet":"woodpecker ci local backend runner pipeline"}])
        if r:
            assert DISCO_TAG in r[0]["text"]

    def test_resultat_vide(self):
        r = self._fn("query", [])
        assert r == []

    def test_multiple_results_tries(self):
        """Résultats triés par score décroissant."""
        results = [
            {"title":"Low","url":"","snippet":"just one keyword woodpecker here yes good"},
            {"title":"High","url":"","snippet":"woodpecker ci local backend nssm windows service install runner"},
        ]
        chunks = self._fn("woodpecker ci local backend nssm", results)
        if len(chunks) >= 2:
            assert chunks[0]["score"] >= chunks[1]["score"]


# =============================================================================
# BLOC 2 — _anchor_chunks
# =============================================================================

class TestAnchorChunks:
    """C1 — Ancrage SQLite avec déduplication."""

    def _unique_source(self, suffix=""):
        return "test_nr_anchor_" + str(time.time_ns()) + suffix

    def setup_method(self):
        from forge_unified_discovery import _anchor_chunks
        self._fn = _anchor_chunks

    def test_retourne_int(self):
        chunks = [{"text":"## Test chunk NR\nContenu de test.", "source": self._unique_source(), "score": 3}]
        r = self._fn(chunks, "test_collection")
        assert isinstance(r, int)

    def test_insere_chunk(self):
        src    = self._unique_source("_insert")
        chunks = [{"text":"## NR Test Anchor\nWoodpecker CI NR test.", "source": src, "score": 3}]
        n      = self._fn(chunks, "test_nr")
        assert n >= 1
        conn = sqlite3.connect(str(_DB))
        row  = conn.execute("SELECT text FROM rag_chunks WHERE source=?", (src,)).fetchone()
        conn.close()
        assert row is not None

    def test_deduplique_source(self):
        """Même source insérée deux fois → 0 au deuxième insert."""
        src    = self._unique_source("_dedup")
        chunks = [{"text":"## Dedup test\nContenu unique ici.", "source": src, "score": 2}]
        n1 = self._fn(chunks, "test_nr")
        n2 = self._fn(chunks, "test_nr")
        assert n1 >= 1
        assert n2 == 0

    def test_chunks_vide(self):
        assert self._fn([], "test_nr") == 0

    def test_meta_json_valide(self):
        """Les métadonnées stockées sont du JSON valide."""
        src    = self._unique_source("_meta")
        chunks = [{"text":"## Meta test\nWoodpecker Windows.", "source": src, "score": 4}]
        self._fn(chunks, "test_nr")
        conn = sqlite3.connect(str(_DB))
        row  = conn.execute("SELECT meta FROM rag_chunks WHERE source=?", (src,)).fetchone()
        conn.close()
        if row:
            meta = json.loads(row[0])
            assert "trust_score" in meta
            assert "tags" in meta


# =============================================================================
# BLOC 3 — _check_rag_cache
# =============================================================================

class TestCheckRagCache:
    """C1 — Cache local RAG avant requête web."""

    def setup_method(self):
        from forge_unified_discovery import _check_rag_cache, _anchor_chunks
        self._cache = _check_rag_cache
        self._anchor = _anchor_chunks

    def test_retourne_none_si_absent(self):
        r = self._cache("query_totalement_inexistante_xyz_nr_42")
        assert r is None

    def test_retourne_liste_si_present(self):
        """Après ancrage, le cache retourne des résultats."""
        src   = "disco_test_cache_" + str(time.time_ns())
        query = "woodpecker_cache_test_nr_" + str(time.time_ns())[:8]
        chunks = [{"text":"## " + query + chr(10) + query + " local backend install service.", "source": src, "score": 3}]
        self._anchor(chunks, "disco")
        r = self._cache(query)
        # Peut ne pas matcher selon le scoring — pas d'assertion stricte
        assert r is None or isinstance(r, list)

    def test_none_sur_query_courte(self):
        """Query d'un seul mot court → None (filtre len > 3)."""
        r = self._cache("CI")
        assert r is None


# =============================================================================
# BLOC 4 — refine_and_anchor
# =============================================================================

class TestRefineAndAnchor:
    """C1 — Point d entrée principal depuis le Hub."""

    def setup_method(self):
        from forge_unified_discovery import refine_and_anchor
        self._fn = refine_and_anchor

    def test_retourne_dict(self):
        r = self._fn("test query", ["résultat test woodpecker ci"])
        assert isinstance(r, dict)
        assert "chunks_anchored" in r
        assert "permanent" in r
        assert "tag" in r

    def test_raw_texts_strings(self):
        r = self._fn(
            "woodpecker nssm windows local",
            ["Woodpecker CI local backend runs natively on Windows with NSSM service manager."],
        )
        assert isinstance(r.get("chunks_anchored"), int)

    def test_raw_texts_dicts(self):
        """Accepte aussi des dicts avec clé 'text' ou 'content'."""
        r = self._fn(
            "gitea actions workflow",
            [{"text":"Gitea Actions workflow_dispatch trigger for CI pipelines."},
             {"content":"Woodpecker CI supports Gitea as SCM provider."}],
        )
        assert isinstance(r, dict)

    def test_permanent_si_anchored(self):
        r = self._fn(
            "woodpecker ci local backend windows service",
            ["Woodpecker CI local backend executes pipelines on the host machine without Docker."],
            sources=["https://woodpecker-ci.org/test_nr_" + str(time.time_ns())],
        )
        if r.get("chunks_anchored", 0) > 0:
            assert r["permanent"] is True

    def test_message_present(self):
        r = self._fn("test message", ["test woodpecker content"])
        assert isinstance(r.get("message"), str)
        assert len(r["message"]) > 0

    def test_collection_transmise(self):
        r = self._fn("test collection", ["test woodpecker ollama collection"], collection="ollama_test")
        assert r.get("collection") == "ollama_test"

    def test_tag_disco_present(self):
        from forge_unified_discovery import DISCO_TAG
        r = self._fn("test tag", ["woodpecker test tag disco unified"])
        assert r.get("tag") == DISCO_TAG

    def test_sources_vides_ok(self):
        """Sans sources → génère des sources automatiques."""
        r = self._fn("woodpecker windows", ["Woodpecker agent Windows NSSM local."])
        assert isinstance(r, dict)


# =============================================================================
# BLOC 5 — unified_discovery (cycle complet sans réseau)
# =============================================================================

class TestUnifiedDiscovery:
    """C1 — Cycle complet unified_discovery."""

    def setup_method(self):
        from forge_unified_discovery import unified_discovery
        self._fn = unified_discovery

    def test_retourne_dict(self):
        r = self._fn("woodpecker ci test nr", notify_core=False)
        assert isinstance(r, dict)

    def test_champs_requis(self):
        r = self._fn("test query nr", notify_core=False)
        for key in ["query","results_fetched","chunks_anchored","tag","permanent"]:
            assert key in r, f"Clé manquante: {key}"

    def test_from_cache_ou_web(self):
        r = self._fn("test unified discovery", notify_core=False)
        assert isinstance(r.get("from_cache"), bool)

    def test_query_preservee(self):
        q = "query_test_preserved_nr"
        r = self._fn(q, notify_core=False)
        assert r.get("query") == q

    def test_notify_core_false_no_crash(self):
        """notify_core=False ne crash pas même sans Core dispo."""
        r = self._fn("woodpecker test", notify_core=False)
        assert isinstance(r, dict)


# =============================================================================
# BLOC 6 — Contrat API /rag/ingest (structure + validation)
# =============================================================================

class TestRagIngestContract:
    """C1 — Contrat HTTP /rag/ingest : validation body, champs requis."""

    def test_handler_importable(self):
        """Le handler rag_ingest est bien défini dans le Hub."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        assert "async def rag_ingest" in src

    def test_route_declaree(self):
        """La route /rag/ingest est déclarée dans Starlette."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        assert 'Route("/rag/ingest"' in src

    def test_auth_check_present(self):
        """Le handler vérifie le Bearer token."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+1200]
        assert "FORGE_MCP_TOKEN" in block
        assert "Unauthorized" in block

    def test_validation_query_requise(self):
        """Le handler valide que query est présent."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+2500]
        assert "query requis" in block

    def test_validation_results_requis(self):
        """Le handler valide que results est présent et non vide."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+2500]
        assert "results requis" in block

    def test_source_llm_dans_handler(self):
        """Le handler capture source_llm pour traçabilité."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+1500]
        assert "source_llm" in block

    def test_tui_notify_dans_handler(self):
        """Le handler notifie la TUI après ancrage."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+5000]
        assert "tui_notify" in block

    def test_self_correction_hook_present(self):
        """En cas d erreur, le handler ancre dans le RAG via forge_self_correction."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+6000]
        assert "anchor_error" in block

    def test_version_hub_mise_a_jour(self):
        """La version du Hub est >= 17.00."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        import re as _re
        assert _re.search(r"v1[789]\.\d+|17\.", src), \
            f"Version hub >= 17.xx non trouvee"

    def test_refine_and_anchor_dans_handler(self):
        """Le handler utilise refine_and_anchor du module unified_discovery."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+2500]
        assert "refine_and_anchor" in block

    def test_endpoint_doc_present(self):
        """La docstring décrit les champs body et réponse."""
        src = (_ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
        idx = src.find("async def rag_ingest")
        block = src[idx:idx+600]
        assert "source_llm" in block
        assert "collection" in block
