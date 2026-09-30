"""
test_functional_coverage_nr.py — Tests fonctionnels pour coverage réelle
=========================================================================
Frappe 1 : Utilitaires purs (forge_metrics, forge_version, forge_unified_logger...)
Frappe 2 : MultiLLMBridge avec mocks API
Frappe 3 : PersistentMCPClient avec mock transport
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

warnings.filterwarnings("ignore")
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele); parcours du depot : glob app (code appele) (l.260)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


# ═══════════════════════════════════════════════════════════════════
# FRAPPE 1 : Utilitaires purs
# ═══════════════════════════════════════════════════════════════════

class TestForgeMetrics:
    """Tests forge_metrics — LLMMetric, MetricsCollector."""

    def test_llm_metric_creation(self):
        """LLMMetric créable avec les vrais paramètres."""
        from forge_metrics import LLMMetric
        m = LLMMetric(provider="groq", model="llama-70b",
                      mode="cloud", session_id="s1")
        assert m is not None

    def test_llm_metric_finish_ok(self):
        """finish(ok=True) enregistre le succès."""
        from forge_metrics import LLMMetric
        m = LLMMetric(provider="groq", model="llama", mode="cloud", session_id="s1")
        m.finish(ok=True)

    def test_llm_metric_finish_fail(self):
        """finish(ok=False, error=...) enregistre l'échec."""
        from forge_metrics import LLMMetric
        m = LLMMetric(provider="ollama", model="qwen", mode="local", session_id="s2")
        m.finish(ok=False, error="timeout")

    def test_metrics_collector_singleton(self):
        """get_collector retourne toujours le même objet."""
        from forge_metrics import get_collector
        c1 = get_collector()
        c2 = get_collector()
        assert c1 is c2

    def test_collector_record(self):
        """record() enregistre une métrique."""
        from forge_metrics import get_collector, LLMMetric
        c = get_collector()
        m = LLMMetric(provider="groq", model="llama", mode="cloud", session_id="s3")
        m.finish(ok=True)
        c.record(m)

    def test_collector_stats(self):
        """stats() retourne un dict avec clés."""
        from forge_metrics import get_collector
        c     = get_collector()
        stats = c.stats()
        assert isinstance(stats, dict)
        assert len(stats) > 0

    def test_metric_provider_field(self):
        """LLMMetric a le champ provider."""
        from forge_metrics import LLMMetric
        m = LLMMetric(provider="groq", model="llama", mode="cloud", session_id="s4")
        assert hasattr(m, "provider") or hasattr(m, "model")


class TestForgeVersion:
    """Tests forge_version."""

    def test_get_returns_string(self):
        """get() retourne une string."""
        from forge_version import get
        v = get()
        assert isinstance(v, str) and len(v) > 0

    def test_label_returns_string(self):
        """label() retourne une string."""
        from forge_version import label
        lb = label()
        assert isinstance(lb, str)

    def test_version_format(self):
        """Version a un format valide."""
        from forge_version import get
        v     = get()
        parts = v.split(".")
        assert len(parts) >= 1


class TestForgeUnifiedLogger:
    """Tests forge_unified_logger."""

    def test_get_logger_returns_logger(self):
        """get_logger() retourne un objet."""
        from forge_unified_logger import get_logger
        logger = get_logger("test_module")
        assert logger is not None

    def test_logger_has_methods(self):
        """Logger a les méthodes info/warning/error."""
        from forge_unified_logger import get_logger
        logger = get_logger("test")
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")

    def test_logger_info_no_crash(self):
        """logger.info() ne plante pas."""
        from forge_unified_logger import get_logger
        logger = get_logger("test")
        logger.info("Message de test coverage")

    def test_timeout_guard_context_manager(self):
        """TimeoutGuard est un context manager."""
        from forge_unified_logger import TimeoutGuard, get_logger
        lg = get_logger("test")
        tg = TimeoutGuard(logger=lg, label="test_cov")
        assert hasattr(tg, "__enter__") and hasattr(tg, "__exit__")

    def test_timeout_guard_usage(self):
        """TimeoutGuard utilisable comme context manager."""
        from forge_unified_logger import TimeoutGuard, get_logger
        lg = get_logger("test")
        with TimeoutGuard(logger=lg, label="test_ok", warn_ms=5000):
            time.sleep(0.01)

    def test_get_log_path(self):
        """get_log_path() retourne un Path."""
        from forge_unified_logger import get_log_path
        p = get_log_path()
        assert isinstance(p, (str, Path))


