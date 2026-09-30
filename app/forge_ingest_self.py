"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_ingest_self.py — Auto-ingestion structurée du Kernel Nokido
===================================================================
Passe le RAG de "bibliothèque de docs Python" à "mémoire vive du système".

Niveaux de volatilité :
  Ring 0 — Code source réel (vérité terrain, rarement change)
  Ring 1 — Architecture & infra (change à chaque décision majeure)
  Ring 2 — Session memory (décisions validées, backlog, état courant)

Sécurité anti-boucle :
  - Exclut .db, .log, __pycache__, .onnx, sandbox, venv
  - Limite 4000 chars/chunk (sinon embedding dégradé)
  - Tag [DECISION_VALIDATED] pour les chunks importants

Usage :
  await force_self_ingestion(rag_engine)
  ou depuis la TUI : @evolve bootstrap
"""


import ast
import hashlib
import logging
import pathlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

# ── Racine projet ─────────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── Fichiers/dossiers exclus (anti-boucle infinie) ───────────────────────────
_IGNORE_SUFFIXES = {
    ".db",
    ".log",
    ".onnx",
    ".pkl",
    ".bin",
    ".npy",
    ".zip",
    ".gz",
    ".tar",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".sqlite",
    ".sqlite3",
    ".whl",
    ".egg-info",
}
_IGNORE_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    ".git",
    "node_modules",
    "sandbox",
    "cache",
    "RAG",
    "workspace",
    "backups",
    "logs",
    "models",
    ".lint_cache",
    "dist",
    "build",
}
_IGNORE_FILES = {"_tmp_lf.py", "Nokido_tmp.py", "Nokido.py"}  # trop gros

# ── Fichiers clés Ring 0 (code source critique, parse complet) ────────────────
_RING0_PRIORITY = [
    "forge_rag_engine.py",
    "forge_task_bus.py",
    "forge_orchestrator.py",
    "forge_nlu.py",
    "forge_mcp_security.py",
    "forge_integrity.py",
    "forge_prompt_guard.py",
    "forge_dispatch.py",
    "forge_agents.py",  # SmartRouter multi-providers
    "forge_collab_modes.py",  # _smart_ask + modes collab
    "forge_routing.py",  # facade SmartRouter
    "forge_runtime.py",
    "brain_worker.py",
    "forge_network.py",
    "forge_settings.py",
    "forge_ingest_self.py",  # s'auto-indexer
]

# ── Fichiers INFRA.md / SITUATION.md / décisions ─────────────────────────────
_RING1_FILES = [
    "SITUATION.md",
    "INFRA.md",
    "BACKLOG.md",
    "README.md",
    "Nokido.env",  # filtré des secrets
]

# Fichiers hors app/ à indexer en Ring0 (chemins relatifs depuis ROOT)
_RING0_EXTRA_PATHS = [
    "tools/nokido_mcp_server.py",  # MCP server v16.5 (tool llm, _rag_context_for)
]

CHUNK_MAX = 3500  # chars max par chunk


# Context:


def _safe_read(path: str) -> str:
    """Lit un fichier texte en ignorant les erreurs d'encodage.

    Args:
        path: Chemin du fichier  lire.

    Returns:
        Contenu du fichier en tant que chane, ou chane vide en cas d'erreur.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.read()
    except Exception as e:
        logging.error(f"Error reading file {path}: {e}")
        return ""


def _filter_env(content: str) -> str:
    """Supprime les secrets du .env avant ingestion."""
    SECRET_KEYS = {"TOKEN", "KEY", "SECRET", "PASS", "PWD", "PRIVATE", "API"}
    lines = []
    for line in content.splitlines():
        if any(s in line.upper() for s in SECRET_KEYS) and "=" in line:
            key = line.split("=")[0].strip()
            lines.append(f"{key}=<REDACTED>")
        else:
            lines.append(line)
    return "\n".join(lines)


