# -*- coding: utf-8 -*-
"""
forge_token_meter.py — Compteur et Agrégateur de Dépense Tokens par CLI
========================================================================
Agrège en temps réel la consommation de tokens et les coûts (USD) par agent
(CLAUDE, GEMINI, ANTIGRAVITY, CODEX...) à partir de la table token_usage.

Exécution directe (0 appel cloud, 100% local SQLite) :
    python tools/forge_token_meter.py [--agent AGENT_NAME] [--hours N]
"""

from __future__ import annotations

__FORGE_COLOR__ = "observabilite/metrics : compteur et agregateur de depense tokens par CLI"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse, json, sqlite3, sys
from pathlib import Path
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
# LECTEUR de `token_usage` : voir la note dans `forge_provider_quota`. Ce module
# ne lit que ce journal, la substitution de la constante est donc sure.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from nokido_agent.app.forge_db_path import CheminJournal as _CheminJournal
    DB_PATH = _CheminJournal("token_usage")
except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
    DB_PATH = ROOT / "RAG" / "embeddings.db"


def aggregate_by_agent(since_hours: int = 720) -> Dict[str, Dict[str, Any]]:
    """Agrège la consommation de tokens et le coût en USD par agent."""
    if not DB_PATH.exists():
        return {}
    
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        query = f"""
            SELECT 
                COALESCE(agent_id, 'inconnu') as agent,
                COUNT(*) as call_count,
                SUM(prompt_tokens) as prompt_tok,
                SUM(completion_tokens) as comp_tok,
                SUM(total_tokens) as total_tok,
                SUM(cost_usd) as total_cost
            FROM token_usage
            WHERE ts >= datetime('now', '-{int(since_hours)} hours')
            GROUP BY COALESCE(agent_id, 'inconnu')
            ORDER BY total_cost DESC, total_tok DESC
        """
        rows = conn.execute(query).fetchall()
        result = {}
        for r in rows:
            agent_name = str(r["agent"]).upper()
            result[agent_name] = {
                "calls": int(r["call_count"] or 0),
                "prompt_tokens": int(r["prompt_tok"] or 0),
                "completion_tokens": int(r["comp_tok"] or 0),
                "total_tokens": int(r["total_tok"] or 0),
                "cost_usd": round(float(r["total_cost"] or 0.0), 6),
            }
        return result
    finally:
        conn.close()


def get_agent_usage(agent_name: str, since_hours: int = 720) -> Dict[str, Any]:
    """Retourne la consommation détaillée pour un agent spécifique."""
    all_usage = aggregate_by_agent(since_hours=since_hours)
    target = agent_name.upper()
    return all_usage.get(target, {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    })


def format_meter_report(since_hours: int = 720, filter_agent: str | None = None) -> str:
    """Génère un rapport ASCII / Markdown de la dépense métabolique par agent."""
    usage = aggregate_by_agent(since_hours=since_hours)
    if filter_agent:
        target = filter_agent.upper()
        usage = {k: v for k, v in usage.items() if k == target}

    lines = [
        f"📊 [FORGE TOKEN METER] Dépense Métabolique (dernières {since_hours}h)",
        "┌────────────────────┬──────────┬─────────────┬─────────────┬──────────────┬─────────────┐",
        "│ Agent CLI          │ Appels   │ Prompt Tok  │ Compl. Tok  │ Total Tok    │ Coût (USD)  │",
        "├────────────────────┼──────────┼─────────────┼─────────────┼──────────────┼─────────────┤",
    ]
    
    total_calls = 0
    total_tok = 0
    total_cost = 0.0
    
    if not usage:
        lines.append("│ Aucune donnée enregistrée sur la période                                           │")
    else:
        for agent, stats in usage.items():
            c = stats["calls"]
            p = stats["prompt_tokens"]
            comp = stats["completion_tokens"]
            tot = stats["total_tokens"]
            cost = stats["cost_usd"]
            
            total_calls += c
            total_tok += tot
            total_cost += cost
            
            lines.append(f"│ {agent:<18} │ {c:>8} │ {p:>11,}".replace(",", " ") +
                         f" │ {comp:>11,}".replace(",", " ") +
                         f" │ {tot:>12,}".replace(",", " ") +
                         f" │ ${cost:>9.4f} │")

    lines.append("├────────────────────┼──────────┼─────────────┼─────────────┼──────────────┼─────────────┤")
    lines.append(f"│ TOTAL GLOBAL       │ {total_calls:>8} │             │             │ {total_tok:>12,}".replace(",", " ") +
                 f" │ ${total_cost:>9.4f} │")
    lines.append("└────────────────────┴──────────┴─────────────┴─────────────┴──────────────┴─────────────┘")
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Forge Token Meter CLI")
    parser.add_argument("--agent", type=str, help="Filtrer par nom d'agent CLI (ex: ANTIGRAVITY, CLAUDE)")
    parser.add_argument("--hours", type=int, default=720, help="Fenêtre d'analyse en heures (défaut: 720h / 30j)")
    parser.add_argument("--json", action="store_true", help="Sortie en format JSON pur")
    args = parser.parse_args()

    if args.json:
        data = aggregate_by_agent(since_hours=args.hours)
        if args.agent:
            data = {k: v for k, v in data.items() if k == args.agent.upper()}
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(format_meter_report(since_hours=args.hours, filter_agent=args.agent))


if __name__ == "__main__":
    main()
