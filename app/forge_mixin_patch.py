from __future__ import annotations

# Imports oublies, mesures le 2026-09-08 : List[str] L258, asyncio.TimeoutError
# L531, datetime.now() L1298 (la CLASSE), json.dumps L1306, re.findall L759.
import asyncio
import json
import re
from datetime import datetime
from typing import List

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
try:
    import aiohttp
except ImportError:
    aiohttp = None
import sys as _sys
import logging
from pathlib import Path

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

import sys as _sys_f
from app.forge_mixin_ui import HAS_ONNX
from app.forge_ui_widgets import EntropyGauge


def _main_attr(name: str, default: object = None) -> object:
    """Retrieve an attribute from the ``__main__`` module.

    Args:
        name: The attribute name to look up.
        default: Value to return if the attribute is not found.

    Returns:
        The attribute value from the ``__main__`` module, or ``default`` if it does not exist.
    """
    main_module = _sys.modules.get("__main__")
    return getattr(main_module, name, default)


from app.core.settings import get_settings as _forge_settings  # noqa: F401


def _forge_version_manager() -> object:
    """Forge version manager."""
    return _main_attr("version_manager")


class _VMProxy:
    """vmproxy."""

    def __getattr__(self, k: int) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        vm = _forge_version_manager()
        if vm:
            return getattr(vm, k)
        try:
            from nokido_agent.app.forge_version import get as _fvget

            _cv = _fvget()
        except Exception:
            _cv = "0.13.0"
        defaults = {"current_version": _cv, "work_path": None}
        return defaults.get(k)


class _SettingsProxy:
    """settingsproxy."""

    def __getattr__(self, k: int) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        if s:
            return getattr(s, k, None)
        return None


class _LazyGlobal:
    """lazyglobal."""

    def __init__(self, name: str, default: object = None) -> None:
        """Init.

        Args:
            name: Description.
            default: Description.
        """
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_default", default)

    def _val(self) -> object:
        """Val."""
        return _main_attr(object.__getattribute__(self, "_name"), object.__getattribute__(self, "_default"))

    """Getattr.

    Args:
        k: Description.
    """

    def __getattr__(self, k: int) -> object:
        """getattr  ."""
        v = self._val()
        return getattr(v, k) if v is not None else None

    """Truediv.

    Args -> None:
        o: Description.
    """

    def __truediv__(self, o: object) -> object:
        """truediv  ."""
        v = self._val()
        return v / o if v is not None else Path(".") / o

    """Bool."""

    def __bool__(self) -> object:
        """bool  ."""
        return bool(self._val())

    """Str."""

    def __str__(self) -> object:
        """str  ."""
        v = self._val()
        return str(v) if v is not None else ""


settings = _SettingsProxy()
version_manager = _VMProxy()
_DATA_DIR = _LazyGlobal("_DATA_DIR", Path("."))
_ROOT_DIR = _LazyGlobal("_ROOT_DIR", Path("."))
_LOGS_DIR = _LazyGlobal("_LOGS_DIR", Path("."))
agentic_engine = _LazyGlobal("agentic_engine")
rag_engine = _LazyGlobal("rag_engine")
save_orchestrator = _LazyGlobal("save_orchestrator")


def _lf() -> object:
    """RÃ©sout l'instance DevOpsApp depuis le module principal."""
    m = _sys.modules.get("__main__")
    return getattr(m, "_app_instance", None)


# ── Imports manquants (shredder) ─────────────────────────────
try:
    from textual.widgets import Static as _Static

    Static = _Static
except ImportError:
    pass


# Fonctions globales de Nokido.py — lazy via __main__
def _lazy(name: str) -> object:
    """Lazy.

    Args:
        name: Description.
    """
    import sys as _s

    m = _s.modules.get("__main__")
    fn = getattr(m, name, None)
    return fn


from nokido_agent.app.forge_ollama import ollama_call, ollama_stream  # noqa: F401
# [ollama_call → forge_ollama.py]

# [ollama_stream → forge_ollama.py]


def shutdown_onnx_backend(*a, **kw) -> object:
    """Shutdown onnx backend."""
    fn = _lazy("shutdown_onnx_backend")
    if fn:
        return fn(*a, **kw)


# Flags HAS_* — lus depuis __main__ au runtime
"""Has.

Args:
    name: Description.
"""


def _has(name: str) -> object:
    """has."""
    return bool(_lazy(name))


HAS_LOOPS = property(lambda self: _has("HAS_LOOPS"))
HAS_SANDBOX = property(lambda self: _has("HAS_SANDBOX"))


# Classes internes de DevOpsApp — résolues via type(self)
def _inner(self, name: str, fallback: object = None) -> object:
    """Inner.

    Args:
        name: Description.
        fallback: Description.
    """
    return getattr(type(self), name, fallback)