def _chunk_code(filepath: str, content: str) -> list[tuple[str, str]]:
    """
    Découpe le code en chunks sémantiques.
    Chaque chunk est wrappé avec son contexte fichier pour que le LLM comprenne.
    Retourne [(chunk_id, text), ...]
    """
    chunks = []
    header = f"FORGE_SOURCE: {filepath}\n"

    # Essayer de parser les classes/fonctions pour des chunks plus fins
    try:
        tree = ast.parse(content)
        items = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef)):
                if hasattr(node, "lineno"):
                    items.append((node.lineno, node.end_lineno, type(node).__name__, node.name))
        items.sort()

        if items:
            lines = content.splitlines()
            for start, end, kind, name in items[:30]:  # max 30 fonctions/classe
                snippet = "\n".join(lines[start - 1 : min(end, start + 60)])
                text = f"{header}# {kind}: {name}\n{snippet}"[:CHUNK_MAX]
                cid = hashlib.md5(text.encode()).hexdigest()[:8]
                chunks.append((f"src:{filepath}:{name}:{cid}", text))
            return chunks
    except SyntaxError:
        pass

    # Fallback : découpe par blocs de CHUNK_MAX
    for i in range(0, len(content), CHUNK_MAX - len(header)):
        block = content[i : i + CHUNK_MAX - len(header)]
        text = header + block
        cid = hashlib.md5(text.encode()).hexdigest()[:8]
        chunks.append((f"src:{filepath}:blk{i // CHUNK_MAX}:{cid}", text))
    return chunks


def _generate_infra_manifest() -> str:
    """
    Génère INFRA.md à la volée si absent.
    Décrit l'architecture réelle du système.
    """
    manifest = f"""# INFRA Nokido — Manifeste Architecture
Généré : {datetime.now().isoformat(timespec="seconds")}

## Identité Système
- Nom : Nokido TUI v0.13.2
- Supercontrôleur souverain : Nokido
- Racine projet : {_ROOT}

## Stack Technique
- Python : miniforge3
- TUI : Textual 8.0.1
- LLM local : Ollama (qwen2.5-coder, deepseek-coder)
- Embeddings : bge-m3 via NPU/DirectML (Ryzen 8700G iGPU)
- MCP Server : tools/nokido_mcp_server.py (port 8765)
- Brain Worker : app/brain_worker.py (ZMQ port 5557)
- Base vectorielle : RAG/embeddings.db (SQLite WAL)

## Rings d'Intégrité
- Ring -1 : MASTER_OVERRIDE (TTL 5min)
- Ring  0 : Nokido (supercontrôleur)
- Ring  1 : Agents système (NR_runner, audit)
- Ring  2 : Agents DEV (Claude MCP avec token LF-)
- Ring  3 : Agents TRUSTED (Ollama local avec droits RAG)
- Ring  4 : Agents UNTRUSTED (cloud sans MCP = lecture seule)

## Règle d'Or
Un agent sans accès MCP validé (token LF-) ne peut pas proposer de patch.
Les modèles cloud (deepseek-cloud, gpt-oss) = interdit de patch.
Nokido émet les tokens LF- et reste souverain.

## Ports & Interfaces
- MCP HTTP  : 127.0.0.1:8765/mcp
- Brain ZMQ : tcp://127.0.0.1:5557
- Ollama    : http://localhost:11434

## Fichiers Critiques
- app/Nokido.py           : TUI principale (622 KB)
- app/forge_rag_engine.py : Moteur RAG (85 KB)
- app/forge_task_bus.py   : Bus tâches multi-agents
- app/forge_integrity.py  : Rings + tokens LF-
- tools/nokido_mcp_server.py : Serveur MCP (DEV mode actif)
- Nokido.env             : Configuration (LAFORGE_MCP_DEV=true)
"""
    # Écrire INFRA.md si absent
    infra_path = _ROOT / "INFRA.md"
    if not infra_path.exists():
        try:
            infra_path.write_text(manifest, encoding="utf-8")
            logger.info("[IngestSelf] INFRA.md généré")
        except Exception:
            pass
    return manifest


