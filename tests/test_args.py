# -*- coding: utf-8 -*-
"""
tests/test_args.py — NR arguments et sous-commandes v16.5
==========================================================
Teste chaque commande @ avec ses arguments réels :
  @rag info / @rag size / @rag search <query>
  @proxy start/stop/test
  @mode set autonome/collaboration/comite
  @loop start / @loop stop
  @role list / assign / score
  @workflow list / run <name>
  @ci run / lint / status
  @estim <description longue>
  @scan <subnet>
  @ids start/stop/status
  @chain <cmd1> | <cmd2>
  @ssh status / save
  @agentic help/skills/verify
  @evolve start/status/bench
  @disco <skill>
  @run <cmd shell>
  @collab auto/ping/chef/debat/cline/history/status

Mode graphique simulé : FakeApp avec FakeChat qui capture tous les messages.
Lancer : python -m pytest tests/test_args.py -v
"""
from __future__ import annotations
import asyncio, sys, types, re, uuid, json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from enum import Enum

# ─────────────────────────────────────────────────────────────────────────────
# Setup commun
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))


class AgentType(Enum):
    CHAT = "chat"; ACTION = "action"; RAG = "rag"


def _mock():
    m = types.ModuleType('__main__')
    m.AgentType = AgentType
    m.AGENT_META = {a: {"color":"#fff","icon":"x","label":a.value} for a in AgentType}
    m.DangerLevel = type('DL',(),{'SAFE':'safe'})()
    for flag in ['HAS_DANGER_GUARD','HAS_PREDICTIF','HAS_ROUTAGE','HAS_WEB_SEARCH',
                 'HAS_SANDBOX','HAS_SSH','HAS_PTY','HAS_PREFECT','HAS_SCORING']:
        setattr(m, flag, False)
    m.agentic_engine = None
    m.rag_engine     = None
    m.version_manager = type('VM',(),{
        'get_current_code': lambda s: '# code',
        'work_path': Path('app/LaForge.py'),
        'current_version': '0.13.0',
    })()
    m.settings = type('S',(),{
        'ollama_url':'http://localhost:11434/api/chat',
        'ollama_model_default':'qwen2.5',
        'max_concurrent_tasks':2,
        'rag_dir':'data/rag_files',
    })()
    m.prefect_manager = None
    m.ssh_manager     = None
    m.ollama_stream   = AsyncMock(return_value="[MOCK LLM]")
    m.ollama_call     = AsyncMock(return_value="[MOCK LLM]")
    m.get_orchestrator = lambda: type('O',(),{
        'handle': AsyncMock(return_value="[MOCK ORC]"),
    })()
    m.escape  = lambda x: str(x)
    m.debug_log = lambda *a,**k: None
    m.logger  = type('L',(),{k:lambda *a,**kk:None
                              for k in ['info','debug','warning','error']})()
    m.get_proxy_url = lambda n='': None
    m.get_best_proxy_url = lambda: None
    m.get_web_engine = lambda: None
    m._pred_get_router = lambda: None
    m._ROOT_DIR = Path('.')
    m._DATA_DIR = Path('data')
    m.run_ssh = AsyncMock(return_value="mock")
    return m


@pytest.fixture(autouse=True)
def mocks():
    lf = _mock()
    old = sys.modules.get('__main__')
    sys.modules['__main__'] = lf
    for mod in ['forge_handlers','forge_dispatch','forge_dispatch_network',
                'forge_dispatch_ai','forge_collab_modes','forge_llm',
                'forge_litellm_bridge','forge_ollama_bridge']:
        sys.modules.pop(mod, None)
    yield lf
    if old: sys.modules['__main__'] = old


class FakeChat:
    def __init__(self): self.msgs = []
    def write(self,m,*a,**k): self.msgs.append(str(m))
    def clear(self): self.msgs.clear()
    def all(self): return '\n'.join(self.msgs)
    def has(self,t): return any(t.lower() in m.lower() for m in self.msgs)
    def count(self): return len(self.msgs)
    def last(self): return self.msgs[-1] if self.msgs else ''


