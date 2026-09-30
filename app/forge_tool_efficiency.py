"""forge_tool_efficiency.py — Comparaison périodique d'efficacité des tools.

Mapping bio↔code :
- Sélection naturelle = tools peu efficaces sont identifiés et candidats au remplacement
- Métabolisme         = mesure tokens consommés / résultat utile
- Tolérance/dépendance= si un tool dégrade dans le temps, alerter

PROBLÈME ADRESSÉ
================
Nokido appelle des dizaines de tools (MCP slots, Ollama models, llama.cpp, providers
cloud free, hub /mcp tool calls). Au fil du temps :
- Un provider devient lent (rate-limit, dégradation infra)
- Un modèle local mange plus de tokens pour même résultat
- Un MCP tool tourne mais retourne pas ce qu'on attend

Aujourd'hui : aucune comparaison automatique. On apprend manuellement
("tiens, gpt-4.1-mini est devenu lent") après douleur.

PIPELINE
========
1. Lecture token_usage (forge_token_monitor) + network_log (durée + ok)
2. Pour chaque tool/model, compute :
   - throughput_tok_per_s  (output_tokens / latency_s)
   - cost_per_useful_tok   (cost_usd / output_tokens)
   - failure_rate          (count(status=ERR) / total)
   - degradation_score     (perf actuelle / perf 7j passés)
3. Ranking par use_case (code, reasoning, speed, etc.)
4. Recommandations : si degradation > 30%, alert + propose alternative
5. Output : sandbox/tool_efficiency_<date>.json + recommandations

Hook orchestrateur : appelé toutes les 2h par forge_homeostasis_orchestrator.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def metrics_token_usage(conn, since_hours: int = 168) -> list[dict]:
    """Stats par (provider, model) sur fenêtre récente (default 7j).

    Retourne pour chaque slot :
    - calls, avg_latency_ms, total_tokens, total_cost_usd
    - tok_per_s_avg = avg(output_tok / latency_s)
    - cost_per_1k_out = total_cost_usd / total_output_tokens * 1000
    """
    # `token_usage` est un JOURNAL qui suit `sandbox/journaux.switch` ; ce module
    # lit aussi `network_log`, qui reste dans la base du RAG. La connexion arrive
    # en PARAMETRE et sert aux deux : on ne la remplace donc pas, on ouvre une
    # connexion DEDIEE au journal UNIQUEMENT s'il a bascule. Tant que rien n'est
    # pose, `_base` vaut la base de `conn` et ce bloc ne change rien -- la
    # signature de la fonction et ses appelants restent intacts.
    try:
        from nokido_agent.app.forge_db_path import journal_path as _jp
        _base = _jp("token_usage")
    except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
        _base = str(DB)
    _dedie = _base != str(DB)
    _c = sqlite3.connect(_base, timeout=10) if _dedie else conn
    try:
        if not _table_exists(_c, "token_usage"):
            return []
        cutoff = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = _c.execute(
            "SELECT provider, model, COUNT(*) as n, "
            "AVG(latency_ms) as avg_lat, "
            "SUM(prompt_tokens) as p_tok, SUM(completion_tokens) as c_tok, "
            "SUM(cost_usd) as cost "
            "FROM token_usage WHERE ts >= ? "
            "GROUP BY provider, model HAVING n >= 3 "
            "ORDER BY n DESC LIMIT 50",
            (cutoff,),
        ).fetchall()
    finally:
        # Ne fermer QUE ce qu'on a ouvert : fermer la connexion de l'appelant le
        # priverait de la sienne au milieu de son propre travail.
        if _dedie:
            _c.close()
    out = []
    for r in rows:
        prov, model, n, avg_lat, p_tok, c_tok, cost = r
        c_tok = c_tok or 0
        avg_lat = avg_lat or 1
        tok_per_s = round((c_tok / max(n, 1)) / max(avg_lat / 1000, 0.001), 2) if c_tok else 0
        cost_per_1k_out = round((cost / max(c_tok, 1)) * 1000, 6) if c_tok else 0
        out.append(
            {
                "provider": prov,
                "model": model,
                "calls": n,
                "avg_latency_ms": round(avg_lat, 0),
                "prompt_tokens": p_tok or 0,
                "completion_tokens": c_tok,
                "total_cost_usd": round(cost or 0, 6),
                "tok_per_s_avg": tok_per_s,
                "cost_per_1k_completion_tok": cost_per_1k_out,
            }
        )
    return out


def metrics_network_log(conn, since_hours: int = 24) -> list[dict]:
    """Stats par (channel, tool) depuis network_log."""
    if not _table_exists(conn, "network_log"):
        return []
    cutoff = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT channel, tool, COUNT(*) as n, "
        "SUM(CASE WHEN status='OK' THEN 1 ELSE 0 END) as ok_count, "
        "AVG(CASE WHEN meta LIKE '%latency_ms%' "
        "  THEN CAST(substr(meta, instr(meta,'\"latency_ms\":') + 14, 8) AS REAL) "
        "  ELSE NULL END) as avg_lat "
        "FROM network_log WHERE ts >= ? "
        "GROUP BY channel, tool HAVING n >= 3 "
        "ORDER BY n DESC LIMIT 30",
        (cutoff,),
    ).fetchall()
    out = []
    for r in rows:
        ch, tool, n, ok_count, avg_lat = r
        out.append(
            {
                "channel": ch,
                "tool": tool,
                "calls": n,
                "ok_count": ok_count or 0,
                "failure_rate": round(1 - (ok_count or 0) / max(n, 1), 3),
                "avg_latency_ms": round(avg_lat or 0, 0),
            }
        )
    return out


def detect_degradations(token_metrics: list[dict], threshold_pct: float = 0.3) -> list[dict]:
    """Compare semaine actuelle vs précédente (heuristique simple : flagge tout tool
    avec failure_rate > 20% ou cost_per_1k > p90).
    """
    alerts = []
    for m in token_metrics:
        if m["calls"] < 5:
            continue
        # Critères simples (extensible avec historique)
        if m.get("avg_latency_ms", 0) > 10000:
            alerts.append(
                {
                    "kind": "high_latency",
                    "provider": m["provider"],
                    "model": m["model"],
                    "metric": f"{m['avg_latency_ms']}ms avg latency",
                    "severity": "warn",
                    "recommendation": "Tester un slot alternatif dans la même chain USE_CASE_CHAINS",
                }
            )
        if m.get("tok_per_s_avg", 0) < 5 and m.get("calls", 0) >= 5:
            alerts.append(
                {
                    "kind": "low_throughput",
                    "provider": m["provider"],
                    "model": m["model"],
                    "metric": f"{m['tok_per_s_avg']} tok/s",
                    "severity": "warn",
                    "recommendation": "Considérer downgrade modèle ou batch sizing",
                }
            )
    return alerts


def rank_by_use_case(token_metrics: list[dict]) -> dict:
    """Ranking des modèles par tok/s (proxy d'efficacité runtime)."""
    sorted_models = sorted(token_metrics, key=lambda m: -m.get("tok_per_s_avg", 0))
    top10 = []
    for m in sorted_models[:10]:
        top10.append(
            {
                "rank_provider_model": f"{m['provider']}/{m['model']}",
                "tok_per_s": m["tok_per_s_avg"],
                "cost_per_1k": m["cost_per_1k_completion_tok"],
                "calls": m["calls"],
            }
        )
    return {"top10_by_throughput": top10}


def run_cycle() -> dict:
    conn = _conn()
    t0 = time.time()
    tu = metrics_token_usage(conn, since_hours=168)
    nl = metrics_network_log(conn, since_hours=24)
    alerts = detect_degradations(tu)
    ranking = rank_by_use_case(tu)
    conn.close()

    out = {
        "ts": datetime.now().isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "token_usage_metrics": tu,
        "network_metrics": nl,
        "alerts": alerts,
        "ranking": ranking,
        "summary": {
            "models_tracked": len(tu),
            "channels_tracked": len(nl),
            "alerts_count": len(alerts),
        },
    }

    SANDBOX.mkdir(parents=True, exist_ok=True)
    out_path = SANDBOX / f"tool_efficiency_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido tool efficiency comparator")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=7200)  # 2h
    args = ap.parse_args()
    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    while True:
        out = run_cycle()
        s = out["summary"]
        print(
            f"[efficiency] cycle {out['duration_s']}s : "
            f"models={s['models_tracked']} channels={s['channels_tracked']} "
            f"alerts={s['alerts_count']}",
            flush=True,
        )
        for r in out["ranking"]["top10_by_throughput"][:5]:
            print(
                f"  🏆 {r['rank_provider_model']:40s} {r['tok_per_s']:>5} tok/s ${r['cost_per_1k']:.6f}/1K", flush=True
            )
        for a in out["alerts"]:
            print(f"  ⚠ {a['kind']}: {a['provider']}/{a['model']} ({a['metric']})", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
