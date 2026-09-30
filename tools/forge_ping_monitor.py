"""
forge_ping_monitor.py — Nokido v18.5
=======================================
Moniteur de latence LLM en temps réel.
Mesure TTFT (Time To First Token) + TPS pour chaque provider actif.
Met à jour la table provider_scores → DT router s'adapte dynamiquement.

Seuils (April 2026) :
    EXCELLENT : TTFT < 200ms   (SambaNova, Groq Llama 3.1 8B)
    GOOD      : TTFT < 800ms   (Gemini Flash, Mistral Small)
    SLOW      : TTFT > 2000ms  (Gemini Pro, modèles reasoning)
    DOWN      : erreur / timeout

Usage:
    python tools/forge_ping_monitor.py             # one-shot
    python tools/forge_ping_monitor.py --daemon    # daemon continu
    python tools/forge_ping_monitor.py --route "ma requête" # recommander
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
LOG = logging.getLogger("forge.ping")

# ── Endpoint config par provider ──────────────────────────────────────────
PROVIDERS_CONFIG = {
    "groq/llama-3.1-8b": {
        "key_wm": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "body": {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        "ua": "curl/7.88.1",
        "timeout": 8,
    },
    "groq/llama-3.3-70b": {
        "key_wm": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "body": {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        "ua": "curl/7.88.1",
        "timeout": 8,
    },
    "gemini/flash": {
        "key_wm": "GEMINI_API_KEY",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
        "body": {
            "contents": [{"parts": [{"text": "ping"}], "role": "user"}],
            "generationConfig": {"maxOutputTokens": 2},
        },
        "ua": None,
        "timeout": 10,
        "key_in_url": True,
    },
    "mistral/small": {
        "key_wm": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "body": {
            "model": "mistral-small-latest",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        "ua": "curl/7.88.1",
        "timeout": 10,
    },
    "xai/grok-mini": {
        "key_wm": "XAI_API_KEY",
        "url": "https://api.x.ai/v1/chat/completions",
        "body": {
            "model": "grok-3-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 2,
        },
        "ua": "curl/7.88.1",
        "timeout": 12,
    },
    "sambanova/llama-3.3-70b": {
        "key_wm": "SAMBANOVA_API_KEY",
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "body": {
            "model": "Meta-Llama-3.3-70B-Instruct",
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
        },
        "ua": "curl/7.88.1",
        "timeout": 10,
    },
    "openrouter/gemma4:free": {
        "key_wm": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "body": {
            "model": "google/gemma-4-26b-a4b-it:free",
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
        },
        "ua": "curl/7.88.1",
        "timeout": 12,
    },
    "ollama/qwen3:8b": {
        "key_wm": None,
        "url": "http://localhost:11434/api/generate",
        "body": {
            "model": "qwen3:8b",
            "prompt": "ping",
            "stream": False,
            "options": {"num_predict": 1},
        },
        "ua": None,
        "timeout": 30,
    },
    "llamacpp/gemma4": {
        "key_wm": None,
        "url": "http://127.0.0.1:8090/v1/chat/completions",
        "body": {
            "model": "gemma4",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "thinking": False,
        },
        "ua": None,
        "timeout": 30,
    },
}

# Mapping provider_id → agent broker
PROVIDER_TO_AGENT = {
    "groq/llama-3.1-8b": "agt_groq",
    "groq/llama-3.3-70b": "agt_groq",
    "gemini/flash": "agt_gemini",
    "mistral/small": "agt_mistral",
    "xai/grok-mini": "agt_gemini",  # fallback Gemini si Grok
    "sambanova/llama-3.3-70b": "agt_groq",  # fallback Groq si SambaNova UP
    "openrouter/gemma4:free": "agt_gemini",
    "ollama/qwen3:8b": "agt_local",
    "llamacpp/gemma4": "agt_local",
}


def _load_key(key_name: str) -> str:
    try:
        import keyring

        v = keyring.get_password("Nokido", key_name)
        if v:
            return v
    except:
        pass
    return os.environ.get(key_name, "")


def ping_provider(name: str, cfg: dict) -> dict:
    """Mesurer TTFT pour un provider. Retourne dict résultat."""
    key = _load_key(cfg["key_wm"]) if cfg.get("key_wm") else ""
    url = cfg["url"].format(key=key)

    body = json.dumps(cfg["body"]).encode()
    hdrs = {"Content-Type": "application/json"}
    if key and not cfg.get("key_in_url"):
        hdrs["Authorization"] = f"Bearer {key}"
    if cfg.get("ua"):
        hdrs["User-Agent"] = cfg["ua"]

    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, data=body, headers=hdrs)
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            _ = r.read()
        ttft_ms = round((time.perf_counter() - t0) * 1000)
        if ttft_ms < 200:
            grade = "EXCELLENT"
        elif ttft_ms < 800:
            grade = "GOOD"
        elif ttft_ms < 2000:
            grade = "SLOW"
        else:
            grade = "VERY_SLOW"
        return {"provider": name, "ttft_ms": ttft_ms, "grade": grade, "status": "ok"}
    except urllib.error.HTTPError as e:
        # 429 = rate limit = provider UP mais surchargé
        if e.code == 429:
            return {"provider": name, "ttft_ms": 2000, "grade": "SLOW", "status": "rate_limited"}
        return {"provider": name, "ttft_ms": 9999, "grade": "ERROR", "status": f"HTTP {e.code}"}
    except Exception as e:
        return {"provider": name, "ttft_ms": 9999, "grade": "DOWN", "status": str(e)[:40]}


def _ensure_table():
    conn = sqlite3.connect(str(DB), timeout=3)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provider_scores (
            provider    TEXT PRIMARY KEY,
            agent_id    TEXT,
            ttft_ms     INTEGER DEFAULT 9999,
            grade       TEXT DEFAULT 'UNKNOWN',
            status      TEXT DEFAULT 'unknown',
            measured_at TEXT DEFAULT (datetime('now')),
            priority    INTEGER DEFAULT 5
        )""")
    conn.commit()
    conn.close()


