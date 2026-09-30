"""
app/forge_handler_skill.py — Handler @skill TUI
================================================
Interface Nokido pour le connecteur ClawHub isolé en silo.

Commandes :
  @skill search <query>          → recherche sur ClawHub
  @skill install <slug>          → installe + review Guardian + RAG
  @skill run <slug> [contexte]   → exécute dans silo isolé
  @skill list                    → skills installées
  @skill info <slug>             → détails d'une skill
  @skill remove <slug>           → désinstalle
  @skill status                  → état du bridge
"""

from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _bridge():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from nokido_agent.app.forge_clawhub_bridge import get_clawhub_bridge

    return get_clawhub_bridge()


async def handle_skill(app, args: str) -> None:
    chat = app._chat_log()
    parts = args.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    # ── status ────────────────────────────────────────────────────────────────
    if cmd in ("", "status"):
        await _cmd_status(chat)
        return

    # ── list ──────────────────────────────────────────────────────────────────
    if cmd == "list":
        await _cmd_list(chat)
        return

    # ── search <query> ────────────────────────────────────────────────────────
    if cmd == "search":
        if not rest:
            chat.write("[yellow]Usage: @skill search <query>[/]")
            return
        await _cmd_search(chat, rest)
        return

    # ── install <slug> [--force] ──────────────────────────────────────────────
    if cmd == "install":
        slug = rest.replace("--force", "").strip()
        force = "--force" in rest
        if not slug:
            chat.write("[yellow]Usage: @skill install <slug>[/]")
            return
        await _cmd_install(chat, slug, force)
        return

    # ── info <slug> ───────────────────────────────────────────────────────────
    if cmd == "info":
        if not rest:
            chat.write("[yellow]Usage: @skill info <slug>[/]")
            return
        await _cmd_info(chat, rest)
        return

    # ── remove <slug> ─────────────────────────────────────────────────────────
    if cmd == "remove":
        if not rest:
            chat.write("[yellow]Usage: @skill remove <slug>[/]")
            return
        _bridge().remove(rest)
        chat.write(f"[dim]Skill '{rest}' désinstallée.[/]")
        return

    # ── run <slug> [--context <texte>] ───────────────────────────────────────
    if cmd == "run":
        # parse: run <slug> --context <texte> ou run <slug> <texte direct>
        import re

        m = re.match(r"(\S+)\s+(?:--context\s+)?(.*)", rest, re.DOTALL)
        if not m:
            chat.write("[yellow]Usage: @skill run <slug> <contexte>[/]")
            return
        slug = m.group(1)
        context = m.group(2).strip()
        if not context:
            chat.write("[yellow]Précise le contexte : @skill run <slug> <ce que tu veux faire>[/]")
            return
        await _cmd_run(chat, slug, context)
        return

    chat.write(f"[yellow]Commande inconnue: '{cmd}' — disponibles: search install run list info remove status[/]")


# ── Implémentations ────────────────────────────────────────────────────────────


async def _cmd_status(chat):
    bridge = _bridge()
    installed = bridge.list_installed()
    chat.write("[bold cyan]🦀 ClawHub Bridge — Status[/]")
    chat.write("  API       : [dim]https://clawhub.ai/api/v1[/]")
    chat.write(f"  Installées: [bold]{len(installed)}[/] skills")
    chat.write("  Guardian  : deepseek-coder:6.7b (local, aucun cloud)")
    chat.write("  Runner    : qwen2.5-coder:7b (silo isolé)")
    chat.write("  RAG       : index local Nokido")
    if installed:
        approved = sum(1 for s in installed if s.get("local_status") == "approved")
        warned = sum(1 for s in installed if s.get("local_status") == "warning")
        rejected = sum(1 for s in installed if s.get("local_status") == "rejected")
        chat.write(
            f"\n  Guardian stats: [green]{approved} approuvées[/] · "
            f"[yellow]{warned} warning[/] · [red]{rejected} rejetées[/]"
        )
    chat.write("\n[dim]Commandes: @skill search|install|run|list|info|remove[/]")


async def _cmd_list(chat):
    bridge = _bridge()
    installed = bridge.list_installed()
    if not installed:
        chat.write("[dim]Aucune skill installée. Lance: @skill search audit[/]")
        return
    chat.write(f"[bold cyan]🦀 Skills ClawHub installées ({len(installed)})[/]\n")
    STATUS_COLOR = {"approved": "green", "warning": "yellow", "rejected": "red", "unreviewed": "dim"}
    for s in sorted(installed, key=lambda x: x.get("local_status", "")):
        col = STATUS_COLOR.get(s.get("local_status", ""), "dim")
        rag = "✓" if s.get("rag_indexed") else "✗"
        chat.write(
            f"  [{col}]{s.get('local_status', '?').upper():<12}[/{col}] "
            f"[bold]{s['slug']}[/] v{s.get('version', '?')} "
            f"[dim]risk={s.get('local_risk', 0):.2f} RAG={rag}[/]"
        )
        chat.write(f"    [dim]{s.get('description', '')[:70]}[/]")


async def _cmd_search(chat, query: str):
    chat.write(f"[bold cyan]🦀 ClawHub Search: {query}[/]")
    bridge = _bridge()
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: bridge.search(query, limit=10))
    except Exception as e:
        chat.write(f"[red]Erreur: {e}[/]")
        return

    if not results:
        chat.write("[dim]Aucun résultat.[/]")
        return

    # Marque les skills déjà installées
    installed_slugs = {s["slug"] for s in bridge.list_installed()}
    chat.write(f"\n  {len(results)} résultats:\n")
    for r in results:
        slug = r.get("slug", "")
        score = r.get("score", 0)
        summary = r.get("summary", "")[:65]
        inst = " [green](installée)[/]" if slug in installed_slugs else ""
        chat.write(f"  [bold]{slug}[/]{inst}")
        chat.write(f"    [dim]{summary}[/]  score={score:.2f}")

    chat.write("\n[dim]Installe avec: @skill install <slug>[/]")


