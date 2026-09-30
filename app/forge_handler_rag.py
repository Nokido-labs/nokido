# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_handler_rag
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_handler_rag.py — Handlers RAG/knowledge base
===================================================
Extrait de forge_handlers.py — Phase 3 refactor.
Importez depuis ce module plutôt que forge_handlers pour ce domaine.
"""

import asyncio
import logging
from pathlib import Path
from app.core.settings import get_app_attr as _g  # noqa — requis par handlers
from app.forge_ollama import ollama_call

logger = logging.getLogger("Nokido.Forge.Handler.Rag")


async def _handle_rag(app, args: str) -> None:
    """Handle rag.

    Args:
        app: Description.
        args: Description.
    """
    import logging as _lg

    _lg.getLogger("Nokido.Commands").info(">>> CIBLE ATTEINTE _handle_rag args=%r", args)
    """
    chat = app._chat_log()
    @rag                       — aide
    @rag info                  — stats (chunks, taille fichier, sources)
    @rag size                  — taille détaillée par source
    @rag list                  — liste des documents indexés
    @rag reindex               — réindexer les nouveaux fichiers + retirer supprimés
    @rag del <source>          — supprimer les chunks d'une source
    @rag purge session         — vider les chunks de conversation
    @rag purge all             — vider TOUT le RAG (irréversible)
    @rag build                 — reconstruire index FAISS+BM25
    @rag download <chemin>     — indexer un fichier
    """
    chat = app._chat_log()
    parts = args.split()
    if not parts:
        chat.write(
            "[bold #58a6ff]@rag[/] — Gestion de la base de connaissances :\n"
            "  [bold]info[/]              stats · [bold]size[/]       taille par source\n"
            "  [bold]list[/]              documents indexés\n"
            "  [bold]reindex[/]           rescan + retire fichiers supprimés\n"
            "  [bold]del[/] [dim]<source>[/]     supprime une source\n"
            "  [bold]purge session[/]     vide l'historique de conversation\n"
            "  [bold]purge all[/]         [red]vide tout le RAG[/]\n"
            "  [bold]build[/]             reconstruit FAISS+BM25\n"
            "  [bold]download[/] [dim]<path>[/]  indexe un fichier\n"
            "  [bold]drop[/] [dim]<fichier|URL>[/] [bold #f7c948]⚡ FAST-TRACK[/] ring=TRUSTED, prio=0\n"
            "  [bold]trust[/]             alias de drop"
        )
        return

    sub = parts[0].lower()

    # Cherche rag_engine sur app (TUI) puis globals Nokido
    from nokido_agent.app import forge_context as _fc

    _re = _fc.rag_engine

    if sub == "info" and _re is not None:
        import os as _os

        _emb_size = 0
        try:
            _emb_size = _os.path.getsize(_re.emb_file) // 1024
        except Exception:
            pass
        _sources = {}
        for c in _re.chunks:
            src = c.get("source", "?").split(":")[0]
            _sources[src] = _sources.get(src, 0) + 1
        _src_summary = " · ".join(f"{k}:{v}" for k, v in sorted(_sources.items()))
        # DB active + version — source de vérité
        try:
            from nokido_agent.app.forge_rag_engine import _EMBEDDINGS_DB as _edb

            _db_label = f"[bold #3fb950]{_edb.parent.name}/{_edb.name}[/]"
            _db_size = f"{_edb.stat().st_size // 1024}KB" if _edb.exists() else "?"
        except Exception:
            _db_label, _db_size = "[dim]?[/]", "?"
        try:
            from nokido_agent.app.forge_version import full_label as _fvfl

            _ver_label = _fvfl()
        except Exception:
            _ver_label = "?"
        chat.write(
            f"[bold]RAG[/] [bold]{len(_re.chunks)}[/] chunks mémoire · "
            f"[dim]{_emb_size} Ko[/] rag_files · "
            f"FAISS={'[green]✓[/]' if _re.faiss_index else '[red]✗[/]'} · "
            f"BM25={'[green]✓[/]' if _re.bm25_index else '[red]✗[/]'}\n"
            f"  DB active : {_db_label} ({_db_size})\n"
            f"  Version   : [dim]{_ver_label}[/]\n"
            f"  Sources   : [dim]{_src_summary or 'aucune'}[/]"
        )
    elif sub == "size" and _re is not None:
        import os as _os

        _by_src: dict = {}
        _by_dom: dict = {}
        _by_role: dict = {}
        for _c in _re.chunks:
            _s = _c.get("source", "?")
            _d = _c.get("domain", "?")
            _r = _c.get("role_hint", "?")
            _by_src[_s] = _by_src.get(_s, 0) + 1
            _by_dom[_d] = _by_dom.get(_d, 0) + 1
            _by_role[_r] = _by_role.get(_r, 0) + 1
        if not _by_src:
            chat.write("[dim]RAG vide[/]")
        else:
            chat.write(f"[bold]RAG — {len(_re.chunks)} chunks :[/]")
            for _s, _cnt in sorted(_by_src.items(), key=lambda x: -x[1])[:12]:
                bar = "█" * min(_cnt // 5, 25)
                chat.write(f"  [dim]{_s[:42]:<42}[/] [cyan]{_cnt:>4}[/] {bar}")
            _dcol = {
                "reseau": "#79c0ff",
                "securite": "#ff7b72",
                "devops": "#d2a8ff",
                "code": "#f0883e",
                "ia": "#3fb950",
                "systeme": "#8b949e",
            }
            dom_ln = "  ".join(
                f"[{_dcol.get(_d, 'white')}]{_d}[/]:{_n}" for _d, _n in sorted(_by_dom.items(), key=lambda x: -x[1])
            )
            chat.write(f"  [dim]Domaines :[/]  {dom_ln}")
            rcol = {"action": "#f0883e", "rag": "#3fb950", "chat": "#58a6ff"}
            role_ln = "  ".join(
                f"[{rcol.get(_r, 'white')}]{_r}[/]:{_n}" for _r, _n in sorted(_by_role.items(), key=lambda x: -x[1])
            )
            chat.write(f"  [dim]Role hints :[/] {role_ln}")
        try:
            _sz = _os.path.getsize(_re.emb_file)
            chat.write(f"  [dim]embeddings.json : {_sz // 1024} Ko[/]")
        except Exception:
            pass

    elif sub == "list" and _re is not None:
        sources = sorted(set(c.get("source", "?") for c in _re.chunks))
        if not sources:
            chat.write("[dim]RAG vide[/]")
        else:
            chat.write(f"[bold]{len(sources)}[/] source(s) indexée(s) :")
            for s in sources:
                cnt = sum(1 for c in _re.chunks if c.get("source") == s)
                chat.write(f"  [dim]{s}[/] — {cnt} chunk(s)")

    elif sub == "reindex" and _re is not None:
        chat.write("[dim]⏳ Réindexation RAG en cours…[/]")
        app.role_panel.set_rag(True)

        async def _do_reindex() -> None:
            """Do reindex."""
            try:
                before = len(_re.chunks)
                await _re.index_pending()
                after = len(_re.chunks)
                diff = after - before
                chat.write(
                    f"[green]✅ Réindexation terminée[/] ({'[green]+' if diff >= 0 else '[red]'}{diff}[/] chunks)"
                )
            except Exception as re_err:
                chat.write(f"[red]❌ Reindex: {re_err}[/]")
            finally:
                await asyncio.sleep(3)
                app.role_panel.reset()

        asyncio.create_task(_do_reindex())

    elif sub == "del" and _re is not None:
        if len(parts) < 2:
            chat.write("[yellow]⚠ Usage : @rag del <source>[/]  (voir @rag list)")
            return
        target = " ".join(parts[1:])
        # ── Double confirmation obligatoire ───────────────────────────
        _pkey = f"del:{target}"
        if app._rag_pending_confirm.get("key") == _pkey:
            # 2e frappe → exécution réelle
            app._rag_pending_confirm = {}
            before = len(_re.chunks)
            _re.chunks = [c for c in _re.chunks if c.get("source", "") != target and target not in c.get("source", "")]
            removed = before - len(_re.chunks)
            if removed:
                _re._save_embeddings()
                _re.faiss_index = _re.bm25_index = None
                chat.write(f"[green]✅ {removed} chunk(s) supprimés[/] (source: [dim]{target}[/])")
                if target in _re.indexed:
                    del _re.indexed[target]
                    _re._save_json(_re.indexed_file, _re.indexed)
            else:
                chat.write(f"[yellow]⚠ Source '[dim]{target}[/]' non trouvée[/]")
        else:
            # 1re frappe → demander confirmation
            affected = sum(1 for c in _re.chunks if c.get("source", "") == target or target in c.get("source", ""))
            app._rag_pending_confirm = {"key": _pkey}
            chat.write(
                f"[bold yellow]⚠ Confirmer suppression ?[/]\n"
                f"  Source : [bold]{target}[/]  ·  {affected} chunk(s) concerné(s)\n"
                f"  [dim]→ Retapez [bold]@rag del {target}[/] pour confirmer,\n"
                f"    ou toute autre commande pour annuler.[/]"
            )

    elif sub == "purge" and _re is not None:
        mode = parts[1].lower() if len(parts) > 1 else ""
        if mode == "session":
            before = len(_re.chunks)
            _re.chunks = [
                c
                for c in _re.chunks
                if not c.get("source", "").startswith("session:")
                and not c.get("source", "").startswith("exchange_history")
            ]
            removed = before - len(_re.chunks)
            _re._save_embeddings()
            _re.faiss_index = _re.bm25_index = None
            chat.write(f"[green]✅ Session purgée[/] — {removed} chunk(s) supprimés")
        elif mode == "all":
            # ── Double confirmation obligatoire ───────────────────────
            if app._rag_pending_confirm.get("key") == "purge:all":
                app._rag_pending_confirm = {}
                # ── PRE-FLIGHT : cold backup avant purge destructive ───────────────
                try:
                    from nokido_agent.app.forge_snapshot import cold_backup, preflight_check, PreFlightError

                    preflight_check("knowledge")
                    _bk = cold_backup(mode="knowledge", label="pre_purge_all", read_only=True, caller="tui")
                    chat.write(f"[dim]🧊 Cold backup : {_bk['timestamp']} sha={_bk['sha256'][:12]}...[/]")
                except PreFlightError as _pfe:
                    chat.write(f"[bold red]❌ Purge annulée :[/] {_pfe}")
                    return
                except Exception as _bke:
                    chat.write(f"[yellow]⚠ Backup partiel : {_bke}[/]")
                # ── Purge effective ───────────────────────────────────────────────
                n_chunks = len(_re.chunks)
                n_files = len(_re.indexed)
                _re.chunks.clear()
                _re.indexed.clear()
                _re.faiss_index = None
                _re.bm25_index = None
                _re._save_embeddings()
                _re._save_json(_re.indexed_file, {})
                chat.write(f"[bold red]🗑 RAG entièrement vidé[/] [dim]({n_chunks} chunks · {n_files} fichier(s))[/]")
            else:
                app._rag_pending_confirm = {"key": "purge:all"}
                chat.write(
                    "[bold red]⚠⚠ ATTENTION — Suppression irréversible[/]\n"
                    f"  Contenu : [bold]{len(_re.chunks)} chunks[/] "
                    f"· [bold]{len(_re.indexed)} fichier(s) indexé(s)[/]\n"
                    "  [dim]→ Retapez [bold]@rag purge all[/] pour confirmer définitivement.\n"
                    "    Toute autre commande annule l'opération.[/]"
                )
        else:
            chat.write("[yellow]⚠ Usage : @rag purge session | @rag purge all[/]")

    elif sub in ("paranoid", "zero-context"):
        """@rag paranoid [on|off] — Zero-Context : aucun contexte RAG envoyé aux LLM cloud."""
        state = parts[1].lower() if len(parts) > 1 else "on"
        enabled = state != "off"
        try:
            from nokido_agent.app.forge_conv_sanitizer import set_paranoid_mode

            session = getattr(getattr(app, "context", None), "session_id", None) or getattr(app, "session_name", "")
            set_paranoid_mode(session, enabled)
            icon = "🔒" if enabled else "🔓"
            chat.write(
                f"{icon} [bold {'red' if enabled else 'green'}]"
                f"Mode {'Paranoïaque ACTIVÉ' if enabled else 'Normal'}[/] — "
                f"{'Aucun contexte RAG ne quitte le bunker.' if enabled else 'Contexte filtré DLP.'}"
            )
        except Exception as _pe:
            chat.write(f"[red]❌ paranoid: {_pe}[/]")

    elif sub in ("dev", "dev-mode"):
        """
        @rag dev [on|off|status] — Bascule LAFORGE_ENV=dev|prod.
        Persistance dans Nokido.env + rechargement os.environ à chaud.
        NON exposé via MCP (géré uniquement par la TUI ou Nokido.env).
        """
        state = parts[1].lower() if len(parts) > 1 else "status"
        env_path = Path(__file__).resolve().parent.parent / "Nokido.env"

        if state == "status":
            import os

            current = os.environ.get("LAFORGE_ENV", "prod")
            # Lire aussi depuis le fichier
            try:
                for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip().startswith("LAFORGE_ENV"):
                        current = line.split("=", 1)[-1].strip()
                        break
            except Exception:
                pass
            icon = "🟢" if current == "dev" else "🔴"
            chat.write(
                f"{icon} Mode actuel : [bold]{current.upper()}[/]\n"
                f"  [dim]dev  → logging LLM activé, @chat disponible, shared_prompt_log alimenté[/]\n"
                f"  [dim]prod → silence total, zéro log LLM sortant[/]"
            )
            return

        enabled = state in ("on", "dev", "1", "true")
        new_val = "dev" if enabled else "prod"

        # 1. Rechargement à chaud dans os.environ
        import os

        os.environ["LAFORGE_ENV"] = new_val

        # 2. Persistance dans Nokido.env
        try:
            env_text = env_path.read_text(encoding="utf-8", errors="ignore")
            if "LAFORGE_ENV" in env_text:
                # Remplacer la ligne existante
                new_lines = []
                for line in env_text.splitlines():
                    if line.strip().startswith("LAFORGE_ENV"):
                        new_lines.append(f"LAFORGE_ENV={new_val}")
                    else:
                        new_lines.append(line)
                env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                env_path.write_text(env_text.rstrip() + f"\nLAFORGE_ENV={new_val}\n", encoding="utf-8")
            persist_ok = True
        except Exception as _ep:
            persist_ok = False
            chat.write(f"[yellow]⚠ Nokido.env non mis à jour : {_ep}[/]")

        # 3. Invalider le cache _is_dev_mode dans forge_collab_modes
        try:
            pass
            # _is_dev_mode() lit os.environ à chaque appel — pas de cache
        except Exception:
            pass

        icon = "🟢" if enabled else "🔴"
        persist_tag = " [dim](persisté Nokido.env)[/]" if persist_ok else " [dim](en mémoire seulement)[/]"
        chat.write(
            f"{icon} [bold {'green' if enabled else 'yellow'}]"
            f"Mode {new_val.upper()} activé[/]{persist_tag}\n"
            + (
                "  [dim]• @chat disponible\n"
                "  • Logs LLM → shared_prompt_log (is_private=0)\n"
                "  • Fail-Safe actif : secrets → is_private=1 forcé[/]"
                if enabled
                else "  [dim]• Silence total — zéro log LLM sortant\n  • @chat toujours disponible (Ollama local)[/]"
            )
        )

    elif sub == "build" and _re is not None:
        _re.build_faiss()
        _re.build_bm25()
        chat.write("[green]✅ Index FAISS+BM25 reconstruit[/]")

        # Promotion CoVe des drafts en arriere-plan
        async def _promote_drafts() -> None:
            """Promote drafts."""
            try:
                from nokido_agent.app.forge_rag_truth import batch_promote_draft as _bpd

                stats = _bpd(validator_id="system:nr_runner", validator_ring=0)
                n = stats.get("promoted", 0)
                if n:
                    chat.write(f"[dim]  └ CoVe : {n} chunk(s) promu(s) draft→verified[/]")
            except Exception as _e:
                pass

        asyncio.create_task(_promote_drafts())
        app.rag_info.sync()

    elif sub in ("drop", "trust") and _re is not None:
        """
        @rag drop <fichier|URL>  — Fast-track Ring 2 (TRUSTED), prio=0
        @rag trust <fichier|URL> — alias, même comportement
        L'humain est le validateur. CoVe skippé. Indexé en < 2s.
        """
        if len(parts) < 2:
            chat.write(
                "[bold #58a6ff]@rag drop[/] [dim]<fichier|URL>[/]\n"
                "  Ingestion [bold]prioritaire[/] ring=TRUSTED, prio=0 (FLASH)\n"
                "  L'humain valide → CoVe skippé → disponible immédiatement\n"
                "  Ex : @rag drop rapport.pdf\n"
                "       @rag drop https://docs.python.org/fr/3/"
            )
            return
        target = " ".join(parts[1:]).strip()

        async def _do_drop(_t=target) -> None:
            """Do drop.

            Args:
                _t: Description.
            """
            try:
                # ── PRE-FLIGHT : vérifier espace disque avant ingestion ──────────
                try:
                    from nokido_agent.app.forge_snapshot import preflight_check, PreFlightError

                    preflight_check("knowledge")
                except PreFlightError as _pfe:
                    chat.write(f"[bold red]❌ Drop annulé :[/] {_pfe}")
                    return
                except Exception:
                    pass  # preflight non bloquant pour drop
                from nokido_agent.app.forge_hot_ingest import hot_ingest_file, hot_ingest_url

                if _t.startswith(("http://", "https://")):
                    result = await hot_ingest_url(_t, _re, log_fn=chat.write, provenance="tui_drop")
                else:
                    _fp = Path(_t)
                    if not _fp.is_absolute():
                        # Chercher dans rag_dir si pas de chemin absolu
                        _rd = Path(str(getattr(getattr(_re, "rag_dir", None), "__str__", lambda: "data/rag_files")()))
                        if (_rd / _fp.name).exists():
                            _fp = _rd / _fp.name
                    result = await hot_ingest_file(_fp, _re, log_fn=chat.write, provenance="tui_drop")
                if result["ok"]:
                    _re.faiss_index = _re.bm25_index = None
                    _re.build_faiss()
                    _re.build_bm25()
                    app.rag_info.sync()
                    chat.write(
                        f"[bold green]⚡ Fast-track OK[/] — "
                        f"{result['chunks']} chunks · ring=TRUSTED · "
                        f"trust={result['trust']:.1f} · [bold]disponible[/]"
                    )
                else:
                    chat.write(f"[red]❌ Drop échoué :[/] {result['msg']}")
            except Exception as _de:
                chat.write(f"[red]❌ hot_ingest: {_de}[/]")

        asyncio.create_task(_do_drop())

    elif sub == "download" and len(parts) >= 2 and _re is not None:
        _do_del = "--delete" in parts
        _fparts = [p for p in parts[1:] if p != "--delete"]
        fpath = Path(" ".join(_fparts))
        _note = " [dim](supprimé après)[/]" if _do_del else ""
        chat.write(f"[dim]⏳ Indexation [bold]{fpath.name}[/]{_note}…[/]")

        async def do_dl(_fp=fpath, _del=_do_del) -> None:
            """Do dl.

            Args:
                _fp: Description.
                _del: Description.
            """
            ok = await _re.add_document(_fp, delete_after=_del)
            chat.write(
                f"[green]✅ Indexé: {_fp.name}{'  [dim](supprimé)[/]' if _del and ok else ''}[/]"
                if ok
                else f"[red]❌ Échec: {_fp.name}[/]"
            )
            app.rag_info.sync()

        asyncio.create_task(do_dl())

    else:
        chat.write("[yellow]⚠ Sous-commande inconnue — @rag pour l'aide[/]")


async def _validate_suggestion_async(
    app,
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
    for pattern, reason in app._DANGER_PATTERNS:
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
        available = getattr(app, "_available_models", [])
        reviewer = next(
            (m for p in _review_pref for m in available if p in m.lower()),
            app.model_rag,
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
