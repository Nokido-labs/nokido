import pytest
import asyncio
from app.api_facade import get_async_facade

@pytest.mark.asyncio
async def test_facade_rag_query():
    """Vérifie que la façade branche correctement sur le RAG."""
    facade = get_async_facade()
    # On mock le RAG engine pour éviter les dépendances lourdes en test
    # (Ou on teste le branchement si le module est présent)
    results = await facade.rag_query_async("test query", k=1)
    assert isinstance(results, list)

@pytest.mark.asyncio
async def test_facade_agents_status():
    """Vérifie que la façade retourne le statut des agents."""
    facade = get_async_facade()
    status = await facade.agents_status_async()
    assert "status" in status
    assert status["status"] in ("ok", "unavailable", "error")

@pytest.mark.asyncio
async def test_facade_cortex_integration():
    """Vérifie que le Cortex Hybride est bien injecté."""
    facade = get_async_facade()
    # get_facade() initialise le cortex
    sync_facade = facade._sync
    assert sync_facade.cortex is not None
    
    # Test Preflight
    ok, ctx = await sync_facade.preflight_async("test", {"files": {"test.py": "print('hello')" * 100}})
    assert ok is True
    assert "ast_compressed" in ctx

@pytest.mark.asyncio
async def test_facade_scan_code():
    """Vérifie la fonction scan_code_async."""
    facade = get_async_facade()
    res = await facade.scan_code_async("import os\nos.system('rm -rf /')")
    assert isinstance(res, dict)
    assert "safe" in res

@pytest.mark.asyncio
async def test_facade_ask_llm():
    """Vérifie que la façade dispatche correctement les requêtes LLM."""
    facade = get_async_facade()
    # Pour éviter un vrai call LLM coûteux en test unitaire, on s'assure
    # que la façade gère au moins gracieusement les backends bidons.
    res = await facade.ask_llm_async("test", backend="unknown_backend")
    assert "[facade-async] backend inconnu" in res

@pytest.mark.asyncio
async def test_facade_list_models():
    """Vérifie la fonction list_models_async."""
    facade = get_async_facade()
    models = await facade.list_models_async("unknown_backend")
    assert isinstance(models, list)
    assert len(models) == 0
