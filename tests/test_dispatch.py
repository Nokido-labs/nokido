# -*- coding: utf-8 -*-
"""
tests/test_dispatch.py — Suite de non-régression du dispatcher @
=================================================================
Couvre :
  1.  AST — forge_dispatch.py et Nokido.py syntaxiquement valides
  2.  REGISTRY — toutes les commandes connues présentes
  3.  Handlers — tous les callables existent et sont async
  4.  Méthodes injectées — présentes dans Nokido.py avec bonne signature
  5.  Indentation — pas de closures / create_task orphelins à indent <= 8
  6.  Imports circulaires — forge_dispatch n'importe pas app.Nokido au top-level
  7.  Routeur — dispatch() résout correctement chaque commande (MockApp)
  8.  Commandes inconnues — retourne message d'erreur sans exception
  9.  Autotools — TOOLS_REGISTRY valide et handle_tools présent
  10. Cohérence @help — toutes les commandes du REGISTRY sont documentées

Lancer :
    cd __import__("os").path.expanduser("~/Script python IA/LaForge")
    python -m pytest tests/test_dispatch.py -v
"""
from __future__ import annotations

import ast
import asyncio
import re
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Chemins & sources
# ─────────────────────────────────────────────────────────────────────────────
ROOT  = Path(__file__).resolve().parent.parent
APP   = ROOT / "app"
TOOLS = ROOT / "tools"
TESTS = ROOT / "tests"

sys.path.insert(0, str(APP))
sys.path.insert(0, str(TOOLS))

LF_SRC   = (APP / "Nokido.py").read_text(encoding="utf-8", errors="ignore")
# forge_dispatch.py recyclé Phase 1 — remplacé par forge_hub_handlers + forge_at_dispatch
import pytest as _pytest
_fd_path = APP / "forge_dispatch.py"
if not _fd_path.exists():
    _pytest.skip("forge_dispatch.py recyclé (Phase 1 refactor)", allow_module_level=True)
FD_SRC = _fd_path.read_text(encoding="utf-8", errors="ignore")
AT_SRC   = (TOOLS / "autotools.py").read_text(encoding="utf-8", errors="ignore")
LF_LINES = LF_SRC.splitlines()
FD_LINES = FD_SRC.splitlines()

# Commandes @ attendues (référence avant refonte)
EXPECTED_CMDS = {
    "@help", "@diag", "@run", "@ssh", "@scan", "@ids",
    "@disco", "@estim", "@agentic", "@evolve", "@loop",
    "@role", "@mode", "@model", "@rag", "@proxy", "@workflow",
    "@ci", "@switch", "@chain", "@collab", "@audit", "@apply",
    "@code", "@test", "@sandbox", "@nlu",
}

# Méthodes injectées dans Nokido.py
INJECTED_METHODS = [
    "_handle_run", "_handle_ssh", "_handle_disco",
    "_handle_agentic", "_handle_evolve",
]


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dispatch_module():
    """Charge forge_dispatch avec mocks pour éviter les imports lourds."""
    # Mocks des modules optionnels
    for mod in ["forge_dispatch_network", "forge_collab_modes"]:
        m = types.ModuleType(mod)
        async def _stub(*a, **k): pass
        m.handle_scan = m.handle_ids = m.handle_chain = m.handle_switch = _stub
        m.run_collab = _stub
        sys.modules.setdefault(mod, m)

    import forge_dispatch
    return forge_dispatch


@pytest.fixture(scope="module")
def autotools_module():
    """Charge autotools.py."""
    import autotools
    return autotools


@pytest.fixture
def mock_app():
    """DevOpsApp minimal pour tester le routeur."""
    app = MagicMock()
    messages = []

    class FakeLog:
        def write(self, msg, *a, **kw):
            messages.append(str(msg))

    app._chat_log.return_value = FakeLog()
    app._messages = messages
    app._show_help = MagicMock()
    app._select_model = AsyncMock()
    app._handle_run    = AsyncMock()
    app._handle_ssh    = AsyncMock()
    app._handle_disco  = AsyncMock()
    app._handle_agentic= AsyncMock()
    app._handle_evolve = AsyncMock()
    app._handle_loop   = AsyncMock()
    app._handle_role   = AsyncMock()
    app._handle_mode   = AsyncMock()
    app._handle_rag    = AsyncMock()
    app._handle_proxy  = AsyncMock()
    app._handle_workflow = AsyncMock()
    app._handle_ci     = AsyncMock()
    app._handle_audit  = AsyncMock()
    app._handle_apply  = AsyncMock()
    app._handle_estim  = AsyncMock()
    return app


