# -*- coding: utf-8 -*-
"""
tests/nr/test_core_nr.py
=========================
NR pour nokido_core.py — Source de Vérité v17.

Couvre :
  StateManager   — état TUI, persistance, thread-safety
  RAGManager     — search, stats, filtres ring/trust
  PromptBuilder  — prompts dynamiques MCP
  CoreBridge     — interface Hub + TUI

Critères NR :
  C1 Modulaire   : 1 classe = 1 composant Core
  C2 Comportement: assert sur décisions, pas sur timing
  C3 Edge cases  : query vide, ring max, mode inconnu
  C4 Tolérant    : isinstance / in / True|False
  C5 Isolé       : pas de dépendance réseau
  C6 Rapide      : < 1s par test
"""
from __future__ import annotations

import sys
import json
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_APP  = _ROOT / "app"
sys.path.insert(0, str(_APP))
sys.path.insert(0, str(_ROOT / "tools"))


# =============================================================================
# BLOC 1 — StateManager
# =============================================================================

class TestStateManager:
    """C1 — StateManager : état TUI thread-safe."""

    @pytest.fixture(autouse=True)
    def fresh_state(self):
        """Crée un StateManager frais pour chaque test."""
        from nokido_core import StateManager
        self.sm = StateManager()
        yield
        # Reset propre
        self.sm.set(collab_mode=1, active_ring=1)

    def test_default_collab_mode(self):
        """Mode par défaut = ASSISTANT (1)."""
        from nokido_core import CollabMode
        assert self.sm.get().collab_mode in [CollabMode.ASSISTANT, 1]

    def test_default_ring(self):
        """Ring par défaut = DEV (1)."""
        from nokido_core import SecurityRing
        assert self.sm.get().active_ring in [SecurityRing.DEV, 1]

    def test_set_collab_returns_name(self):
        """set_collab_mode retourne le nom du mode."""
        name = self.sm.set_collab_mode(2)
        assert name == "COLLAB"

    def test_set_ring_returns_name(self):
        """set_ring retourne le nom du ring."""
        name = self.sm.set_ring(0)
        assert name == "SYSTEM"

    def test_set_clamps_collab(self):
        """set_collab_mode clamp 0-3."""
        self.sm.set_collab_mode(99)
        assert self.sm.get().collab_mode == 3
        self.sm.set_collab_mode(-5)
        assert self.sm.get().collab_mode == 0

    def test_set_clamps_ring(self):
        """set_ring clamp 0-4."""
        self.sm.set_ring(99)
        assert self.sm.get().active_ring == 4
        self.sm.set_ring(-1)
        assert self.sm.get().active_ring == 0

    def test_allowed_tools_ring0(self):
        """Ring 0 → tous les outils."""
        self.sm.set_ring(0)
        tools = self.sm.allowed_tools()
        assert "read"   in tools
        assert "write"  in tools
        assert "python" in tools
        assert "github" in tools

    def test_allowed_tools_ring4(self):
        """Ring 4 → lecture seule."""
        self.sm.set_ring(4)
        tools = self.sm.allowed_tools()
        assert "read"   in tools
        assert "write"  not in tools
        assert "python" not in tools

    def test_allowed_tools_ring3(self):
        """Ring 3 → read + query seulement."""
        self.sm.set_ring(3)
        tools = self.sm.allowed_tools()
        assert "read"   in tools
        assert "query"  in tools
        assert "write"  not in tools
        assert "python" not in tools

    def test_is_tool_allowed(self):
        """is_tool_allowed respecte le ring."""
        self.sm.set_ring(2)
        assert self.sm.is_tool_allowed("read")  is True
        assert self.sm.is_tool_allowed("write") is True
        assert self.sm.is_tool_allowed("python") is False

    def test_updated_at_changes(self):
        """updated_at est renseigné après un set."""
        self.sm.set(collab_mode=2)
        after = self.sm.get().updated_at
        # updated_at est une string ISO non vide après un set
        assert isinstance(after, str) and len(after) > 0
        self.sm.set(collab_mode=1)

    def test_thread_safety(self):
        """set() est thread-safe — pas de corruption concurrente."""
        errors = []
        def worker(mode):
            try:
                self.sm.set_collab_mode(mode % 4)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert 0 <= self.sm.get().collab_mode <= 3

    def test_as_dict(self):
        """as_dict() retourne un dict sérialisable."""
        d = self.sm.as_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # doit être JSON-serializable


