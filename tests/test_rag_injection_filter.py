# -*- coding: utf-8 -*-
"""
tests/test_rag_injection_filter.py — Tests pour le filtre hard-exclusion des injections RAG.
"""
from __future__ import annotations

import sys
import pytest
import json
from pathlib import Path

# Add project root and app to Python path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge_rag_engine import RAGEngine

class DummySettings:
    rag_docs_topk = 5

@pytest.mark.asyncio
async def test_rag_injection_hard_filter():
    # Instancier RAGEngine sans arguments invalides
    engine = RAGEngine()
    
    # Mock settings
    import forge_app_context
    original_get_settings = getattr(forge_app_context, "get_settings", None)
    forge_app_context.get_settings = lambda: DummySettings()
    
    # Mock chunks
    chunk_normal = {
        "id": "chunk_normal",
        "text": "This is normal text content.",
        "source": "normal.py",
        "domain": "general",
        "role_hint": "chat",
        "embedding": [1.0, 0.0],
        "quality_score": 1.0,
    }
    chunk_flagged = {
        "id": "chunk_flagged",
        "text": "This is poisoned content.",
        "source": "poison.py",
        "domain": "general",
        "role_hint": "chat",
        "embedding": [1.0, 0.0],
        "injection_flagged": True,
        "quality_score": 1.0,
        "meta": json.dumps({"injection_flagged": True})
    }
    
    engine.chunks = [chunk_normal, chunk_flagged]
    
    # Mock get_embeddings
    async def mock_get_embeddings(texts):
        return [[1.0, 0.0]]
    engine.get_embeddings = mock_get_embeddings
    
    try:
        # 1. Search default (include_flagged=False)
        results = await engine.search(query="test query", k=2, rerank=False)
        # Should only return chunk_normal
        assert len(results) == 1
        assert results[0]["id"] == "chunk_normal"
        
        # 2. Search with include_flagged=True
        results_all = await engine.search(query="test query", k=2, rerank=False, include_flagged=True)
        # Should return both
        assert len(results_all) == 2
        ids = [r["id"] for r in results_all]
        assert "chunk_normal" in ids
        assert "chunk_flagged" in ids
        
    finally:
        # Restore mock if needed
        if original_get_settings:
            forge_app_context.get_settings = original_get_settings