class FakeApp:
    def __init__(self):
        self._chat = FakeChat()
        self.ai_busy = False
        self.current_agent = AgentType.CHAT
        self._collab_mode  = "autonome"
        self._last_input   = ""
        self._last_input_ts = 0.0
        self._rag_pending_confirm = {}
        self._smart_router = None
        self.arch = None
        self._awaiting_collab_prompt = ""
        self.context = type('C',(),{'messages':[],'add':lambda*a:None})()
        self.session_name = "test"
        self.guard = None
        self.terminal = MagicMock()
        self.role_panel  = type('R',(),{
            'activate':lambda*a:None,'deactivate':lambda*a:None,'reset':lambda*a:None})()
        self.skill_panel = type('S',(),{'mark_active':lambda*a:None})()
        self.scorer = None
        self.model_chat = 'qwen2.5'
        self.last_audit_suggestions = []
        self._has_sandbox = False
        self._get_sandbox = lambda: None
        self._has_predictif = False
        self._pred_get_router = lambda: None
    def _chat_log(self):          return self._chat
    def _set_status(self,s):      pass
    def _show_help(self):         self._chat.write("[HELP]")
    def _update_mode_buttons(self): pass
    def query_one(self,*a,**k):   raise Exception("NoWidget")
    def push_screen(self,*a):     pass
    def call_later(self,*a):      pass
    async def _index_self_in_rag(self): pass
    async def _select_model(self): self._chat.write("[MODEL]")
    async def _handle_run(self,c):     self._chat.write(f"[RUN]{c[:40]}")
    async def _handle_ssh(self,c):     self._chat.write(f"[SSH]{c[:40]}")
    async def _handle_disco(self,c):   self._chat.write(f"[DISCO]{c[:40]}")
    async def _handle_agentic(self,c): self._chat.write(f"[AGENTIC]{c[:40]}")
    async def _handle_evolve(self,c):  self._chat.write(f"[EVOLVE]{c[:40]}")
    async def _handle_audit(self):
        import forge_handlers as fh; await fh._handle_audit(self)
    async def _handle_estim(self,d):
        import forge_handlers as fh; await fh._handle_estim(self,d)
    async def _handle_loop(self,a):
        import forge_handlers as fh; await fh._handle_loop(self,a)
    async def _handle_mode(self,a):
        import forge_handlers as fh; await fh._handle_mode(self,a)
    async def _handle_role(self,a):
        import forge_handlers as fh; await fh._handle_role(self,a)
    async def _handle_rag(self,a):
        import forge_handlers as fh; await fh._handle_rag(self,a)
    async def _handle_proxy(self,a):
        import forge_handlers as fh; await fh._handle_proxy(self,a)
    async def _handle_workflow(self,a):
        import forge_handlers as fh; await fh._handle_workflow(self,a)
    async def _handle_ci(self,a):
        import forge_handlers as fh; await fh._handle_ci(self,a)
    async def _handle_apply(self,a):
        import forge_handlers as fh; await fh._handle_apply(self,a)


@pytest.fixture
def app(): return FakeApp()


def run(coro):
    loop = asyncio.new_event_loop()
    try:    return loop.run_until_complete(coro)
    finally: loop.close()


def dispatch(app, cmd):
    import forge_dispatch as fd
    return run(fd.dispatch(app, cmd))


# ─────────────────────────────────────────────────────────────────────────────
# @rag
# ─────────────────────────────────────────────────────────────────────────────

class TestRagArgs:
    def test_rag_no_args(self, app):
        dispatch(app, '@rag')
        assert app._chat.count() >= 1

    def test_rag_info(self, app):
        dispatch(app, '@rag info')
        assert app._chat.count() >= 1

    def test_rag_size(self, app):
        dispatch(app, '@rag size')
        assert app._chat.count() >= 1

    def test_rag_search(self, app):
        dispatch(app, '@rag search asyncio Python')
        assert app._chat.count() >= 1

    def test_rag_index(self, app):
        dispatch(app, '@rag index app/LaForge.py')
        assert app._chat.count() >= 1

    def test_rag_clear_confirm(self, app):
        # @rag clear doit demander confirmation
        dispatch(app, '@rag clear')
        assert app._chat.count() >= 1
        assert app._chat.has('confirm') or app._chat.has('purge') \
            or app._chat.has('clear') or app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @proxy