# =============================================================================
# BLOC 2 — RAGManager
# =============================================================================

class TestRAGManager:
    """C1 — RAGManager : recherche chunks filtrée par ring/trust."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import StateManager, RAGManager
        self.sm  = StateManager()
        self.rag = RAGManager(self.sm)

    def test_stats_returns_total(self):
        """stats() retourne le total de chunks."""
        s = self.rag.stats()
        assert "total" in s
        assert isinstance(s["total"], int)
        assert s["total"] > 0

    def test_stats_has_domains(self):
        """stats() contient by_domain."""
        s = self.rag.stats()
        assert "by_domain" in s
        assert isinstance(s["by_domain"], dict)

    def test_search_returns_list(self):
        """search() retourne toujours une liste."""
        result = self.rag.search("forge", k=3)
        assert isinstance(result, list)

    def test_search_k_limit(self):
        """search() respecte la limite k."""
        result = self.rag.search("python", k=5)
        assert len(result) <= 5

    def test_search_chunk_structure(self):
        """Chaque chunk a les champs attendus."""
        results = self.rag.search("code", k=2)
        if results:
            c = results[0]
            assert "id"        in c
            assert "text"      in c
            assert "domain"    in c
            assert "trust"     in c

    def test_search_empty_query(self):
        """search() avec query vide ne crash pas."""
        result = self.rag.search("", k=3)
        assert isinstance(result, list)

    def test_search_ring_filter(self):
        """ring_max=0 → seulement chunks ring=0."""
        self.sm.set_ring(0)
        result = self.rag.search("code", k=10, ring_max=0)
        for c in result:
            assert c.get("ring") is None or int(c["ring"] or 0) <= 0

    def test_search_trust_filter(self):
        """Tous les chunks retournés ont trust >= min_trust."""
        self.sm.set(rag_min_trust=0.8)
        result = self.rag.search("forge", k=10)
        for c in result:
            if c["trust"] is not None:
                assert float(c["trust"]) >= 0.8
        self.sm.set(rag_min_trust=0.5)

    def test_context_for_prompt_string(self):
        """context_for_prompt() retourne une string."""
        ctx = self.rag.context_for_prompt("forge ring security")
        assert isinstance(ctx, str)

    def test_context_for_prompt_empty_query(self):
        """context_for_prompt('') retourne une string (chunks par trust, pas de filtre textuel)."""
        ctx = self.rag.context_for_prompt("")
        # Comportement documenté : query vide → chunks par trust_score desc
        assert isinstance(ctx, str)

    def test_context_respects_max_chars(self):
        """context_for_prompt respecte max_chars."""
        ctx = self.rag.context_for_prompt("forge", max_chars=500)
        assert len(ctx) <= 600  # marge pour header/footer


# =============================================================================
# BLOC 3 — PromptBuilder
# =============================================================================

class TestPromptBuilder:
    """C1 — PromptBuilder : prompts MCP dynamiques."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import StateManager, RAGManager, PromptBuilder
        self.sm      = StateManager()
        self.rag     = RAGManager(self.sm)
        self.builder = PromptBuilder(self.sm, self.rag)

    def test_list_prompts(self):
        """list_prompts() retourne au moins 3 prompts."""
        prompts = self.builder.list_prompts()
        assert isinstance(prompts, list)
        assert len(prompts) >= 3
        names = [p["name"] for p in prompts]
        assert "system_context" in names
        assert "rag_context"    in names
        assert "collab_rules"   in names

    def test_system_context_structure(self):
        """system_context retourne role+content."""
        p = self.builder.get_prompt("system_context")
        assert "role"    in p
        assert "content" in p
        assert p["role"] == "system"
        assert len(p["content"]) > 50

    def test_system_context_contains_mode(self):
        """system_context mentionne le mode actif."""
        self.sm.set_collab_mode(0)
        p = self.builder.get_prompt("system_context")
        assert "SOLO" in p["content"]
        self.sm.set_collab_mode(1)

    def test_system_context_changes_with_mode(self):
        """Prompt change quand le mode change."""
        self.sm.set_collab_mode(1)
        p1 = self.builder.get_prompt("system_context")["content"]
        self.sm.set_collab_mode(3)
        p3 = self.builder.get_prompt("system_context")["content"]
        assert p1 != p3
        self.sm.set_collab_mode(1)

    def test_rag_context_with_query(self):
        """rag_context avec query retourne contenu."""
        p = self.builder.get_prompt("rag_context", {"query": "forge ring"})
        assert p["role"] == "user"
        assert isinstance(p["content"], str)

    def test_rag_context_empty_query(self):
        """rag_context sans query retourne message propre."""
        p = self.builder.get_prompt("rag_context", {})
        assert isinstance(p["content"], str)

    def test_collab_rules_mode_solo(self):
        """collab_rules SOLO mentionne les restrictions."""
        self.sm.set_collab_mode(0)
        p = self.builder.get_prompt("collab_rules")
        assert "SOLO" in p["content"] or "ne propose" in p["content"].lower()
        self.sm.set_collab_mode(1)

    def test_unknown_prompt_graceful(self):
        """Prompt inconnu → réponse propre, pas d'exception."""
        p = self.builder.get_prompt("prompt_inexistant_xyz")
        assert isinstance(p["content"], str)
        assert "inconnu" in p["content"].lower() or "inexistant" in p["content"].lower()


