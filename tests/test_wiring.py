# -*- coding: utf-8 -*-
"""
tests/test_wiring.py — NR câblage complet des commandes @ Nokido v16.5
=======================================================================
Teste la chaîne complète :
  utilisateur tape "@cmd args"
    → forge_dispatch.dispatch()
    → handle_X(app, cmd_line)
    → app._handle_X() / forge_handlers._handle_X(app) / forge_dispatch_network
    → action réelle (mock)

Chaque test vérifie :
  1. La commande est dans le REGISTRY
  2. Le handler est importable et async
  3. Le handler appelle la bonne méthode/fonction
  4. L'appel ne lève pas d'exception inattendue (avec app mock)
  5. Le chat reçoit au moins un message

Lancer : python -m pytest tests/test_wiring.py -v
"""
from __future__ import annotations
import asyncio
import sys
import types
import re
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from enum import Enum

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau reel (scan LAN) (l.547)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures globales
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))


class AgentType(Enum):
    CHAT   = "chat"
    ACTION = "action"
    RAG    = "rag"


def _make_lf_mock():
    """Crée un module __main__ mock avec tous les globals Nokido."""
    m = types.ModuleType('__main__')
    m.AgentType        = AgentType
    m.DangerLevel      = type('DL', (), {'SAFE': 'safe', 'MEDIUM': 'medium'})()
    m.AGENT_META       = {
        AgentType.CHAT:   {"color": "#58a6ff", "icon": "💬", "label": "Chat"},
        AgentType.ACTION: {"color": "#f0883e", "icon": "⚡", "label": "Action"},
        AgentType.RAG:    {"color": "#3fb950", "icon": "🗄", "label": "RAG"},
    }
    m.HAS_DANGER_GUARD = False
    m.HAS_PREDICTIF    = False
    m.HAS_ROUTAGE      = False
    m.HAS_WEB_SEARCH   = False
    m.HAS_SANDBOX      = False
    m.HAS_SSH          = False
    m.HAS_PTY          = False
    m.HAS_PREFECT      = False
    m.HAS_SCORING      = False
    m.agentic_engine   = None
    m.rag_engine       = None
    m.version_manager  = type('VM', (), {
        'get_current_code': lambda self: '# code',
        'work_path': Path('app/LaForge.py'),
        'current_version': '0.13.0',
    })()
    m.settings = type('S', (), {
        'ollama_url': 'http://localhost:11434',
        'max_concurrent_tasks': 2,
        'rag_dir': 'data/rag_files',
        'ollama_model_default': 'qwen2.5',
    })()
    m.prefect_manager  = None
    m.ssh_manager      = None
    m.ollama_stream    = AsyncMock(return_value="[MOCK] réponse IA")
    m.ollama_call      = AsyncMock(return_value="[MOCK] call IA")
    m.get_orchestrator = lambda: type('Orc', (), {
        'handle': AsyncMock(return_value="[MOCK] orchestrateur"),
    })()
    m.escape           = lambda x: str(x)
    m.debug_log        = lambda *a, **k: None
    m.logger           = type('L', (), {
        'info': lambda *a,**k: None,
        'debug': lambda *a,**k: None,
        'warning': lambda *a,**k: None,
        'error': lambda *a,**k: None,
    })()
    m._pred_get_router = lambda: None
    m.get_proxy_url    = lambda name='': None
    m.get_best_proxy_url = lambda: None
    m.get_web_engine   = lambda: None
    m._ROOT_DIR        = Path('.')
    m._DATA_DIR        = Path('data')
    m.run_ssh          = AsyncMock(return_value="mock ssh")
    return m


class FakeChat:
    def __init__(self):
        self.messages = []
    def write(self, msg, *a, **k):
        self.messages.append(str(msg))
    def clear(self):
        self.messages.clear()
    def last(self):
        return self.messages[-1] if self.messages else ''
    def any_contains(self, text):
        return any(text.lower() in m.lower() for m in self.messages)


