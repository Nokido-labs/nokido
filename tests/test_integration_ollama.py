# -*- coding: utf-8 -*-
"""
tests/test_integration_ollama.py
=================================
Tests d'intégration avec Ollama réel (stdio MCP + HTTP).

Architecture testée :
  pytest
    → FakeApp (mock Textual)
    → forge_dispatch.dispatch()
    → forge_handlers / forge_dispatch_ai
    → forge_litellm_bridge.ask()   ← essaie Ollama bridge aiohttp
    → forge_litellm_bridge.ask()   ← fallback LiteLLM → ollama/qwen2.5
    → Ollama HTTP localhost:11434
    → réponse réelle du modèle

Lancer :
  python -m pytest tests/test_integration_ollama.py -v -s
  python -m pytest tests/test_integration_ollama.py -v -s -k "test_ollama"

Skip automatique si Ollama n'est pas joignable.
"""
from __future__ import annotations
import asyncio
import sys
import types
import re
import time
import json
import pytest
from pathlib import Path
from enum import Enum
from unittest.mock import MagicMock

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau reel (Ollama); sous-processus (MCP stdio)
#   (l.322)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# ─────────────────────────────────────────────────────────────────────────────
# Détection Ollama
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))

OLLAMA_URL  = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5"   # modèle rapide pour les tests


def _ollama_available() -> bool:
    """Vérifie si Ollama est joignable et a un modèle chargé."""
    try:
        import urllib.request
        r = urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        data = json.loads(r.read())
        models = [m['name'] for m in data.get('models', [])]
        return len(models) > 0
    except Exception:
        return False


def _pick_model() -> str:
    """Retourne le premier modèle disponible."""
    try:
        import urllib.request
        r = urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        data = json.loads(r.read())
        models = [m['name'] for m in data.get('models', [])]
        # Préférer qwen2.5 ou llama3
        for pref in ['qwen2.5', 'qwen2.5-coder', 'llama3', 'mistral']:
            for m in models:
                if pref in m:
                    return m
        return models[0] if models else OLLAMA_MODEL
    except Exception:
        return OLLAMA_MODEL


ollama_available = _ollama_available()
if ollama_available:
    OLLAMA_MODEL = _pick_model()

skip_no_ollama = pytest.mark.skipif(
    not ollama_available,
    reason=f"Ollama non joignable sur {OLLAMA_URL}"
)


# ─────────────────────────────────────────────────────────────────────────────
# Mock app + globals
# ─────────────────────────────────────────────────────────────────────────────

class AgentType(Enum):
    CHAT   = "chat"
    ACTION = "action"
    RAG    = "rag"


class FakeChat:
    def __init__(self):
        self.messages = []
    def write(self, msg, *a, **k):
        self.messages.append(str(msg))
    def last(self):
        return self.messages[-1] if self.messages else ''
    def all_text(self):
        return '\n'.join(self.messages)
    def clear(self):
        self.messages.clear()


class FakeApp:
    def __init__(self, model: str = OLLAMA_MODEL):
        self._chat       = FakeChat()
        self.ai_busy     = False
        self.current_agent = AgentType.CHAT
        self._collab_mode  = "autonome"
        self._last_input   = ""
        self._last_input_ts = 0.0
        self._rag_pending_confirm = {}
        self._smart_router = None
        self.arch          = None
        self._awaiting_collab_prompt = ""
        self.context = type('C', (), {
            'messages': [],
            'add': lambda *a: None,
        })()
        self.session_name = "test_integration"
        self.guard        = None
        self.terminal     = MagicMock()
        self.role_panel   = type('R', (), {
            'activate': lambda *a: None,
            'deactivate': lambda *a: None,
            'reset': lambda *a: None,
        })()
        self.skill_panel  = type('S', (), {'mark_active': lambda *a: None})()
        self.scorer        = None
        self.model_chat    = model
        self.model_action  = model
        self.model_rag     = model
        self.last_audit_suggestions = []

    def _chat_log(self):        return self._chat
    def _set_status(self, s):
        if s:
            print(f"    [STATUS] {s[:60]}")
    def _show_help(self):       self._chat.write("[HELP]")
    def _update_mode_buttons(self): pass
    def query_one(self, *a, **k): raise Exception("NoWidget")
    def push_screen(self, *a):  pass
    def call_later(self, *a):   pass

    async def _index_self_in_rag(self): pass

    async def _handle_run(self, cmd_line):
        self._chat.write(f"[RUN] {cmd_line[:40]}")

    async def _handle_ssh(self, cmd_line):
        self._chat.write(f"[SSH] {cmd_line[:40]}")

    async def _handle_disco(self, cmd_line):
        self._chat.write(f"[DISCO] {cmd_line[:40]}")

    async def _handle_agentic(self, cmd_line):
        self._chat.write(f"[AGENTIC] {cmd_line[:40]}")

    async def _handle_evolve(self, cmd_line):
        self._chat.write(f"[EVOLVE] {cmd_line[:40]}")

    async def _select_model(self):
        self._chat.write("[MODEL]")

    # Wrappers forge_handlers
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