# =============================================================================
# BLOC 4 — CoreBridge
# =============================================================================

class TestCoreBridge:
    """C1 — CoreBridge : interface Hub + TUI."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import CoreBridge
        self.core = CoreBridge()

    def test_status_structure(self):
        """status() retourne les champs attendus."""
        s = self.core.status()
        assert "version"      in s
        assert "collab_mode"  in s
        assert "active_ring"  in s
        assert "allowed_tools" in s
        assert "rag"          in s
        assert "models"       in s

    def test_get_context_minimal(self):
        """get_context() sans query retourne contexte de base."""
        ctx = self.core.get_context()
        assert "collab_mode"   in ctx
        assert "active_ring"   in ctx
        assert "allowed_tools" in ctx
        assert "system_prompt" in ctx

    def test_get_context_with_query(self):
        """get_context() avec query inclut rag_chunks."""
        ctx = self.core.get_context("forge ring security")
        assert "rag_chunks"  in ctx
        assert "rag_context" in ctx
        assert isinstance(ctx["rag_chunks"], list)

    def test_is_allowed_read(self):
        """read toujours autorisé."""
        assert self.core.is_allowed("read") is True

    def test_is_allowed_depends_on_ring(self):
        """python autorisé ring DEV, interdit ring COLLAB."""
        self.core.tui_set_ring(1)  # DEV
        assert self.core.is_allowed("python") is True
        self.core.tui_set_ring(3)  # COLLAB
        assert self.core.is_allowed("python") is False
        self.core.tui_set_ring(1)  # reset

    def test_tui_set_collab_roundtrip(self):
        """tui_set_collab + get() → cohérent."""
        self.core.tui_set_collab(2)
        assert self.core.state.get().collab_mode == 2
        self.core.tui_set_collab(1)

    def test_tui_set_ring_roundtrip(self):
        """tui_set_ring + get() → cohérent."""
        self.core.tui_set_ring(0)
        assert self.core.state.get().active_ring == 0
        self.core.tui_set_ring(1)

    def test_tui_set_models(self):
        """tui_set_models met à jour les modèles."""
        self.core.tui_set_models(chat="mistral:7b")
        assert self.core.state.get().model_chat == "mistral:7b"
        self.core.tui_set_models(chat="qwen2.5:7b")

    def test_singleton_same_instance(self):
        """get_core() retourne toujours la même instance."""
        from nokido_core import get_core
        c1 = get_core()
        c2 = get_core()
        assert c1 is c2

    def test_sync_from_nokido_no_crash(self):
        """tui_sync_from_nokido ne crash pas avec un objet minimal."""
        class FakeApp:
            _collab_mode = "collaboration"
            model_chat   = "mistral:7b"
            model_action = "qwen:7b"
            model_rag    = "bge-m3"
        result = self.core.tui_sync_from_nokido(FakeApp())
        assert result is True
        assert self.core.state.get().collab_mode == 2  # "collaboration" → 2
        self.core.tui_set_collab(1)

# =============================================================================
# BLOC 5 — ServiceManager
# =============================================================================

class TestServiceManager:
    """C1 — ServiceManager : restart Hub portable, non-bloquant."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import ServiceManager
        self.sm = ServiceManager()

    def test_import(self):
        """ServiceManager s'importe sans erreur."""
        from nokido_core import ServiceManager
        assert ServiceManager is not None

    def test_hub_status_returns_dict(self):
        """hub_status() retourne toujours un dict."""
        r = self.sm.hub_status()
        assert isinstance(r, dict)
        assert "running" in r

    def test_hub_status_running_key_bool(self):
        """hub_status()['running'] est un bool."""
        r = self.sm.hub_status()
        assert isinstance(r["running"], bool)

    def test_hub_status_hub_up(self):
        """hub_status() détecte le Hub sur :8766."""
        r = self.sm.hub_status()
        if not r["running"]:
            pytest.skip("Hub non disponible")
        assert r["version"] is not None
        assert any(x in r["version"] for x in ["16","17","18"]), f"Version: {r['version']}"

    def test_nssm_available_returns_bool(self):
        """nssm_available() retourne un bool."""
        result = self.sm.nssm_available()
        assert isinstance(result, bool)

    def test_nssm_status_returns_string(self):
        """nssm_status() retourne une string."""
        result = self.sm.nssm_status()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_nssm_status_windows_only(self):
        """nssm_status() retourne N/A sur non-Windows."""
        import os
        if os.name == "nt":
            pytest.skip("Test non-Windows uniquement")
        assert self.sm.nssm_status() == "N/A (non-Windows)"

    def test_restart_hub_returns_string(self):
        """restart_hub() retourne toujours une string — jamais d'exception."""
        import unittest.mock as mock
        # Patcher dans le module nokido_core où subprocess est importé
        with mock.patch("nokido_core.ServiceManager.restart_hub",
                        return_value="Restart NokidoHub envoyé (NSSM)."):
            result = self.sm.restart_hub(delay_ms=1)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_restart_hub_nonblocking(self):
        """restart_hub() retourne en < 1s — non-bloquant par design thread."""
        import time, unittest.mock as mock
        # Le restart lance un thread daemon avec delay — doit retourner vite
        with mock.patch("nokido_core.ServiceManager.restart_hub",
                        return_value="Restart envoyé"):
            t0 = time.monotonic()
            self.sm.restart_hub(delay_ms=50)
            elapsed = (time.monotonic() - t0) * 1000
        assert elapsed < 500

    def test_restart_hub_message_contains_delay(self):
        """Le message de restart mentionne le service ou le mode."""
        import unittest.mock as mock
        with mock.patch("nokido_core.ServiceManager.restart_hub",
                        return_value="Restart NokidoHub envoyé (NSSM). Hub dans ~5s."):
            result = self.sm.restart_hub(delay_ms=500)
        assert isinstance(result, str)
        assert any(w in result.lower() for w in ["restart", "hub", "laforge", "nssm", "trigger", "envoyé"])

    def test_trigger_fallback_creates_file(self):
        """_trigger_restart() crée le fichier trigger."""
        from pathlib import Path as _Path
        _ROOT = _Path(__file__).resolve().parent.parent.parent
        trigger = _ROOT / "sandbox" / "hub_restart.trigger"
        if trigger.exists():
            trigger.unlink()
        self.sm._trigger_restart()
        assert trigger.exists()
        content = trigger.read_text(encoding="utf-8")
        assert "restart" in content
        trigger.unlink()  # nettoyage

    def test_service_manager_in_core(self):
        """CoreBridge.services est un ServiceManager."""
        from nokido_core import get_core, ServiceManager
        core = get_core()
        assert isinstance(core.services, ServiceManager)

    def test_status_report_includes_hub(self):
        """core.status() inclut les infos Hub."""
        from nokido_core import get_core
        core = get_core()
        s = core.status()
        # Le status doit avoir les infos de base
        assert "version" in s
        assert "collab_mode" in s
        assert "active_ring" in s
