# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_handler_patch
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_handler_patch.py — Handlers patch, apply, code
=====================================================
Extrait de forge_handlers.py — Phase 3 refactor.
Importez depuis ce module plutôt que forge_handlers pour ce domaine.
"""

import re
import asyncio
import logging
from rich.markup import escape
from nokido_agent.app.forge_logging import debug_log
from app.core.settings import get_app_attr as _g
from nokido_agent.app import forge_context
from nokido_agent.app.forge_context import get_version_manager as _gvm_global  # noqa — requis par handlers
from app.forge_llm import RAG_KEYWORDS
from app.forge_llm import SHELL_COMMANDS
from app.forge_llm import SHELL_SPECIAL_CHARS
from app.forge_llm import _CMD_EXTRACT
from app.forge_llm import _NLU_ACTION_PATTERNS
from app.forge_llm import _NLU_RAG_PATTERNS
from app.forge_ui_widgets import ConfirmScreen

logger = logging.getLogger("Nokido.Forge.Handler.Patch")


async def _handle_apply(app: "App", args: str) -> None:
    """Handle apply.

    Args:
        app: Description.
        args: Description.
    """
    chat = app._chat_log()
    if not args or not args.isdigit():
        app._chat_log().write("[red]Usage: @apply <numéro>[/]")
        return
    num = int(args)
    sugg = next((s for s in app.last_audit_suggestions if s["num"] == num), None)
    if not sugg:
        app._chat_log().write(f"[red]Aucune suggestion numéro {num} trouvée.[/]")
        return

    # Déléguer à _apply_suggestion (cumulatif + PatchGuard + propagation)
    _ok = await app._apply_suggestion(sugg, _ask_restart=False)
    if _ok:
        app._propose_restart(f"@apply {num} → v{_gvm_global().current_version}")


async def _handle_run(app, cmd_line: str) -> None:
    """Handle run.

    Args:
        app: Description.
        cmd_line: Description.
    """
    chat = app._chat_log()
    raw = re.sub(r"\s+", " ", cmd_line[4:].strip())
    subparts = raw.split(maxsplit=1)
    sudo = False
    if subparts and subparts[0] == "-sudo":
        sudo = True
        command = subparts[1] if len(subparts) > 1 else ""
    else:
        command = raw
    if not command:
        chat.write("[red]❌ Commande manquante[/]")
        return
    # ── DangerGuard ──────────────────────────────────────────────
    if app.guard and _g("HAS_DANGER_GUARD", False):
        from danger_guard import DangerLevel, should_auto_block, danger_confirmation_message

        _chk = app.guard.check(command)
        if should_auto_block(_chk):
            chat.write(f"[bold red]☠ BLOQUÉ — {_chk.rule_name}[/]\n{_chk.explanation}")
            return
        if _chk.level >= DangerLevel.WARNING:
            _cmd_capture, _sudo_capture = command, sudo

            async def _confirmed_run(ok: bool) -> None:
                """Confirmed run.

                Args:
                    ok: Description.
                """
                if not ok:
                    app._chat_log().write("[dim]Commande annulée.[/]")
                    return
                await app.terminal.inject(_cmd_capture)
                try:
                    _pm = forge_context.get_settings() and forge_context.get_prefect_manager()
                    out = await _pm.run_ssh_command(_cmd_capture, sudo=_sudo_capture)
                    if out.strip():
                        app._chat_log().write(f"[green]✅ Résultat :[/]\n{escape(out.strip())}")
                    else:
                        app._chat_log().write("[green]✅ Commande exécutée (pas de sortie)[/]")
                except Exception as e:
                    app._chat_log().write(f"[red]❌ Erreur : {escape(str(e))}[/]")

            app.push_screen(
                ConfirmScreen(
                    danger_confirmation_message(_chk),
                    lambda ok: asyncio.create_task(_confirmed_run(ok)),
                )
            )
            return
    # ── Exécution directe (commande sûre) ────────────────────────
    chat.write(f"[dim]⏳ Exécution : [bold]{escape(command)}[/][/]")
    _cmd, _sudo = command, sudo

    async def do_run() -> None:
        """Do run."""
        await app.terminal.inject(_cmd)
        try:
            _pm = forge_context.get_settings() and forge_context.get_prefect_manager()
            out = await _pm.run_ssh_command(_cmd, sudo=_sudo)
            if out.strip():
                chat.write(f"[green]✅ Résultat :[/]\n{escape(out.strip())}")
            else:
                chat.write("[green]✅ Commande exécutée (pas de sortie)[/]")
        except Exception as e:
            chat.write(f"[red]❌ Erreur : {escape(str(e))}[/]")

    asyncio.create_task(do_run())


def _propagate_patch(new_path: Path, vm, chat) -> bool:
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
        chat.write(f"[yellow]⚠ Propagation échouée : {e}\n  Copie manuelle : workspace/{new_path.name} → Nokido.py[/]")
        return False


def _validate_patch(app, new_path: Path, prev_path: Path, surgical: bool = False) -> str:
    """
    Valide un patch avant de l'accepter.
    Retourne la raison du rejet (str non vide) ou '' si OK.

    Critères :
      1. Syntaxe Python valide
      2. Taille >= 50% de l'original (détecte les snippets orphelins)
      3. Marqueurs structurels Nokido présents

    surgical=True : patch ciblé sur une fonction — skip les marqueurs structurels
                    car le patch est injecté dans le fichier complet avant validation.
    """
    try:
        new_code = new_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"lecture impossible : {e}"

    # 1. Syntaxe
    try:
        compile(new_code, str(new_path), "exec")
    except SyntaxError as e:
        return f"SyntaxError L{e.lineno} : {e.msg}"

    # 2. Taille relative (skip si prev_path=None — ex: rollback)
    new_lines = len(new_code.splitlines())
    if prev_path is not None and prev_path.exists():
        try:
            prev_lines = len(prev_path.read_text(encoding="utf-8", errors="replace").splitlines())
            if prev_lines > 100 and new_lines < prev_lines * 0.5:
                return f"trop court : {new_lines} lignes vs {prev_lines} (<50%)"
        except Exception:
            pass  # lecture prev_path optionnelle — non bloquant

    # 3. Marqueurs structurels (skip en mode chirurgical)
    if not surgical:
        required = ["class DevOpsApp", "def _handle_audit", "version_manager"]
        missing = [m for m in required if m not in new_code]
        if missing:
            return f"marqueurs manquants : {', '.join(missing)}"

    return ""  # OK


def classify_with_cmd(
    cmd: str,
    _chat_q_pat=None,
    _chat_starters=None,
    _conv_pat=None,
    _sys_tools=None,
) -> tuple:
    """
    Retourne (AgentType, commande_extraite_ou_None).
    ORDRE DE PRIORITÉ v3 :
      0. CHAT_STARTERS (premier mot conversationnel fort) → CHAT immédiat
      1. Commande shell directe (premier mot dans SHELL_COMMANDS)
      2. Questions/conversations françaises → CHAT  ← AVANT les chars shell
      3. Chars shell vrais (|><&;$`\\*)
      4. Patterns NLU ACTION (formulations naturelles)
      5. Patterns NLU RAG
      6. Keywords RAG legacy
      7. CHAT fallback
    """
    text = cmd  # texte a classer ; `cmd` est reaffecte plus bas a la commande extraite
    from nokido_agent.app.forge_core_models import AgentType

    # ── MARQUEUR DEBUG — détecte si [CONTEXTE CIBLE] passe encore ici ───
    _ctx_leak = "[CONTEXTE CIBLE]" in text or "[DEMANDE]" in text
    if _ctx_leak:
        debug_log(
            "ROUTE",
            "classify_with_cmd",
            "⚠ BUG DETECTE: contexte enrichi reçu au lieu du raw_input",
            {"preview": text[:80], "len": len(text)},
        )
    lower = text.lower().strip()
    words = lower.split()
    first = words[0] if words else ""

    # ── 0. CHAT_STARTERS : premier mot conversationnel fort → CHAT immédiat ─
    # Ex: "oui bien sûr", "ok merci", "non pas ça", "bonjour"
    if first in _chat_starters and len(words) <= 8:
        # Court + commence par mot conv → pas une commande
        debug_log(
            "ROUTE",
            "IntentClassifier.classify_with_cmd",
            "CHAT_STARTER priority",
            {"first": first, "len": len(words), "text": text[:80]},
        )
        return AgentType.CHAT, None

    # ── 1. Premier mot = commande shell directe ───────────────────────────
    if first in SHELL_COMMANDS:
        debug_log(
            "ROUTE", "IntentClassifier.classify_with_cmd", "SHELL_CMD direct", {"first": first, "text": text[:80]}
        )
        return AgentType.ACTION, text.strip()

    # ── 2. Question / conversation française → CHAT (prioritaire) ─────────
    # NB : vérifie AVANT les chars shell pour éviter que "?" piège les questions
    is_question = bool(_chat_q_pat.match(lower))
    is_conv = bool(_conv_pat.match(lower))
    # ── 2b. Phrase se terminant par "?" sans contenir de vrai char shell ──
    # Ex: "quel jour sommes nous ?", "peux tu agir sur le poste ?"
    # Le "?" seul ne fait pas d'une phrase une commande shell
    _has_real_shell = any(c in text for c in {"|", ">", "<", "&", ";", "$", "`", "\\", "*"})
    _ends_with_q = lower.rstrip().endswith("?")
    if _ends_with_q and not _has_real_shell:
        is_question = True
    # ── 2c. Phrase très courte sans caractère shell → probablement CHAT ───
    if len(words) <= 3 and not _has_real_shell and first not in SHELL_COMMANDS:
        is_conv = True
    if is_question or is_conv:
        has_sys_tool = any(w in words for w in _sys_tools)
        if not has_sys_tool:
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                "CHAT_QUESTION priority",
                {"is_question": is_question, "is_conv": is_conv, "ends_with_q": _ends_with_q, "text": text[:80]},
            )
            return AgentType.CHAT, None

    # ── 3. Caractères shell vrais (|><&;$`\*) ─────────────────────────────
    # NB: ?, [, ], (, ), {, } exclus — faux-positifs massifs en français
    found_char = next((c for c in SHELL_SPECIAL_CHARS if c in text), None)
    if found_char:
        debug_log(
            "ROUTE", "IntentClassifier.classify_with_cmd", "SHELL_CHAR match", {"char": found_char, "text": text[:80]}
        )
        return AgentType.ACTION, text.strip()

    # ── 4. Patterns NLU ACTION ────────────────────────────────────────────
    for i, (pattern, cmd_group) in enumerate(_NLU_ACTION_PATTERNS):
        m = pattern.search(text)
        if m:
            cmd = None
            if cmd_group and cmd_group <= len(m.groups()):
                cmd = m.group(cmd_group).strip()
            else:
                em = _CMD_EXTRACT.search(text)
                cmd = em.group(1).strip() if em else None
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                f"NLU_ACTION PAT[{i}]",
                {"match": m.group(0)[:60], "cmd_extracted": cmd, "text": text[:80]},
            )
            return AgentType.ACTION, cmd

    # ── 5. Patterns NLU RAG ───────────────────────────────────────────────
    for pat in _NLU_RAG_PATTERNS:
        m = pat.search(text)
        if m:
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                "NLU_RAG match",
                {"match": m.group(0)[:60], "text": text[:80]},
            )
            return AgentType.RAG, None

    # ── 6. RAG keywords legacy ────────────────────────────────────────────
    matched_kw = next((kw for kw in RAG_KEYWORDS if kw in lower), None)
    if matched_kw:
        debug_log(
            "ROUTE",
            "IntentClassifier.classify_with_cmd",
            "RAG_KEYWORD legacy",
            {"keyword": matched_kw, "text": text[:80]},
        )
        return AgentType.RAG, None

    debug_log("ROUTE", "IntentClassifier.classify_with_cmd", "CHAT fallback", {"text": text[:80]})
    return AgentType.CHAT, None
