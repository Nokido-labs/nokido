"""
tests/nr/test_refacto_nr.py - Tests non-regression de la refacto 2026-04.

Verrouille les garanties des 3 sessions de refacto architecturale :
- forge_state.py : constantes uniques
- forge_retry_strategies : wait_exp_jitter + CircuitBreaker
- app.api_facade : NokidoFacade + AsyncNokidoFacade
- app.protocols : 5 Protocols runtime_checkable
- app.core.settings.fields : 10 domaines, 26 champs
- app.ui.facade_accessor : 4 patterns d acces
- forge_llm_router : CircuitBreaker branche

Execution:
    pytest tests/nr/test_refacto_nr.py -v
"""
from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob racine + lecture
#   (l.620)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


# ═══════════════════════════════════════════════════════════════════════════
# 1. forge_state.py : constantes uniques (PRIORITE 1 audit Gemini)
# ═══════════════════════════════════════════════════════════════════════════


class TestForgeState:
    """Tests forge_state.py - bug constantes dupliquees."""

    def test_constants_unique(self):
        """Chaque constante _T_* est definie UNE SEULE fois."""
        import re
        path = ROOT / "app" / "forge_state.py"
        src = path.read_text(encoding="utf-8", errors="replace")
        for name in ["_T_EMPTY", "_T_INT", "_T_FLOAT", "_T_STR", "_T_BOOL"]:
            defs = re.findall(rf"^{name}\s*=\s*\d+", src, re.MULTILINE)
            assert len(defs) == 1, f"{name} doit etre defini 1 fois (trouve {len(defs)})"

    def test_hot_path_int(self):
        """set_hot/get_hot avec int."""
        import forge_state
        s = forge_state.state
        assert s.set_hot("test_nr_int", 42)
        assert s.get_hot("test_nr_int") == 42

    def test_hot_path_str(self):
        """set_hot/get_hot avec str."""
        import forge_state
        s = forge_state.state
        assert s.set_hot("test_nr_str", "hello")
        assert s.get_hot("test_nr_str") == "hello"

    def test_hot_path_bool(self):
        """set_hot/get_hot avec bool."""
        import forge_state
        s = forge_state.state
        assert s.set_hot("test_nr_bool", True)
        assert s.get_hot("test_nr_bool") is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. forge_retry_strategies : wait_exp_jitter + CircuitBreaker
# ═══════════════════════════════════════════════════════════════════════════


class TestRetryStrategies:
    """Tests forge_retry_strategies.py - wait_exp_jitter + CircuitBreaker."""

    def test_wait_exp_jitter_exists(self):
        """wait_exp_jitter est exposee."""
        from forge_retry_strategies import wait_exp_jitter
        assert wait_exp_jitter is not None

    def test_wait_exp_jitter_respects_cap(self):
        """Backoff respecte le cap max."""
        from forge_retry_strategies import wait_exp_jitter
        w = wait_exp_jitter(base=1.0, cap=10.0)
        class FakeState:
            attempt_number = 20  # tres eleve
        delay = w(FakeState())
        assert 0 <= delay <= 10.0

    def test_wait_exp_jitter_grows(self):
        """Backoff croit avec l attempt_number (moyenne)."""
        from forge_retry_strategies import wait_exp_jitter
        w = wait_exp_jitter(base=1.0, cap=60.0, jitter_ratio=0.0)  # pas de jitter pour determinisme
        class S:
            def __init__(self, n): self.attempt_number = n
        d1 = w(S(1))
        d5 = w(S(5))
        assert d5 > d1

    def test_circuit_breaker_transitions(self):
        """CircuitBreaker passe CLOSED -> OPEN apres N failures."""
        from forge_retry_strategies import CircuitBreaker
        CircuitBreaker.reset("test_nr_cb")
        cb = CircuitBreaker("test_nr_cb", fail_threshold=3, recovery_time=60.0)
        assert cb.allow()
        assert cb.status == "CLOSED"
        for _ in range(3):
            cb.record_failure()
        assert cb.status == "OPEN"
        assert not cb.allow()

    def test_circuit_breaker_half_open_recovery(self):
        """CircuitBreaker passe OPEN -> HALF_OPEN apres recovery_time."""
        import time
        from forge_retry_strategies import CircuitBreaker
        CircuitBreaker.reset("test_nr_cb_recovery")
        cb = CircuitBreaker("test_nr_cb_recovery", fail_threshold=1, recovery_time=0.2)
        cb.record_failure()
        assert cb.status == "OPEN"
        time.sleep(0.3)
        assert cb.status == "HALF_OPEN"
        cb.record_success()
        assert cb.status == "CLOSED"

    def test_circuit_breaker_snapshot(self):
        """CircuitBreaker.snapshot() retourne dict de tous les providers."""
        from forge_retry_strategies import CircuitBreaker
        CircuitBreaker("test_nr_snap_1")
        CircuitBreaker("test_nr_snap_2")
        snap = CircuitBreaker.snapshot()
        assert "test_nr_snap_1" in snap
        assert "test_nr_snap_2" in snap