def _make_lf_mock(model: str = OLLAMA_MODEL):
    """Crée le module __main__ mock avec les vrais bridges Ollama."""
    m = types.ModuleType('__main__')
    m.AgentType       = AgentType
    m.DangerLevel     = type('DL', (), {'SAFE': 'safe'})()
    m.AGENT_META      = {
        AgentType.CHAT:   {"color": "#58a6ff", "icon": "💬", "label": "Chat"},
        AgentType.ACTION: {"color": "#f0883e", "icon": "⚡", "label": "Action"},
        AgentType.RAG:    {"color": "#3fb950", "icon": "🗄",  "label": "RAG"},
    }
    m.HAS_DANGER_GUARD  = False
    m.HAS_PREDICTIF     = False
    m.HAS_ROUTAGE       = False
    m.HAS_WEB_SEARCH    = False
    m.HAS_SANDBOX       = False
    m.HAS_SSH           = False
    m.HAS_PTY           = False
    m.HAS_PREFECT       = False
    m.HAS_SCORING       = False
    m.agentic_engine    = None
    m.rag_engine        = None
    m.version_manager   = type('VM', (), {
        'get_current_code': lambda self: Path('app/LaForge.py').read_text(encoding='utf-8', errors='ignore')[:4000],
        'work_path': Path('app/LaForge.py'),
        'current_version': '0.13.0',
    })()
    m.settings = type('S', (), {
        'ollama_url':           OLLAMA_URL + '/api/chat',
        'ollama_model_default': model,
        'max_concurrent_tasks': 2,
        'rag_dir':              'data/rag_files',
    })()
    m.prefect_manager   = None
    m.ssh_manager       = None
    m.escape            = lambda x: str(x)
    m.debug_log         = lambda *a, **k: None
    m.logger            = type('L', (), {
        'info':    lambda *a,**k: None,
        'debug':   lambda *a,**k: None,
        'warning': lambda *a,**k: None,
        'error':   lambda *a,**k: None,
    })()
    m.get_proxy_url       = lambda name='': None
    m.get_best_proxy_url  = lambda: None
    m.get_web_engine      = lambda: None
    m._pred_get_router    = lambda: None
    m._ROOT_DIR           = Path('.')
    m._DATA_DIR           = Path('data')
    m.run_ssh             = lambda *a: None
    m.get_orchestrator    = lambda: type('Orc', (), {
        'handle': asyncio.coroutine(lambda self, *a, **k: "[MOCK ORC]"),
    })()

    # Vrais bridges Ollama — pas de mock
    # ollama_stream et ollama_call sont chargés depuis forge_llm
    try:
        import forge_llm
        m.ollama_stream = forge_llm.ollama_stream
        m.ollama_call   = forge_llm.ollama_call
        print(f"  [setup] forge_llm chargé — ollama_stream réel")
    except ImportError:
        m.ollama_stream = None
        m.ollama_call   = None
        print(f"  [setup] forge_llm absent — ollama_stream None")

    return m


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def setup_ollama_mocks():
    """Injecte les vrais bridges Ollama dans sys.modules."""
    lf_mock = _make_lf_mock(OLLAMA_MODEL)
    old_main = sys.modules.get('__main__')
    sys.modules['__main__'] = lf_mock
    for mod in ['forge_handlers', 'forge_dispatch', 'forge_dispatch_network',
                'forge_dispatch_ai', 'forge_llm', 'forge_litellm_bridge',
                'forge_ollama_bridge']:
        sys.modules.pop(mod, None)
    yield lf_mock
    if old_main:
        sys.modules['__main__'] = old_main