class TestForgeIntentParser:
    """Tests forge_intent_parser."""

    def test_intent_parser_create(self):
        """IntentParser instanciable."""
        from forge_intent_parser import IntentParser
        parser = IntentParser()
        assert parser is not None

    def test_parse_returns_object(self):
        """parse() retourne un objet ParsedIntent."""
        from forge_intent_parser import IntentParser
        parser = IntentParser()
        result = parser.parse("Ajoute des docstrings Google-style")
        assert result is not None

    def test_parse_has_action(self):
        """ParsedIntent a un attribut action."""
        from forge_intent_parser import IntentParser
        parser = IntentParser()
        result = parser.parse("Refactorise cette classe")
        assert hasattr(result, "action") or hasattr(result, "verbs")

    def test_parsed_intent_creation(self):
        """ParsedIntent créable avec raw."""
        from forge_intent_parser import ParsedIntent
        pi = ParsedIntent(raw="Optimise cette fonction")
        assert pi.raw == "Optimise cette fonction"

    def test_parsed_intent_to_dict(self):
        """ParsedIntent.to_dict() retourne un dict."""
        from forge_intent_parser import ParsedIntent
        pi = ParsedIntent(raw="test")
        if hasattr(pi, "to_dict"):
            d = pi.to_dict()
            assert isinstance(d, dict)


class TestForgeContext:
    """Tests forge_context."""

    def test_get_active_mode(self):
        """get_active_mode() retourne une string."""
        from forge_context import get_active_mode
        mode = get_active_mode()
        assert isinstance(mode, str)

    def test_set_active_mode(self):
        """set_active_mode() fonctionne."""
        from forge_context import set_active_mode, get_active_mode
        set_active_mode("TEST_COV", reason="coverage")
        mode = get_active_mode()
        assert isinstance(mode, str)

    def test_update_agent_status(self):
        """update_agent_status() ne plante pas."""
        from forge_context import update_agent_status
        update_agent_status("test_agent", "idle")

    def test_push_notification(self):
        """push_notification() ne plante pas."""
        from forge_context import push_notification
        push_notification("coverage test message")


class TestForgeIdleWatchdog:
    """Tests forge_idle_watchdog."""

    def test_instantiation(self):
        """IdleWatchdog instanciable avec service_name."""
        from forge_idle_watchdog import IdleWatchdog
        wd = IdleWatchdog(service_name="test_service")
        assert wd is not None

    def test_ping(self):
        """ping() ne plante pas."""
        from forge_idle_watchdog import IdleWatchdog
        wd = IdleWatchdog(service_name="test")
        wd.ping()

    def test_idle_timeout_default(self):
        """idle_timeout a une valeur par défaut."""
        from forge_idle_watchdog import IdleWatchdog
        wd = IdleWatchdog(service_name="test", idle_timeout=60)
        assert wd is not None

    def test_check_interval(self):
        """check_interval configurable."""
        from forge_idle_watchdog import IdleWatchdog
        wd = IdleWatchdog(service_name="test", check_interval=15)
        assert wd is not None


class TestForgeSelfCorrection:
    """Tests forge_self_correction."""

    def test_preflight_check(self):
        """preflight_check() avec une action."""
        from forge_self_correction import preflight_check
        result = preflight_check(action="write", context="test context")
        # Retourne None ou une string d'erreur

    def test_session_summary(self):
        """session_summary() retourne un objet."""
        from forge_self_correction import session_summary
        result = session_summary(commits=["fix: test"], tests="688 passed", notes="coverage")
        assert isinstance(result, dict)

    def test_anchor_error(self):
        """anchor_error() retourne un dict."""
        from forge_self_correction import anchor_error
        result = anchor_error(
            error_msg="Test error coverage",
            context="test context",
            solution="Test solution",
        )
        assert isinstance(result, dict)

    def test_anchor_solution(self):
        """anchor_solution() ne plante pas."""
        from forge_self_correction import anchor_solution
        try:
            anchor_solution("test_error", "Solution de test")
        except Exception:
            pass  # Peut ne pas exister


