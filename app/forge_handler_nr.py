# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_handler_nr.py — Handler @nr extrait de forge_handlers.py
===============================================================
Gère les commandes NR (Non-Regression) :
  @nr        — run_fast()
  @nr all    — suite complète
  @nr cert   — certification behavior_gold.json
  @nr status — derniers rapports archivés
"""

import asyncio
import logging
from pathlib import Path

from nokido_agent.app import forge_context as _forge_ctx


def _g_rag():
    """g rag."""
    return _forge_ctx.rag_engine


logger = logging.getLogger("Nokido.Handler.NR")


async def _handle_nr(app, args: str) -> None:
    """
    @nr              — lance run_fast() et affiche le dashboard
    @nr all          — suite complète
    @nr cert         — certificat de bunkerisation (behavior_gold.json)
    @nr status       — derniers rapports archivés
    """
    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else "fast"

    if sub in ("fast", "") or not parts:
        chat.write("[bold #a371f7]\u26a1 NR FAST[/] — lancement...")

        async def _do_nr_fast() -> None:
            """Do nr fast."""
            import io, sys as _sys

            buf = io.StringIO()
            old_stdout = _sys.stdout
            _sys.stdout = buf
            try:
                for k in list(_sys.modules):
                    if "forge_" in k or k == "mcp_nr":
                        del _sys.modules[k]
                from nokido_agent.app.mcp_nr import run_fast

                fails = run_fast()
            finally:
                _sys.stdout = old_stdout
            output = buf.getvalue()
            icon = "[bold green]\u2705 FAST OK[/]" if fails == 0 else f"[bold red]\u274c {fails} FAIL(S)[/]"
            chat.write(f"[bold #a371f7]NR[/] {icon}")
            for line in output.splitlines():
                if line.strip() and "\u2550" not in line:
                    color = "green" if "\u2705" in line else ("red" if "\u274c" in line else "dim")
                    chat.write(f"  [{color}]{line}[/{color}]")
            try:
                import sqlite3

                conn = sqlite3.connect(
                    str(_g_rag().emb_file.parent.parent.parent / "RAG" / "embeddings.db")
                    if _g_rag()
                    else "RAG/embeddings.db"
                )
                rows = conn.execute(
                    "SELECT json_extract(meta,'$.ring') as r, json_extract(meta,'$.consensus_level') as l, COUNT(*) as n FROM rag_chunks GROUP BY r,l ORDER BY r"
                ).fetchall()
                total = sum(x[2] for x in rows) or 1
                conn.close()
                chat.write(
                    "[dim]\u2514 RAG : " + "  ".join(f"ring{r}={n} ({n * 100 // total}%)" for r, l, n in rows) + "[/]"
                )
            except Exception:
                pass

        asyncio.create_task(_do_nr_fast())

    elif sub == "all":
        chat.write("[bold #a371f7]\u26a1 NR ALL[/] — suite compl\u00e8te...")

        async def _do_nr_all() -> None:
            """Do nr all."""
            import io, sys as _sys

            buf = io.StringIO()
            old = _sys.stdout
            _sys.stdout = buf
            try:
                for k in list(_sys.modules):
                    if "forge_" in k or k == "mcp_nr":
                        del _sys.modules[k]
                from nokido_agent.app.mcp_nr import run_all

                fails = run_all()
            finally:
                _sys.stdout = old
            icon = "[bold green]\u2705 ALL OK[/]" if fails == 0 else f"[bold red]\u274c {fails} FAIL(S)[/]"
            chat.write(f"[bold #a371f7]NR ALL[/] {icon}")

        asyncio.create_task(_do_nr_all())

    elif sub in ("cert", "certif"):
        chat.write("[bold #f7c948]\u26a1 CERTIFICATION[/] — behavior_gold.json...")

        async def _do_cert() -> None:
            """Do cert."""
            import sys as _sys

            for k in list(_sys.modules):
                if "forge_" in k:
                    del _sys.modules[k]
            try:
                from pathlib import Path as _P
                import json as _j

                bg = _P("data_nr/expected/behavior_gold.json")
                gold = _j.loads(bg.read_text(encoding="utf-8"))
                scenarios = {k: v for k, v in gold.items() if not k.startswith("_")}
                ok_n = 0
                fail_n = 0
                from nokido_agent.app.forge_rag_truth import RagTruth

                rt = RagTruth()
                for name, expected in scenarios.items():
                    try:
                        result = rt.verify(name, expected)
                        if result:
                            ok_n += 1
                        else:
                            fail_n += 1
                            chat.write(f"  [red]\u274c {name}[/]")
                    except Exception as e:
                        fail_n += 1
                        chat.write(f"  [red]\u274c {name}: {e}[/]")
                icon = "[green]\u2705[/]" if fail_n == 0 else "[red]\u274c[/]"
                chat.write(f"[bold #f7c948]CERT[/] {icon} {ok_n}/{ok_n + fail_n} scenarios OK")
            except Exception as e:
                chat.write(f"[red]CERT erreur: {e}[/]")

        asyncio.create_task(_do_cert())

    elif sub == "status":

        async def _do_status() -> None:
            """Do status."""
            import json as _j

            try:
                reports_dir = Path("data_nr/reports")
                if not reports_dir.exists():
                    chat.write("[dim]Aucun rapport NR trouvé[/]")
                    return
                reports = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
                if not reports:
                    chat.write("[dim]Aucun rapport NR trouvé[/]")
                    return
                chat.write("[bold #a371f7]NR STATUS[/] — 5 derniers rapports:")
                for r in reports:
                    try:
                        data = _j.loads(r.read_text(encoding="utf-8"))
                        ts = data.get("timestamp", r.stem)
                        ok = data.get("passed", "?")
                        fail = data.get("failed", "?")
                        chat.write(f"  [dim]{ts}[/] — [green]{ok} OK[/] / [red]{fail} FAIL[/]")
                    except Exception:
                        chat.write(f"  [dim]{r.name}[/]")
            except Exception as e:
                chat.write(f"[red]STATUS erreur: {e}[/]")

        asyncio.create_task(_do_status())

    else:
        chat.write(f'[yellow]@nr : sous-commande inconnue "{sub}" — fast|all|cert|status[/]')
