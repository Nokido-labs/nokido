"""
app/forge_handler_fragment.py — Handler @fragment TUI
======================================================
Interface avec le Siloed Fragmentation Engine + Noise Guardian.

Commandes :
  @fragment <texte>              → pipeline complet (3 silos + réconciliation)
  @fragment scan                 → fragmente le dernier scan réseau
  @fragment validate <texte>     → test NoiseGuardian sans envoi LLM
  @fragment status               → stats de la session

Exemple :
  @fragment Port 445 SMB ouvert, anonymous login Freebox, CVE-2017-0143 possible
  @fragment validate localhost avec Metasploit BlueKeep 0xDEADBEEF
"""

from __future__ import annotations
import logging, sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _engine():
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from nokido_agent.app.forge_silo_fragmenter import get_fragmenter

    return get_fragmenter()


async def handle_fragment(app, args: str) -> None:
    chat = app._chat_log()
    raw = args.strip()

    # ── validate ──────────────────────────────────────────────────────────────
    if raw.lower().startswith("validate "):
        text = raw[9:].strip()
        eng = _engine()
        rpt = eng.validate_only(text)
        chat.write("[bold cyan]🔍 Noise Guardian — Analyse[/]")
        chat.write(
            f"  Sensibilité avant : [{'red' if rpt['sensitivity_before'] > 0.5 else 'green'}]{rpt['sensitivity_before']:.2f}[/]"
        )
        chat.write(f"  IPs              : {rpt['neutralized_ips']}")
        chat.write(f"  Signatures       : {rpt['neutralized_sigs']}")
        chat.write(f"  Magic constants  : {rpt['neutralized_magic']}")
        chat.write(
            f"  Sensibilité après: [{'red' if rpt['sensitivity_after'] > 0.5 else 'green'}]{rpt['sensitivity_after']:.2f}[/]"
        )
        status = "[red]BLOQUÉ[/]" if rpt["blocked"] else "[green]OK — envoi autorisé[/]"
        chat.write(f"  Statut           : {status}")
        if rpt["blocked"]:
            chat.write(f"  Raison           : [dim]{rpt['block_reason']}[/]")
        return

    # ── status ────────────────────────────────────────────────────────────────
    if raw.lower() == "status":
        chat.write("[bold cyan]🔀 Fragmentation Engine — Status[/]")
        chat.write("  Modèles:")
        from nokido_agent.app.forge_silo_fragmenter import FragmentationEngine

        for silo, model in FragmentationEngine.SILO_MODELS.items():
            chat.write(f"    {silo:<10} → {model}")
        chat.write("  Usage: @fragment <rapport>  |  @fragment validate <texte>")
        return

    # ── pipeline complet ──────────────────────────────────────────────────────
    # Si "scan" → prend le dernier scan depuis le serveur recon
    if raw.lower() == "scan":
        try:
            import urllib.request, json

            hosts = json.loads(urllib.request.urlopen("http://127.0.0.1:7331/export", timeout=5).read())
            report_lines = []
            for h in hosts.get("hosts", []):
                report_lines.append(
                    f"HOTE {h['ip']} ({h.get('type', '?')}) RISK={h.get('risk_score', 0)}\n"
                    f"  Services: {', '.join(str(p) for p in h.get('ports', []))}"
                )
            raw = "\n".join(report_lines) if report_lines else "Aucun hôte scanné"
        except Exception as e:
            chat.write(f"[red]Recon Silo non disponible: {e}[/]")
            return

    if not raw or len(raw) < 10:
        chat.write("[yellow]Usage: @fragment <rapport ou texte à fragmenter>[/]")
        return

    chat.write(
        f"[bold red]🔀 FRAGMENTEUR[/] [dim]→ {len(raw)} chars[/]\n"
        f"[dim]Noise Guardian + 3 silos parallèles + réconciliation locale Ryzen[/]"
    )

    eng = _engine()

    def on_frag(f):
        if f.blocked:
            chat.write(f"  [red]✗ BLOQUÉ[/] [{f.silo.upper():<8}] sensibilité trop élevée")
        else:
            grpt = f.guardian_rpt
            chat.write(
                f"  [green]✓[/] [{f.silo.upper():<8}] "
                f"[dim]{f.model.split(':')[0]}[/] "
                f"[green]{f.duration}s[/] [dim]{f.tokens}tok[/] | "
                f"neutralisé: IPs={grpt.get('neutralized_ips', 0)} "
                f"sigs={grpt.get('neutralized_sigs', 0)} "
                f"magic={grpt.get('neutralized_magic', 0)}"
            )
        if f.output and len(f.output) > 20 and "[BLOQUÉ" not in f.output:
            preview = f.output[:100].replace("\n", " ")
            chat.write(f"    [dim]{preview}...[/]")

    def on_prog(step, msg):
        icons = {
            "extract": "✂️",
            "guardian": "🛡",
            "silos_ready": "🔀",
            "reconcile": "🔗",
            "done": "✅",
        }
        chat.write(f"  {icons.get(step, '·')} [dim]{msg[:75]}[/]")

    try:
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: eng.fragment_sync(raw, on_fragment_done=on_frag, on_progress=on_prog)
        )

        stats = result.stats
        chat.write(
            f"\n[bold green]━━ SYNTHÈSE LOCALE[/] "
            f"[dim]{result.duration}s | {stats.get('total_tokens', 0)}tok | "
            f"{stats.get('total_neutralized', 0)} éléments neutralisés | "
            f"RAG {'✓' if result.rag_indexed else '✗'}[/]\n"
        )

        # Affiche la synthèse
        for line in result.synthesis.splitlines()[:40]:
            if line.startswith("##"):
                chat.write(f"[bold cyan]{line}[/]")
            elif line.startswith("####") or line.startswith("###"):
                chat.write(f"[bold]{line}[/]")
            elif line.startswith("```"):
                continue
            elif line.strip().startswith("$") or "smbclient" in line or "hydra" in line:
                chat.write(f"  [green bold]{line.strip()}[/]")
            elif line.strip().startswith("-") or line.strip().startswith("*"):
                chat.write(f"  [dim]•[/] {line.strip()[1:].strip()}")
            elif line.strip():
                chat.write(f"  {line}")

        sens_max = stats.get("sensitivity_max", 0)
        sens_after = stats.get("sensitivity_after", 0)
        chat.write(
            f"\n[dim]NoiseGuardian: sensibilité {sens_max:.2f}→{sens_after:.2f} | "
            f"silos bloqués: {stats.get('blocked_silos', 0)}/3[/]"
        )

    except Exception as e:
        chat.write(f"[red]Fragment erreur: {e}[/]")
        logger.exception("[handle_fragment]")