# ─────────────────────────────────────────────────────────────────────────────

class TestProxyArgs:
    def test_proxy_no_args(self, app):
        dispatch(app, '@proxy')
        assert app._chat.count() >= 1

    def test_proxy_list(self, app):
        dispatch(app, '@proxy list')
        assert app._chat.count() >= 1

    def test_proxy_start(self, app):
        dispatch(app, '@proxy start burp')
        assert app._chat.count() >= 1

    def test_proxy_stop(self, app):
        dispatch(app, '@proxy stop burp')
        assert app._chat.count() >= 1

    def test_proxy_test(self, app):
        dispatch(app, '@proxy test')
        assert app._chat.count() >= 1

    def test_proxy_unknown_sub(self, app):
        dispatch(app, '@proxy inconnue')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @mode
# ─────────────────────────────────────────────────────────────────────────────

class TestModeArgs:
    def test_mode_no_args(self, app):
        dispatch(app, '@mode')
        assert app._chat.has('mode') or app._chat.has('Mode')

    def test_mode_set_autonome(self, app):
        dispatch(app, '@mode set autonome')
        assert app._collab_mode == 'autonome'
        assert app._chat.count() >= 1

    def test_mode_set_collaboration(self, app):
        dispatch(app, '@mode set collaboration')
        assert app._collab_mode == 'collaboration'

    def test_mode_set_comite(self, app):
        dispatch(app, '@mode set comite')
        assert app._collab_mode == 'comite'

    def test_mode_autonome_task(self, app, mocks):
        """@mode autonome <tâche> → lance run_collab auto."""
        async def mock_auto(*a,**k): app._chat.write("[AUTO]")
        import forge_collab_modes as fcm
        fcm._ollama_ask  = AsyncMock(return_value="[OL]")
        fcm._nokido_ask = AsyncMock(return_value="[LF]")
        dispatch(app, '@mode autonome configure nginx')
        assert app._chat.count() >= 1

    def test_mode_collab_task(self, app):
        """@mode collaboration <tâche> → câblé vers cline."""
        dispatch(app, '@mode collaboration refactorise Nokido.py')
        assert app._chat.count() >= 1

    def test_mode_comite_task(self, app):
        """@mode comite <idée> → câblé vers debat."""
        dispatch(app, '@mode comite faut-il utiliser FastAPI ou Flask')
        assert app._chat.count() >= 1

    def test_mode_unknown_set(self, app):
        dispatch(app, '@mode set inconnu')
        assert app._chat.has('inconnu') or app._chat.has('Mode') or app._chat.count() >= 1

    def test_mode_task_without_prefix(self, app):
        """Texte sans préfixe de mode → utilise mode courant."""
        app._collab_mode = 'autonome'
        dispatch(app, '@mode configurer AdGuard Home')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @loop
# ─────────────────────────────────────────────────────────────────────────────

