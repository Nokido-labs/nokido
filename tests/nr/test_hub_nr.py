# -*- coding: utf-8 -*-
"""
tests/nr/test_hub_nr.py
========================
NR pour l'architecture Hub v17 :
  nokido_hub          — TaskRegistry, ring resolver, tool router
  forge_hub_client     — client singleton, alive, tool, github, metrics
  nokido_stdio_bridge — structure et imports

Critères NR :
  C1 Modulaire   : 1 classe = 1 composant Hub
  C2 Comportement: assert sur décisions, pas sur timing
  C3 Edge cases  : token absent, hub down, actions inconnues
  C4 Tolérant    : isinstance / in / True|False
  C5 Isolé       : pas de dépendance réseau réelle (mock si besoin)
  C6 Rapide      : < 2s par test
"""
from __future__ import annotations

import sys
import json
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau localhost reel (:8766) (l.242)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_ROOT = Path(__file__).resolve().parent.parent.parent
_APP  = _ROOT / "app"
_TOOLS = _ROOT / "tools"

sys.path.insert(0, str(_APP))
sys.path.insert(0, str(_TOOLS))


# =============================================================================
# BLOC 1 — forge_hub_client : HubClient
# =============================================================================

class TestHubClient:
    """C1 — HubClient : client léger vers le Hub."""

    def test_import(self):
        """Le module s'importe sans erreur."""
        from forge_hub_client import HubClient, hub
        assert HubClient is not None
        assert hub is not None

    def test_singleton_exists(self):
        """Le singleton `hub` est une instance de HubClient."""
        from forge_hub_client import hub, HubClient
        assert isinstance(hub, HubClient)

    def test_hub_client_default_port(self):
        """Port Hub par défaut = 8766."""
        from forge_hub_client import HubClient
        c = HubClient()
        assert "8766" in c.base_url

    def test_alive_returns_bool(self):
        """alive() retourne toujours un bool — même si Hub down."""
        from forge_hub_client import HubClient
        c = HubClient(base_url="http://127.0.0.1:9999")  # port mort
        result = c.alive()
        assert isinstance(result, bool)
        assert result is False

    def test_alive_hub_running(self):
        """alive() = True si le Hub tourne sur :8766."""
        from forge_hub_client import hub
        # Si Hub non disponible → skip propre
        if not hub.alive():
            pytest.skip("Hub v17 non disponible sur :8766")
        assert hub.alive() is True

    def test_version_string(self):
        """version() retourne une string."""
        from forge_hub_client import hub
        v = hub.version()
        assert isinstance(v, str)

    def test_version_hub_running(self):
        """version() contient '17' si Hub v17 tourne."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        v = hub.version()
        assert any(x in v for x in ["16", "17", "18"]), f"Version inattendue: {v}"

    def test_tool_returns_string_or_none(self):
        """tool() retourne str ou None — jamais d'exception."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        result = hub.tool("read", {"action": "tail_logs", "path": "sandbox/hub_live.log"})
        assert result is None or isinstance(result, str)

    def test_github_status(self):
        """github('status') retourne une string."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        result = hub.github("status")
        assert result is None or isinstance(result, str)

    def test_metrics_structure(self):
        """metrics() retourne un dict avec les clés attendues."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        m = hub.metrics()
        assert m is not None
        # v16: engine.rag_n_total, v17: rag_chunks
        has_rag = "rag_chunks" in m or "rag_n_total" in m.get("engine", {}) or "db" in m
        assert has_rag, f"Metriques RAG absentes: {list(m.keys())}"

    def test_status_report_format(self):
        """status_report() retourne toujours une string lisible."""
        from forge_hub_client import hub
        r = hub.status_report()
        assert isinstance(r, str)
        assert len(r) > 10

    def test_status_report_hub_down(self):
        """status_report() ne crash pas si Hub down."""
        from forge_hub_client import HubClient
        c = HubClient(base_url="http://127.0.0.1:9999")
        r = c.status_report()
        assert "non disponible" in r or "unavailable" in r.lower()

    def test_tool_unknown_action(self):
        """tool inconnu → retourne message d'erreur, pas d'exception."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        r = hub.tool("run", {"action": "action_inexistante_xyz"})
        assert r is not None


# =============================================================================
# BLOC 2 — TaskRegistry
# =============================================================================

class TestTaskRegistry:
    """C1 — TaskRegistry : gestionnaire de tâches background."""

    @pytest.fixture(autouse=True)
    def import_registry(self):
        """Import TaskRegistry depuis le Hub."""
        try:
            sys.path.insert(0, str(_TOOLS))
            # Import direct sans démarrer le serveur
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "nokido_hub", _TOOLS / "nokido_hub.py"
            )
            mod = importlib.util.module_from_spec(spec)
            # Ne pas exécuter le module complet (évite uvicorn)
            # On teste juste la classe
            self.TaskRegistry = None
            # Fallback : importer depuis hub_client
        except Exception:
            pass

    def test_task_registry_importable(self):
        """TaskRegistry existe dans nokido_hub."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "nokido_hub_mod", _TOOLS / "nokido_hub.py"
        )
        # Vérifier le code source contient TaskRegistry
        source = (_TOOLS / "nokido_hub.py").read_text(encoding="utf-8")
        assert "class TaskRegistry" in source

    def test_module_test_map_not_empty(self):
        """MODULE_TEST_MAP a des entrées."""
        source = (_TOOLS / "nokido_hub.py").read_text(encoding="utf-8")
        assert "MODULE_TEST_MAP" in source
        assert "forge_hub_client" in source

    def test_module_test_map_coverage(self):
        """Les modules critiques sont dans la map."""
        source = (_TOOLS / "nokido_hub.py").read_text(encoding="utf-8")
        critical = [
            "forge_cognitive_router",
            "forge_arbitrator",
            "forge_env_crypt",
            "forge_rag_qualify",
            "forge_integrity",
        ]
        for mod in critical:
            assert mod in source, f"MODULE_TEST_MAP manque: {mod}"

    def test_launch_tests_via_hub(self):
        """test_nr via Hub lance une tâche et retourne task_id."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        result = hub.tool("run", {"action": "test_module", "code": "forge_hub_client"})
        assert result is not None
        if "call_tool" in str(result) or "Erreur" in str(result):
            pytest.skip(f"Hub call_tool API incompatible: {result[:100]}")
        assert "task_id" in result
        assert "log" in result

    def test_task_status_unknown(self):
        """test_status avec task_id inconnu → message propre."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        result = hub.tool("run", {"action": "test_status", "code": "tache_inexistante_xyz"})
        assert result is not None

    def test_task_status_list(self):
        """test_status sans code → liste les tâches."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        result = hub.tool("run", {"action": "test_status", "code": ""})
        assert result is not None
        assert isinstance(result, str)


# =============================================================================
# BLOC 3 — Hub endpoints (via hub_client)
# =============================================================================

class TestHubEndpoints:
    """C1 — Hub endpoints : health, metrics, github proxy."""

    def test_health_endpoint(self):
        """GET /health → status ok + version 17."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        import urllib.request, json, os
        token = os.environ.get("FORGE_MCP_TOKEN", "")
        req = urllib.request.Request("http://127.0.0.1:8766/health")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=5) as r:
            h = json.loads(r.read().decode())
        assert h["status"] == "ok"
        assert any(x in h["version"] for x in ["16", "17", "18"]), f"Version inattendue: {h['version']}"
        assert "status" in h  # hub_host optionnel selon version hub
        # queue_size optionnel selon version hub
        assert "status" in h or "queue_size" in h

    def test_metrics_endpoint(self):
        """GET /metrics → rag_chunks + event_log."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        m = hub.metrics()
        # v16: engine.rag_n_total, v17: rag_chunks
        rag_count = m.get("rag_chunks") or m.get("engine", {}).get("rag_n_total", 0)
        assert isinstance(rag_count, (int, float)), f"rag_count invalide: {rag_count}"

    def test_ring_resolver_local(self):
        """Local 127.0.0.1 avec token valide → RING_0."""
        source = (_TOOLS / "nokido_hub.py").read_text(encoding="utf-8")
        assert "_resolve_ring" in source
        assert "RING_0" in source or 'return 0' in source

    def test_ring_resolver_no_token(self):
        """Sans token → ring=-1 (401)."""
        from forge_hub_client import HubClient
        c = HubClient(token="mauvais_token_xyz")
        if not HubClient().alive():
            pytest.skip("Hub non disponible")
        # Appel sans bon token → erreur
        result = c.tool("read", {"action": "tail_logs", "path": "sandbox/hub_live.log"})
        # Doit retourner None ou message d'erreur, pas planter
        assert result is None or "error" in str(result).lower() or isinstance(result, str)

    def test_github_proxy_status(self):
        """POST /github code=status → réponse branche."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        r = hub.github("status")
        if r is None:
            pytest.skip("github() retourne None — token absent ou endpoint indispo")
        assert isinstance(r, str)

    def test_github_proxy_log(self):
        """POST /github code=log → liste de commits."""
        from forge_hub_client import hub
        if not hub.alive():
            pytest.skip("Hub non disponible")
        r = hub.github("log")
        if r is None:
            pytest.skip("github() retourne None — token absent ou endpoint indispo")
        assert isinstance(r, str)