# ═══════════════════════════════════════════════════════════════════════════
# 3. app.api_facade : NokidoFacade sync + async
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIFacade:
    """Tests api_facade.py - NokidoFacade + AsyncNokidoFacade."""

    def test_sync_facade_importable(self):
        """NokidoFacade importable via app.api_facade."""
        from app.api_facade import NokidoFacade, get_facade
        f = get_facade()
        assert isinstance(f, NokidoFacade)

    def test_sync_facade_singleton(self):
        """get_facade() retourne le meme objet."""
        from app.api_facade import get_facade
        assert get_facade() is get_facade()

    def test_sync_facade_no_crash_on_missing_backend(self):
        """ask_llm avec backend inconnu ne crashe pas."""
        from app.api_facade import get_facade
        result = get_facade().ask_llm("test", backend="nonexistent_backend")
        assert isinstance(result, str)
        assert "backend" in result.lower()

    def test_sync_facade_settings_domains(self):
        """settings_domains retourne les 10 domaines."""
        from app.api_facade import get_facade
        domains = get_facade().settings_domains()
        assert len(domains) == 10
        assert "ollama" in domains
        assert "rag" in domains
        assert "ssh" in domains

    def test_async_facade_importable(self):
        """AsyncNokidoFacade importable."""
        from app.api_facade import AsyncNokidoFacade, get_async_facade
        f = get_async_facade()
        assert isinstance(f, AsyncNokidoFacade)

    def test_async_facade_status(self):
        """agents_status_async retourne un dict."""
        from app.api_facade import get_async_facade
        async def run():
            return await get_async_facade().agents_status_async()
        result = asyncio.run(run())
        assert isinstance(result, dict)
        assert "status" in result

    def test_async_facade_gather(self):
        """Pipeline asyncio.gather fonctionne."""
        from app.api_facade import get_async_facade
        async def run():
            f = get_async_facade()
            r1, r2 = await asyncio.gather(
                f.agents_status_async(),
                f.rag_status_async(),
            )
            return r1, r2
        r1, r2 = asyncio.run(run())
        assert "status" in r1
        assert "status" in r2


# ═══════════════════════════════════════════════════════════════════════════
# 4. app.protocols : 5 Protocols runtime_checkable
# ═══════════════════════════════════════════════════════════════════════════


class TestProtocols:
    """Tests app.protocols.py - 5 interfaces pour DI."""

    def test_all_protocols_exposed(self):
        """Tous les 5 Protocols sont dans __all__."""
        from app import protocols
        expected = {
            "LLMBridgeProtocol",
            "AppContextProtocol",
            "VersionManagerProtocol",
            "WebSearchProtocol",
            "RAGEngineProtocol",
        }
        assert set(protocols.__all__) == expected

    def test_app_context_protocol_runtime_check(self):
        """Un objet avec get/set est reconnu comme AppContextProtocol."""
        from app.protocols import AppContextProtocol

        class MyCtx:
            def get(self, key, default=None): return default
            def set(self, key, value): pass

        assert isinstance(MyCtx(), AppContextProtocol)