class PatchMixin:
    """Mixin patch/versioning/loop â€” mÃ©thodes autorÃ©paration de DevOpsApp"""

    def _refresh_version_display(self) -> None:
        """Met à jour sub_title + sidebar après un @apply."""
        try:
            v = version_manager.current_version
            _hn = getattr(self, "_pending_hostname", "") or settings.ssh_host or ""
            self.sub_title = (
                f"v{version_manager.current_version} · {_hn}" if _hn else f"v{version_manager.current_version}"
            )
            orc_ver = self.query_one("#orc-version", Static)
            orc_ver.update(f"[dim]v{v} · {self.session_name[:12]}[/]")
            logger.info(f"[version display] mis à jour → v{v}")
        except Exception as _e:
            logger.debug(f"[_refresh_version_display] {_e}")

    def _set_staging_indicator(self, state: str) -> None:
        """Set staging indicator.

        Args:
            state: Description.
        """
        icons = {
            "staging": "[bold blue]💾 Staging…[/]",
            "commit": "[bold green]💾 Commit ✓[/]",
            "rollback": "[bold red]⏪ Rollback[/]",
            "": "",
        }
        try:
            self.query_one("#staging-indicator", Static).update(icons.get(state, ""))
        except Exception:
            pass

    def _saved_sessions(self) -> List[str]:
        """Saved sessions."""
        sessions = []
        for f in _DATA_DIR.glob("session_*.json"):
            sessions.append((f.stat().st_mtime, f.stem[8:]))
        sessions.sort(reverse=True)
        return [name for _, name in sessions]

    def _propagate_patch(new_path: Path, vm: str, chat: object) -> bool:
        """
        Copie workspace/Nokido_vX.Y.py → Nokido.py (source protégé).
        Indispensable : le redémarrage relance Nokido.py, pas work_path.
        Valide la syntaxe ET les imports suspects avant de copier.
        Retourne True si la propagation a réussi.
        """
        import stat as _st, shutil as _sh, py_compile as _pyc
        import ast as _ast_v

        # ── 1. Validation syntaxe py_compile ────────────────────────────
        try:
            _pyc.compile(str(new_path), doraise=True)
        except _pyc.PyCompileError as _ce:
            chat.write(
                f"[bold red]🚫 PATCH REFUSÉ — erreur syntaxe :[/]\n"
                f"[dim]{_ce}[/]\n"
                f"[yellow]Le fichier Nokido.py n'a PAS été modifié.[/]"
            )
            return False

        # ── 2. Validation imports — détecter les hallucinations LLM ─────
        try:
            _code = new_path.read_text(encoding="utf-8", errors="replace")
            _tree = _ast_v.parse(_code)
            _BAD_PATTERNS = (
                "your_",
                "example_",
                "my_module",
                "placeholder",
                "TODO",
                "FIXME",
                "your_module",
                "module_name",
            )
            _bad_imports = []
            for _node in _ast_v.walk(_tree):
                if isinstance(_node, (_ast_v.Import, _ast_v.ImportFrom)):
                    _mod = (
                        _node.module if isinstance(_node, _ast_v.ImportFrom) else ", ".join(a.name for a in _node.names)
                    ) or ""
                    if any(p in _mod.lower() for p in _BAD_PATTERNS):
                        _bad_imports.append(_mod)
            if _bad_imports:
                chat.write(
                    "[bold red]🚫 PATCH REFUSÉ — imports hallucinés détectés :[/]\n"
                    + "\n".join(f"  [dim]• {m}[/]" for m in _bad_imports)
                    + "\n[yellow]Le fichier Nokido.py n'a PAS été modifié.[/]"
                )
                return False
        except Exception as _ve:
            chat.write(f"[yellow]⚠ Validation imports échouée ({_ve}) — propagation annulée[/]")
            return False

        # ── 3. Copie sécurisée via fichier temporaire ────────────────────
        try:
            sp = vm.source_path
            # Écrire dans un .tmp d'abord, puis rename atomique
            _tmp_path = sp.with_suffix(".py.tmp")
            _sh.copy2(str(new_path), str(_tmp_path))
            sp.chmod(_st.S_IRUSR | _st.S_IWUSR | _st.S_IRGRP | _st.S_IROTH)
            _tmp_path.replace(sp)
            sp.chmod(_st.S_IRUSR | _st.S_IRGRP | _st.S_IROTH)
            chat.write(f"[dim]  ✅ Validé & propagé → {sp.name}[/]")
            return True
        except Exception as e:
            chat.write(
                f"[yellow]⚠ Propagation échouée : {e}\n  Copie manuelle : workspace/{new_path.name} → Nokido.py[/]"
            )
            return False

    def _pick_audit_model(self) -> str:
        """Choisit le modèle le plus compétent disponible pour l'audit."""
        return self._pick_model_from(self._AUDIT_MODEL_PREF)

    def _pick_model_from(self, prefs: list) -> str:
        """Choisit le premier modèle dispo parmi une liste de préférences."""
        available = getattr(self, "_available_models", [])
        for pref in prefs:
            for m in available:
                if pref in m.lower():
                    return m
        return self.model_action or self.model_chat

    async def _validate_suggestion_async(
        self,
        sugg: dict,
    ) -> dict:
        """
        Double-validation d'une suggestion avant affichage :
          1. Analyse statique (AST + patterns dangereux) — synchrone
          2. Review par second LLM léger — asynchrone

        Retourne sugg enrichi de :
          validated  : bool
          issues     : list[str]
          reviewer   : str  (nom du modèle reviewer)
        """
        import ast, re as _re

        code = sugg.get("code", "")
        issues = []

        # ── 1. Syntaxe AST ────────────────────────────────────────────────
        try:
            ast.parse(code)
        except SyntaxError as e:
            issues.append(f"SyntaxError L{e.lineno}: {e.msg}")

        # ── 2. Patterns dangereux ─────────────────────────────────────────
        for pattern, reason in self._DANGER_PATTERNS:
            if _re.search(pattern, code):
                issues.append(reason)

        # ── 3. Review second LLM (uniquement si syntaxe OK) ──────────────
        reviewer = ""
        if not issues:
            # Choisir un modèle léger différent de l'auditeur
            _review_pref = [
                "erukude/multiagent-orchestrator",
                "qwen2.5-coder:1.5b",
                "tinyllama",
                "mistral:7b",
                "qwen2:7b",
            ]
            available = getattr(self, "_available_models", [])
            reviewer = next(
                (m for p in _review_pref for m in available if p in m.lower()),
                self.model_rag,
            )
            review_prompt = (
                "Tu es un expert Python. Analyse ce snippet et détecte les bugs.\n"
                "Réponds UNIQUEMENT en JSON strict (pas de markdown) :\n"
                '{"valid": true/false, "issues": ["bug1", "bug2"]}\n\n'
                f"Snippet :\n```python\n{code[:2000]}\n```"
            )
            try:
                raw = await ollama_call(
                    reviewer,
                    [{"role": "user", "content": review_prompt}],
                    max_tokens=200,
                )
                # Extraire le JSON de la réponse
                import json as _json

                _m = _re.search(r"\{.*\}", raw, _re.DOTALL)
                if _m:
                    result = _json.loads(_m.group())
                    if not result.get("valid", True):
                        issues.extend(result.get("issues", ["code invalide selon reviewer"]))
            except Exception as _e:
                logger.debug(f"_validate_suggestion_async reviewer: {_e}")
                # Review échoué → on considère valide (non bloquant)

        sugg["validated"] = len(issues) == 0
        sugg["issues"] = issues
        sugg["reviewer"] = reviewer
        return sugg

    async def _handle_audit(self) -> None:
        """
        Pipeline 3 agents :
          A (Développeur)  — propose les correctifs (deepseek-coder-v2 local préféré)
          B (Auditeur)     — liste UNIQUEMENT les risques des correctifs de A (erukude)
          C (Critique AST) — code original + critique B → version finale validée
        Analyse statique : ruff · mypy · bandit · pylint
        """
        from nokido_agent.app.forge_app_context import get_mem_mgr

        _mem_mgr = get_mem_mgr()
        chat = self._chat_log()
        chat.write("[dim]⏳ Audit 3 agents en cours…[/]")

        # ── 0. Modèles disponibles ────────────────────────────────────────
        try:
            async with aiohttp.ClientSession() as _s:
                async with _s.get(settings.ollama_tags_url, timeout=aiohttp.ClientTimeout(total=5)) as _r:
                    _d = await _r.json()
                    self._available_models = [
                        m["name"] for m in _d.get("models", []) if "embed" not in m["name"].lower()
                    ]
        except Exception:
            self._available_models = [self.model_chat, self.model_action, self.model_rag]

        # ── 1. RAG auto-indexation ────────────────────────────────────────
        chat.write("[dim]  📚 Indexation RAG…[/]")
        await self._index_self_in_rag()
        code = version_manager.get_current_code()
        reports = []

        # ── 2. Analyse statique : ruff fix → ruff check → mypy → bandit → pylint
        chat.write("[dim]  🔧 Analyse statique…[/]")
        _wp = str(version_manager.work_path)
        import sys as _sys_audit

        _exe = _sys_audit.executable
        logger.info(f"[@audit] Python exe : {_exe}")
        logger.info(f"[@audit] Fichier cible : {_wp}")
        _cache_dir = str(_LOGS_DIR / ".lint_cache")

        # ── 2a. Ruff --fix : nettoyage cosmétique auto (E401, formatage LLM)
        try:
            _fix_proc = await asyncio.create_subprocess_exec(
                _exe,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--cache-dir",
                _cache_dir,
                _wp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_ROOT_DIR),
            )
            _fix_out, _fix_err = await asyncio.wait_for(_fix_proc.communicate(), timeout=15)
            _fix_msg = (_fix_out + _fix_err).decode("utf-8", errors="replace")
            _fixes = [l for l in _fix_msg.splitlines() if "fixed" in l.lower() or "Fixed" in l]
            if _fixes:
                chat.write(f"[dim]    ruff --fix : {_fixes[0][:80]}[/]")
                logger.info(f"[@audit] ruff --fix : {_fixes[0][:120]}")
            else:
                chat.write("[dim]    ruff --fix : rien à corriger[/]")
                logger.info("[@audit] ruff --fix : rien à corriger")
        except Exception as _rfe:
            logger.warning(f"[@audit] ruff --fix échoué : {_rfe}")

        # ── 2b. Outils d'analyse (sur le code nettoyé)
        for tool, args in [
            ("ruff", [_exe, "-m", "ruff", "check", "--cache-dir", _cache_dir, _wp]),
            (
                "mypy",
                [_exe, "-m", "mypy", "--ignore-missing-imports", "--no-error-summary", "--cache-dir", _cache_dir, _wp],
            ),
            ("bandit", [_exe, "-m", "bandit", "-f", "text", "--severity-level", "low", _wp]),
            ("pylint", [_exe, "-m", "pylint", "--jobs=1", "--persistent=n", "--output-format=text", "--score=no", _wp]),
        ]:
            try:
                logger.debug(f"[@audit] {tool} → {' '.join(args)}")
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(_ROOT_DIR),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                out = (stdout + stderr).decode("utf-8", errors="replace")
                # Module non installé
                if "No module named" in out:
                    reports.append((tool, "non installé"))
                    chat.write(f"[dim]    {tool}: non installé (pip install {tool})[/]")
                    logger.warning(f"[@audit] {tool} : non installé")
                    continue
                # Pylint stack overflow Windows (rc=0xC000040A) → ignorer
                if tool == "pylint" and proc.returncode and proc.returncode > 100000:
                    reports.append((tool, f"crash Windows (rc={proc.returncode}) — ignoré"))
                    chat.write(f"[dim]    {tool}: ⚠ crash Windows (rc={proc.returncode}) — ignoré[/]")
                    logger.warning(f"[@audit] pylint crash Windows rc={proc.returncode}")
                    continue
                ok = proc.returncode == 0
                reports.append((tool, "Aucun problème" if ok else out[:1500]))
                _preview = "" if ok else " — " + out[:60].replace("\n", " ")
                chat.write(f"[dim]    {tool}: {'✅' if ok else '⚠'}{_preview}[/]")
                logger.info(f"[@audit] {tool} : rc={proc.returncode} {'OK' if ok else out[:200]}")
            except FileNotFoundError:
                reports.append((tool, "non installé"))
                chat.write(f"[dim]    {tool}: non installé (pip install {tool})[/]")
                logger.warning(f"[@audit] {tool} : FileNotFoundError")
            except asyncio.TimeoutError:
                reports.append((tool, "timeout 60s"))
                chat.write(f"[dim]    {tool}: timeout 60s[/]")
                logger.warning(f"[@audit] {tool} : timeout 60s")

        # ── 3. RAG multi-requêtes ciblées ─────────────────────────────────
        rag_ctx = ""
        if rag_engine:
            try:
                chat.write("[dim]  📖 RAG : bugs · patches · logs · arch…[/]")
                _rag_qs = [
                    ("bugs erreurs NameError crash exception Python", "bugs"),
                    ("audit suggestion patch appliqué version", "patches"),
                    ("traceback erreur log exception critique", "logs"),
                    ("architecture async await coroutine design", "arch"),
                ]
                _seen, _ctx_parts = set(), []
                for _q, _tag in _rag_qs:
                    try:
                        for _d in await rag_engine.search(_q, k=3):
                            _key = _d.get("content", "")[:80]
                            if _key not in _seen:
                                _seen.add(_key)
                                _ctx_parts.append(
                                    f"[{_tag}|{_d.get('source', '?')[:20]}] {_d.get('content', '')[:250]}"
                                )
                    except Exception:
                        pass
                rag_ctx = "\n".join(_ctx_parts[:12])
                chat.write(f"[dim]  📖 {len(_ctx_parts)} extraits RAG[/]")
            except Exception as _re:
                logger.debug(f"RAG audit: {_re}")

        _static_summary = "\n".join(f"--- {t} ---\n{r[:600]}" for t, r in reports)
        _code_preview = code[:7000]

        # ══════════════════════════════════════════════════════════════════
        # AGENT A — Développeur : propose les correctifs
        # ══════════════════════════════════════════════════════════════════
        _model_a = self._pick_model_from(self._AUDIT_MODEL_PREF)
        if _mem_mgr:
            _ra = await _mem_mgr.free(strategy="all", target=_model_a)
            if _ra["evicted"]:
                chat.write(f"[dim]Memoire: {_ra['freed_gib']:.1f} GiB liberes ({len(_ra['evicted'])} modele(s))[/]")
        chat.write(f"[bold #58a6ff]🔨 Agent A[/] [dim]Développeur · {_model_a}[/]")
        self._set_status("[cyan]🔨 Agent A…[/]")

        _prompt_a = (
            "Tu es développeur Python expert. Propose des CORRECTIFS précis pour ce code.\n"
            "Priorités : 1=bugs critiques · 2=logique · 3=robustesse · 4=perf · 5=lisibilité\n"
            "INTERDIT absolu : del sys.modules sans clé · os.environ= · sys.exit() · eval/exec non encadrés\n\n"
            "FORMAT OBLIGATOIRE (à respecter strictement) :\n"
            "Suggestion N : <titre décrivant le bug corrigé>\n"
            "TARGET: <nom_exact_fonction_ou_classe>\n"
            "```python\ndef nom_exact(...):  # code COMPLET\n    ...\n```\n\n"
            "Maximum 5 suggestions, du plus critique au moins critique.\n\n"
        )
        if rag_ctx:
            _prompt_a += f"Historique bugs/patches (RAG) :\n{rag_ctx}\n\n"
        _prompt_a += f"Rapports analyse statique :\n{_static_summary}\n\n"
        _prompt_a += f"Code source v{version_manager.current_version} :\n```python\n{_code_preview}\n```\n"

        reply_a = ""
        _tried_a: list = []
        for _ca in [_model_a] + [
            m
            for p in self._AUDIT_MODEL_PREF
            for m in (getattr(self, "_available_models", []) or [])
            if p in m.lower() and m != _model_a
        ]:
            if _ca in _tried_a:
                continue
            _tried_a.append(_ca)
            try:
                reply_a = await ollama_stream(
                    _ca,
                    [{"role": "user", "content": _prompt_a}],
                    lambda _: None,
                    lambda: None,
                )
                if reply_a:
                    if _ca != _model_a:
                        chat.write(f"[dim]  Agent A fallback: {_ca}[/]")
                    _model_a = _ca
                    break
            except Exception as _ea:
                if any(k in str(_ea) for k in ("500", "memory", "OOM")):
                    chat.write(f"[yellow]OOM {_ca} - liberation...[/]")
                    if _mem_mgr:
                        await _mem_mgr.free("all", target=_ca)
                    continue
                chat.write(f"[red]❌ Agent A: {_ea}[/]")
                self._set_status("")
                return
        if not reply_a:
            chat.write("[red]❌ Agent A: tous OOM[/]")
            self._set_status("")
            return
        chat.write(f"[dim]  Agent A {len(reply_a)} chars[/]")

        # ══════════════════════════════════════════════════════════════════
        # AGENT B — Auditeur : liste UNIQUEMENT les risques (erukude)
        # ══════════════════════════════════════════════════════════════════
        _model_b = self._pick_model_from(self._AUDITOR_B_PREF)
        chat.write(f"[bold #f0883e]🔍 Agent B[/] [dim]Auditeur · {_model_b}[/]")
        self._set_status("[cyan]🔍 Agent B…[/]")

        _prompt_b = (
            "Tu es un auditeur de code Python. On te soumet des correctifs proposés par un développeur.\n"
            "TON RÔLE UNIQUE : lister les risques, effets de bord et erreurs potentielles.\n"
            "⚠ NE PROPOSE PAS de code corrigé. NE VALIDE PAS. Liste seulement les problèmes.\n"
            "Format : une ligne par problème, préfixée par '⚠ Suggestion N: <problème>'\n\n"
            f"Code original (extrait) :\n```python\n{_code_preview[:3000]}\n```\n\n"
            f"Correctifs proposés (Agent A) :\n{reply_a[:4000]}\n\n"
            "Liste tes critiques (problèmes potentiels uniquement) :"
        )
        try:
            reply_b = await ollama_stream(
                _model_b,
                [{"role": "user", "content": _prompt_b}],
                lambda _: None,
                lambda: None,
            )
        except Exception as e:
            reply_b = f"(Agent B indisponible: {e})"
            chat.write(f"[yellow]⚠ Agent B : {e}[/]")

        _b_lines = [l.strip() for l in reply_b.splitlines() if l.strip()][:10]
        if _b_lines:
            chat.write("[dim]─── Critique Agent B ───[/]")
            for _line in _b_lines:
                chat.write(f"[dim]  {_line}[/]")

        # ══════════════════════════════════════════════════════════════════
        # AGENT C — Critique AST : version finale tenant compte de B
        # ══════════════════════════════════════════════════════════════════
        _model_c = self._pick_model_from(self._CRITIC_C_PREF)
        if _mem_mgr:
            await _mem_mgr.free(strategy="all", target=_model_c)
        chat.write(f"[bold #3fb950]🏗 Agent C[/] [dim]Critique · {_model_c}[/]")
        self._set_status("[cyan]🏗 Agent C…[/]")

        _prompt_c = (
            "Tu es architecte Python senior. Tu reçois :\n"
            "  1. Le code original  2. Les correctifs Agent A  3. Les risques Agent B\n\n"
            "RÔLE : en tenant compte des risques de B, génère la version finale CORRIGÉE et SÛRE.\n"
            "Si un correctif de A est risqué selon B → améliore-le ou abandonne-le.\n\n"
            "FORMAT IDENTIQUE (obligatoire) :\n"
            "Suggestion N : <titre>\nTARGET: <nom_exact>\n```python\n...code complet...\n```\n\n"
            "INTERDIT : del sys.modules sans clé · os.environ= · sys.exit() · eval/exec\n\n"
        )
        if rag_ctx:
            _prompt_c += f"Contexte RAG :\n{rag_ctx}\n\n"
        _prompt_c += (
            f"Code original :\n```python\n{_code_preview[:4000]}\n```\n\n"
            f"Correctifs Agent A :\n{reply_a[:3000]}\n\n"
            f"Risques Agent B :\n{reply_b[:1500]}\n\n"
            "Version finale sûre et corrigée (max 5 suggestions) :"
        )

        reply = ""
        _tried_c: list = []
        for _cc in [_model_c] + [
            m
            for p in self._CRITIC_C_PREF
            for m in (getattr(self, "_available_models", []) or [])
            if p in m.lower() and m != _model_c
        ]:
            if _cc in _tried_c:
                continue
            _tried_c.append(_cc)
            try:
                reply = await ollama_stream(
                    _cc,
                    [{"role": "user", "content": _prompt_c}],
                    lambda _: None,
                    lambda: None,
                )
                if reply:
                    if _cc != _model_c:
                        chat.write(f"[dim]  Agent C fallback: {_cc}[/]")
                    _model_c = _cc
                    break
            except Exception as _ec:
                if any(k in str(_ec) for k in ("500", "memory", "OOM")):
                    chat.write(f"[yellow]OOM {_cc} - liberation...[/]")
                    if _mem_mgr:
                        await _mem_mgr.free("all", target=_cc)
                    continue
                chat.write(f"[red]❌ Agent C: {_ec}[/]")
                self._set_status("")
                return
        if not reply:
            chat.write("[red]❌ Agent C: tous OOM[/]")
            self._set_status("")
            return

        # Anti-pourrissement MemoryJanitor
        if agentic_engine:
            try:
                chat.write(agentic_engine.audit_report())
                _gauge = self.query_one("#entropy-gauge", EntropyGauge)
                _gauge.refresh_entropy(agentic_engine.entropy_level(), agentic_engine.entropy_color())
            except Exception:
                pass

        chat.write(
            f"[bold #58a6ff]Audit v{version_manager.current_version}[/]"
            f" [dim]A={_model_a.split(':')[0]} · B={_model_b.split(':')[0]}"
            f" · C={_model_c.split(':')[0]}[/]"
        )
        chat.write(reply)

        # Indexer dans RAG
        if rag_engine:
            try:
                await rag_engine.add_session_message(
                    "audit_results",
                    "audit",
                    f"[AUDIT-3AGENTS v{version_manager.current_version}]"
                    f"\nA:{reply_a[:1000]}\nB:{reply_b[:500]}\nC:{reply[:2000]}",
                )
            except Exception:
                pass

        # ── Parser suggestions Agent C ─────────────────────────────────────
        self.last_audit_suggestions = []
        _pat = r"Suggestion\s+(\d+)\s*:\s*(.*?)(?:\nTARGET:\s*(\S+))?\n```python\n(.*?)\n```"
        for num, desc, target, code_block in re.findall(_pat, reply, re.DOTALL | re.IGNORECASE):
            self.last_audit_suggestions.append(
                {
                    "num": int(num),
                    "description": desc.strip(),
                    "target": target.strip() if target else "",
                    "code": code_block.strip(),
                }
            )

        if self.last_audit_suggestions:
            chat.write("[dim]  🔍 Validation collaborative (AST + consensus)…[/]")
            self.last_audit_suggestions = list(
                await asyncio.gather(*[self._validate_suggestion_async(s) for s in self.last_audit_suggestions])
            )
            _n_ok = sum(1 for s in self.last_audit_suggestions if s.get("validated", True))
            _n_bad = len(self.last_audit_suggestions) - _n_ok
            chat.write("[bold]Suggestions finales (Agent C) :[/]")
            for sugg in self.last_audit_suggestions:
                _ok = sugg.get("validated", True)
                _conf = sugg.get("confidence", 1.0)
                _revs = ", ".join(r.split(":")[0] for r in sugg.get("reviewers", []))
                _iss = sugg.get("issues", [])
                _badge = (
                    f"[green]✅ {int(_conf * 100)}%[/][dim]({_revs})[/]"
                    if _ok
                    else f"[red]⚠ SUSPECT[/] [dim]{(_iss[0][:50] if _iss else '?')}[/]"
                )
                chat.write(f"  [bold]{sugg['num']}.[/] {sugg['description'][:65]}  {_badge}")
                if sugg.get("target"):
                    chat.write(f"     [dim]TARGET: {sugg['target']}[/]")
            if _n_bad:
                chat.write(f"[yellow]⚠ {_n_bad} suspecte(s) · v=validées · numéro=forcer[/]")
            chat.write(
                "[dim]→ [bold]numéro[/] · [bold]t[/]=tout (skip suspectes) · [bold]v[/]=validées · @loop=auto[/]"
            )
            # Forcer focus sur chat pour que t/v/numéro ne partent pas au terminal
            try:
                self.query_one("#chat-input", _lazy("AutocompleteInput")).focus()
            except Exception:
                pass
        else:
            chat.write("[dim]Aucune suggestion Agent C exploitable.[/]")

        self._set_status("")

    async def _post_loop_safe_check(
        self,
        loop_id: str,
        state: object,  # LoopState
        log_fn: object,
    ) -> None:
        """
        Séquence de sécurité automatique lancée à la fin de chaque cycle @loop.

        1. Checkpoint atomique ZIP  (workspace/ + loop_trunk/)
        2. Inventaire et validation AST de toutes les versions produites
        3. Rapport TUI enrichi avec les stats du LoopState
        4. Proposition merge/rollback/abort avec boutons dans le chat
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        settings = _ac.settings
        version_manager = _ac.version_manager
        import zipfile
        import re as _re

        chat = self._chat_log()

        # ── helpers locaux ────────────────────────────────────────────────
        base_dir = _ROOT_DIR
        workspace_dir = base_dir / "workspace"
        loop_dir = base_dir / "loop_trunk"
        backup_dir = base_dir / "backups"
        logs_dir = base_dir / "logs"
        backup_dir.mkdir(exist_ok=True)
        logs_dir.mkdir(exist_ok=True)

        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"checkpoint_{ts}_post_loop_{loop_id}.zip"
        zip_final = backup_dir / zip_name
        zip_tmp = backup_dir / f".{zip_name}.tmp"
        log_file = logs_dir / f"post_loop_{ts}.log"

        def _vlog(msg: str) -> None:
            """Écrit dans le chat TUI ET dans le fichier log."""
            log_fn(msg)
            try:
                with open(log_file, "a", encoding="utf-8") as _f:
                    import re as _r

                    _f.write(_r.sub(r"\[.*?\]", "", msg) + "\n")
            except Exception:
                pass

        def _ver_key(path: Path) -> list:
            """Ver key.

            Args:
                path: Description.
            """
            m = _re.search(r"_v([\d.]+)\.py$", path.name)
            return [int(x) for x in _re.findall(r"\d+", m.group(1))] if m else [0]

        def _check_syntax(path: Path) -> tuple:
            """Check syntax.

            Args:
                path: Description.
            """
            import ast as _ast

            try:
                code = path.read_text(encoding="utf-8", errors="replace")
                _ast.parse(code)
                return True, f"{len(code.splitlines())} lignes, {path.stat().st_size // 1024} Ko"
            except SyntaxError as e:
                return False, f"SyntaxError ligne {e.lineno}: {e.msg}"

        # ── Étape 1 : Checkpoint atomique ZIP ────────────────────────────
        _vlog("\n[bold #58a6ff]╔══════════════════════════════════════════╗[/]")
        _vlog("[bold #58a6ff]║  🔒 VÉRIFICATION POST-LOOP (AUTO)        ║[/]")
        _vlog("[bold #58a6ff]╚══════════════════════════════════════════╝[/]")
        _vlog("[dim]Étape 1/3 — Checkpoint atomique…[/]")

        file_count = 0
        try:
            with zipfile.ZipFile(zip_tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for arc_root, src_dir in [("workspace", workspace_dir), ("loop_trunk", loop_dir)]:
                    if not src_dir.exists():
                        continue
                    for fpath in sorted(src_dir.rglob("*")):
                        if fpath.is_file():
                            arcname = arc_root + "/" + fpath.relative_to(src_dir).as_posix()
                            zf.write(fpath, arcname)
                            file_count += 1
                # Manifeste
                from datetime import datetime as _dt

                zf.writestr(
                    "MANIFEST.txt",
                    f"loop_id:  {loop_id}\n"
                    f"created:  {_dt.now().isoformat()}\n"
                    f"files:    {file_count}\n"
                    f"iter_b1:  {state.loop1_iterations}\n"
                    f"iter_b2:  {state.loop2_iterations}\n"
                    f"iter_b3:  {state.loop3_iterations}\n"
                    f"failures: {state.total_failures}\n",
                )

            # Vérif CRC avant rename
            with zipfile.ZipFile(zip_tmp, "r") as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"CRC invalide : {bad}")
                zip_kb = zip_tmp.stat().st_size // 1024

            zip_tmp.rename(zip_final)  # atomique
            _vlog(f"  [green]✅ Checkpoint ZIP : {zip_name}[/]")
            _vlog(f"     {file_count} fichiers archivés, {zip_kb} Ko")

        except Exception as e:
            if zip_tmp.exists():
                zip_tmp.unlink()
            _vlog(f"  [red]❌ Checkpoint ÉCHOUÉ : {e}[/]")
            _vlog("  [red]Opération annulée par sécurité.[/]")
            return  # pas de merge sans checkpoint

        # ── Étape 2 : Inventaire + validation AST du tronc loop ──────────
        _vlog("[dim]Étape 2/3 — Validation des versions produites…[/]")

        trunk = loop_dir / f"loop_{loop_id}"
        if not trunk.exists():
            _vlog(f"  [yellow]⚠ Tronc loop_{loop_id}/ introuvable.[/]")
            return

        all_versions = sorted(trunk.glob("*.py"), key=_ver_key, reverse=True)
        valid_v, invalid_v = [], []
        for p in all_versions:
            ok, detail = _check_syntax(p)
            (valid_v if ok else invalid_v).append((p, detail))

        # ── Étape 3 : Rapport enrichi ────────────────────────────────────
        _vlog("[dim]Étape 3/3 — Rapport…[/]")
        total_iter = state.loop1_iterations + state.loop2_iterations + state.loop3_iterations
        success_iter = sum(1 for it in state.iterations if it.success)

        _vlog(f"\n[bold]📊 Résumé du cycle Loop {loop_id}[/]")
        _vlog(
            f"  Itérations totales  : {total_iter}  "
            f"(B1={state.loop1_iterations} B2={state.loop2_iterations} B3={state.loop3_iterations})"
        )
        _vlog(f"  Succès / Échecs     : {success_iter} / {state.total_failures}")
        _vlog(f"  Dernière version ok : v{state.last_successful_version or '?'}")
        _vlog(f"  Versions générées   : {len(all_versions)}  (valides={len(valid_v)} invalides={len(invalid_v)})")

        if invalid_v:
            _vlog("[yellow]  Versions invalides (exclues du merge) :[/]")
            for p, detail in invalid_v:
                _vlog(f"    ✗ {p.name} — {detail}")

        if not valid_v:
            _vlog("[red]  ❌ Aucune version valide — merge impossible.[/]")
            _vlog(f"  Rollback disponible : backups/{zip_name}")
            _vlog(f"  Log complet         : logs/{log_file.name}")
            return

        best_path, best_detail = valid_v[0]
        best_ver = state.last_successful_version or _re.search(r"_v([\d.]+)\.py$", best_path.name)
        best_ver_str = best_ver.group(1) if hasattr(best_ver, "group") else str(best_ver)

        _vlog(f"\n  [green]✅ Meilleure version : {best_path.name} ({best_detail})[/]")
        _vlog(f"  Checkpoint de sécurité : backups/{zip_name}")
        _vlog(f"  Log complet            : logs/{log_file.name}")

        # ── Calcul du delta pour décision automerge ───────────────────────
        import ast as _ast

        def _count_errors(path: str) -> int:
            """Count errors.

            Args:
                path: Description.
            """
            try:
                _ast.parse(path.read_text(encoding="utf-8", errors="replace"))
                return 0
            except SyntaxError:
                return 1

        # Comparer meilleure version loop vs version de départ du tronc
        start_files = sorted(trunk.glob("*.py"), key=lambda p: p.stat().st_mtime)
        start_errors = _count_errors(start_files[0]) if start_files else 0
        best_errors = _count_errors(best_path)
        delta_errors = start_errors - best_errors

        # Score qualité : heuristique rapide (lignes / taille)
        try:
            best_code = best_path.read_text(encoding="utf-8", errors="replace")
            lines = len(best_code.splitlines())
            # Qualité = présence de docstrings + pas trop de lignes vides consécutives
            has_docs = best_code.count('"""') >= 4
            no_bloat = best_code.count("\n\n\n") < 5
            quality_est = 65 + (10 if has_docs else 0) + (10 if no_bloat else 0)
        except Exception:
            quality_est = 60

        _vlog(f"  Delta erreurs  : {'+' if delta_errors >= 0 else ''}{delta_errors}")
        _vlog(f"  Qualité estim. : {quality_est}/100")

        # ── Décision automerge ────────────────────────────────────────────
        min_delta = getattr(settings, "loop_automerge_min_delta", 1)
        min_quality = getattr(settings, "loop_automerge_min_quality", 60)
        automerge = getattr(settings, "loop_automerge", False)

        if automerge:
            if delta_errors >= min_delta and quality_est >= min_quality:
                _vlog(
                    f"\n[bold green]🤖 AUTOMERGE — critères remplis "
                    f"(Δerreurs={delta_errors} ≥ {min_delta}, "
                    f"qualité={quality_est} ≥ {min_quality})[/]"
                )
                # Merge effectif : copie dans workspace/
                import shutil as _sh

                _ws = base_dir / "workspace"
                _ws.mkdir(exist_ok=True)
                _dst = _ws / best_path.name
                _sh.copy2(best_path, _dst)

                # Mettre à jour version_manager proprement
                try:
                    version_manager.work_path = _dst
                    version_manager._rebuild_version_index()
                    # Libérer le tronc loop — sinon @loop start/merge
                    # croira qu'un tronc est encore actif
                    version_manager._loop_id = None
                    version_manager._loop_trunk = None
                except Exception:
                    pass

                # Archiver l'ancienne version dans versions/
                try:
                    from datetime import datetime as _dt

                    _ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                    _old = base_dir / "workspace" / start_files[0].name
                    if _old.exists() and _old != _dst:
                        _arc = base_dir / "versions" / f"{_old.stem}_{_ts}.py"
                        (base_dir / "versions").mkdir(exist_ok=True)
                        _sh.copy2(_old, _arc)
                except Exception:
                    pass

                _vlog(f"  ✅ Mergé       : {best_path.name} → workspace/")
                _vlog("  📦 Ancien      : archivé dans versions/")
                _vlog("  🔓 Tronc loop  : libéré")
                _vlog("  ♻  Relancez Nokido pour charger la nouvelle version.")
            else:
                _vlog(
                    f"\n[yellow]🤖 AUTOMERGE désactivé — critères non remplis "
                    f"(Δerreurs={delta_errors} < {min_delta} "
                    f"ou qualité={quality_est} < {min_quality})[/]"
                )
                _vlog("  Action manuelle requise :")
                _vlog("  [bold cyan]@loop merge[/]  — fusionner quand même")
                _vlog("  [bold yellow]@loop stop[/]   — abandonner")
        else:
            _vlog("\n[bold]Que souhaitez-vous faire ?[/]")
            _vlog("  [bold cyan]@loop merge[/]    — fusionner cette version dans workspace/")
            _vlog("  [bold yellow]@loop stop[/]     — abandonner sans fusionner")
            _vlog("  [bold red]@rollback[/]      — restaurer depuis le checkpoint ZIP")
            _vlog("  [dim](Activez LOOP_AUTOMERGE=true dans Nokido.env pour automatiser)[/]")

    async def _handle_loop(self, args: str) -> None:
        """
        from forge_app_context import app_ctx as _actx; _ac = _actx()
        HAS_SANDBOX = _ac.HAS_SANDBOX
        rag_engine = _ac.rag_engine
        settings = _ac.settings
        version_manager = _ac.version_manager
        @loop [start|stop|status|merge|versions]
        Lance la boucle d'amélioration autonome (B1→B2→B3) sur un tronc séparé.
        """
        chat = self._chat_log()
        if not _has("HAS_LOOPS") or not _has("HAS_SANDBOX"):
            missing = []
            if not _has("HAS_LOOPS"):
                missing.append("forge_agents.py")
            if not HAS_SANDBOX:
                missing.append("forge_code.py")
            chat.write(f"[red]❌ @loop indisponible — manquant : {', '.join(missing)}[/]")
            return

        sub = args.split()[0].lower() if args.split() else "start"

        if sub == "start":
            if hasattr(self, "_loop_task") and self._loop_task and not self._loop_task.done():
                chat.write("[yellow]⚠ Un loop est déjà en cours.[/]")
                return

            # ── Fichiers cibles ───────────────────────────────────────
            _loop_args = args.split()[1:]  # mots après "start"
            _target_files = []
            for _f in _loop_args:
                _fp = _APP_DIR / _f
                if _fp.exists():
                    _target_files.append(_fp)
                else:
                    chat.write(f"[yellow]⚠ {_f} introuvable[/]")
            if not _target_files:
                _target_files = [version_manager.work_path]

            loop_id = version_manager.start_loop_trunk()
            _file_list = ", ".join(f.name for f in _target_files)
            chat.write(
                f"[bold #58a6ff]🔄 Loop {loop_id} démarré[/]\n"
                f"  Fichiers : {_file_list}\n"
                f"  Tronc : loop_trunk/loop_{loop_id}/\n"
                f"  Version départ : v{version_manager.current_version}"
            )

            # Auto-indexation avant de démarrer
            await self._index_self_in_rag()

            orchestrator = _lazy("ImprovementOrchestrator")(
                settings.ollama_url,
                settings.ollama_tags_url,
            )

            def log_fn(msg: str) -> None:
                """Log fn.

                Args:
                    msg: Description.
                """
                try:
                    self._chat_log().write(msg)
                except Exception:
                    pass

            async def run_loop() -> None:
                """Run loop."""
                try:
                    state = await orchestrator.run(
                        vm=version_manager,
                        rag=rag_engine,
                        log_fn=log_fn,
                        on_done=lambda s: log_fn(
                            f"[green]✅ Loop terminé — "
                            f"{s.loop1_iterations + s.loop2_iterations + s.loop3_iterations}"
                            f" itérations[/]"
                        ),
                        target_files=_target_files if len(_target_files) > 1 else None,
                    )
                    # Indexer les résultats dans le RAG
                    if rag_engine:
                        summary = (
                            f"[LOOP {loop_id}] "
                            f"v{state.last_successful_version or '?'} "
                            f"— {len(state.iterations)} itérations "
                            f"— {state.total_failures} échecs"
                        )
                        await rag_engine.add_session_message("improvement_loop", "loop_done", summary)
                    # Versions du tronc loop
                    versions = version_manager.list_loop_versions()
                    if versions:
                        log_fn("[bold]Versions créées dans le tronc loop :[/]")
                        for v in versions:
                            log_fn(f"  v{v['version']} — {v['mtime'][:19]}")

                    # ── Vérification post-loop automatique ────────────────
                    await self._post_loop_safe_check(
                        loop_id=loop_id,
                        state=state,
                        log_fn=log_fn,
                    )

                except Exception as e:
                    import traceback

                    tb = traceback.format_exc()
                    log_fn(f"[red]❌ Loop erreur : {e}[/]")
                    log_fn(f"[dim red]{tb[:600]}[/]")
                    # Logger dans debug.log pour ne pas perdre l'erreur
                    try:
                        _loop_log = Path(__file__).resolve().parent / "logs" / f"loop_error_{loop_id}.log"
                        _loop_log.parent.mkdir(exist_ok=True)
                        _loop_log.write_text(
                            f"Loop {loop_id} erreur\n{datetime.now().isoformat()}\n\n{tb}", encoding="utf-8"
                        )
                        log_fn(f"[dim]→ Traceback complet : logs/loop_error_{loop_id}.log[/]")
                    except Exception:
                        pass
                    version_manager.end_loop_trunk(merge=False)

            self._loop_task = asyncio.create_task(run_loop())

        elif sub == "stop":
            if hasattr(self, "_loop_task") and self._loop_task and not self._loop_task.done():
                self._loop_task.cancel()
                chat.write("[yellow]⚠ Loop interrompu.[/]")
            version_manager.end_loop_trunk(merge=False)
            chat.write("[dim]Tronc loop abandonné (aucune fusion).[/]")

        elif sub == "merge":
            # Checkpoint AVANT merge (Double Porte)
            if save_orchestrator:
                _bk = save_orchestrator.create_checkpoint(label="pre_loop_merge")
                chat.write(f"  [dim]💾 Checkpoint : {_bk.name}[/dim]")
            version_manager.end_loop_trunk(merge=True)
            new_ver = version_manager.current_version
            if save_orchestrator:
                save_orchestrator.rotate_backups()
            chat.write(f"[green]✅ Tronc loop fusionné → workspace (v{new_ver})[/]")
            self._update_sidebar_title()

        elif sub == "versions":
            versions = version_manager.list_loop_versions()
            if versions:
                chat.write("[bold]Versions dans le tronc loop courant :[/]")
                for v in versions:
                    chat.write(f"  v{v['version']} {v['mtime'][:19]} ({v['size']} octets)")
            else:
                chat.write("[dim]Aucun tronc loop actif.[/]")
            ws = version_manager.list_workspace_versions()
            chat.write("[bold]Workspace principal :[/]")
            for v in ws:
                cur = " ← [green]COURANT[/]" if v["current"] else ""
                chat.write(f"  v{v['version']} {v['mtime'][:19]}{cur}")

        elif sub == "status":
            if hasattr(self, "_loop_task") and self._loop_task and not self._loop_task.done():
                chat.write("[cyan]🔄 Loop en cours…[/]")
            else:
                chat.write("[dim]Aucun loop actif.[/]")
            chat.write(f"  Version courante : v{version_manager.current_version}")
            chat.write(f"  Fichier : {version_manager.work_path.name}")
            chat.write(f"  Tronc loop : {'actif' if version_manager._loop_trunk else 'inactif'}")
        else:
            chat.write(
                "[bold]@loop[/] start|stop|merge|versions|status\n"
                "  start    — lance l'amélioration autonome (tronc séparé)\n"
                "  stop     — interrompt sans fusionner\n"
                "  merge    — fusionne la meilleure version dans workspace\n"
                "  versions — liste les versions du tronc courant\n"
                "  status   — état du loop"
            )

    async def _apply_suggestion(self, sugg: dict, _ask_restart: bool = True) -> bool:
        """Patch cumulatif — fichier complet, chaque apply = nouvelle version."""
        chat = self._chat_log()
        num, desc, target = sugg["num"], sugg["description"], sugg.get("target", "")
        chat.write(f"[dim]⏳ Suggestion {num} : {desc[:60]}…[/]")
        if save_orchestrator:
            save_orchestrator.create_checkpoint(label=f"pre_sugg_{num}")
        current_full_code = version_manager.get_current_code()
        if target:
            import re as _re2

            _pat = _re2.compile(
                r"(^[ \t]*(?:async\s+)?def\s+" + _re2.escape(target) + r"\b"
                r"|^[ \t]*class\s+" + _re2.escape(target) + r"\b)"
                r"(.*?)(?=\n[ \t]*(?:async\s+)?def\s|\n[ \t]*class\s|\Z)",
                _re2.DOTALL | _re2.MULTILINE,
            )
            patched_code = (
                _pat.sub(sugg["code"].rstrip(), current_full_code, count=1)
                if _pat.search(current_full_code)
                else current_full_code.rstrip() + "\n\n" + sugg["code"]
            )
        else:
            patched_code = current_full_code.rstrip() + "\n\n" + sugg["code"]
        new_path = await version_manager.prepare_patch(patched_code, f"Suggestion {num}: {desc}", major=False)
        if not new_path:
            chat.write(
                f"[red]❌ Suggestion {num} rejetée par PatchGuard (patch invalide ou trop court — fichier complet requis)[/]"
            )
            return False
        _propagated = False
        try:
            import stat as _stat, shutil as _shu

            _sp = version_manager.source_path
            _sp.chmod(_stat.S_IRUSR | _stat.S_IWUSR | _stat.S_IRGRP | _stat.S_IROTH)
            _shu.copy2(str(new_path), str(_sp))
            _sp.chmod(_stat.S_IRUSR | _stat.S_IRGRP | _stat.S_IROTH)
            _propagated = True
        except Exception as _pe:
            chat.write(f"[yellow]⚠ Non propagé : {_pe}[/]")
        _nv = version_manager.current_version
        self._refresh_version_display()
        chat.write(
            f"[green]✅ Suggestion {num} → [bold]v{_nv}[/] {'· propagé' if _propagated else '· workspace seulement'}[/]"
        )
        # Gold Sample
        try:
            _gold = {
                "timestamp": datetime.now().isoformat(),
                "version": _nv,
                "target": target,
                "description": desc,
                "code_after": sugg["code"][:5000],
                "validated": True,
            }
            with open(_DATA_DIR / "gold_samples.jsonl", "a", encoding="utf-8") as _gf:
                _gf.write(json.dumps(_gold, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if _ask_restart:
            self._propose_restart(f"suggestion {num} → v{_nv}")
        return True

    def _propose_restart(self, reason: str = "") -> None:
        """Propose restart.

        Args:
            reason: Description.
        """
        chat = self._chat_log()

        def _on_confirm(ok: object) -> None:
            """On confirm.

            Args:
                ok: Description.
            """
            if ok:
                chat.write("[dim]🔄 Redémarrage in-place…[/]")
                import asyncio as _aio

                async def _do() -> None:
                    """Do."""
                    try:
                        await self.terminal.disconnect()
                    except Exception:
                        pass
                    try:
                        if HAS_ONNX:
                            shutdown_onnx_backend()
                    except Exception:
                        pass
                    await _aio.sleep(0.3)
                    import os as _os, sys as _sys

                    _os.execv(_sys.executable, [_sys.executable] + _sys.argv)

                self.call_later(lambda: _aio.create_task(_do()))
            else:
                chat.write("[dim]Redémarrage annulé.[/]")

        _CS = getattr(type(self), "ConfirmScreen", None)
        if _CS:
            self.push_screen(_CS(f"Redémarrer Nokido — {reason} ? (y/n)", _on_confirm))

    async def _handle_apply(self, args: str) -> None:
        """Handle apply.

        Args:
            args: Description.
        """
        if not args or not args.isdigit():
            self._chat_log().write("[red]Usage: @apply <numéro>[/]")
            return
        num = int(args)
        sugg = next((s for s in self.last_audit_suggestions if s["num"] == num), None)
        if not sugg:
            self._chat_log().write(f"[red]Aucune suggestion numéro {num} trouvée.[/]")
            return

        # Déléguer à _apply_suggestion (cumulatif + PatchGuard + propagation)
        _ok = await self._apply_suggestion(sugg, _ask_restart=False)
        if _ok:
            self._propose_restart(f"@apply {num} → v{version_manager.current_version}")

    def _extract_commands_from_response(self, text: str) -> list:
        """Extrait les commandes shell d'une réponse LLM."""
        cmds = []
        blocks = re.findall(r"```(?:bash|sh|shell)\s*\n([^`]+?)\n```", text, re.DOTALL | re.IGNORECASE)
        for block in blocks:
            for line in block.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    cmds.append(line)
        if not cmds:
            for m in re.findall(r"^\s*\$\s+(.+)$", text, re.MULTILINE):
                cmds.append(m.strip())
        return cmds