def run_async(coro):
    """Exécute une coroutine dans un event loop de test."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. AST — syntaxe valide
# ─────────────────────────────────────────────────────────────────────────────

class TestAST:
    def test_nokido_ast_valid(self):
        """Nokido.py doit être syntaxiquement valide."""
        try:
            ast.parse(LF_SRC)
        except SyntaxError as e:
            pytest.fail(f"Nokido.py SyntaxError L{e.lineno}: {e.msg}")

    def test_forge_dispatch_ast_valid(self):
        """forge_dispatch.py doit être syntaxiquement valide."""
        try:
            ast.parse(FD_SRC)
        except SyntaxError as e:
            pytest.fail(f"forge_dispatch.py SyntaxError L{e.lineno}: {e.msg}")

    def test_autotools_ast_valid(self):
        """autotools.py doit être syntaxiquement valide."""
        try:
            ast.parse(AT_SRC)
        except SyntaxError as e:
            pytest.fail(f"autotools.py SyntaxError L{e.lineno}: {e.msg}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. REGISTRY — couverture des commandes
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_registry_exists(self, dispatch_module):
        assert hasattr(dispatch_module, "REGISTRY"), "REGISTRY absent de forge_dispatch"

    def test_registry_not_empty(self, dispatch_module):
        assert len(dispatch_module.REGISTRY) > 0

    def test_all_expected_commands_present(self, dispatch_module):
        """Toutes les commandes de référence doivent être dans REGISTRY."""
        registered = set()
        for key in dispatch_module.REGISTRY:
            if isinstance(key, tuple):
                registered.update(key)
            else:
                registered.add(key)
        missing = EXPECTED_CMDS - registered
        assert not missing, f"Commandes manquantes dans REGISTRY: {missing}"

    def test_no_duplicate_keys(self, dispatch_module):
        """Pas de commandes en doublon dans REGISTRY."""
        seen = []
        for key in dispatch_module.REGISTRY:
            cmds = key if isinstance(key, tuple) else (key,)
            for cmd in cmds:
                assert cmd not in seen, f"Doublon dans REGISTRY: {cmd}"
                seen.append(cmd)

    def test_tools_registered(self, dispatch_module):
        """@tools doit être enregistré dans REGISTRY."""
        registered = set()
        for key in dispatch_module.REGISTRY:
            if isinstance(key, tuple):
                registered.update(key)
            else:
                registered.add(key)
        assert "@tools" in registered, "@tools absent du REGISTRY"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Handlers — callables async
# ─────────────────────────────────────────────────────────────────────────────

class TestHandlers:
    def test_all_handlers_callable(self, dispatch_module):
        for key, fn in dispatch_module.REGISTRY.items():
            assert callable(fn), f"Handler non callable pour {key}: {fn}"

    def test_all_handlers_are_coroutines(self, dispatch_module):
        """Tous les handlers doivent être des coroutines async."""
        import inspect
        for key, fn in dispatch_module.REGISTRY.items():
            assert inspect.iscoroutinefunction(fn), \
                f"Handler non-async pour {key}: {fn.__name__}"

    def test_dispatch_function_exists(self, dispatch_module):
        assert hasattr(dispatch_module, "dispatch"), "fonction dispatch() absente"
        import inspect
        assert inspect.iscoroutinefunction(dispatch_module.dispatch)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Méthodes injectées dans Nokido.py
# ─────────────────────────────────────────────────────────────────────────────

class TestInjectedMethods:
    def test_injected_methods_present(self):
        for name in INJECTED_METHODS:
            assert f"async def {name}" in LF_SRC, \
                f"Méthode injectée absente de Nokido.py: {name}"

    def test_handle_at_delegates_to_dispatch(self):
        """_handle_at doit appeler forge_dispatch.dispatch."""
        assert "forge_dispatch" in LF_SRC or "from forge_dispatch" in LF_SRC, \
            "forge_dispatch non référencé dans Nokido.py"
        # Vérifier que _handle_at est court (routeur mince)
        in_handle = False
        handle_lines = []
        for line in LF_LINES:
            if "async def _handle_at" in line:
                in_handle = True
            elif in_handle and line.strip().startswith("async def "):
                break
            if in_handle:
                handle_lines.append(line)
        assert len(handle_lines) <= 15, \
            f"_handle_at trop long ({len(handle_lines)} lignes) — pas un routeur mince"

    def test_injected_methods_have_self(self):
        """Les méthodes injectées doivent prendre self en premier param."""
        for name in INJECTED_METHODS:
            pattern = rf"async def {re.escape(name)}\(self"
            assert re.search(pattern, LF_SRC), \
                f"{name} n'a pas 'self' comme premier paramètre"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Indentation — pas d'orphelins
# ─────────────────────────────────────────────────────────────────────────────

class TestIndentation:
    def test_no_orphan_create_task_at_class_level(self):
        """Pas de asyncio.create_task() à indent=8 (niveau classe) hors méthodes."""
        known_methods_at_8 = {
            "_handle_run", "_handle_ssh", "_handle_disco", "_handle_agentic",
            "_handle_evolve", "_handle_at", "_reboot_cb", "_select_model",
            "_handle_rag", "_handle_proxy", "_handle_workflow", "_handle_ci",
            "_handle_chain", "_handle_switch", "_handle_audit", "_handle_estim",
            "_handle_loop", "_handle_mode", "_handle_role", "_handle_apply",
            "_dispatch_ai", "_show_help", "_handle_orchestrated",
            "_post_loop_safe_check", "_apply_suggestion", "_propose_restart",
            "_index_self_in_rag", "_propagate_patch",
        }
        for i, line in enumerate(LF_LINES, 1):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 8 and "create_task" in line:
                # Vérifier si c'est dans une méthode connue
                # (remonter pour trouver la def parente)
                parent = None
                for j in range(i-2, max(0, i-200), -1):
                    l = LF_LINES[j]
                    if l.strip().startswith("async def ") or l.strip().startswith("def "):
                        parent = l.strip().split("(")[0].split()[-1]
                        break
                assert parent and parent in known_methods_at_8, \
                    f"create_task orphelin à indent=8, L{i}: {line.strip()!r} (parent={parent})"

    def test_no_orphan_closure_at_class_level(self):
        """Pas de async def sans self à indent=8 hors définitions connues."""
        known_at_8 = {
            "_handle_run", "_handle_ssh", "_handle_disco", "_handle_agentic",
            "_handle_evolve", "_handle_at", "_reboot_cb", "_select_model",
            "_handle_rag", "_handle_proxy", "_handle_workflow", "_handle_ci",
            "_handle_chain", "_handle_switch", "_handle_audit", "_handle_estim",
            "_handle_loop", "_handle_mode", "_handle_role", "_handle_apply",
            "_dispatch_ai", "_show_help", "_handle_orchestrated",
            "_post_loop_safe_check", "_apply_suggestion", "_propose_restart",
            "_index_self_in_rag", "_propagate_patch",
        }
        for i, line in enumerate(LF_LINES, 1):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()
            if (indent == 8
                    and stripped.startswith("async def ")
                    and "self" not in stripped):
                name = stripped.split("(")[0].split()[-1]
                assert name in known_at_8, \
                    f"Closure orpheline à indent=8, L{i}: {stripped!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Imports circulaires
# ─────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_no_toplevel_nokido_import_in_dispatch(self):
        """forge_dispatch ne doit pas importer app.Nokido au top-level."""
        tree = ast.parse(FD_SRC)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Autoriser les imports locaux (dans des fonctions)
                # Vérifier que ce n'est pas au niveau module
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert "Nokido" not in mod or not isinstance(
                        ast.parse(FD_SRC).body[0], (ast.Import, ast.ImportFrom)
                    ), f"Import circulaire top-level: {mod}"

    def test_forge_dispatch_importable(self, dispatch_module):
        """forge_dispatch doit s'importer sans erreur."""
        assert dispatch_module is not None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Routeur — dispatch() résout correctement
