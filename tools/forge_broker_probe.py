"""
forge_broker_probe.py — Nokido v18.5
Sonde de surveillance token cost & latence pour tous les brokers.
Mode: daemon (poll DB toutes les 30s) ou one-shot (--once) ou dashboard.

Usage:
    python tools/forge_broker_probe.py          # Dashboard continu
    python tools/forge_broker_probe.py --once   # Snapshot unique
    python tools/forge_broker_probe.py --daemon # Daemon + notify Hub
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# LECTEUR de `token_usage` : voir la note dans `forge_provider_quota`. Ce module
# ne lit que ce journal, la substitution de la constante est donc sure.
import sys as _sys_journal
if str(ROOT) not in _sys_journal.path:
    _sys_journal.path.insert(0, str(ROOT))
try:
    from nokido_agent.app.forge_db_path import CheminJournal as _CheminJournal
    DB = _CheminJournal("token_usage")
except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
    DB = ROOT / "RAG" / "embeddings.db"
HUB = "http://127.0.0.1:8766"

ANSI = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "reset": "\033[0m",
    "dim": "\033[2m",
}


def c(text, color):
    return f"{ANSI.get(color, '')}{text}{ANSI['reset']}"


def _query(sql, *args):
    conn = sqlite3.connect(str(DB), timeout=5)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def snapshot() -> dict:
    """Lire les stats token_usage de la dernière heure."""
    # Total par agent (dernière heure)
    by_agent = _query("""
        SELECT agent_id, provider,
               COUNT(*) calls,
               SUM(prompt_tokens) ptok, SUM(completion_tokens) ctok,
               ROUND(SUM(cost_usd),6) cost,
               ROUND(AVG(latency_ms)) avg_ms,
               MAX(ts) last_call
        FROM token_usage
        WHERE ts >= datetime('now','-1 hour')
        GROUP BY agent_id, provider
        ORDER BY cost DESC
    """)
    # Grand total session (depuis minuit)
    totals = _query("""
        SELECT COUNT(*) calls, SUM(total_tokens) tokens,
               ROUND(SUM(cost_usd),4) cost
        FROM token_usage
        WHERE ts >= date('now')
    """)
    # Par model (aujourd hui)
    by_model = _query("""
        SELECT model, SUM(prompt_tokens) ptok, SUM(completion_tokens) ctok,
               ROUND(SUM(cost_usd),4) cost, COUNT(*) calls
        FROM token_usage WHERE ts >= date('now')
        GROUP BY model ORDER BY cost DESC LIMIT 10
    """)
    return {
        "by_agent": by_agent,
        "totals": totals[0] if totals else (0, 0, 0),
        "by_model": by_model,
    }


def display(data: dict) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    ts = time.strftime("%H:%M:%S")
    print(c(f"\n{'=' * 65}", "cyan"))
    print(c(f"  Nokido Token Cost Probe  {ts}  [q=quit]", "bold"))
    print(c(f"{'=' * 65}", "cyan"))

    # Totals du jour
    calls, tokens, cost = data["totals"]
    print(c(f"\n  Aujourd'hui : {calls} appels | {tokens:,} tokens | ${cost:.4f} USD", "bold"))

    # Par agent/provider (dernière heure)
    print(c("\n  ── Dernière heure par agent ──────────────────────────────", "dim"))
    print(
        f"  {'Agent':15s} {'Provider':25s} {'Appels':6s} {'In':6s} {'Out':6s} {'Coût $':10s} {'ms':6s}"
    )
    print(f"  {'-' * 14} {'-' * 24} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 10} {'-' * 6}")
    for row in data["by_agent"]:
        agent_id, prov, calls, ptok, ctok, cost, avg_ms, last = row
        ptok = ptok or 0
        ctok = ctok or 0
        cost = cost or 0
        cost_col = c(f"${cost:.6f}", "red" if cost > 0.01 else "green" if cost == 0 else "yellow")
        print(
            f"  {agent_id:15s} {prov[:24]:25s} {calls:6d} {ptok:6d} {ctok:6d} {cost_col:10s} {avg_ms or 0:6.0f}"
        )

    # Par modele
    if data["by_model"]:
        print(c("\n  ── Modèles du jour ───────────────────────────────────────", "dim"))
        for model, ptok, ctok, cost, calls in data["by_model"]:
            bar_len = min(20, int((cost or 0) * 1000))
            bar = "█" * bar_len + "░" * (20 - bar_len)
            print(f"  {model[:30]:30s} [{bar}] ${cost or 0:.4f} ({calls} calls)")

    print(c(f"\n{'=' * 65}\n", "cyan"))


def hub_notify_cost(data: dict) -> None:
    """Envoyer résumé coût au Hub pour le TUI."""
    import urllib.request

    try:
        import keyring

        token = keyring.get_password("Nokido", "FORGE_MCP_TOKEN") or ""
    except:
        token = ""
    calls, tokens, cost = data["totals"]
    top = data["by_model"][:3] if data["by_model"] else []
    top_str = " | ".join(f"{r[0][:15]}=${r[3]:.4f}" for r in top)
    msg = f"[TOKEN-PROBE] {time.strftime('%H:%M')} | {calls} appels | {tokens:,} tok | ${cost:.4f} | {top_str}"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "hub", "arguments": {"action": "notify", "message": msg}},
            "id": 1,
        }
    ).encode()
    req = urllib.request.Request(
        f"{HUB}/mcp",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except:
        pass


def main():
    ap = argparse.ArgumentParser(description="Nokido Token Cost Probe")
    ap.add_argument("--once", action="store_true", help="Snapshot unique JSON")
    ap.add_argument("--daemon", action="store_true", help="Daemon + notify Hub")
    ap.add_argument("--interval", type=int, default=30, help="Intervalle daemon (s)")
    args = ap.parse_args()

    if args.once:
        data = snapshot()
        print(json.dumps({"totals": data["totals"], "by_model": data["by_model"]}, indent=2))
        return

    if args.daemon:
        import logging

        log = logging.getLogger("forge.probe")
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s [probe] %(message)s", datefmt="%H:%M:%S"
        )
        log.info(f"Probe daemon démarré | interval={args.interval}s")
        while True:
            try:
                data = snapshot()
                calls, tokens, cost = data["totals"]
                log.info(f"{calls} appels | {tokens:,} tok | ${cost:.6f}")
                hub_notify_cost(data)
            except Exception as e:
                log.error(f"probe err: {e}")
            time.sleep(args.interval)

    # Mode dashboard interactif (défaut)
    try:
        while True:
            data = snapshot()
            display(data)
            time.sleep(5)
    except KeyboardInterrupt:
        print("Probe arrêtée.")


if __name__ == "__main__":
    main()