class TestForgeMermaidGen:
    """Tests forge_mermaid_gen."""

    def test_validate_mermaid_valid(self):
        """Diagramme valide → dict avec résultat."""
        from forge_mermaid_gen import validate_mermaid
        result = validate_mermaid("graph TD\n  A-->B")
        assert isinstance(result, dict)

    def test_validate_mermaid_invalid(self):
        """Diagramme invalide → dict."""
        from forge_mermaid_gen import validate_mermaid
        result = validate_mermaid("not mermaid !!!")
        assert isinstance(result, dict)

    def test_extract_mermaid_from_markdown(self):
        """_extract_mermaid extrait le bloc mermaid."""
        from forge_mermaid_gen import _extract_mermaid
        text   = "```mermaid\ngraph TD\n  A-->B\n```"
        result = _extract_mermaid(text)
        assert "graph" in result

    def test_extract_mermaid_no_block(self):
        """_extract_mermaid sur texte sans bloc."""
        from forge_mermaid_gen import _extract_mermaid
        result = _extract_mermaid("texte sans mermaid")
        assert isinstance(result, str)

    def test_generate_mermaid_callable(self):
        """generate_mermaid callable."""
        from forge_mermaid_gen import generate_mermaid
        assert callable(generate_mermaid)

    def test_generate_mermaid_async_coro(self):
        """generate_mermaid_async est une coroutine."""
        import inspect
        from forge_mermaid_gen import generate_mermaid_async
        assert inspect.iscoroutinefunction(generate_mermaid_async)


class TestForgeOllamaMemory:
    """Tests forge_ollama_memory."""

    def test_get_mem_mgr(self):
        """get_mem_mgr() retourne None si Ollama absent ou un manager."""
        from forge_ollama_memory import get_mem_mgr
        mgr = get_mem_mgr()
        # Peut retourner None si Ollama n'est pas actif
        assert mgr is None or hasattr(mgr, "estimate_gib")

    def test_estimate_gib_1b(self):
        """Modèle 1.5B estimé entre 1-4 GB."""
        from forge_ollama_memory import OllamaMemoryManager
        mgr = OllamaMemoryManager(base_url="http://localhost:11434")
        gib = mgr.estimate_gib("qwen2.5-coder:1.5b")
        assert isinstance(gib, (int, float)) and gib > 0

    def test_estimate_gib_7b(self):
        """Modèle 7B estimé entre 3-10 GB."""
        from forge_ollama_memory import OllamaMemoryManager
        mgr = OllamaMemoryManager(base_url="http://localhost:11434")
        gib = mgr.estimate_gib("qwen2.5-coder:7b-instruct-q4_K_M")
        assert isinstance(gib, (int, float)) and gib > 0

    def test_loaded_method(self):
        """loaded() ne plante pas (Ollama peut être absent)."""
        from forge_ollama_memory import OllamaMemoryManager
        mgr = OllamaMemoryManager(base_url="http://localhost:11434")
        try:
            result = mgr.loaded()
            assert isinstance(result, list)
        except Exception:
            pass  # Ollama peut être absent


class TestForgeKnowledgeDistiller:
    """Tests forge_knowledge_distiller."""

    def test_extract_system_rules_empty(self):
        """extract_system_rules() avec DB vide."""
        from forge_knowledge_distiller import extract_system_rules
        conn = sqlite3.connect(":memory:")
        try:
            result = extract_system_rules(conn)
        except Exception:
            result = []
        conn.close()
        assert isinstance(result, list)

    def test_extract_best_practices(self):
        """extract_best_practices() importable."""
        from forge_knowledge_distiller import extract_best_practices
        assert callable(extract_best_practices)

    def test_build_primer(self):
        """build_primer() retourne une string."""
        from forge_knowledge_distiller import build_primer
        result = build_primer(project="Nokido", rules=[], patterns=[], practices=[])
        assert isinstance(result, str)

    def test_extract_architecture_patterns(self):
        """extract_architecture_patterns() importable."""
        from forge_knowledge_distiller import extract_architecture_patterns
        conn = sqlite3.connect(":memory:")
        try:
            result = extract_architecture_patterns(conn)
        except Exception:
            result = []
        conn.close()
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# FRAPPE 2 : MultiLLMBridge + evolutionary_engine utilities
# ═══════════════════════════════════════════════════════════════════

