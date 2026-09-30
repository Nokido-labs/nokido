"""
app/forge_handler_evolve.py — Handler @evolve pour Nokido TUI
===============================================================
Interface directe avec le Siloed Reasoning Engine.

Commandes :
  @evolve <intention>              → pipeline complet auto
  @evolve <intention> --fast       → mode rapide (modèles 1.5b)
  @evolve <intention> --noise      → bruit sémantique activé
  @evolve <intention> --domains code,security
  @evolve status                   → état des modèles locaux
  @evolve rag <query>              → requête RAG sur les évolutions passées

Exemples :
  @evolve Scanner localhost/24 et exploiter les vulnérabilités SMB
  @evolve Refactoriser forge_dispatch.py --domains code,doc --fast
  @evolve Architecturer un fallback MSF → Impacket intelligent
"""

from __future__ import annotations

# DEAD_IMPORT removed: import asyncio
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_engine():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from nokido_agent.app.forge_silo_engine import get_silo_engine

    return get_silo_engine()


async def handle_evolve(app, args: str) -> None:
    """Handler @evolve — Siloed Reasoning Engine."""
    chat = app._chat_log()
    raw = args.strip()

    # ── @evolve status ────────────────────────────────────────────────────────
    if raw in ("status", ""):
        await _show_status(chat)
        return

    # ── @evolve rag <query> ───────────────────────────────────────────────────
    if raw.lower().startswith("rag "):
        query = raw[4:].strip()
        await _rag_query(chat, query)
        return

    # ── Parse flags ───────────────────────────────────────────────────────────
    fast = "--fast" in raw
    noise = "--noise" in raw
    domains = None

    # Extrait --domains code,security
    import re

    dm = re.search(r"--domains\s+([\w,]+)", raw)
    if dm:
        domains = [d.strip() for d in dm.group(1).split(",")]

    # Nettoie l'intention
    intention = re.sub(r"--fast|--noise|--domains\s+[\w,]+", "", raw).strip()

    if not intention:
        chat.write("[yellow]Usage: @evolve <intention> [--fast] [--noise] [--domains d1,d2][/]")
        return

    # ── Lance le pipeline ─────────────────────────────────────────────────────
    flags = []
    if fast:
        flags.append("⚡ FAST")
    if noise:
        flags.append("🔀 NOISE")
    if domains:
        flags.append(f"📌 {','.join(domains)}")
    flag_str = " | ".join(flags) if flags else "AUTO"

    chat.write(f"[bold red]🧠 EVOLVE[/] [dim]{flag_str}[/]\n[dim]{intention[:80]}[/]")

    engine = _get_engine()

    # Importe les domaines si fournis
    hint_domains = None
    if domains:
        from nokido_agent.app.forge_silo_engine import SiloDomain

        hint_domains = [d for d in SiloDomain if d.value in domains]

    t0 = time.time()
    silo_count = [0]

    def on_silo_done(silo):
        silo_count[0] += 1
        icon = {
            "code": "💻",
            "security": "🔒",
            "recon": "🔍",
            "exploit": "⚡",
            "strategy": "🗺",
            "synthesis": "📋",
            "doc": "📝",
        }.get(silo.domain.value, "●")
        chat.write(
            f"  {icon} [bold]{silo.domain.value.upper()}[/] "
            f"[dim]{silo.model.split(':')[0]}[/] "
            f"[green]{silo.duration}s[/] [dim]{silo.tokens_out}tok[/]"
        )
        # Affiche un extrait si pertinent
        if silo.output and len(silo.output) > 20:
            preview = silo.output[:120].replace("\n", " ")
            chat.write(f"    [dim]{preview}...[/]")

    def on_progress(step, msg):
        icons = {
            "decompose": "✂️",
            "silos_ready": "🔀",
            "synthesis": "🔗",
            "done": "✅",
        }
        icon = icons.get(step, "·")
        chat.write(f"  {icon} [dim]{msg[:70]}[/]")

    try:
        task = await engine.evolve(
            intention=intention,
            hint_domains=hint_domains,
            noise=noise,
            on_silo_done=on_silo_done,
            on_progress=on_progress,
        )

        elapsed = round(time.time() - t0, 1)
        total_tok = sum(s.tokens_out for s in task.silos)

        chat.write(
            f"\n[bold green]━━ SYNTHÈSE[/] [dim]{elapsed}s | {total_tok}tok | "
            f"{silo_count[0]} silos | RAG {'✓' if task.rag_indexed else '✗'}[/]\n"
        )

        # Affiche la synthèse formatée
        for line in task.synthesis.splitlines()[:30]:
            if line.startswith("##"):
                chat.write(f"[bold cyan]{line}[/]")
            elif line.startswith("**"):
                chat.write(f"[bold]{line}[/]")
            elif line.startswith("- ") or line.startswith("* "):
                chat.write(f"  [green]•[/] {line[2:]}")
            elif line.strip():
                chat.write(f"  {line}")

        if len(task.synthesis) > 1500:
            chat.write(f"  [dim]... ({len(task.synthesis)} chars total — indexé RAG)[/]")

    except Exception as e:
        chat.write(f"[red]Evolve erreur: {e}[/]")
        logger.exception("[handle_evolve]")


async def _show_status(chat):
    """Affiche l'état des modèles + dernières évolutions."""
    import subprocess

    chat.write("[bold cyan]🧠 Siloed Reasoning Engine — Status[/]\n")

    # Modèles disponibles
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=8, errors="replace")
    if r.returncode == 0:
        chat.write("[dim]Modèles locaux:[/]")
        from nokido_agent.app.forge_silo_engine import MODEL_MAP, SiloDomain

        for domain, model in MODEL_MAP.items():
            # Vérifie si disponible
            available = any(model.split(":")[0] in line for line in r.stdout.splitlines())
            icon = "✓" if available else "✗"
            color = "green" if available else "red"
            chat.write(f"  [{color}]{icon}[/{color}] [dim]{domain.value:<12}[/] [bold]{model}[/]")
    else:
        chat.write("[yellow]Ollama non disponible[/]")

    # Dernières évolutions dans le RAG
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_rag_engine import get_rag

        rag = get_rag()
        results = await rag.search("silo synthesis", k=3)
        if results:
            chat.write("\n[dim]Dernières évolutions (RAG):[/]")
            for r in results[:3]:
                text = r.get("text", "")[:100].replace("\n", " ")
                chat.write(f"  [dim]· {text}[/]")
    except Exception:
        pass

    chat.write(
        "\n[dim]Usage:[/] @evolve <intention> | "
        "@evolve <intention> --fast | "
        "@evolve <intention> --domains code,security"
    )


async def _rag_query(chat, query: str):
    """Requête RAG sur les évolutions passées."""
    try:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_rag_engine import get_rag

        rag = get_rag()
        results = await rag.search(query, k=5)
        if not results:
            chat.write(f"[yellow]Aucun résultat RAG pour: {query}[/]")
            return
        chat.write(f"[bold cyan]RAG — {len(results)} résultats pour '{query}'[/]")
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            src = r.get("source", "?")
            score = r.get("score", 0)
            chat.write(f"\n[dim]{i}. [{src[:30]}] score={score:.2f}[/]")
            chat.write(f"   {text[:200].replace(chr(10), ' ')}")
    except Exception as e:
        chat.write(f"[red]RAG erreur: {e}[/]")