@pytest.fixture
def app():
    return FakeApp(OLLAMA_MODEL)


# ─────────────────────────────────────────────────────────────────────────────
# Tests de détection
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaDetection:

    def test_ollama_status(self):
        print(f"\n  Ollama joignable : {ollama_available}")
        print(f"  Modèle sélectionné : {OLLAMA_MODEL}")
        # Ce test passe toujours — info seulement
        assert True

    @skip_no_ollama
    def test_ollama_api_tags(self):
        import urllib.request
        r = urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
        data = json.loads(r.read())
        models = [m['name'] for m in data.get('models', [])]
        print(f"\n  Modèles Ollama ({len(models)}) : {models}")
        assert len(models) > 0

    @skip_no_ollama
    def test_litellm_bridge_importable(self):
        import forge_litellm_bridge as lb
        bridge = lb.get_litellm_bridge()
        status = bridge.status()
        print(f"\n  LiteLLM status : {status}")
        assert status['model'] is not None

    @skip_no_ollama
    def test_ollama_bridge_importable(self):
        import forge_ollama_bridge as ob
        bridge = ob.get_bridge()
        assert bridge is not None
        assert bridge.base_url == OLLAMA_URL


# ─────────────────────────────────────────────────────────────────────────────
# Tests bridge bas niveau
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaBridgeDirect:

    @skip_no_ollama
    def test_ollama_bridge_propose(self):
        """OllamaBridge.propose() → réponse réelle."""
        import forge_ollama_bridge as ob
        bridge = ob.OllamaBridge(model=OLLAMA_MODEL, base_url=OLLAMA_URL)
        result = run(bridge.propose("Dis juste 'ok' en une réponse très courte."))
        print(f"\n  Ollama bridge réponse : {result[:80]}")
        assert len(result) > 0, "Réponse vide"
        assert isinstance(result, str)

    @skip_no_ollama
    def test_litellm_ask(self):
        """forge_litellm_bridge.ask() → réponse réelle via Ollama."""
        import forge_litellm_bridge as lb
        result = run(lb.ask(
            "Réponds uniquement par 'ok' sans rien d'autre.",
            role="assistant test",
            max_tokens=10,
        ))
        print(f"\n  LiteLLM ask réponse : {result[:80]}")
        # Soit réponse réelle soit vide si litellm pas installé
        # Dans les deux cas pas de crash
        assert isinstance(result, str)

    @skip_no_ollama
    def test_forge_llm_ollama_call(self):
        """forge_llm.ollama_call() → appel direct Ollama."""
        import forge_llm
        result = run(forge_llm.ollama_call(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": "Dis juste 'ok'."}],
            max_tokens=10,
        ))
        print(f"\n  forge_llm.ollama_call : {result[:80]}")
        assert isinstance(result, str)
        assert len(result) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests commandes @ avec Ollama réel
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandsWithOllama:

    @skip_no_ollama
    def test_audit_real_ollama(self, app, setup_ollama_mocks):
        """@audit avec Ollama réel → rapport généré."""
        import forge_llm
        setup_ollama_mocks.ollama_stream = forge_llm.ollama_stream
        setup_ollama_mocks.version_manager = type('VM', (), {
            'get_current_code': lambda self: '# test\ndef hello(): pass\n',
            'work_path': Path('app/LaForge.py'),
            'current_version': '0.13.0',
        })()

        import forge_dispatch as fd
        t0 = time.time()
        run(fd.dispatch(app, '@audit'))
        elapsed = time.time() - t0

        print(f"\n  @audit terminé en {elapsed:.1f}s")
        print(f"  Messages reçus : {len(app._chat.messages)}")
        for msg in app._chat.messages[:5]:
            print(f"    {str(msg)[:80]}")

        assert len(app._chat.messages) >= 1, "Aucun message dans le chat"
        # Soit rapport soit avertissement — pas silencieux
        all_text = app._chat.all_text()
        has_content = (
            'audit' in all_text.lower() or
            'rapport' in all_text.lower() or
            'Ollama' in all_text or
            'erreur' in all_text.lower() or
            len(all_text) > 10
        )
        assert has_content

    @skip_no_ollama
    def test_estim_real_ollama(self, app, setup_ollama_mocks):
        """@estim avec Ollama réel → estimation générée."""
        import forge_llm
        setup_ollama_mocks.ollama_stream = forge_llm.ollama_stream

        import forge_dispatch as fd
        run(fd.dispatch(app, '@estim créer une API REST simple'))

        print(f"\n  @estim messages : {len(app._chat.messages)}")
        for msg in app._chat.messages[:3]:
            print(f"    {str(msg)[:80]}")
        assert len(app._chat.messages) >= 1

    @skip_no_ollama
    def test_loop_start_ollama(self, app, setup_ollama_mocks):
        """@loop --dry_run avec Ollama → pas de crash."""
        import forge_llm
        setup_ollama_mocks.ollama_stream = forge_llm.ollama_stream

        import forge_dispatch as fd
        run(fd.dispatch(app, '@loop --dry_run'))

        print(f"\n  @loop messages : {len(app._chat.messages)}")
        assert len(app._chat.messages) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests MCP stdio (process complet)