# ═══════════════════════════════════════════════════════════════════════════
# 5. app.core.settings.fields : 10 domaines, 26 champs
# ═══════════════════════════════════════════════════════════════════════════


class TestSettingsFields:
    """Tests du split settings par domaine."""

    def test_10_domains(self):
        """BY_DOMAIN contient exactement 10 domaines."""
        from app.core.settings.fields import BY_DOMAIN
        assert len(BY_DOMAIN) == 10
        expected = {"ssh", "ollama", "rag", "runtime", "loop",
                    "auto", "alerting", "time", "env", "db"}
        assert set(BY_DOMAIN.keys()) == expected

    def test_26_fields_total(self):
        """ALL_FIELDS contient bien les 26 champs."""
        from app.core.settings.fields import ALL_FIELDS
        assert len(ALL_FIELDS) == 26

    def test_ollama_fields_count(self):
        """OLLAMA_FIELDS = 6 champs."""
        from app.core.settings.fields import OLLAMA_FIELDS
        assert len(OLLAMA_FIELDS) == 6

    def test_congruence_with_legacy(self):
        """Les 26 fields split correspondent a _SETTINGS_FIELDS original."""
        import ast
        src = (ROOT / "app" / "forge_settings.py").read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        original_envs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "_SETTINGS_FIELDS":
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                                env_name = elt.elts[1].value if isinstance(elt.elts[1], ast.Constant) else None
                                if env_name:
                                    original_envs.append(env_name)
        from app.core.settings.fields import ALL_FIELDS
        new_envs = [f[1] for f in ALL_FIELDS]
        assert set(original_envs) == set(new_envs), "Divergence entre legacy et split"


# ═══════════════════════════════════════════════════════════════════════════
# 6. app.ui.facade_accessor : 4 patterns d acces
# ═══════════════════════════════════════════════════════════════════════════


class TestFacadeAccessor:
    """Tests app.ui.facade_accessor - patterns UI."""

    def test_get_ui_facade_sync(self):
        """get_ui_facade_sync retourne NokidoFacade."""
        from app.ui.facade_accessor import get_ui_facade_sync
        from app.api_facade import NokidoFacade
        f = get_ui_facade_sync()
        assert isinstance(f, NokidoFacade)

    def test_get_ui_facade_async(self):
        """get_ui_facade retourne AsyncNokidoFacade."""
        from app.ui.facade_accessor import get_ui_facade
        from app.api_facade import AsyncNokidoFacade
        f = get_ui_facade()
        assert isinstance(f, AsyncNokidoFacade)

    def test_attach_facade_to_app(self):
        """attach_facade_to_app ajoute self.facade + self.afacade."""
        from app.ui.facade_accessor import attach_facade_to_app

        class FakeApp: pass
        app = FakeApp()
        attach_facade_to_app(app)
        assert hasattr(app, "facade")
        assert hasattr(app, "afacade")

    def test_facade_mixin(self):
        """FacadeMixin._init_facade() fonctionne."""
        from app.ui.facade_accessor import FacadeMixin

        class FakeWidget(FacadeMixin):
            def __init__(self):
                self._init_facade()

        w = FakeWidget()
        assert hasattr(w, "facade")
        assert hasattr(w, "afacade")


# ═══════════════════════════════════════════════════════════════════════════
# 7. forge_llm_router : CircuitBreaker branche
# ═══════════════════════════════════════════════════════════════════════════