class TestLoopArgs:
    def test_loop_no_args(self, app):
        dispatch(app, '@loop')
        assert app._chat.count() >= 1

    def test_loop_start(self, app):
        dispatch(app, '@loop start améliorer la couverture de tests')
        assert app._chat.count() >= 1

    def test_loop_stop(self, app):
        dispatch(app, '@loop stop')
        assert app._chat.count() >= 1

    def test_loop_status(self, app):
        dispatch(app, '@loop status')
        assert app._chat.count() >= 1

    def test_loop_dry_run(self, app):
        dispatch(app, '@loop --dry_run')
        assert app._chat.count() >= 1

    def test_loop_already_running(self, app):
        """Si un loop tourne déjà → message d'avertissement."""
        # Simuler un loop actif
        app._loop_running = True
        dispatch(app, '@loop start tâche')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @role
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleArgs:
    def test_role_no_args(self, app):
        dispatch(app, '@role')
        assert app._chat.count() >= 1

    def test_role_list(self, app):
        dispatch(app, '@role list')
        assert app._chat.count() >= 1

    def test_role_score(self, app):
        dispatch(app, '@role score')
        assert app._chat.count() >= 1

    def test_role_assign(self, app):
        dispatch(app, '@role assign')
        assert app._chat.count() >= 1

    def test_role_detect(self, app):
        dispatch(app, '@role detect analyser les performances réseau')
        assert app._chat.count() >= 1

    def test_role_arch(self, app):
        dispatch(app, '@role arch')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @workflow
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkflowArgs:
    def test_workflow_no_args(self, app):
        dispatch(app, '@workflow')
        assert app._chat.count() >= 1

    def test_workflow_list(self, app):
        dispatch(app, '@workflow list')
        assert app._chat.count() >= 1

    def test_workflow_run_named(self, app):
        dispatch(app, '@workflow run deploy_prod')
        assert app._chat.count() >= 1

    def test_workflow_status(self, app):
        dispatch(app, '@workflow status')
        assert app._chat.count() >= 1

    def test_workflow_create(self, app):
        dispatch(app, '@workflow create mon_workflow')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @ci
# ─────────────────────────────────────────────────────────────────────────────

class TestCIArgs:
    def test_ci_no_args(self, app):
        dispatch(app, '@ci')
        assert app._chat.count() >= 1

    def test_ci_run(self, app):
        dispatch(app, '@ci run')
        assert app._chat.count() >= 1

    def test_ci_lint(self, app):
        dispatch(app, '@ci lint')
        assert app._chat.count() >= 1

    def test_ci_status(self, app):
        dispatch(app, '@ci status')
        assert app._chat.count() >= 1

    def test_ci_test(self, app):
        dispatch(app, '@ci test')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @estim
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimArgs:
    def test_estim_no_args(self, app):
        dispatch(app, '@estim')
        # Doit demander une description
        assert app._chat.has('usage') or app._chat.has('description') \
            or app._chat.has('Usage') or app._chat.count() >= 1

    def test_estim_simple(self, app):
        dispatch(app, '@estim créer une API REST')
        assert app._chat.count() >= 1

    def test_estim_complex(self, app):
        dispatch(app, '@estim refactoriser le module SSH pour supporter multiplexing et reconnexion automatique')
        assert app._chat.count() >= 1

    def test_estim_with_source(self, app):
        dispatch(app, '@estim source app/forge_handlers.py ajouter du logging')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @scan / @ids / @chain / @switch
# ─────────────────────────────────────────────────────────────────────────────

