# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_disco
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""forge_disco.py — Découverte de compétences web→RAG (v16.5)"""

import asyncio
from pathlib import Path
from rich.markup import escape
import logging

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
from app.core.settings import get_app_attr as _g  # centralisé
from app.forge_web import get_web_engine


async def handle_disco(app, cmd_line: str) -> object:
    # ── Découverte de compétences via web → RAG ─────────────────
    """Handle disco.

    Args:
        app: Description.
        cmd_line: Description.
    """
    from nokido_agent.app import forge_context as _fc_disco

    agentic_engine = _fc_disco.get_agentic_engine()
    rag_engine = _fc_disco.get_rag_engine()
    skill_arg = cmd_line[6:].strip()
    chat = app._chat_log()
    if not skill_arg:
        chat.write(
            "[bold]@disco[/] <compétence>  — découvre et ingère une compétence dans le RAG\n"
            "  [dim]Exemples :\n"
            "    @disco kubernetes helm\n"
            "    @disco python asyncio\n"
            "    @disco securite firewall nftables[/dim]"
        )
    else:
        # Extraire "via <proxy>" si présent
        _via_proxy = ""
        _disco_parts = skill_arg.split()
        if "via" in _disco_parts:
            _via_idx = _disco_parts.index("via")
            _via_proxy = _disco_parts[_via_idx + 1] if _via_idx + 1 < len(_disco_parts) else ""
            skill_arg = " ".join(_disco_parts[:_via_idx]).strip()
            from nokido_agent.app.forge_app_context import app_ctx as _actx

            _ac = _actx()
            agentic_engine = _ac.agentic_engine
            rag_engine = _ac.rag_engine
        _via_str = f" [dim]via proxy {_via_proxy}[/]" if _via_proxy else ""
        chat.write(f"[dim]🔍 Découverte : [bold]{escape(skill_arg)}[/]{_via_str}…[/]")

        async def _do_disco(_skill=skill_arg, _proxy_name=_via_proxy) -> object:
            """Do disco.

            Args:
                _skill: Description.
                _proxy_name: Description.
            """
            try:
                # ── 0. Score RAG avant ────────────────────────────
                score_before = 0.0
                if agentic_engine:
                    score_before = await agentic_engine.check_competence(_skill)
                    agentic_engine._ui(_skill, "searching")

                # ── 0b. Connaissance RAG déjà suffisante ? ────────
                _DISCO_THRESHOLD = 0.25  # ~10 chunks source-match suffisent
                _force = "--force" in _skill
                if _force:
                    _skill = _skill.replace("--force", "").strip()

                # ── Fallback manuel --file / --text ───────────────
                # @disco --file /path/to/doc.md keyword1 keyword2
                # @disco --text "contenu libre" keyword1 keyword2
                _manual_content = None
                _manual_source = None

                if _skill.startswith("--file "):
                    _parts = _skill[7:].strip().split(None, 1)
                    _fpath = Path(_parts[0])
                    _skill = _parts[1] if len(_parts) > 1 else _fpath.stem
                    if _fpath.exists():
                        _manual_content = _fpath.read_text(encoding="utf-8", errors="replace")
                        _manual_source = f"file:{_fpath.name}"
                        chat.write(f"[dim]📂 Ingestion manuelle: {_fpath.name} → '{_skill}'[/]")
                    else:
                        chat.write(f"[red]❌ Fichier introuvable: {_fpath}[/]")
                        return

                elif _skill.startswith("--text "):
                    _rest = _skill[7:].strip()
                    # Format: --text "contenu" mot-clef1 mot-clef2
                    # ou:     --text contenu mot-clef1
                    if _rest.startswith('"') or _rest.startswith("'"):
                        _q = _rest[0]
                        _end = _rest.find(_q, 1)
                        if _end > 0:
                            _manual_content = _rest[1:_end]
                            _skill = _rest[_end + 1 :].strip() or "manual_ingest"
                        else:
                            _manual_content = _rest[1:]
                            _skill = "manual_ingest"
                    else:
                        # Pas de guillemets — les 5 premiers mots = contenu, le reste = keyword
                        _words = _rest.split()
                        _manual_content = " ".join(_words[:10])
                        _skill = " ".join(_words[10:]) or " ".join(_words[:3])
                    _manual_source = f"manual:{_skill[:40]}"
                    chat.write(f"[dim]✍ Ingestion manuelle texte → '{_skill}'[/]")

                # Si contenu manuel fourni → bypass le web search
                if _manual_content and rag_engine:
                    import datetime as _dt_m

                    _now_m = _dt_m.datetime.utcnow().isoformat()
                    _rf_m = _DATA_DIR / "rag_files" / f"manual_{_skill.replace(' ', '_')}_{_now_m[:10]}.md"
                    try:
                        _rf_m.parent.mkdir(exist_ok=True)
                        _rf_m.write_text(
                            f"# Manual Ingest: {_skill}" + chr(10) + chr(10) + _manual_content, encoding="utf-8"
                        )
                    except Exception:
                        pass

                    _n = await rag_engine.ingest_web_content(
                        session_name=f"manual_{_skill.replace(' ', '_')}",
                        content=_manual_content,
                        skill=_skill,
                    )
                    # Anchor via unified_discovery pour tag + déduplication
                    try:
                        from nokido_agent.app.forge_unified_discovery import refine_and_anchor as _raa

                        _raa(
                            query=_skill,
                            raw_texts=[_manual_content],
                            collection="disco_manual",
                            sources=[_manual_source],
                        )
                    except Exception:
                        pass

                    chat.write(
                        f"[green]✅ Ingestion manuelle[/] : [bold]{escape(_skill)}[/] ({_n} chunk(s) vectorisé(s))"
                    )
                    if agentic_engine:
                        agentic_engine._ui(_skill, "mastered")
                    return  # Bypass le web search
                if score_before >= _DISCO_THRESHOLD and not _force:
                    # Infos bibliothèque
                    _lib_entry = {}
                    if agentic_engine:
                        try:
                            _lib_entry = agentic_engine.library_lookup(_skill)
                        except Exception:
                            pass
                    _existing = []
                    try:
                        _existing = await rag_engine.search(_skill, k=5)
                    except Exception:
                        pass
                    _sources = list(
                        {c.get("source", "?").split(".pdf")[0].split("/")[-1].split("\\")[-1] for c in _existing}
                    )[:4]
                    _niveau = _lib_entry.get("niveau", "")
                    _urls = _lib_entry.get("urls_canoniques", [])
                    _niv_str = f" · niveau=[bold]{_niveau}[/]" if _niveau else ""
                    _urls_str = f"\n  [dim]📚 Docs : {', '.join(_urls[:2])}[/]" if _urls else ""
                    chat.write(
                        f"[green]✅ Connaissance existante[/] sur [bold]{escape(_skill)}[/] "
                        f"(score={score_before:.2f}{_niv_str})\n"
                        f"  [dim]Sources : {chr(44).join(_sources) if _sources else 'RAG local'}[/]"
                        f"{_urls_str}\n"
                        f"  [dim]→ [bold]@disco {_skill} --force[/] pour enrichir quand même[/]"
                    )
                    if agentic_engine:
                        agentic_engine._ui(_skill, "mastered")
                    return

                # ── 1. Recherche web + extraction contenu ─────────
                results = []
                if _g("HAS_WEB_SEARCH", False):
                    # Proxy spécifique si "via <nom>" demandé
                    from nokido_agent.app.forge_web import _get_proxy_url

                    _active_proxy = _get_proxy_url(_proxy_name or "")
                    if _active_proxy:
                        chat.write(f"[dim]  ↳ Proxy actif : {_active_proxy}[/]")
                    # Queries courtes anglaises = meilleurs résultats DDG
                    _skill_en = (
                        _skill.replace("sécurité", "security").replace("réseau", "network").replace("système", "system")
                    )
                    _queries = [
                        f"{_skill_en} documentation",
                        f"{_skill_en} guide tutorial",
                    ]
                    raw_all = []
                    for _q in _queries:
                        chat.write(f"[dim]  ↳ DDG: {_q[:55]}…[/]")
                        _r = await get_web_engine().search(_q, max_results=4, fetch_full=True)
                        raw_all.extend(_r)
                    # Trier par score de qualité de domaine
                    try:
                        from nokido_agent.app.forge_web import _url_quality_score

                        def _score(r: str) -> int:
                            """Score.

                            Args:
                                r: Description.
                            """
                            url = r.split("\n")[-1] if "\n" in r else ""
                            return _url_quality_score(url)

                        raw_all.sort(key=_score, reverse=True)
                        # Exclure les résultats de domaines bloqués
                        raw_all = [r for r in raw_all if _score(r) >= 0]
                    except Exception:
                        pass
                    results = [r for r in raw_all if len(r) > 200]
                    chat.write(f"[dim]  ↳ {len(results)} résultat(s) qualifiés[/]")
                else:
                    chat.write(
                        "[yellow]⚠ Web search indisponible.[/]\n"
                        "  [dim]pip install duckduckgo-search trafilatura "
                        "--break-system-packages[/]"
                    )
                    return

                if not results:
                    chat.write(f"[yellow]⚠ Aucun résultat pour [bold]{escape(_skill)}[/][/]")
                    if agentic_engine:
                        agentic_engine._ui(_skill, "waiting")
                    return

                # ── 2. Notifier learning ──────────────────────────
                if agentic_engine:
                    agentic_engine._ui(_skill, "learning")

                # ── 3. Ingestion RAG via AgenticEngine._discover ──
                # Utiliser le pipeline complet d'AgenticEngine
                # (layer disco, UNVERIFIED, sauvegarde permanente)
                if agentic_engine:
                    # Injecter les résultats web directement
                    combined = "\n\n".join(r[:2000] for r in results[:3])
                    import datetime as _dt

                    now_iso = _dt.datetime.utcnow().isoformat()
                    doc_content = f"[DISCO] {_skill}\n{combined}"
                    # Pipeline complet : nettoyage + chunking + embed + persistance
                    if rag_engine:
                        # Sauvegarde permanente dans rag_files/
                        _rf = _DATA_DIR / "rag_files" / f"disco_{_skill.replace(' ', '_')}_{now_iso[:10]}.md"
                        try:
                            _rf.parent.mkdir(exist_ok=True)
                            _rf.write_text(f"# Disco: {_skill}\n\n{combined}", encoding="utf-8")
                        except Exception as _we:
                            logger.debug(f"disco write: {_we}")
                        # Ingestion via pipeline complet
                        n_chunks = await rag_engine.ingest_web_content(
                            session_name=f"disco_{_skill.replace(' ', '_')}",
                            content=combined,
                            skill=_skill,
                        )
                        chat.write(f"[dim]  ↳ {n_chunks} chunks vectorisés[/]")
                elif rag_engine:
                    # Fallback sans AgenticEngine
                    combined = "\n\n".join(r[:2000] for r in results[:3])
                    await rag_engine.ingest_web_content(
                        session_name=f"disco_{_skill.replace(' ', '_')}",
                        content=combined,
                        skill=_skill,
                    )

                # ── 4. Score RAG après ────────────────────────────
                score_after = 0.0
                if agentic_engine:
                    score_after = await agentic_engine.check_competence(_skill)
                    # Mettre à jour le SkillEntry
                    entry = agentic_engine._skills.setdefault(
                        _skill, __import__("forge_rag_engine", fromlist=["SkillEntry"]).SkillEntry(name=_skill)
                    )
                    entry.score = score_after
                    entry.status = "mastered" if score_after >= 0.7 else "learning"
                    entry.unverified = True
                    entry.uses += 1
                    agentic_engine._ui(_skill, entry.status)
                    agentic_engine._save_skills()

                # ── 5. Rapport final ──────────────────────────────
                delta = score_after - score_before
                delta_str = f"[green]+{delta:.2f}[/]" if delta > 0 else f"[dim]{delta:.2f}[/]"
                status_icon = "✅" if score_after >= 0.7 else "🧪"
                chat.write(
                    f"[green]{status_icon} @disco[/] [bold]{escape(_skill)}[/]\n"
                    f"  {len(results)} source(s) · "
                    f"score RAG : [dim]{score_before:.2f}[/] → "
                    f"[bold]{score_after:.2f}[/] ({delta_str}) · "
                    f"[dim]UNVERIFIED — s'améliore avec l'usage[/]"
                )
            except Exception as _e:
                logger.error(f"@disco {_skill}: {_e}")
                chat.write(f"[red]❌ @disco : {escape(str(_e))}[/]")

        asyncio.create_task(_do_disco())