async def force_self_ingestion(
    rag_engine,
    log_fn: Optional[Callable[[str], None]] = None,
    include_source: bool = True,
    include_infra: bool = True,
    include_session: bool = True,
) -> dict:
    """
    Ingestion structurée en 3 rings.

    Args:
        rag_engine      : instance RAGEngine Nokido
        log_fn          : callback pour la TUI (chat.write)
        include_source  : Ring 0 — code source
        include_infra   : Ring 1 — architecture & infra
        include_session : Ring 2 — session memory & décisions

    Returns:
        {"chunks": int, "sources": int, "errors": int, "duration_s": float}
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    import time

    t0 = time.monotonic()

    def _log(msg: str) -> None:
        """log."""
        if log_fn:
            log_fn(msg)
        logger.info(msg.replace("[", "").replace("]", ""))

    stats = {"chunks": 0, "sources": 0, "errors": 0}

    _log("[bold #58a6ff]🧠 Auto-ingestion Kernel Nokido[/bold #58a6ff]")

    # ══════════════════════════════════════════════════════════════
    # RING 1 — Architecture & Infra (priorité absolue, pinné)
    # ══════════════════════════════════════════════════════════════
    if include_infra:
        _log("  [dim]Ring 1 — Architecture & Infra...[/dim]")

        # INFRA.md (généré si absent)
        infra_text = _generate_infra_manifest()
        try:
            await rag_engine.add_session_message(
                "INFRA_MANIFEST", "architecture", f"[PINNED][DECISION_VALIDATED] {infra_text}"
            )
            stats["chunks"] += 1
            stats["sources"] += 1
            _log("  [green]✓[/green] INFRA_MANIFEST (architecture)")
        except Exception as e:
            stats["errors"] += 1
            _log(f"  [red]✗ INFRA: {e}[/red]")

        # SITUATION.md
        sit_path = _ROOT / "SITUATION.md"
        if sit_path.exists():
            sit_text = _safe_read(sit_path)[:4000]
            try:
                await rag_engine.add_session_message(
                    "SITUATION_COURANTE", "projet", f"[PINNED] SITUATION INTER-SESSIONS:\n{sit_text}"
                )
                stats["chunks"] += 1
                stats["sources"] += 1
                _log("  [green]✓[/green] SITUATION.md")
            except Exception as e:
                stats["errors"] += 1

        # Nokido.env (sans secrets)
        env_path = _ROOT / "Nokido.env"
        if env_path.exists():
            env_safe = _filter_env(_safe_read(env_path))[:2000]
            try:
                await rag_engine.add_session_message(
                    "CONFIG_ENV", "configuration", f"[CONFIG Nokido.env — secrets redacted]\n{env_safe}"
                )
                stats["chunks"] += 1
                stats["sources"] += 1
                _log("  [green]✓[/green] Nokido.env (secrets filtrés)")
            except Exception as e:
                stats["errors"] += 1

    # ══════════════════════════════════════════════════════════════
    # RING 0 — Code source (vérité terrain)
    # ══════════════════════════════════════════════════════════════
    if include_source:
        _log("  [dim]Ring 0 — Code source prioritaire...[/dim]")
        app_dir = _ROOT / "app"

        # Priorité 1 : fichiers clés
        for fname in _RING0_PRIORITY:
            fpath = app_dir / fname
            if not fpath.exists():
                continue
            content = _safe_read(fpath)
            if not content.strip():
                continue
            chunks = _chunk_code(fname, content)
            ok = 0
            for cid, text in chunks[:15]:  # max 15 chunks par fichier
                try:
                    await rag_engine.add_session_message(cid, "code_source", text)
                    ok += 1
                    stats["chunks"] += 1
                except Exception:
                    stats["errors"] += 1
            if ok:
                _log(f"  [green]✓[/green] {fname} ({ok} chunks)")
                stats["sources"] += 1

        # Priorité 1b : fichiers hors app/ (tools/, etc.)
        for rel_path in _RING0_EXTRA_PATHS:
            fpath = _ROOT / rel_path
            if not fpath.exists():
                continue
            content = _safe_read(fpath)
            if not content.strip():
                continue
            chunks = _chunk_code(fpath.name, content)
            ok = 0
            for cid, text in chunks[:10]:  # max 10 chunks
                try:
                    await rag_engine.add_session_message(cid, "code_source", text)
                    ok += 1
                    stats["chunks"] += 1
                except Exception:
                    stats["errors"] += 1
            if ok:
                _log(f"  [green]✓[/green] {rel_path} ({ok} chunks)")
                stats["sources"] += 1

        # Priorité 2 : autres modules forge_*.py (stub — juste les signatures)
        _log("  [dim]Ring 0 — Modules secondaires (signatures)...[/dim]")
        for fpath in sorted(app_dir.glob("forge_*.py")):
            if fpath.name in _IGNORE_FILES or fpath.name in _RING0_PRIORITY:
                continue
            if fpath.stat().st_size > 200_000:  # skip > 200KB
                continue
            content = _safe_read(fpath)
            # Extraire seulement les signatures (docstrings + def)
            try:
                tree = ast.parse(content)
                sigs = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        doc = ast.get_docstring(node) or ""
                        sig = f"# {type(node).__name__}: {node.name}"
                        if doc:
                            sig += f'\n  """{doc[:120]}"""'
                        sigs.append(sig)
                if sigs:
                    text = f"FORGE_SOURCE: {fpath.name}\n# Signatures & docstrings\n" + "\n".join(sigs[:40])
                    text = text[:CHUNK_MAX]
                    cid = f"sig:{fpath.name}:{hashlib.md5(text.encode()).hexdigest()[:6]}"
                    await rag_engine.add_session_message(cid, "code_source", text)
                    stats["chunks"] += 1
                    stats["sources"] += 1
            except Exception:
                stats["errors"] += 1

    # ══════════════════════════════════════════════════════════════
    # RING 2 — Session memory (décisions, backlog, état)
    # ══════════════════════════════════════════════════════════════
    if include_session:
        _log("  [dim]Ring 2 — Session memory...[/dim]")

        # Backlog
        for bl_name in ["BACKLOG.md", "backlog_bugs.json", "backlog.md"]:
            bl_path = _ROOT / bl_name
            if bl_path.exists():
                bl_text = _safe_read(bl_path)[:3000]
                try:
                    await rag_engine.add_session_message("BACKLOG_ACTUEL", "debug", f"[BACKLOG BUGS & PERF]\n{bl_text}")
                    stats["chunks"] += 1
                    stats["sources"] += 1
                    _log(f"  [green]✓[/green] {bl_name}")
                    break
                except Exception:
                    stats["errors"] += 1

        # WMI pending — chunks en attente d'embedding (déposés par CLAUDE inter-session)
        wmi_path = _ROOT / "data" / "wmi_pending.json"
        if wmi_path.exists():
            try:
                import json as _json

                wmi_items = _json.loads(wmi_path.read_text(encoding="utf-8"))
                wmi_ok = 0
                for item in wmi_items:
                    text = item.get("text", "").strip()
                    source = item.get("source", "wmi")
                    domain = item.get("domain", "general")
                    if not text:
                        continue
                    cid = f"wmi:{source}:{hashlib.md5(text[:80].encode()).hexdigest()[:8]}"
                    try:
                        await rag_engine.add_session_message(cid, domain, f"[WMI:{source}] {text}")
                        wmi_ok += 1
                        stats["chunks"] += 1
                    except Exception:
                        stats["errors"] += 1
                if wmi_ok:
                    _log(f"  [green]✓[/green] WMI pending: {wmi_ok} chunks ({wmi_path.name})")
                    # Archive le fichier traité
                    wmi_path.rename(wmi_path.with_suffix(".processed.json"))
                    stats["sources"] += 1
            except Exception as _we:
                _log(f"  [yellow]⚠[/yellow] WMI pending: {_we}")
                stats["errors"] += 1

        # Décisions architecturales déjà dans le RAG — les re-pincer
        try:
            decisions = await rag_engine.search("decision architecturale Nokido", k=8)
            if decisions:
                combined = "\n\n".join(f"[DECISION_VALIDATED] {d.get('content', '')[:400]}" for d in decisions)
                await rag_engine.add_session_message(
                    "DECISIONS_SESSION", "architecture", f"[PINNED] DECISIONS ARCHITECTURALES VALIDÉES:\n{combined}"
                )
                stats["chunks"] += 1
                _log(f"  [green]✓[/green] {len(decisions)} décisions architecturales pinnées")
        except Exception as e:
            stats["errors"] += 1

    # ── Cartes RAG évolutives ─────────────────────────────────────────────────
    try:
        import json as _jrag

        _rag_index = ROOT / "shadow_mutation" / "rag_index"
        if _rag_index.exists():
            _cards = list(_rag_index.glob("*.json"))
            _texts = []
            for _card_path in _cards:
                _card = _jrag.loads(_card_path.read_text(encoding="utf-8"))
                _txt = (
                    f"[RAG_CARD] {_card.get('module', '?')} | "
                    f"score={_card.get('fitness_score', '?')} | "
                    f"integrity={_card.get('integrity_level', '?')} | "
                    f"agent={_card.get('last_mutation_agent', '?')} | "
                    f"audit={_card.get('last_audit', '?')[:10]} | "
                    f"classes={_card.get('classes', [])} | "
                    f"tags={_card.get('rag_tags', [])} | "
                    f"critical={_card.get('critical_components', [])}"
                )
                _texts.append({"text": _txt, "source": f"rag_card:{_card.get('file', '?')}"})
            if _texts:
                await rag_engine.ingest_batch(_texts)
                stats["chunks"] += len(_texts)
                _log(f"  [green]✓[/green] {len(_texts)} cartes RAG évolutives indexées")
    except Exception as _e:
        stats["errors"] += 1

    # ── Performance history ────────────────────────────────────────────────────
    try:
        import json as _jph

        _ph_path = ROOT / "shadow_mutation" / "performance_history.json"
        if _ph_path.exists():
            _ph = _jph.loads(_ph_path.read_text(encoding="utf-8"))
            _ph_lines = []
            for _pk, _pv in list(_ph.items())[:50]:  # top 50
                _target, _agent = _pk.split("::", 1) if "::" in _pk else (_pk, "?")
                _ph_lines.append(
                    f"[MUTATION_HISTORY] {_target} via {_agent} | "
                    f"ok={_pv.get('ok', 0)} fail={_pv.get('fail', 0)} "
                    f"last_ms={_pv.get('last_ms', 0)}"
                )
            if _ph_lines:
                _sep = chr(10)
                await rag_engine.ingest_text(_sep.join(_ph_lines), source="performance_history")
                stats["chunks"] += 1
                _log(f"  [green]✓[/green] performance_history indexé ({len(_ph)} entrées)")
    except Exception as _e:
        stats["errors"] += 1

    # ── Résumé ────────────────────────────────────────────────────────────────
    duration = round(time.monotonic() - t0, 1)
    summary = (
        f"[bold green]✅ Auto-ingestion terminée[/bold green]\n"
        f"  {stats['sources']} sources · "
        f"{stats['chunks']} chunks · "
        f"{stats['errors']} erreurs · "
        f"{duration}s\n"
        f"  [dim]RAG connait maintenant son Kernel.[/dim]"
    )
    _log(summary)
    stats["duration_s"] = duration
    return stats