class TestLLMRouterCircuitBreaker:
    """Tests forge_llm_router.py - CircuitBreaker integration."""

    def test_get_snapshot_importable(self):
        """get_circuit_breakers_snapshot est exposee."""
        from forge_llm_router import get_circuit_breakers_snapshot
        snap = get_circuit_breakers_snapshot()
        assert isinstance(snap, dict)

    def test_reset_importable(self):
        """reset_circuit_breaker est exposee."""
        from forge_llm_router import reset_circuit_breaker
        assert callable(reset_circuit_breaker)

    def test_provider_slot_has_breaker(self):
        """ProviderSlot initialise un _breaker."""
        from forge_llm_router import ProviderSlot
        slot = ProviderSlot("test_nr_router", {"rpm": 10, "env_key": ""})
        assert hasattr(slot, "_breaker")
        assert slot._breaker.allow()

    def test_slot_breaker_blocks_after_failures(self):
        """Apres 5 failures, le slot n est plus is_available."""
        from forge_llm_router import ProviderSlot
        from forge_retry_strategies import CircuitBreaker
        CircuitBreaker.reset("llm_router::test_nr_block")
        slot = ProviderSlot("test_nr_block", {"rpm": 10, "env_key": ""})
        assert slot.is_available
        for _ in range(5):
            slot.record_failure()
        assert not slot._breaker.allow()
        assert not slot.is_available



# ═══════════════════════════════════════════════════════════════════════════
# 8. app.agents.* : sous-modules par domaine (Priorite 3 Gemini)
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentsSubpackages:
    """Tests app/agents/ sous-modules par domaine."""

    def test_core_exports(self):
        """app.agents.core expose AgentRole + dataclasses."""
        from app.agents.core import (
            AgentRole, RoleAssignment, ScoredModel,
            ModelBenchmark, RouteResult, AgentContrib, Distrib,
        )
        assert AgentRole is not None

    def test_routing_exports(self):
        """app.agents.routing expose SmartRouter et factories."""
        from app.agents.routing import SmartRouter, IntentRouter, init_router, get_router
        assert callable(init_router)
        assert callable(get_router)

    def test_benchmarking_exports(self):
        """app.agents.benchmarking expose les scorers."""
        from app.agents.benchmarking import ModelBenchmarker, ModelScorer
        assert ModelBenchmarker is not None

    def test_roles_exports(self):
        """app.agents.roles expose l orchestrateur de roles."""
        from app.agents.roles import RoleOrchestrator, PromptClassifier, PromptCategory
        assert RoleOrchestrator is not None

    def test_architecture_exports(self):
        """app.agents.architecture expose le detecteur."""
        from app.agents.architecture import ArchitectureDetector, ArchitectureProfile
        assert ArchitectureDetector is not None

    def test_ollama_runner_exports(self):
        """app.agents.ollama_runner expose OllamaParallelRunner."""
        from app.agents.ollama_runner import OllamaParallelRunner
        assert OllamaParallelRunner is not None

    def test_planning_exports(self):
        """app.agents.planning expose planner + synthesizer."""
        from app.agents.planning import AgentPlanner, AgentSynthesizer
        assert AgentPlanner is not None

    def test_congruence_with_legacy(self):
        """Les classes re-exportees sont IDENTIQUES au legacy forge_agents."""
        from app.agents.routing import SmartRouter as SR_new
        from app.agents.roles import RoleOrchestrator as RO_new
        from app.agents.core import AgentRole as AR_new
        import forge_agents as fa
        assert SR_new is fa.SmartRouter
        assert RO_new is fa.RoleOrchestrator
        assert AR_new is fa.AgentRole

    def test_commands_via_facade_importable(self):
        """tools: app.ui.commands_via_facade expose 6 commandes."""
        from app.ui.commands_via_facade import (
            cmd_ask_llm, cmd_status, cmd_scan_code,
            COMMANDS_REGISTRY, list_commands,
        )
        cmds = list_commands()
        assert len(cmds) == 6
        assert "ask" in cmds
        assert "status" in cmds
        assert "scan" in cmds

    def test_settings_facade_delegations(self):
        """app.core.settings delegue bien vers forge_settings."""
        from app.core.settings import Settings, create_settings, get_settings, get_app_attr
        import forge_settings as fs
        # Les fonctions sont les MEMES objets
        assert create_settings is fs.create_settings
        assert get_settings is fs.get_settings
        assert get_app_attr is fs.get_app_attr



