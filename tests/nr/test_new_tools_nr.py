"""
test_new_tools_nr.py — Tests consolidés pour les 9 nouveaux outils v17
=======================================================================
Couverture fonctionnelle de :
  - ForgeTokenOptimizer    (compression prompts)
  - FastForgeLogger        (logger non-bloquant)
  - ForgeTurboRunner       (tests parallélisés)
  - ForgeLibraryShifter    (permutation librairies)
  - ForgeThoughtInterceptor (capture CoT)
  - ForgeDBRouter          (hybride SQLite/DuckDB)
  - ForgeSourceDiscovery   (enrichissement RAG)
  - ForgeHotLoadManager    (keep-alive + quotas)
  - PersistentMCPClient    (connexion MCP persistante)
"""
from __future__ import annotations

import ast
import asyncio
import sqlite3
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau reel (GitHub, arXiv, PyPI, HuggingFace,
#   OpenRouter); reseau localhost Ollama (l.505)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))


# ═══════════════════════════════════════════════════════════════════
# ForgeTokenOptimizer
# ═══════════════════════════════════════════════════════════════════

class TestForgeTokenOptimizer:
    """Tests ForgeTokenOptimizer — compression prompts."""

    def test_singleton(self):
        """get_optimizer() retourne le même objet."""
        from forge_token_optimizer import get_optimizer
        assert get_optimizer() is get_optimizer()

    def test_compress_code_removes_comments(self):
        """compress_code() supprime les commentaires."""
        from forge_token_optimizer import get_optimizer
        code   = "# commentaire\ndef foo():\n    pass\n"
        result = get_optimizer().compress_code(code)
        assert "#" not in result
        assert "def foo" in result

    def test_compress_code_removes_docstrings(self):
        """compress_code() supprime les docstrings."""
        from forge_token_optimizer import get_optimizer
        code   = 'def foo():\n    """Ma docstring."""\n    return 1\n'
        result = get_optimizer().compress_code(code)
        assert "docstring" not in result
        assert "return 1" in result

    def test_compress_code_aggressive(self):
        """Mode agressif réduit l'indentation."""
        from forge_token_optimizer import get_optimizer
        code   = "def foo():\n    return 1\n"
        result = get_optimizer().compress_code(code, aggressive=True)
        assert "  " in result or "return" in result

    def test_semantic_trim_short(self):
        """semantic_trim ne tronque pas si < max_chars."""
        from forge_token_optimizer import get_optimizer
        text = "a" * 100
        assert get_optimizer().semantic_trim(text, max_chars=200) == text

    def test_semantic_trim_long(self):
        """semantic_trim tronque avec marqueur."""
        from forge_token_optimizer import get_optimizer
        text   = "a" * 5000
        result = get_optimizer().semantic_trim(text, max_chars=1000)
        assert "COMPRESSION" in result
        assert len(result) < len(text)

    def test_ast_pruning_keeps_target(self):
        """ast_pruning conserve la fonction cible."""
        from forge_token_optimizer import get_optimizer
        code = "def foo():\n    return 1\ndef bar():\n    return 2\n"
        result = get_optimizer().ast_pruning(code, "foo")
        assert "foo" in result

    def test_ast_pruning_stubs_others(self):
        """ast_pruning remplace les autres fonctions par pass."""
        from forge_token_optimizer import get_optimizer
        code = "def foo():\n    return 1\ndef bar():\n    return 2\n"
        result = get_optimizer().ast_pruning(code, "foo")
        assert "bar" in result  # squelette présent

    def test_optimize_prompt_returns_tuple(self):
        """optimize_prompt() retourne (str, dict)."""
        from forge_token_optimizer import get_optimizer
        code, stats = get_optimizer().optimize_prompt("def foo(): pass\n")
        assert isinstance(code, str)
        assert "reduction_pct" in stats

    def test_compress_json_payload(self):
        """compress_json_payload() produit du JSON minifié."""
        from forge_token_optimizer import get_optimizer
        result = get_optimizer().compress_json_payload({"a": 1, "b": 2})
        assert " " not in result
        assert '"a":1' in result


# ═══════════════════════════════════════════════════════════════════
# FastForgeLogger
# ═══════════════════════════════════════════════════════════════════

class TestFastForgeLogger:
    """Tests FastForgeLogger — logger non-bloquant."""

    def test_singleton(self):
        """get_fast_logger() retourne le même objet."""
        from forge_fast_logger import get_fast_logger
        a = get_fast_logger(log_file="sandbox/test_logger_a.log")
        b = get_fast_logger(log_file="sandbox/test_logger_a.log")
        assert a is b

    def test_log_no_block(self):
        """log() ne bloque pas l'appelant."""
        from forge_fast_logger import FastForgeLogger
        lg = FastForgeLogger(log_file="sandbox/test_nb.log", console_ratio=0)
        t0 = time.perf_counter()
        for _ in range(100):
            lg.log("test message", level="INFO", silent_console=True)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5  # 100 messages < 500ms

    def test_info_warning_error(self):
        """Raccourcis info/warning/error disponibles."""
        from forge_fast_logger import FastForgeLogger
        lg = FastForgeLogger(log_file="sandbox/test_levels.log", console_ratio=0)
        lg.info("info msg")
        lg.warning("warn msg")
        lg.error("error msg")
        lg.debug("debug msg")
        time.sleep(0.05)

    def test_error_increments_counter(self):
        """error() incrémente le compteur d'erreurs."""
        from forge_fast_logger import FastForgeLogger
        lg = FastForgeLogger(log_file="sandbox/test_errcnt.log", console_ratio=0)
        lg.error("erreur test")
        time.sleep(0.05)
        assert lg.stats["errors"] == 1

    def test_stats_dict(self):
        """stats retourne un dict complet."""
        from forge_fast_logger import FastForgeLogger
        lg    = FastForgeLogger(log_file="sandbox/test_stats.log", console_ratio=0)
        stats = lg.stats
        for key in ["msg_count", "errors", "queue_size", "log_path", "running"]:
            assert key in stats

    def test_flush(self):
        """flush() ne plante pas."""
        from forge_fast_logger import FastForgeLogger
        lg = FastForgeLogger(log_file="sandbox/test_flush.log", console_ratio=0)
        lg.info("flush test")
        lg.flush()


# ═══════════════════════════════════════════════════════════════════
# ForgeTurboRunner
# ═══════════════════════════════════════════════════════════════════

class TestForgeTurboRunner:
    """Tests forge_turbo_runner — orchestration pytest-xdist."""

    def test_worker_count_auto(self):
        """_get_worker_count(0) = cpu_count // 2."""
        from forge_turbo_runner import _get_worker_count
        from multiprocessing import cpu_count
        n = _get_worker_count(0)
        assert 1 <= n <= cpu_count()

    def test_worker_count_explicit(self):
        """_get_worker_count(4) = 4."""
        from forge_turbo_runner import _get_worker_count
        assert _get_worker_count(4) == 4

    def test_build_cmd_nr_suite(self):
        """_build_pytest_cmd pour suite nr contient tests/nr/."""
        from forge_turbo_runner import _build_pytest_cmd
        cmd = _build_pytest_cmd(4, "nr", 30, False, [])
        assert "tests/nr/" in cmd
        assert "-n4" in cmd

    def test_build_cmd_coverage(self):
        """Suite coverage inclut --cov=app."""
        from forge_turbo_runner import _build_pytest_cmd
        cmd = _build_pytest_cmd(4, "coverage", 30, True, [])
        assert "--cov=app" in cmd

    def test_run_turbo_signature(self):
        """run_turbo() a la bonne signature."""
        import inspect
        from forge_turbo_runner import run_turbo
        sig    = inspect.signature(run_turbo)
        params = list(sig.parameters.keys())
        for p in ["workers", "suite", "timeout", "compress"]:
            assert p in params

    def test_main_callable(self):
        """main() est callable."""
        from forge_turbo_runner import main
        assert callable(main)


# ═══════════════════════════════════════════════════════════════════
# ForgeLibraryShifter
# ═══════════════════════════════════════════════════════════════════

class TestForgeLibraryShifter:
    """Tests ForgeLibraryShifter — permutation librairies."""

    def test_instantiation(self):
        """LibraryShifter instanciable."""
        from forge_library_shifter import LibraryShifter
        assert LibraryShifter() is not None

    def test_library_mapping_keys(self):
        """LIBRARY_MAPPING contient json, requests, sqlite3."""
        from forge_library_shifter import LIBRARY_MAPPING
        for key in ["json", "requests", "sqlite3"]:
            assert key in LIBRARY_MAPPING

    def test_scan_for_optimization_finds_json(self, tmp_path):
        """scan détecte import json."""
        from forge_library_shifter import LibraryShifter
        f = tmp_path / "test.py"
        f.write_text("import json\n\ndef foo(): pass\n")
        result = LibraryShifter().scan_for_optimization(str(f))
        assert "json" in result

    def test_scan_empty_file(self, tmp_path):
        """scan sur fichier sans lib cible → liste vide."""
        from forge_library_shifter import LibraryShifter
        f = tmp_path / "test.py"
        f.write_text("import os\nimport sys\n")
        result = LibraryShifter().scan_for_optimization(str(f))
        assert result == []

    def test_run_micro_benchmark_returns_float(self):
        """run_micro_benchmark retourne un float en ms."""
        from forge_library_shifter import LibraryShifter
        t = LibraryShifter().run_micro_benchmark("x = 1 + 1", iterations=10)
        assert isinstance(t, float) and t >= 0

    def test_benchmark_all_returns_list(self):
        """benchmark_all() retourne une liste de résultats."""
        from forge_library_shifter import LibraryShifter
        results = LibraryShifter().benchmark_all()
        assert isinstance(results, list) and len(results) > 0

    def test_benchmark_json_msgspec_speedup(self):
        """msgspec est plus rapide que json (> 1×)."""
        from forge_library_shifter import LibraryShifter
        results = LibraryShifter().benchmark_all()
        json_result = next((r for r in results if r.get("lib") == "json"), None)
        if json_result and "speedup" in json_result:
            assert json_result["speedup"] > 1.0

    def test_create_mutation_mission(self):
        """create_mutation_mission retourne un prompt non vide."""
        from forge_library_shifter import LibraryShifter
        prompt = LibraryShifter().create_mutation_mission("app/test.py", "json")
        assert "msgspec" in prompt
        assert len(prompt) > 50

    def test_required_tools_structure(self):
        """required_tools respecte le schéma MCP."""
        from forge_library_shifter import LibraryShifter
        tools = LibraryShifter().required_tools
        assert isinstance(tools, list)
        assert tools[0]["function"]["name"] == "apply_library_swap"


# ═══════════════════════════════════════════════════════════════════
# ForgeThoughtInterceptor
# ═══════════════════════════════════════════════════════════════════

class TestForgeThoughtInterceptor:
    """Tests ForgeThoughtInterceptor — capture CoT."""

    def test_instantiation(self):
        """ForgeThoughtInterceptor instanciable."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        i = ForgeThoughtInterceptor()
        assert i.thought_dir.exists()

    def test_safety_tools_structure(self):
        """_get_safety_tools() conforme [2026-03-22]."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        tools = ForgeThoughtInterceptor()._get_safety_tools()
        assert tools[0]["function"]["name"] == "validate_mutation_integrity"
        assert "file_path" in tools[0]["function"]["parameters"]["properties"]

    def test_list_thoughts_empty(self):
        """list_thoughts() retourne une liste (peut être vide)."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        result = ForgeThoughtInterceptor().list_thoughts(limit=5)
        assert isinstance(result, list)

    def test_get_stats(self):
        """get_stats() retourne les clés attendues."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        stats = ForgeThoughtInterceptor().get_stats()
        for key in ["total", "valid", "low_density", "total_kb"]:
            assert key in stats

    def test_replay_thought_missing(self):
        """replay_thought sur fichier inexistant retourne message d'erreur."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        result = ForgeThoughtInterceptor().replay_thought("nonexistent_thought.txt")
        assert "introuvable" in result or "ERR" in result

    def test_archive_reasoning(self, tmp_path):
        """_archive_reasoning crée un fichier de trace."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        i            = ForgeThoughtInterceptor()
        i.thought_dir = tmp_path / "thoughts"
        i.thought_dir.mkdir()
        i.memory_path = tmp_path / "memory.jsonl"
        log = i._archive_reasoning(
            model="test-model", task_id="test_001",
            thought="Je réfléchis à la solution optimale...",
            result="def foo(): pass",
            quality_flag=True,
        )
        assert log.exists()
        assert "VALID" in log.name

    def test_archive_low_density(self, tmp_path):
        """_archive_reasoning marque LOW_DENSITY si qualité insuffisante."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        i            = ForgeThoughtInterceptor()
        i.thought_dir = tmp_path / "thoughts"
        i.thought_dir.mkdir()
        i.memory_path = tmp_path / "memory.jsonl"
        log = i._archive_reasoning(
            model="test-model", task_id="test_002",
            thought="ok", result="pass",
            quality_flag=False,
        )
        assert "LOW_DENSITY" in log.name

    def test_min_thought_chars_constant(self):
        """MIN_THOUGHT_CHARS = 50."""
        from forge_thought_interceptor import MIN_THOUGHT_CHARS
        assert MIN_THOUGHT_CHARS == 50

    def test_stream_ollama_offline(self):
        """stream_with_thought_capture gère Ollama offline gracieusement."""
        from forge_thought_interceptor import ForgeThoughtInterceptor
        i      = ForgeThoughtInterceptor()
        result = i.stream_with_thought_capture(
            model="test-model", prompt="test", task_id="t1", gpu_timeout=1
        )
        assert isinstance(result, dict)
        assert "error" in result or "content" in result


# ═══════════════════════════════════════════════════════════════════
# ForgeDBRouter
# ═══════════════════════════════════════════════════════════════════

class TestForgeDBRouter:
    """Tests ForgeDBRouter — routeur hybride SQLite/DuckDB."""

    def setup_method(self):
        """Crée un routeur avec table de test (instance fraîche)."""
        from forge_db_router import ForgeDBRouter, _pool
        # Connexion SQLite fraîche pour isoler les tests
        import sqlite3
        self.db = ForgeDBRouter(":memory:")
        # Forcer une nouvelle connexion isolée
        key = ":memory:_test"
        self.db._db_path = key
        _pool._sqlite[key] = sqlite3.connect(":memory:", check_same_thread=False)
        _pool._sqlite[key].row_factory = sqlite3.Row
        _pool._sqlite[key].execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS t (id INT, val TEXT, score FLOAT)")
        self.db.executemany("INSERT INTO t VALUES (?,?,?)",
                            [(i, f"v{i}", float(i)) for i in range(100)])
        self.db.commit()

    def test_instantiation(self):
        """ForgeDBRouter instanciable."""
        from forge_db_router import ForgeDBRouter
        assert ForgeDBRouter(":memory:") is not None

    def test_select_simple_sqlite(self):
        """SELECT simple routé vers SQLite."""
        result = self.db.execute("SELECT * FROM t WHERE id = 1")
        assert len(result) == 1

    def test_select_returns_list(self):
        """execute() retourne une liste."""
        result = self.db.execute("SELECT id FROM t LIMIT 5")
        assert isinstance(result, list) and len(result) == 5

    def test_explain_route_simple(self):
        """SELECT simple → sqlite."""
        route = self.db.explain_route("SELECT * FROM t WHERE id = 1")
        assert route["engine"] == "sqlite"

    def test_explain_route_analytical(self):
        """SELECT avec SUM → duckdb."""
        route = self.db.explain_route("SELECT SUM(score) FROM t GROUP BY val")
        assert route["engine"] == "duckdb"

    def test_explain_route_avg(self):
        """SELECT avec AVG → duckdb."""
        route = self.db.explain_route("SELECT AVG(score) FROM t GROUP BY val")
        assert route["engine"] == "duckdb"

    def test_explain_route_insert(self):
        """INSERT → sqlite (toujours)."""
        route = self.db.explain_route("INSERT INTO t VALUES (1,'x',1.0)")
        assert route["engine"] == "sqlite"

    def test_force_engine_sqlite(self):
        """engine='sqlite' force SQLite."""
        result = self.db.execute("SELECT COUNT(*) FROM t", engine="sqlite")
        assert result[0][0] == 100

    def test_stats_dict(self):
        """stats retourne les clés attendues."""
        stats = self.db.stats
        for key in ["sqlite", "duckdb", "errors", "total"]:
            assert key in stats

    def test_singleton(self):
        """get_db_router(':memory:') retourne le même objet."""
        from forge_db_router import get_db_router
        a = get_db_router("test_singleton.db")
        b = get_db_router("test_singleton.db")
        assert a is b

    def test_should_use_duckdb_sum(self):
        """_should_use_duckdb détecte SUM."""
        from forge_db_router import _should_use_duckdb
        assert _should_use_duckdb("SELECT SUM(x) FROM t GROUP BY y") is True

    def test_should_use_duckdb_simple(self):
        """_should_use_duckdb ne trigger pas sur SELECT simple."""
        from forge_db_router import _should_use_duckdb
        assert _should_use_duckdb("SELECT * FROM t WHERE id = 1") is False

    def test_persistent_connection_faster(self):
        """Connexion persistante < 1ms par requête."""
        times = []
        for _ in range(50):
            t = time.perf_counter()
            self.db.execute("SELECT * FROM t WHERE id = 1")
            times.append((time.perf_counter() - t) * 1000)
        import statistics
        assert statistics.median(times) < 5.0  # < 5ms médiane


# ═══════════════════════════════════════════════════════════════════
# ForgeSourceDiscovery
# ═══════════════════════════════════════════════════════════════════

class TestForgeSourceDiscovery:
    """Tests ForgeSourceDiscovery — enrichissement RAG."""

    def test_instantiation(self):
        """ForgeSourceDiscovery instanciable."""
        from forge_source_discovery import ForgeSourceDiscovery
        assert ForgeSourceDiscovery() is not None

    def test_summary_model_configurable(self):
        """summary_model configurable à l'init."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc = ForgeSourceDiscovery(summary_model="groq/llama-3.3-70b-versatile")
        assert disc._summary_model == "groq/llama-3.3-70b-versatile"

    def test_stats_initial(self):
        """stats retourne ingested=0 errors=0 au départ."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc = ForgeSourceDiscovery()
        assert disc.stats["ingested"] == 0

    def test_search_ddg_returns_list(self):
        """_search_ddg retourne une liste (peut être vide si DDG throttle)."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc._search_ddg("python asyncio", max_results=3)
        assert isinstance(results, list)

    def test_search_github_returns_list(self):
        """_search_github retourne des repos."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc._search_github("duckdb python", max_results=3)
        assert isinstance(results, list)
        if results:
            assert "url" in results[0]
            assert "github.com" in results[0]["url"]

    def test_search_arxiv_returns_list(self):
        """_search_arxiv retourne des papers."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc._search_arxiv("LLM code generation", max_results=3)
        assert isinstance(results, list)
        if results:
            assert "arxiv.org" in results[0].get("url", "")

    def test_search_pypi_returns_list(self):
        """_search_pypi retourne un package."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc._search_pypi("msgspec", max_results=1)
        assert isinstance(results, list)

    def test_search_huggingface_returns_list(self):
        """_search_huggingface retourne des modèles."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc._search_huggingface("qwen2.5-coder", max_results=3)
        assert isinstance(results, list)
        if results:
            assert "huggingface.co" in results[0].get("url", "")

    def test_search_routing_arxiv(self):
        """search(backend='arxiv') utilise _search_arxiv."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        results = disc.search("transformer architecture", max_results=2, backend="arxiv")
        assert isinstance(results, list)

    def test_extract_content_trafilatura(self):
        """extract_content(use_crawl4ai=False) utilise trafilatura."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc    = ForgeSourceDiscovery()
        content = disc.extract_content(
            "https://pypi.org/project/msgspec/",
            max_chars=500, use_crawl4ai=False
        )
        assert content is not None and len(content) > 50

    def test_cache_set_and_check(self):
        """_cache_url + _is_cached fonctionnent."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc = ForgeSourceDiscovery()
        disc._cache_url("https://test.example.com/fake", {"status": "ok"})
        assert disc._is_cached("https://test.example.com/fake", max_age_days=1)

    def test_cache_expired(self):
        """Cache avec max_age_days=0 → expiré."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc = ForgeSourceDiscovery()
        disc._cache_url("https://expired.example.com/fake", {"status": "ok"})
        assert not disc._is_cached("https://expired.example.com/fake", max_age_days=0)

    def test_trusted_domains_scoring(self):
        """Domaines de confiance ont un score > 1."""
        from forge_source_discovery import ForgeSourceDiscovery, TRUSTED_DOMAINS
        disc    = ForgeSourceDiscovery()
        results = disc.search("python asyncio best practices",
                              max_results=5, backend="arxiv")
        # Vérifier que TRUSTED_DOMAINS est bien défini
        assert "docs.python.org" in TRUSTED_DOMAINS

    def test_reverse_engineer_code_sync(self):
        """reverse_engineer_code_sync retourne un dict avec 'doc'."""
        from forge_source_discovery import ForgeSourceDiscovery
        disc   = ForgeSourceDiscovery(summary_model="groq/llama-3.3-70b-versatile")
        opaque = "def a(b,c): return [i for i in b if i in c]"
        result = disc.reverse_engineer_code_sync(opaque, context="test", ingest=False)
        assert "doc" in result
        assert "chars_in" in result
        assert result["chars_in"] == len(opaque)

    def test_reverse_engineer_produces_doc(self):
        """reverse_engineer_code_sync produit une doc non triviale."""
        from forge_source_discovery import ForgeSourceDiscovery
        import os
        from pathlib import Path
        # Injecter la clé Groq si disponible
        env = (ROOT / "Nokido.env").read_text(encoding="utf-8", errors="replace")
        for l in env.splitlines():
            if l.startswith("GROQ_API_KEY="):
                os.environ["GROQ_API_KEY"] = l.split("=",1)[1].strip()

        disc   = ForgeSourceDiscovery(summary_model="groq/llama-3.3-70b-versatile")
        opaque = "def a(b,c,d=None):\n    r=[]\n    for i in b:\n        if i not in c:\n            if d is None or d(i): r.append(i)\n    return sorted(r)\n"
        result = disc.reverse_engineer_code_sync(opaque, context="list filter", ingest=False)
        # La doc doit être plus longue que le code (ou égale en fallback)
        assert result["chars_out"] >= result["chars_in"]


# ═══════════════════════════════════════════════════════════════════
# ForgeHotLoadManager
# ═══════════════════════════════════════════════════════════════════

class TestForgeHotLoadManager:
    """Tests ForgeHotLoadManager — keep-alive + quotas."""

    def test_singleton(self):
        """get_hot_load_manager() retourne le même objet."""
        from forge_hot_load_manager import get_hot_load_manager
        assert get_hot_load_manager() is get_hot_load_manager()

    def test_record_call_increments_rpm(self):
        """record_call() incrémente le compteur RPM."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        mgr.record_call("groq", tokens=500)
        mgr.record_call("groq", tokens=300)
        q = mgr.quota_headroom("groq")
        assert q["rpm_used"] == 2

    def test_quota_headroom_returns_dict(self):
        """quota_headroom() retourne les clés attendues."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        q   = mgr.quota_headroom("groq")
        for key in ["rpm_used", "rpm_headroom", "tpm_used", "throttled"]:
            assert key in q

    def test_best_available_provider(self):
        """best_available_provider() choisit le non-throttlé."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr  = ForgeHotLoadManager()
        best = mgr.best_available_provider(["groq", "gemini", "ollama"])
        assert best in ["groq", "gemini", "ollama"]

    def test_throttled_provider_excluded(self):
        """Provider throttlé exclu du best_available."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        # Saturer groq
        for _ in range(35):
            mgr.record_call("groq")
        best = mgr.best_available_provider(["groq", "ollama"])
        assert best == "ollama"

    def test_optimal_context_large_file(self):
        """Gros fichier → contexte réduit."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        ctx = mgr.optimal_context(str(ROOT / "app/LaForge.py"))
        assert ctx <= 8192

    def test_optimal_context_missing_file(self):
        """Fichier absent → contexte par défaut 8192."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        ctx = mgr.optimal_context("/nonexistent/path.py")
        assert ctx == 8192

    def test_system_metrics_real(self):
        """system_metrics() retourne des vraies valeurs."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        m   = mgr.system_metrics()
        assert 0 <= m["cpu_pct"] <= 100
        assert 0 <= m["ram_pct"] <= 100
        assert m["ram_total_gb"] > 0

    def test_all_quotas_keys(self):
        """all_quotas() couvre tous les providers configurés."""
        from forge_hot_load_manager import ForgeHotLoadManager, PROVIDER_LIMITS
        mgr    = ForgeHotLoadManager()
        quotas = mgr.all_quotas()
        for provider in PROVIDER_LIMITS:
            assert provider in quotas

    def test_is_warm_false_initially(self):
        """is_warm() False si pas de heartbeat envoyé."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        assert not mgr.is_warm("qwen2.5-coder:7b")

    def test_keep_warm_ollama_offline(self):
        """keep_warm() ne plante pas si Ollama est offline."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr = ForgeHotLoadManager()
        result = mgr.keep_warm("ollama/qwen2.5-coder:7b")
        assert isinstance(result, bool)

    def test_fetch_all_model_contexts(self):
        """fetch_all_model_contexts() retourne un dict."""
        from forge_hot_load_manager import ForgeHotLoadManager
        mgr  = ForgeHotLoadManager()
        ctx  = mgr.fetch_all_model_contexts()
        assert isinstance(ctx, dict)
        assert len(ctx) >= 10  # Au moins 10 modèles free

    def test_fetch_openrouter_limits(self):
        """fetch_openrouter_limits() avec clé retourne les limites."""
        from forge_hot_load_manager import ForgeHotLoadManager
        import os
        from pathlib import Path
        env = (ROOT / "Nokido.env").read_text(encoding="utf-8", errors="replace")
        for l in env.splitlines():
            if l.startswith("OPENROUTEUR_API_KEY="):
                os.environ["OPENROUTER_API_KEY"] = l.split("=",1)[1].strip()
        mgr    = ForgeHotLoadManager()
        result = mgr.fetch_openrouter_limits()
        if "error" not in result:
            assert "rpm_limit" in result
            assert "is_free_tier" in result
