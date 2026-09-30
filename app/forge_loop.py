# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_loop
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""forge_loop.py — Loop auto-amélioration + patch (v16.5)"""

import ast as _ast, zipfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


async def post_loop_safe_check(app, loop_id: str, state=None, log_fn=None) -> object:
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
    import re as _re

    chat = app._chat_log()

    # ── helpers locaux ────────────────────────────────────────────────
    base_dir = Path(__file__).resolve().parent
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
    def _count_errors(path) -> int:
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


async def propagate_patch(new_path: Path, vm, chat) -> bool:
    """
    Copie workspace/Nokido_vX.Y.py → Nokido.py (source protégé).
    Indispensable : le redémarrage relance Nokido.py, pas work_path.
    Valide la syntaxe ET les imports suspects avant de copier.
    Retourne True si la propagation a réussi.
    """
    import stat as _st
    import shutil as _sh
    import py_compile as _pyc
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


async def apply_suggestion(app, sugg: dict, _ask_restart: bool = True) -> bool:
    """Patch cumulatif — fichier complet, chaque apply = nouvelle version."""
    chat = app._chat_log()
    from app.core.settings import get_app_attr as _ga
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    version_manager = _actx().version_manager
    save_orchestrator = _ga("save_orchestrator", None)
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
        import stat as _stat
        import shutil as _shu

        _sp = version_manager.source_path
        _sp.chmod(_stat.S_IRUSR | _stat.S_IWUSR | _stat.S_IRGRP | _stat.S_IROTH)
        _shu.copy2(str(new_path), str(_sp))
        _sp.chmod(_stat.S_IRUSR | _stat.S_IRGRP | _stat.S_IROTH)
        _propagated = True
    except Exception as _pe:
        chat.write(f"[yellow]⚠ Non propagé : {_pe}[/]")
    _nv = version_manager.current_version
    app._refresh_version_display()
    chat.write(
        f"[green]✅ Suggestion {num} → [bold]v{_nv}[/] {'· propagé' if _propagated else '· workspace seulement'}[/]"
    )
    if _ask_restart:
        app._propose_restart(f"suggestion {num} → v{_nv}")
    return True