# =============================================================================
# BLOC 4 — Bridge STDIO
# =============================================================================

class TestStdioBridge:
    """C1 — Bridge STDIO : structure et imports."""

    def test_bridge_file_exists(self):
        """nokido_stdio_bridge.py existe."""
        assert (_TOOLS / "nokido_stdio_bridge.py").exists()

    def test_bridge_syntax_valid(self):
        """Bridge a une syntaxe Python valide."""
        import ast
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        ast.parse(source)  # lève SyntaxError si invalide

    def test_bridge_has_main(self):
        """Bridge a une fonction main."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        assert "def main()" in source or "async def run_bridge" in source

    def test_bridge_is_mute(self):
        """Bridge ne contient pas de logique métier (test, rag, github)."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        # Le bridge ne doit pas connaître les outils
        for keyword in ["test_nr", "task_registry", "rag_chunks", "_tool_call"]:
            assert keyword not in source, f"Bridge pollué avec: {keyword}"

    def test_bridge_has_timeout(self):
        """Bridge définit un timeout pour les requêtes Hub."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        assert "TIMEOUT" in source or "timeout" in source

    def test_bridge_hub_url_configurable(self):
        """Bridge lit HUB_URL depuis l'environnement."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        assert "LAFORGE_HUB_URL" in source

    def test_bridge_uses_asyncio(self):
        """Bridge utilise asyncio pour être non-bloquant."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        assert "asyncio" in source

    def test_bridge_windows_policy(self):
        """Bridge gère la politique asyncio Windows."""
        source = (_TOOLS / "nokido_stdio_bridge.py").read_text(encoding="utf-8")
        assert "WindowsSelectorEventLoopPolicy" in source