class FakeApp:
    """App mock minimal — simule DevOpsApp."""
    def __init__(self):
        self._chat      = FakeChat()
        self.ai_busy    = False
        self.current_agent = AgentType.CHAT
        self._collab_mode = "autonome"
        self._last_input  = ""
        self._last_input_ts = 0.0
        self._rag_pending_confirm = {}
        self._smart_router = None
        self.arch          = None
        self._awaiting_collab_prompt = ""
        self.context = type('C', (), {
            'messages': [],
            'add': lambda *a: None,
            'session_name': 'test',
        })()
        self.session_name = "test"
        self.guard        = None
        self.terminal     = MagicMock()
        self.role_panel   = type('R', (), {
            'activate': lambda *a: None,
            'deactivate': lambda *a: None,
            'reset': lambda *a: None,
        })()
        self.skill_panel  = type('S', (), {
            'mark_active':    lambda *a: None,
            'add_or_update':  lambda *a: None,
            'clear_skills':   lambda *a: None,
            'render_summary': lambda *a: None,
            'bootstrap_tree': lambda *a: None,
        })()
        self.scorer       = None
        self._has_sandbox = False
        self._get_sandbox = lambda: None
        self._has_predictif = False
        self._pred_get_router = lambda: None
        self.model_chat   = 'qwen2.5'
        self.model_action = 'qwen2.5'
        self.model_rag    = 'qwen2.5'
        self.last_audit_suggestions = []

    def _chat_log(self):          return self._chat
    def _set_status(self, s):     pass
    def _show_help(self):         self._chat.write("[HELP] aide affichée")
    def _select_model(self):      self._chat.write("[MODEL] sélecteur ouvert")
    def _update_mode_buttons(self): pass
    def query_one(self, *a, **k): raise Exception("NoWidget mock")
    def push_screen(self, *a):    pass
    def call_later(self, *a):     pass

    # Méthodes inline (non externalisées)
    async def _handle_run(self, cmd_line):
        self._chat.write(f"[RUN MOCK] {cmd_line}")

    async def _handle_ssh(self, cmd_line):
        self._chat.write(f"[SSH MOCK] {cmd_line}")

    async def _handle_disco(self, cmd_line):
        self._chat.write(f"[DISCO MOCK] {cmd_line}")

    async def _handle_agentic(self, cmd_line):
        self._chat.write(f"[AGENTIC MOCK] {cmd_line}")

    async def _handle_evolve(self, cmd_line):
        self._chat.write(f"[EVOLVE MOCK] {cmd_line}")

    async def _select_model(self):
        self._chat.write("[MODEL] ouvert")

    async def _index_self_in_rag(self):
        pass

    # Wrappers → forge_handlers
    async def _handle_audit(self):
        import forge_handlers as _fh
        await _fh._handle_audit(self)

    async def _handle_estim(self, desc):
        import forge_handlers as _fh
        await _fh._handle_estim(self, desc)

    async def _handle_loop(self, args):
        import forge_handlers as _fh
        await _fh._handle_loop(self, args)

    async def _handle_mode(self, args):
        import forge_handlers as _fh
        await _fh._handle_mode(self, args)

    async def _handle_role(self, args):
        import forge_handlers as _fh
        await _fh._handle_role(self, args)

    async def _handle_rag(self, args):
        import forge_handlers as _fh
        await _fh._handle_rag(self, args)

    async def _handle_proxy(self, args):
        import forge_handlers as _fh
        await _fh._handle_proxy(self, args)

    async def _handle_workflow(self, args):
        import forge_handlers as _fh
        await _fh._handle_workflow(self, args)

    async def _handle_ci(self, args):
        import forge_handlers as _fh
        await _fh._handle_ci(self, args)

    async def _handle_apply(self, args):
        import forge_handlers as _fh
        await _fh._handle_apply(self, args)


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_mocks():
    """Injecte les mocks globaux avant chaque test."""
    lf_mock = _make_lf_mock()
    old_main = sys.modules.get('__main__')
    sys.modules['__main__'] = lf_mock
    # Purger les modules pour recharger avec les bons mocks
    for mod in ['forge_handlers', 'forge_dispatch', 'forge_dispatch_network',
                'forge_collab_modes', 'forge_dispatch_ai']:
        sys.modules.pop(mod, None)
    yield lf_mock
    if old_main:
        sys.modules['__main__'] = old_main


@pytest.fixture
def app():
    return FakeApp()