def _update_score(result: dict):
    agent = PROVIDER_TO_AGENT.get(result["provider"], "agt_gemini")
    # Priorité inversement proportionnelle au TTFT
    ttft = result["ttft_ms"]
    prio = 1 if ttft < 200 else 2 if ttft < 500 else 3 if ttft < 1000 else 5 if ttft < 3000 else 9
    conn = sqlite3.connect(str(DB), timeout=3)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        INSERT INTO provider_scores (provider,agent_id,ttft_ms,grade,status,priority)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(provider) DO UPDATE SET
            ttft_ms=excluded.ttft_ms, grade=excluded.grade,
            status=excluded.status, measured_at=datetime('now'),
            priority=excluded.priority
    """,
        (result["provider"], agent, ttft, result["grade"], result["status"], prio),
    )
    conn.commit()
    conn.close()


def run_all(verbose: bool = True) -> list[dict]:
    """Pinger tous les providers en séquence. Retourne liste résultats triés."""
    _ensure_table()
    results = []
    for name, cfg in PROVIDERS_CONFIG.items():
        # Skiper si clé absente (providers cloud sans clé WCM)
        if cfg.get("key_wm") and not _load_key(cfg["key_wm"]):
            if verbose:
                print(f"  -- {name:25s} (clé absente)")
            continue
        r = ping_provider(name, cfg)
        _update_score(r)
        results.append(r)
        if verbose:
            g = r["grade"]
            ttft = r["ttft_ms"]
            sym = (
                "EX" if g == "EXCELLENT" else "OK" if g == "GOOD" else "SL" if g == "SLOW" else "DN"
            )
            bar = "█" * min(20, ttft // 100) + "░" * max(0, 20 - ttft // 100)
            print(f"  {sym} {name:25s} {ttft:5d}ms [{bar}] {r['status']}")
    results.sort(key=lambda x: x["ttft_ms"])
    return results


def best_provider(task_hint: str = "general") -> tuple[str, str]:
    """Retourner le provider le plus rapide disponible pour un type de tâche."""
    try:
        conn = sqlite3.connect(str(DB), timeout=3)
        # Prendre le provider avec la meilleure priorité (le plus bas)
        row = conn.execute("""
            SELECT provider, agent_id FROM provider_scores
            WHERE status='ok' ORDER BY priority ASC, ttft_ms ASC LIMIT 1
        """).fetchone()
        conn.close()
        if row:
            return row[0], row[1]
    except:
        pass
    return "groq/llama-3.1-8b", "agt_groq"  # fallback


def hub_notify_scores(results: list[dict]) -> None:
    try:
        import keyring as _kr

        token = _kr.get_password("Nokido", "FORGE_MCP_TOKEN") or ""
        best = results[0] if results else {}
        msg = (
            f"[PING-MONITOR] {time.strftime('%H:%M')} | "
            + " | ".join(f"{r['provider'].split('/')[0]}={r['ttft_ms']}ms" for r in results[:4])
            + f" | Best: {best.get('provider', '-')} {best.get('ttft_ms', 9999)}ms"
        )
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "hub", "arguments": {"action": "notify", "message": msg}},
                "id": 1,
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except:
        pass


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [ping] %(message)s", datefmt="%H:%M:%S"
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true", help="Boucle continue")
    ap.add_argument("--interval", type=int, default=120, help="Intervalle daemon (s)")
    ap.add_argument("--route", type=str, help="Recommander un provider pour cette requête")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.route:
        provider, agent = best_provider(args.route)
        print(f"Recommandation: {provider} → {agent}")
        return

    if args.daemon:
        LOG.info(f"Ping monitor daemon | interval={args.interval}s")
        while True:
            results = run_all(verbose=not args.quiet)
            hub_notify_scores(results)
            time.sleep(args.interval)
        return

    # One-shot
    print(f"\n=== Nokido Provider Ping {time.strftime('%H:%M:%S')} ===\n")
    results = run_all(verbose=True)
    print(f"\nBest: {results[0]['provider']} — {results[0]['ttft_ms']}ms [{results[0]['grade']}]")


if __name__ == "__main__":
    main()