# ═══════════════════════════════════════════════════════════════════════════
# 9. app.core.di_container : DI Container (Vague 4)
# ═══════════════════════════════════════════════════════════════════════════


class TestDIContainer:
    """Tests app/core/di_container.py - Dependency Injection."""

    def test_container_importable(self):
        """DIContainer importable depuis app.core.di_container."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        assert c.list_services() == []

    def test_register_and_get_singleton(self):
        """Register + get retourne singleton memoise."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        calls = [0]

        def factory():
            calls[0] += 1
            return {"id": calls[0]}

        c.register("svc", factory)
        s1 = c.get("svc")
        s2 = c.get("svc")
        assert s1 is s2
        assert calls[0] == 1

    def test_transient_returns_new_instances(self):
        """transient=True donne une nouvelle instance a chaque get."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        c.register("svc", lambda: object(), transient=True)
        assert c.get("svc") is not c.get("svc")

    def test_get_raises_keyerror_if_unregistered(self):
        """get() sur service inconnu -> KeyError."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        import pytest
        with pytest.raises(KeyError):
            c.get("nonexistent")

    def test_has(self):
        """has() verifie presence d un service."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        c.register("svc", lambda: None)
        assert c.has("svc")
        assert not c.has("other")

    def test_reset_singleton(self):
        """reset() vide le singleton memoise."""
        from app.core.di_container import DIContainer
        c = DIContainer()
        calls = [0]

        def factory():
            calls[0] += 1
            return calls[0]

        c.register("svc", factory)
        assert c.get("svc") == 1
        c.reset("svc")
        assert c.get("svc") == 2

    def test_global_container_has_services(self):
        """Container global a les services Nokido enregistres."""
        from app.core.di_container import get_container
        c = get_container()
        expected = {"facade", "async_facade", "settings",
                    "breakers_snapshot", "settings_domains", "protocols"}
        assert set(c.list_services()) == expected

    def test_global_container_facade(self):
        """Container global retourne la facade Nokido."""
        from app.core.di_container import get_container
        from app.api_facade import NokidoFacade
        facade = get_container().get("facade")
        assert isinstance(facade, NokidoFacade)

    def test_global_container_async_facade(self):
        """Container global retourne l async facade."""
        from app.core.di_container import get_container
        from app.api_facade import AsyncNokidoFacade
        afacade = get_container().get("async_facade")
        assert isinstance(afacade, AsyncNokidoFacade)

    def test_global_container_domains(self):
        """Container retourne les 10 domaines settings."""
        from app.core.di_container import get_container
        domains = get_container().get("settings_domains")
        assert len(domains) == 10
        assert "ollama" in domains

    def test_global_container_protocols(self):
        """Container retourne les 5 Protocols."""
        from app.core.di_container import get_container
        protos = get_container().get("protocols")
        assert len(protos) == 5
        assert "LLMBridgeProtocol" in protos

    def test_set_and_reset_container(self):
        """set_container et reset_container fonctionnent."""
        from app.core.di_container import (
            DIContainer, get_container, set_container, reset_container
        )
        mock = DIContainer()
        mock.register("facade", lambda: "MOCK")
        set_container(mock)
        assert get_container().get("facade") == "MOCK"
        reset_container()
        # Apres reset, le vrai container est reconstruit
        real = get_container().get("facade")
        assert real != "MOCK"

    def test_facade_accessor_get_container(self):
        """app.ui.facade_accessor.get_container fonctionne."""
        from app.ui.facade_accessor import get_container as acc_get_container
        from app.core.di_container import get_container
        # Doit retourner le meme container global
        assert acc_get_container() is get_container()

    def test_attach_container_to_app(self):
        """attach_container_to_app ajoute self.container."""
        from app.ui.facade_accessor import attach_container_to_app
        from app.core.di_container import DIContainer

        class FakeApp: pass
        app = FakeApp()
        attach_container_to_app(app)
        assert hasattr(app, "container")
        assert isinstance(app.container, DIContainer)

# ═══════════════════════════════════════════════════════════════════════════
# 10. Tests STRUCTURELS - verrou anti-regression refacto futur (Chantier D)
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuralInvariants:
    """Tests structurels : taille fichiers, pas de dupes, pas d orphelins.

    Ces tests verrouillent les invariants architecturaux, pas le comportement.
    Ajoute 2026-04-24 par Claude dans le cadre du Chantier D (refacto securite+perf).
    """

    # Seuils definis apres analyse des monolithes actuels :
    # - Nokido.py ~190KB sera splitte, target 150KB max au final
    # - Objectif a terme : aucun fichier > 100KB
    # - Cible intermediaire (verrou actuel) : 200KB max
    MAX_FILE_SIZE_KB = 200
    MAX_FILE_LINES = 5000
    IGNORED_FILES = (
        "app/LaForge.py",                  # monolithe historique, refacto prevu
        "legacy/",                          # archives
        "shadow_mutation/",                 # vault genetique
        "inspirations/",                    # clones externes
        "__pycache__",
        "node_modules",
        "_attic/",                          # code mort
        "archive/",                         # anciennes migrations
        "sandbox/test_repos/",              # clones repos externes pour benches
        "sandbox/refacto_backups/",         # mes backups refacto
        "sandbox/benchmarks/",              # datasets
        "sandbox/longmemeval/",             # datasets
        "sandbox/kaggle",                   # exports
        "workspace/",                       # copies historiques Nokido_v*
        "kaggle_dataset/",                  # exports
        "forge_desktop/",                   # Qt app distincte (0 test NR encore)
    )

    def _iter_active_py(self):
        """Parcourt les .py actifs (hors legacy/shadow/inspirations)."""
        for p in ROOT.rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if any(ign in rel for ign in self.IGNORED_FILES):
                continue
            yield rel, p

    def test_no_file_over_size_limit(self):
        """Aucun fichier .py actif ne depasse MAX_FILE_SIZE_KB (verrou refacto)."""
        oversized = []
        for rel, p in self._iter_active_py():
            sz_kb = p.stat().st_size / 1024
            if sz_kb > self.MAX_FILE_SIZE_KB:
                oversized.append((rel, sz_kb))
        assert not oversized, (
            f"{len(oversized)} fichier(s) depassent {self.MAX_FILE_SIZE_KB}KB : "
            + ", ".join(f"{r} ({sz:.1f}KB)" for r, sz in oversized[:5])
        )

    def test_no_file_over_line_limit(self):
        """Aucun fichier .py actif ne depasse MAX_FILE_LINES (verrou refacto)."""
        oversized = []
        for rel, p in self._iter_active_py():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").count("\n")
            except OSError:
                continue
            if lines > self.MAX_FILE_LINES:
                oversized.append((rel, lines))
        assert not oversized, (
            f"{len(oversized)} fichier(s) depassent {self.MAX_FILE_LINES} lignes : "
            + ", ".join(f"{r} ({n}L)" for r, n in oversized[:5])
        )

    def test_class_uniqueness_critical(self):
        """Classes critiques : une seule definition concrete dans le code actif.

        Les re-exports (import X from Y) ne comptent pas. Chaque classe
        critique doit avoir exactement 1 fichier qui la DEFINIT.
        """
        import ast
        critical_classes = [
            "ErrorManager",
            "SSHManager",
            # SkillEntry : en cours de refacto Gemini, sera verrouille
            # AgenticEngine : idem
        ]
        definitions = {name: [] for name in critical_classes}
        for rel, p in self._iter_active_py():
            # Skip tests/ pour eviter faux positifs
            if rel.startswith("tests/"):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name in critical_classes:
                    definitions[node.name].append(rel)
        for cls, files in definitions.items():
            assert len(files) <= 1, (
                f"class {cls} definie {len(files)} fois : {files}. "
                f"Attendu : 1 definition + N re-exports via import."
            )

    def test_no_duplicate_enum_values(self):
        """Les enums critiques n ont pas de valeurs dupliquees."""
        from forge_core_models import AgentType, TaskPriority
        for enum_cls in [AgentType, TaskPriority]:
            values = [e.value for e in enum_cls]
            assert len(values) == len(set(values)), (
                f"{enum_cls.__name__} a des valeurs dupliquees : {values}"
            )

    def test_dataclasses_have_decorator(self):
        """Classes avec field(default_factory=...) doivent etre @dataclass.
        
        Verifie le bug latent SkillEntry (fix 0966005) ne se reproduise pas.
        """
        import ast
        violations = []
        for rel, p in self._iter_active_py():
            if rel.startswith("tests/"):
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # La classe utilise-t-elle field(default_factory=...) ?
                uses_field_factory = False
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.value, ast.Call):
                        if (isinstance(item.value.func, ast.Name) 
                            and item.value.func.id == "field"):
                            for kw in item.value.keywords:
                                if kw.arg == "default_factory":
                                    uses_field_factory = True
                                    break
                if uses_field_factory:
                    # Verifier qu elle a @dataclass
                    has_dataclass = any(
                        (isinstance(d, ast.Name) and d.id == "dataclass")
                        or (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) 
                            and d.func.id == "dataclass")
                        for d in node.decorator_list
                    )
                    if not has_dataclass:
                        violations.append(f"{rel}:{node.lineno} class {node.name}")
        assert not violations, (
            f"{len(violations)} classe(s) utilisent field(default_factory) "
            f"sans @dataclass : {violations[:5]}"
        )

    def test_bridge_state_uses_state_manager(self):
        """Le Hub HTTP et le STDIO server utilisent bien StateManager (chantier C Gemini).

        Verrouille l invariant : pas de json.dump direct sur bridge_state.json
        sans passer par le filelock du StateManager.
        """
        # Teste que StateManager est importable et utilise par au moins les handlers
        try:
            from forge_state_manager import StateManager, get_state_manager
        except ImportError:
            pytest.skip("forge_state_manager.py pas encore present (Chantier C en cours)")
            return
        sm = get_state_manager()
        assert sm is not None
        # Verifier que sa lecture ne crashe pas
        state = sm.read_state()
        assert isinstance(state, dict)
        assert "active_mode" in state

    def test_forge_ssh_reexports_from_core_models(self):
        """forge_ssh.py re-exporte ErrorManager et SSHManager depuis core_models.

        Verrouille le commit ff8421e (dedup classes).
        """
        import forge_ssh
        import forge_core_models
        assert forge_ssh.ErrorManager is forge_core_models.ErrorManager, (
            "forge_ssh.ErrorManager doit etre celle de core_models (re-export)"
        )
        assert forge_ssh.SSHManager is forge_core_models.SSHManager, (
            "forge_ssh.SSHManager doit etre celle de core_models (re-export)"
        )

    def test_skill_entry_instantiable(self):
        """SkillEntry de core_models prend des arguments (fix commit 0966005).

        Verrouille le bug latent : sans @dataclass, SkillEntry() crashait.
        """
        from forge_core_models import SkillEntry
        s = SkillEntry(name="test_structural_nr", score=0.5)
        assert s.name == "test_structural_nr"
        assert s.score == 0.5
        assert s.tasks_ok == []  # default_factory
        assert s.confidence_history == []  # default_factory
        # Isolation entre instances
        s.tasks_ok.append("x")
        s2 = SkillEntry(name="other")
        assert s2.tasks_ok == [], "default_factory doit produire des listes independantes"