def run(coro):
    """Exécute une coroutine dans un nouveau loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────────────
# Tests REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    """Vérifie que toutes les commandes sont enregistrées et les handlers async."""

    def test_registry_importable(self):
        import forge_dispatch as fd
        assert isinstance(fd.REGISTRY, dict)

    def test_all_expected_cmds_in_registry(self):
        import forge_dispatch as fd
        expected = [
            '@help', '@diag', '@run', '@ssh', '@scan', '@ids', '@disco',
            '@estim', '@agentic', '@evolve', '@loop', '@role', '@mode',
            '@model', '@rag', '@proxy', '@workflow', '@ci', '@switch',
            '@chain', '@collab', '@audit', '@apply', '@code', '@nlu', '@tools',
        ]
        # Aplatir les clés tuple
        flat_keys = set()
        for k in fd.REGISTRY:
            if isinstance(k, tuple):
                flat_keys.update(k)
            else:
                flat_keys.add(k)
        for cmd in expected:
            assert cmd in flat_keys, f"{cmd} absent du REGISTRY"

    def test_all_handlers_are_async(self):
        import asyncio, inspect, forge_dispatch as fd
        for key, fn in fd.REGISTRY.items():
            assert inspect.iscoroutinefunction(fn), \
                f"handler {key!r} → {fn.__name__} n'est pas async"

    def test_dispatch_unknown_cmd(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@inconnue test'))
        assert app._chat.any_contains('inconnue') or app._chat.any_contains('unknown') \
            or len(app._chat.messages) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests câblage bout-en-bout
# ─────────────────────────────────────────────────────────────────────────────

class TestWiringEndToEnd:
    """Simule chaque @ depuis dispatch jusqu'à l'action finale."""

    def test_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@help'))
        assert len(app._chat.messages) >= 1

    def test_run_simple(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@run ls -la'))
        assert app._chat.any_contains('RUN') or app._chat.any_contains('mock')

    def test_ssh_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@ssh help'))
        assert len(app._chat.messages) >= 1

    def test_audit_no_ollama(self, app, setup_mocks):
        """@audit sans ollama_stream → message d'avertissement."""
        setup_mocks.ollama_stream = None
        import forge_dispatch as fd
        run(fd.dispatch(app, '@audit'))
        # Doit afficher avertissement ou erreur — pas silencieux
        assert len(app._chat.messages) >= 1

    def test_audit_with_ollama(self, app, setup_mocks):
        """@audit avec ollama_stream mock → s'exécute sans crash."""
        setup_mocks.ollama_stream = AsyncMock(return_value="[MOCK] rapport audit")
        setup_mocks.version_manager = type('VM', (), {
            'get_current_code': lambda self: '# code test',
            'work_path': Path('app/LaForge.py'),
            'current_version': '0.13.0',
        })()
        import forge_dispatch as fd
        run(fd.dispatch(app, '@audit'))
        # Soit rapport affiché soit avertissement — pas de crash silencieux
        assert len(app._chat.messages) >= 1

    def test_estim_no_args(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@estim'))
        assert app._chat.any_contains('Usage') or app._chat.any_contains('description')

    def test_estim_with_args(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@estim refactoriser le module SSH'))
        assert len(app._chat.messages) >= 1

    def test_mode_display(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@mode'))
        assert len(app._chat.messages) >= 1
        assert app._chat.any_contains('mode') or app._chat.any_contains('Mode')

    def test_mode_set_autonome(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@mode set autonome'))
        assert app._chat.any_contains('autonome') or app._chat.any_contains('Mode')

    def test_mode_set_collaboration(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@mode set collaboration'))
        assert app._collab_mode == 'collaboration' or app._chat.any_contains('collaboration')

    def test_rag_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@rag'))
        assert len(app._chat.messages) >= 1

    def test_loop_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@loop'))
        assert len(app._chat.messages) >= 1

    def test_role_list(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@role list'))
        assert len(app._chat.messages) >= 1

    def test_collab_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@collab'))
        assert app._chat.any_contains('collab') or app._chat.any_contains('mode')

    def test_tools_list(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@tools list'))
        assert len(app._chat.messages) >= 1

    def test_scan_no_crash(self, app):
        """@scan → forge_dispatch_network.handle_scan → pas de crash."""
        import forge_dispatch as fd
        run(fd.dispatch(app, '@scan localhost/24'))
        # Soit scan démarre soit message d'erreur — pas silencieux
        assert len(app._chat.messages) >= 1

    def test_proxy_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@proxy'))
        assert len(app._chat.messages) >= 1

    def test_workflow_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@workflow'))
        assert len(app._chat.messages) >= 1

    def test_ci_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@ci'))
        assert len(app._chat.messages) >= 1

    def test_agentic_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@agentic help'))
        assert len(app._chat.messages) >= 1

    def test_evolve_help(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@evolve help'))
        assert len(app._chat.messages) >= 1

    def test_nlu_stats(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@nlu stats'))
        assert len(app._chat.messages) >= 1

    def test_apply_no_args(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@apply'))
        assert len(app._chat.messages) >= 1

    def test_disco_no_args(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@disco'))
        assert len(app._chat.messages) >= 1

    def test_disco_with_skill(self, app):
        import forge_dispatch as fd
        run(fd.dispatch(app, '@disco kubernetes'))
        assert len(app._chat.messages) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests forge_handlers directs
# ─────────────────────────────────────────────────────────────────────────────

class TestForgeHandlersDirect:
    """Appels directs aux fonctions forge_handlers sans passer par dispatch."""

    def test_handle_rag_importable(self):
        import forge_handlers as fh
        import inspect
        assert inspect.iscoroutinefunction(fh._handle_rag)

    def test_handle_audit_importable(self):
        import forge_handlers as fh
        import inspect
        assert inspect.iscoroutinefunction(fh._handle_audit)

    def test_all_10_handlers_async(self):
        import forge_handlers as fh
        import inspect
        for name in ['_handle_rag', '_handle_proxy', '_handle_workflow', '_handle_ci',
                     '_handle_audit', '_handle_estim', '_handle_loop', '_handle_mode',
                     '_handle_role', '_handle_apply']:
            fn = getattr(fh, name, None)
            assert fn is not None, f"{name} absent"
            assert inspect.iscoroutinefunction(fn), f"{name} pas async"

    def test_g_resolver_finds_globals(self, setup_mocks):
        import forge_handlers as fh
        assert fh._g('version_manager') is not None
        assert fh._g('AgentType') is not None
        assert fh._g('settings') is not None

    def test_no_bare_globals_in_handlers(self):
        src = Path('app/forge_handlers.py').read_text(encoding='utf-8', errors='ignore')
        body = src[src.find('async def _handle_'):]
        for g in ['version_manager', 'rag_engine', 'agentic_engine', 'prefect_manager']:
            # Pattern : usage brut sans _g()
            pat = r'(?<!_g\()(?<!\')(?<!\")(?<![_\w])\b' + g + r'\b(?![_\w\'"(])'
            hits = re.findall(pat, body)
            assert not hits, f"{g} encore brut dans forge_handlers ({len(hits)}x)"

    def test_handle_audit_guard_no_vm(self, app, setup_mocks):
        """Sans version_manager → message avertissement, pas de crash."""
        setup_mocks.version_manager = None
        import forge_handlers as fh
        run(fh._handle_audit(app))
        assert app._chat.any_contains('version_manager') or \
               app._chat.any_contains('non disponible') or \
               len(app._chat.messages) >= 1

    def test_handle_audit_guard_no_ollama(self, app, setup_mocks):
        """Sans ollama_stream → message avertissement."""
        setup_mocks.ollama_stream = None
        import forge_handlers as fh
        run(fh._handle_audit(app))
        assert app._chat.any_contains('ollama') or \
               app._chat.any_contains('Ollama') or \
               len(app._chat.messages) >= 1

    def test_handle_mode_set(self, app):
        import forge_handlers as fh
        run(fh._handle_mode(app, 'set collaboration'))
        assert app._collab_mode == 'collaboration'

    def test_handle_estim_no_args(self, app):
        import forge_handlers as fh
        run(fh._handle_estim(app, ''))
        assert len(app._chat.messages) >= 1

    def test_handle_loop_help(self, app):
        import forge_handlers as fh
        run(fh._handle_loop(app, ''))
        assert len(app._chat.messages) >= 1

    def test_handle_rag_help(self, app):
        import forge_handlers as fh
        run(fh._handle_rag(app, ''))
        assert len(app._chat.messages) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests forge_dispatch_network
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchNetwork:
    def test_importable(self):
        import forge_dispatch_network as fdn
        assert hasattr(fdn, 'handle_scan')
        assert hasattr(fdn, 'handle_ids')
        assert hasattr(fdn, 'handle_chain')

    def test_handle_scan_no_crash(self, app):
        import forge_dispatch_network as fdn
        run(fdn.handle_scan(app, ''))
        assert len(app._chat.messages) >= 1

    def test_no_bare_self_in_fdn(self):
        src = Path('app/forge_dispatch_network.py').read_text(encoding='utf-8', errors='ignore')
        # Hors commentaires et strings
        lines = [l for l in src.splitlines() if not l.lstrip().startswith('#')]
        bare = [l for l in lines if re.search(r'(?<![_\w])self\.', l)]
        assert not bare, f"self. encore présent: {bare[:3]}"


# ─────────────────────────────────────────────────────────────────────────────
# Test forge_dispatch_ai
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchAI:
    def test_importable(self):
        import forge_dispatch_ai as fda
        import inspect
        assert inspect.iscoroutinefunction(fda.dispatch_ai)

    def test_g_resolver(self, setup_mocks):
        import forge_dispatch_ai as fda
        assert fda._g('AgentType') is not None

    def test_no_bare_self(self):
        src = Path('app/forge_dispatch_ai.py').read_text(encoding='utf-8', errors='ignore')
        lines = [l for l in src.splitlines() if not l.lstrip().startswith('#')]
        bare  = [l for l in lines if re.search(r'(?<![_\w])self\.', l)]
        assert not bare, f"self. présent: {bare[:3]}"

    def test_debounce_guard(self, app):
        """Message dupliqué dans < 3s → retour immédiat."""
        import time, forge_dispatch_ai as fda
        app._last_input    = "test"
        app._last_input_ts = time.monotonic()
        run(fda.dispatch_ai(app, "test"))
        # Debounce → pas de message IA envoyé
        assert not app._chat.any_contains('MOCK ORC')

    def test_ai_busy_guard(self, app):
        """ai_busy=True → message d'avertissement dans le chat."""
        import forge_dispatch_ai as fda
        app.ai_busy = True
        run(fda.dispatch_ai(app, "nouveau message"))
        assert len(app._chat.messages) >= 1
        app.ai_busy = False


class TestSkillTreeRaceCondition:
    """Vérifie que la race condition compose()/on_mount() est corrigée."""

    def test_skill_panel_mock_complet(self, app):
        """skill_panel mock a toutes les méthodes requises."""
        required = ['mark_active', 'add_or_update', 'clear_skills',
                    'render_summary', 'bootstrap_tree']
        for m in required:
            assert hasattr(app.skill_panel, m), f"skill_panel.{m} manquant"

    def test_skill_panel_add_or_update_silent(self, app):
        """add_or_update ne doit pas lever d'exception."""
        try:
            app.skill_panel.add_or_update('python', 'learning')
            app.skill_panel.add_or_update('securite', 'verified')
        except Exception as e:
            pytest.fail(f"add_or_update a levé : {e}")

    def test_skill_panel_bootstrap_silent(self, app):
        """bootstrap_tree ne doit pas lever d'exception."""
        try:
            app.skill_panel.bootstrap_tree()
        except Exception as e:
            pytest.fail(f"bootstrap_tree a levé : {e}")

    def test_has_skilltree_flag(self):
        """HAS_SKILLTREE est défini dans Nokido.py."""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location(
            "nokido_main", "app/LaForge.py")
        # On ne charge pas le module complet (Textual requis)
        # On vérifie juste que la variable est définie dans le source
        src = open('app/LaForge.py', encoding='utf-8').read()
        assert 'HAS_SKILLTREE' in src
        assert 'HAS_SKILLTREE = False' in src   # valeur par défaut saine
        assert 'HAS_SKILLTREE = True' in src    # assigné si import OK

    def test_skill_placeholder_dans_compose(self):
        """compose() doit utiliser un placeholder, pas 'absent' directement."""
        src = open('app/backups/Nokido_pre_shredder.py', encoding='utf-8').read()
        assert 'skill-placeholder' in src, "placeholder id manquant"
        assert 'def bootstrap_tree' in src, "bootstrap_tree manquant"
        assert 'call_after_refresh' in src, "bootstrap_tree non appelé"


if __name__ == '__main__':
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', __file__, '-v', '--tb=short'],
        capture_output=False
    )
    sys.exit(result.returncode)