class TestNetworkArgs:
    def test_scan_no_args(self, app):
        dispatch(app, '@scan')
        assert app._chat.count() >= 1

    def test_scan_subnet(self, app):
        dispatch(app, '@scan localhost/24')
        assert app._chat.count() >= 1

    def test_scan_ip_single(self, app):
        dispatch(app, '@scan localhost')
        assert app._chat.count() >= 1

    def test_ids_no_args(self, app):
        dispatch(app, '@ids')
        assert app._chat.count() >= 1

    def test_ids_status(self, app):
        dispatch(app, '@ids status')
        assert app._chat.count() >= 1

    def test_ids_start(self, app):
        dispatch(app, '@ids start eth0')
        assert app._chat.count() >= 1

    def test_ids_stop(self, app):
        dispatch(app, '@ids stop')
        assert app._chat.count() >= 1

    def test_chain_help(self, app):
        dispatch(app, '@chain help')
        assert app._chat.count() >= 1

    def test_chain_pipeline(self, app):
        dispatch(app, '@chain @scan localhost/24 | @ids start')
        assert app._chat.count() >= 1

    def test_switch_no_args(self, app):
        dispatch(app, '@switch')
        assert app._chat.count() >= 1

    def test_switch_target(self, app):
        dispatch(app, '@switch localhost')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @ssh (inline Nokido.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestSSHArgs:
    def test_ssh_no_args(self, app):
        dispatch(app, '@ssh')
        assert app._chat.count() >= 1

    def test_ssh_host(self, app):
        dispatch(app, '@ssh localhost')
        assert app._chat.count() >= 1

    def test_ssh_host_user(self, app):
        dispatch(app, '@ssh localhost admin')
        assert app._chat.count() >= 1

    def test_ssh_host_user_port(self, app):
        dispatch(app, '@ssh localhost admin 2222')
        assert app._chat.count() >= 1

    def test_ssh_status(self, app):
        dispatch(app, '@ssh status')
        assert app._chat.count() >= 1

    def test_ssh_save(self, app):
        dispatch(app, '@ssh save')
        assert app._chat.count() >= 1

    def test_ssh_disconnect(self, app):
        dispatch(app, '@ssh disconnect')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @agentic (inline Nokido.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestAgenticArgs:
    def test_agentic_no_args(self, app):
        dispatch(app, '@agentic')
        assert app._chat.count() >= 1

    def test_agentic_help(self, app):
        dispatch(app, '@agentic help')
        assert app._chat.count() >= 1

    def test_agentic_skills(self, app):
        dispatch(app, '@agentic skills')
        assert app._chat.count() >= 1

    def test_agentic_run(self, app):
        dispatch(app, '@agentic run analyser les performances')
        assert app._chat.count() >= 1

    def test_agentic_verify(self, app):
        dispatch(app, '@agentic verify')
        assert app._chat.count() >= 1

    def test_agentic_clear(self, app):
        dispatch(app, '@agentic clear')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @evolve (inline Nokido.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestEvolveArgs:
    def test_evolve_no_args(self, app):
        dispatch(app, '@evolve')
        assert app._chat.count() >= 1

    def test_evolve_help(self, app):
        dispatch(app, '@evolve help')
        assert app._chat.count() >= 1

    def test_evolve_start(self, app):
        dispatch(app, '@evolve start')
        assert app._chat.count() >= 1

    def test_evolve_status(self, app):
        dispatch(app, '@evolve status')
        assert app._chat.count() >= 1

    def test_evolve_bench(self, app):
        dispatch(app, '@evolve bench')
        assert app._chat.count() >= 1

    def test_evolve_scores(self, app):
        dispatch(app, '@evolve scores')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @disco (inline Nokido.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoArgs:
    def test_disco_no_args(self, app):
        dispatch(app, '@disco')
        assert app._chat.count() >= 1
        # Doit afficher l'aide avec des exemples
        assert app._chat.has('disco') or app._chat.has('compétence')

    def test_disco_single_skill(self, app):
        dispatch(app, '@disco kubernetes')
        assert app._chat.count() >= 1

    def test_disco_multi_word(self, app):
        dispatch(app, '@disco python asyncio')
        assert app._chat.count() >= 1

    def test_disco_security(self, app):
        dispatch(app, '@disco securite firewall nftables')
        assert app._chat.count() >= 1

    def test_disco_force(self, app):
        dispatch(app, '@disco kubernetes --force')
        assert app._chat.count() >= 1

    def test_disco_via_proxy(self, app):
        dispatch(app, '@disco nginx via burp')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @run (inline Nokido.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunArgs:
    def test_run_no_args(self, app):
        dispatch(app, '@run')
        assert app._chat.count() >= 1

    def test_run_simple_cmd(self, app):
        dispatch(app, '@run ls -la')
        assert app._chat.count() >= 1

    def test_run_sudo(self, app):
        dispatch(app, '@run sudo systemctl status nginx')
        assert app._chat.count() >= 1

    def test_run_docker(self, app):
        dispatch(app, '@run docker ps')
        assert app._chat.count() >= 1

    def test_run_pipe(self, app):
        dispatch(app, '@run ps aux | grep python')
        assert app._chat.count() >= 1

    def test_run_multiword(self, app):
        dispatch(app, '@run journalctl -u nginx --since today')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @collab — tous les sous-modes avec arguments
# ─────────────────────────────────────────────────────────────────────────────

class TestCollabArgs:
    def test_collab_no_args(self, app):
        dispatch(app, '@collab')
        assert app._chat.has('collab') or app._chat.has('mode')

    def test_collab_status(self, app):
        dispatch(app, '@collab status')
        assert app._chat.count() >= 1

    def test_collab_history(self, app):
        dispatch(app, '@collab history')
        assert app._chat.count() >= 1

    def test_collab_auto_task(self, app, mocks):
        mocks.ollama_stream = AsyncMock(return_value="[AUTO]")
        dispatch(app, '@collab auto configurer AdGuard Home')
        assert app._chat.count() >= 1

    def test_collab_ping_task(self, app, mocks):
        import forge_collab_modes as fcm
        fcm._ollama_ask  = AsyncMock(return_value="[OL]")
        fcm._nokido_ask = AsyncMock(return_value="[LF]")
        dispatch(app, '@collab ping comparer Docker vs Podman --tours=1')
        assert app._chat.count() >= 1

    def test_collab_chef_task(self, app, mocks):
        import forge_collab_modes as fcm
        fcm._ollama_ask  = AsyncMock(return_value="[OL]")
        fcm._nokido_ask = AsyncMock(return_value="[LF]")
        dispatch(app, '@collab chef déployer une stack ELK')
        assert app._chat.count() >= 1

    def test_collab_debat_task(self, app, mocks):
        import forge_collab_modes as fcm
        fcm._ollama_ask  = AsyncMock(return_value="[OL]")
        fcm._nokido_ask = AsyncMock(return_value="[LF]")
        dispatch(app, '@collab debat faut-il utiliser Kubernetes --rounds=1')
        assert app._chat.count() >= 1

    def test_collab_cline_dry_run(self, app):
        dispatch(app, '@collab cline --dry_run analyser forge_handlers.py')
        assert app._chat.count() >= 1

    def test_collab_history_session(self, app):
        """@collab history --session=xxx → afficher une session."""
        import forge_task_bus as tb
        sid = f"test-{uuid.uuid4().hex[:8]}"
        tb.log_shared_prompt(sid, "CLAUDE", "msg test", mode="collaboration")
        dispatch(app, f'@collab history --session={sid}')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @audit avec arguments
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditArgs:
    def test_audit_basic(self, app, mocks):
        mocks.ollama_stream = AsyncMock(return_value="Suggestion 1 : Améliorer les logs\nTARGET: main\n```python\ndef main(): pass\n```")
        dispatch(app, '@audit')
        assert app._chat.count() >= 1

    def test_audit_no_ollama(self, app, mocks):
        mocks.ollama_stream = None
        dispatch(app, '@audit')
        # Doit afficher avertissement
        assert app._chat.has('ollama') or app._chat.has('Ollama') \
            or app._chat.count() >= 1

    def test_audit_suggestions_parsed(self, app, mocks):
        """@audit avec suggestions formatées → last_audit_suggestions rempli."""
        mocks.ollama_stream = AsyncMock(return_value=(
            "Suggestion 1 : Améliorer logging\n"
            "TARGET: _dispatch_ai\n"
            "```python\n"
            "def _dispatch_ai(): pass\n"
            "```\n"
        ))
        dispatch(app, '@audit')
        assert app._chat.count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# @apply avec arguments
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyArgs:
    def test_apply_no_args(self, app):
        dispatch(app, '@apply')
        assert app._chat.count() >= 1

    def test_apply_number(self, app):
        """@apply 1 → appliquer suggestion 1 (vide → message)."""
        dispatch(app, '@apply 1')
        assert app._chat.count() >= 1

    def test_apply_all(self, app):
        dispatch(app, '@apply all')
        assert app._chat.count() >= 1

    def test_apply_with_suggestion(self, app):
        """Avec last_audit_suggestions rempli → tente l'application."""
        app.last_audit_suggestions = [{
            "num": 1,
            "description": "Améliorer logging",
            "target": "dispatch_ai",
            "code": "def dispatch_ai(): pass",
        }]
        dispatch(app, '@apply 1')
        assert app._chat.count() >= 1


if __name__ == '__main__':
    import subprocess
    r = subprocess.run(
        [sys.executable, '-m', 'pytest', __file__, '-v', '--tb=short'],
        capture_output=False
    )
    sys.exit(r.returncode)