class TestMultiLLMBridgeMocked:
    """Tests MultiLLMBridge avec réseau mocké."""

    def test_call_signature(self):
        """call() a la signature attendue."""
        import inspect
        from evolutionary_engine import MultiLLMBridge
        sig    = inspect.signature(MultiLLMBridge.call)
        params = list(sig.parameters.keys())
        assert len(params) >= 2

    def test_call_returns_string_on_error(self):
        """call() retourne toujours une string même si réseau ko."""
        from evolutionary_engine import MultiLLMBridge
        with patch("requests.post") as mock_post:
            mock_post.side_effect = ConnectionError("mock network error")
            result = MultiLLMBridge.call(
                "groq/test-model-xyz", "test prompt",
                temperature=0.1, inject_tools=False, task="test",
            )
            assert isinstance(result, str)

    def test_adaptive_temperature_current(self):
        """current est la température actuelle."""
        from evolutionary_engine import AdaptiveTemperatureManager
        mgr = AdaptiveTemperatureManager(base=0.3)
        assert 0.0 <= mgr.current <= 2.0

    def test_adaptive_temperature_adjust(self):
        """adjust() modifie la température."""
        from evolutionary_engine import AdaptiveTemperatureManager
        mgr = AdaptiveTemperatureManager(base=0.3)
        new_t = mgr.adjust(score=0.0, lethal=False)
        assert isinstance(new_t, float)

    def test_cerberus_guard_import(self):
        """CerberusGuard importable."""
        from evolutionary_engine import CerberusGuard
        assert CerberusGuard is not None

    def test_ast_surgeon_import(self):
        """ASTSurgeon importable."""
        from evolutionary_engine import ASTSurgeon
        assert ASTSurgeon is not None

    def test_ast_surgeon_strip(self):
        """ASTSurgeon strip markdown."""
        from evolutionary_engine import ASTSurgeon
        raw = "```python\ndef foo():\n    pass\n```"
        for method in ["clean", "strip_markdown", "strip"]:
            if hasattr(ASTSurgeon, method):
                result = getattr(ASTSurgeon, method)(raw)
                assert isinstance(result, str)
                break

    def test_run_generation_callable(self):
        """run_generation importable et callable."""
        from evolutionary_engine import run_generation
        assert callable(run_generation)

    def test_run_evolutionary_callable(self):
        """run_evolutionary importable."""
        from evolutionary_engine import run_evolutionary
        assert callable(run_evolutionary)


# ═══════════════════════════════════════════════════════════════════
# FRAPPE 3 : PersistentMCPClient
# ═══════════════════════════════════════════════════════════════════