# ─────────────────────────────────────────────────────────────────────────────

class TestRouter:
    def test_dispatch_calls_help(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@help"))
        mock_app._show_help.assert_called_once()

    def test_dispatch_calls_run(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@run ls -la"))
        mock_app._handle_run.assert_called_once()

    def test_dispatch_calls_ssh(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@ssh status"))
        mock_app._handle_ssh.assert_called_once()

    def test_dispatch_calls_rag(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@rag info"))
        mock_app._handle_rag.assert_called_once()

    def test_dispatch_calls_proxy(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@proxy list"))
        mock_app._handle_proxy.assert_called_once()

    def test_dispatch_calls_disco(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@disco kubernetes"))
        mock_app._handle_disco.assert_called_once()

    def test_dispatch_calls_mode(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@mode action"))
        mock_app._handle_mode.assert_called_once()

    def test_dispatch_calls_loop(self, dispatch_module, mock_app):
        run_async(dispatch_module.dispatch(mock_app, "@loop start"))
        mock_app._handle_loop.assert_called_once()

    def test_dispatch_code_alias(self, dispatch_module, mock_app):
        """@code, @test, @sandbox → même handler."""
        mock_app._has_sandbox = False
        for cmd in ["@code", "@test", "@sandbox"]:
            app2 = MagicMock()
            msgs = []
            class FL:
                def write(self, m, *a): msgs.append(m)
            app2._chat_log.return_value = FL()
            app2._has_sandbox = False
            run_async(dispatch_module.dispatch(app2, f"{cmd} test"))
            assert msgs, f"{cmd} n'a produit aucun message"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Commandes inconnues
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownCommands:
    def test_unknown_command_no_exception(self, dispatch_module, mock_app):
        """Une commande inconnue ne doit pas lever d'exception."""
        try:
            run_async(dispatch_module.dispatch(mock_app, "@inexistant arg"))
        except Exception as e:
            pytest.fail(f"Exception sur commande inconnue: {e}")

    def test_unknown_command_writes_message(self, dispatch_module, mock_app):
        """Une commande inconnue doit écrire un message dans le chat."""
        run_async(dispatch_module.dispatch(mock_app, "@commande_qui_nexiste_pas"))
        assert mock_app._messages, "Aucun message affiché pour commande inconnue"

    def test_empty_input_no_crash(self, dispatch_module, mock_app):
        """Input vide ne doit pas crasher."""
        try:
            run_async(dispatch_module.dispatch(mock_app, ""))
        except Exception as e:
            pytest.fail(f"Exception sur input vide: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Autotools
# ─────────────────────────────────────────────────────────────────────────────

class TestAutotools:
    def test_tools_registry_exists(self, autotools_module):
        assert hasattr(autotools_module, "TOOLS_REGISTRY")
        assert len(autotools_module.TOOLS_REGISTRY) > 0

    def test_tools_registry_keys_are_strings(self, autotools_module):
        for k in autotools_module.TOOLS_REGISTRY:
            assert isinstance(k, str), f"Clé non-string dans TOOLS_REGISTRY: {k!r}"

    def test_all_tools_have_fn(self, autotools_module):
        for name, tool in autotools_module.TOOLS_REGISTRY.items():
            assert callable(tool.fn), f"Tool '{name}' n'a pas de fn callable"

    def test_handle_tools_is_async(self, autotools_module):
        import inspect
        assert hasattr(autotools_module, "handle_tools")
        assert inspect.iscoroutinefunction(autotools_module.handle_tools)

    def test_run_list_returns_string(self, autotools_module):
        result = autotools_module.run_list([])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_check_returns_string(self, autotools_module):
        result = autotools_module.run_check([])
        assert isinstance(result, str)
        assert "AUTOTOOLS CHECK" in result

    def test_tools_registered_in_dispatch(self, dispatch_module):
        """@tools doit être dans le REGISTRY de forge_dispatch."""
        registered = set()
        for key in dispatch_module.REGISTRY:
            if isinstance(key, tuple):
                registered.update(key)
            else:
                registered.add(key)
        assert "@tools" in registered


# ─────────────────────────────────────────────────────────────────────────────
# 10. Cohérence @help
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpCoverage:
    def _get_help_cmds(self):
        cmds = set()
        in_help = False
        for line in LF_LINES:
            if "_show_help" in line and "def " in line:
                in_help = True
            elif in_help and line.strip().startswith("return") and in_help:
                break
            if in_help:
                for m in re.finditer(r"@(\w+)", line):
                    cmds.add(f"@{m.group(1)}")
        return cmds

    def test_no_duplicate_in_dispatch_source(self):
        """Pas de doublon cmd == '@xxx' dans forge_dispatch.py."""
        seen = {}
        for i, line in enumerate(FD_LINES, 1):
            for m in re.finditer(r'"(@\w+)":\s*handle_', line):
                cmd = m.group(1)
                assert cmd not in seen, \
                    f"Doublon dans forge_dispatch REGISTRY: {cmd} (L{seen[cmd]} et L{i})"
                seen[cmd] = i

    def test_dispatch_source_has_all_expected(self):
        """forge_dispatch.py doit mentionner toutes les commandes attendues."""
        # Exclure les alias dans les tuples
        internal_ok = {"@test", "@sandbox"}  # alias de @code
        for cmd in EXPECTED_CMDS - internal_ok:
            assert cmd in FD_SRC, f"Commande {cmd} absente de forge_dispatch.py"