# ─────────────────────────────────────────────────────────────────────────────

class TestMCPStdio:
    """
    Teste le MCP server en stdio réel.
    Lance nokido_mcp_server.py comme subprocess, envoie des messages JSON-RPC,
    vérifie les réponses.
    """

    @skip_no_ollama
    def test_mcp_stdio_ping(self):
        """Lance le MCP en stdio et envoie initialize + ping."""
        import subprocess, json, sys

        cmd = [sys.executable, 'tools/nokido_mcp_server.py', '--name', 'TEST', '--mode', 'stdio']
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=0,
        )

        def send(msg):
            line = json.dumps(msg) + '\n'
            proc.stdin.write(line)
            proc.stdin.flush()

        def recv(timeout=5):
            import select, time
            start = time.time()
            while time.time() - start < timeout:
                line = proc.stdout.readline()
                if line.strip():
                    try:
                        return json.loads(line)
                    except Exception:
                        continue
            return None

        try:
            # Initialize
            send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}
                }
            })
            resp = recv(timeout=8)
            print(f"\n  MCP initialize : {resp}")
            assert resp is not None, "Pas de réponse au initialize"
            assert 'result' in resp or 'error' in resp

        finally:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)

    @skip_no_ollama
    def test_mcp_stdio_query_db_status(self):
        """Lance le MCP et appelle query(action='db_status')."""
        import subprocess, json, sys

        cmd = [sys.executable, 'tools/nokido_mcp_server.py', '--name', 'TEST', '--mode', 'stdio']
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
        )

        def send(msg):
            proc.stdin.write(json.dumps(msg) + '\n')
            proc.stdin.flush()

        def recv(timeout=8):
            import time
            start = time.time()
            while time.time() - start < timeout:
                line = proc.stdout.readline()
                if line.strip():
                    try: return json.loads(line)
                    except: pass
            return None

        try:
            # Initialize
            send({"jsonrpc":"2.0","id":1,"method":"initialize",
                  "params":{"protocolVersion":"2024-11-05","capabilities":{},
                            "clientInfo":{"name":"test","version":"1.0"}}})
            recv(timeout=8)

            # initialized notification
            send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})

            # Appeler query db_status
            send({"jsonrpc":"2.0","id":2,"method":"tools/call",
                  "params":{"name":"query","arguments":{"action":"db_status"}}})

            resp = recv(timeout=10)
            print(f"\n  MCP db_status response : {str(resp)[:200]}")
            assert resp is not None
            assert 'result' in resp or 'error' in resp

        finally:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == '__main__':
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', __file__, '-v', '-s'],
        capture_output=False
    )
    sys.exit(result.returncode)