async def _cmd_install(chat, slug: str, force: bool = False):
    chat.write(f"[bold cyan]🦀 Install: {slug}[/]" + (" [dim](force)[/]" if force else ""))
    bridge = _bridge()

    def on_prog(msg):
        # Colore selon contenu
        if "REJET" in msg or "rejected" in msg.lower():
            chat.write(f"  [red]✗[/] {msg}")
        elif "WARN" in msg or "warning" in msg.lower() or "Risques" in msg:
            chat.write(f"  [yellow]⚠[/] {msg}")
        elif "✓" in msg or "approuv" in msg.lower():
            chat.write(f"  [green]✓[/] {msg}")
        else:
            chat.write(f"  [dim]·[/] {msg}")

    try:
        loop = asyncio.get_event_loop()
        skill = await loop.run_in_executor(None, lambda: bridge.install_sync(slug, force=force, on_progress=on_prog))
    except Exception as e:
        chat.write(f"[red]Erreur install: {e}[/]")
        return

    STATUS_COLOR = {"approved": "green", "warning": "yellow", "rejected": "red"}
    col = STATUS_COLOR.get(skill.local_status, "dim")
    chat.write(f"\n  [{col}]{skill.local_status.upper()}[/{col}] — {skill.name} v{skill.version}")
    if skill.local_reason:
        chat.write(f"  [dim]Guardian: {skill.local_reason[:90]}[/]")
    if skill.rag_indexed:
        chat.write("  [green]RAG indexé ✓[/]")
    if skill.local_status in ("approved", "warning"):
        chat.write(f"\n  [dim]Lance avec: @skill run {slug} <contexte>[/]")


async def _cmd_info(chat, slug: str):
    bridge = _bridge()
    skill = bridge._store.get_skill(slug)
    if not skill:
        # Tente depuis ClawHub
        chat.write(f"[dim]'{slug}' non installée — fetch metadata...[/]")
        try:
            loop = asyncio.get_event_loop()
            skill = await loop.run_in_executor(None, lambda: bridge._client.fetch_skill(slug))
        except Exception as e:
            chat.write(f"[red]Skill '{slug}' introuvable: {e}[/]")
            return

    chat.write(f"[bold cyan]🦀 {skill.name} v{skill.version}[/]")
    chat.write(f"  Slug   : {skill.slug}")
    chat.write(f"  Auteur : {skill.author}")
    chat.write(f"  Tags   : {', '.join(skill.tags) if skill.tags else '(none)'}")
    chat.write(f"  ClawHub: {skill.clawhub_status}")
    if skill.local_status != "unreviewed":
        STATUS_COLOR = {"approved": "green", "warning": "yellow", "rejected": "red"}
        col = STATUS_COLOR.get(skill.local_status, "dim")
        chat.write(f"  Guardian: [{col}]{skill.local_status}[/{col}] (risk={skill.local_risk:.2f})")
        if skill.local_reason:
            chat.write(f"  Raison: [dim]{skill.local_reason[:100]}[/]")
    chat.write(f"\n[dim]Description:[/]\n  {skill.description}")
    if skill.skill_md:
        import re

        clean = re.sub(r"^---\n.*?\n---\n", "", skill.skill_md, flags=re.DOTALL).strip()
        preview = clean[:400].replace("\n", "\n  ")
        chat.write(f"\n[dim]SKILL.md:[/]\n  {preview}")


async def _cmd_run(chat, slug: str, context: str):
    bridge = _bridge()
    skill = bridge._store.get_skill(slug)

    if not skill:
        chat.write(f"[yellow]'{slug}' non installée. Lance: @skill install {slug}[/]")
        return

    STATUS_COLOR = {"approved": "green", "warning": "yellow", "rejected": "red"}
    col = STATUS_COLOR.get(skill.local_status, "dim")
    chat.write(
        f"[bold cyan]🦀 Run: {skill.name}[/] "
        f"[{col}]({skill.local_status})[/{col}]\n"
        f"[dim]Silo: qwen2.5-coder:7b — contexte: {context[:60]}...[/]"
    )

    def on_prog(msg):
        chat.write(f"  [dim]{msg}[/]")

    try:
        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(None, lambda: bridge.run_sync(slug, context, on_progress=on_prog))
    except Exception as e:
        chat.write(f"[red]Erreur run: {e}[/]")
        return

    if not output or output.startswith("[ERREUR]") or output.startswith("[REJETÉ]"):
        chat.write(f"[red]{output}[/]")
        return

    chat.write(f"\n[bold green]━━ Résultat ClawHub/{slug}[/] [dim]({len(output)} chars — indexé RAG)[/]\n")
    for line in output.splitlines()[:40]:
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            chat.write(f"[bold cyan]{line}[/]")
        elif line.startswith("  $") or line.startswith("nmap ") or "nmap" in line.lower()[:15]:
            chat.write(f"  [green]{line.strip()}[/]")
        elif line.strip().startswith("-") or line.strip().startswith("*"):
            chat.write(f"  [dim]•[/] {line.strip()[1:].strip()}")
        elif line.strip():
            chat.write(f"  {line}")
    if len(output.splitlines()) > 40:
        chat.write(f"  [dim]... ({len(output)} chars total — indexé RAG)[/]")