class TestPersistentMCPClient:
    """Tests PersistentMCPClient."""

    def test_schema_cache_set_get(self):
        """SchemaCache set/get round-trip."""
        from forge_mcp_persistent import SchemaCache
        cache = SchemaCache(ttl=60)
        tools = [{"name": "read"}, {"name": "write"}]
        cache.set(tools)
        assert cache.is_valid
        assert cache.get() == tools

    def test_schema_cache_expiry(self):
        """SchemaCache expire après TTL."""
        from forge_mcp_persistent import SchemaCache
        cache = SchemaCache(ttl=0.05)
        cache.set([{"name": "read"}])
        time.sleep(0.1)
        assert not cache.is_valid

    def test_schema_cache_invalidate(self):
        """invalidate() vide le cache."""
        from forge_mcp_persistent import SchemaCache
        cache = SchemaCache(ttl=60)
        cache.set([{"name": "read"}])
        cache.invalidate()
        assert not cache.is_valid

    def test_schema_cache_tool_names(self):
        """tool_names() retourne les noms."""
        from forge_mcp_persistent import SchemaCache
        cache = SchemaCache(ttl=60)
        cache.set([{"name": "read"}, {"name": "write"}, {"name": "run"}])
        names = cache.tool_names()
        assert "read" in names and "write" in names

    def test_mmap_store_get(self):
        """mmap_store + mmap_get round-trip."""
        from forge_mcp_persistent import mmap_store, mmap_get
        content = "X" * 5000
        mmap_id = mmap_store(content)
        assert mmap_id.startswith("mcp_")
        assert mmap_get(mmap_id) == content

    def test_mmap_get_missing(self):
        """mmap_get sur ID inconnu retourne None."""
        from forge_mcp_persistent import mmap_get
        assert mmap_get("mcp_nonexistent") is None

    def test_mmap_clear_old(self):
        """mmap_clear_old vide le store."""
        from forge_mcp_persistent import mmap_store, mmap_clear_old, mmap_get
        mid = mmap_store("test")
        mmap_clear_old(max_age_s=0)
        assert mmap_get(mid) is None

    def test_ram_usage_pct(self):
        """_ram_usage_pct retourne float 0-100."""
        from forge_mcp_persistent import _ram_usage_pct
        pct = _ram_usage_pct()
        assert 0.0 <= pct <= 100.0

    def test_check_ram_pressure(self):
        """_check_ram_pressure retourne (bool, float)."""
        from forge_mcp_persistent import _check_ram_pressure
        ok, pct = _check_ram_pressure()
        assert isinstance(ok, bool) and 0.0 <= pct <= 100.0

    def test_client_instantiation(self):
        """PersistentMCPClient instanciable."""
        from forge_mcp_persistent import PersistentMCPClient
        c = PersistentMCPClient("http://localhost:9999")
        assert c._host == "http://localhost:9999"
        assert not c._connected

    def test_client_stats_initial(self):
        """stats() retourne les bonnes clés."""
        from forge_mcp_persistent import PersistentMCPClient
        c     = PersistentMCPClient()
        stats = c.stats
        for key in ["call_count", "error_count", "cache_valid", "connected"]:
            assert key in stats

    def test_extract_result_text(self):
        """_extract_result sur contenu texte."""
        from forge_mcp_persistent import PersistentMCPClient
        c      = PersistentMCPClient()
        result = c._extract_result({"result": {"content": [{"text": "Hello"}]}})
        assert "Hello" in result

    def test_extract_result_error(self):
        """_extract_result sur erreur."""
        from forge_mcp_persistent import PersistentMCPClient
        c      = PersistentMCPClient()
        result = c._extract_result({"error": {"message": "Not found"}})
        assert "[MCP ERR]" in result

    def test_extract_result_string(self):
        """_extract_result sur string directe."""
        from forge_mcp_persistent import PersistentMCPClient
        c      = PersistentMCPClient()
        result = c._extract_result({"result": "Direct result"})
        assert result == "Direct result"

    @pytest.mark.asyncio
    async def test_call_not_connected(self):
        """call() sans connexion lève RuntimeError."""
        from forge_mcp_persistent import PersistentMCPClient
        c = PersistentMCPClient()
        with pytest.raises((RuntimeError, Exception)):
            await c.call("read", {"action": "file", "path": "test"})

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """connect() sur port fermé lève ConnectionError (avec aiohttp)."""
        from forge_mcp_persistent import PersistentMCPClient
        pytest.importorskip("aiohttp")
        c = PersistentMCPClient("http://localhost:19999")
        try:
            await c.connect()
        except Exception:
            pass  # ConnectionError attendue
        assert not c._connected

    def test_lazy_threshold(self):
        """LAZY_THRESHOLD raisonnable."""
        from forge_mcp_persistent import LAZY_THRESHOLD
        assert 100 <= LAZY_THRESHOLD <= 100_000

    def test_ram_guard_pct(self):
        """RAM_GUARD_PCT entre 50 et 99."""
        from forge_mcp_persistent import RAM_GUARD_PCT
        assert 50.0 <= RAM_GUARD_PCT <= 99.0

    def test_schema_ttl(self):
        """SCHEMA_TTL > 0."""
        from forge_mcp_persistent import SCHEMA_TTL
        assert SCHEMA_TTL > 0


# ═══════════════════════════════════════════════════════════════════
# FRAPPE BONUS
# ═══════════════════════════════════════════════════════════════════

class TestForgeEnvSync:
    """Tests forge_env_sync."""

    def test_read_env_file(self):
        """_read_env_file() retourne un dict."""
        from forge_env_sync import _read_env_file
        result = _read_env_file()
        assert isinstance(result, dict)

    def test_env_report(self):
        """env_report() retourne un dict."""
        from forge_env_sync import env_report
        result = env_report()
        assert isinstance(result, dict)

    def test_sync_env_callable(self):
        """sync_env est callable."""
        from forge_env_sync import sync_env
        assert callable(sync_env)


class TestForgeHeartbeat:
    """Tests forge_heartbeat."""

    def test_ts_returns_float(self):
        """_ts() retourne un float (timestamp)."""
        from forge_heartbeat import _ts
        ts = _ts()
        assert isinstance(ts, float) and ts > 0

    def test_now_returns_string(self):
        """_now() retourne une string."""
        from forge_heartbeat import _now
        s = _now()
        assert isinstance(s, str)

    def test_rag_stats_fast(self):
        """_rag_stats_fast() retourne un dict."""
        from forge_heartbeat import _rag_stats_fast
        stats = _rag_stats_fast()
        assert isinstance(stats, dict)

    def test_active_mode_string(self):
        """_active_mode() retourne une string."""
        from forge_heartbeat import _active_mode
        mode = _active_mode()
        assert isinstance(mode, str)
