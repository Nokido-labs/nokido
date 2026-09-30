from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-07 | VER:v_forge_token_watchdog_v1
#FORGE:[score:85|agent:agt_claude|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:agt_claude|temp:0.00|risk:0.10|color:GREEN]"

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

logger = logging.getLogger("Nokido.TokenWatchdog")

ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = ROOT / "sandbox" / "token_usage.db"

PROVIDER_COSTS: Dict[str, float] = {
    "agt_github": 0.000003,
    "agt_groq": 0.0000002,
    "agt_mistral": 0.0000004,
    "agt_sambanova": 0.0000003,
    "agt_cohere": 0.0000003,
    "agt_hf": 0.0,
    "agt_ollama": 0.0,
    "agt_claude": 0.000015,
    "agt_gemini": 0.0000005,
}


def _budget_usd() -> float:
    try:
        return float(get_secret("LAFORGE_TOKEN_BUDGET_USD") or "5.0")
    except ValueError:
        return 5.0


class TokenWatchdog:
    """Daemon thread tracking LLM token usage per provider. Throttles on budget exceeded."""

    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TokenWatchdog")
        self._db_lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_events (
                    ts         TEXT NOT NULL,
                    provider   TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    input_tok  INTEGER NOT NULL DEFAULT 0,
                    output_tok INTEGER NOT NULL DEFAULT 0,
                    cost       REAL NOT NULL DEFAULT 0.0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_te_ts ON token_events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_te_prov ON token_events(provider)")
            conn.commit()

    def start(self) -> None:
        self._thread.start()
        logger.info("[TokenWatchdog] started (budget=%.2f/h, interval=%ds)", _budget_usd(), self.check_interval)

    def stop(self) -> None:
        self._stop.set()

    def record(self, provider: str, input_tokens: int, output_tokens: int, session_id: str = "default") -> None:
        cost_per_tok = PROVIDER_COSTS.get(provider, 0.000001)
        cost = (input_tokens + output_tokens) * cost_per_tok
        ts = datetime.now().isoformat()
        with self._db_lock:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                conn.execute(
                    "INSERT INTO token_events(ts,provider,session_id,input_tok,output_tok,cost) VALUES(?,?,?,?,?,?)",
                    (ts, provider, session_id, input_tokens, output_tokens, cost),
                )
                conn.commit()

    def get_usage(self, provider: str, window_sec: int = 3600) -> dict:
        cutoff = (datetime.now() - timedelta(seconds=window_sec)).isoformat()
        with sqlite3.connect(str(_DB_PATH)) as conn:
            row = conn.execute(
                """
                SELECT SUM(input_tok), SUM(output_tok), SUM(cost)
                FROM token_events
                WHERE provider=? AND ts >= ?
            """,
                (provider, cutoff),
            ).fetchone()
        inp, out, cost = (row[0] or 0), (row[1] or 0), (row[2] or 0.0)
        return {"input": inp, "output": out, "total": inp + out, "cost_usd": round(cost, 6)}

    def should_throttle(self, provider: str) -> bool:
        usage = self.get_usage(provider, window_sec=3600)
        return usage["cost_usd"] >= _budget_usd()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.check_interval)
            if self._stop.is_set():
                break
            try:
                self._log_summary()
                self._purge_old()
            except Exception as exc:
                logger.debug("[TokenWatchdog] loop error: %s", exc)

    def _log_summary(self) -> None:
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        with sqlite3.connect(str(_DB_PATH)) as conn:
            rows = conn.execute(
                """
                SELECT provider, SUM(input_tok+output_tok), SUM(cost)
                FROM token_events WHERE ts >= ?
                GROUP BY provider ORDER BY SUM(cost) DESC
            """,
                (cutoff,),
            ).fetchall()
        if rows:
            parts = [f"{r[0]}={r[1]}tok/${r[2]:.4f}" for r in rows]
            logger.info("[TokenWatchdog] 1h usage: %s", " | ".join(parts))

    def _purge_old(self) -> None:
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        with self._db_lock:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                conn.execute("DELETE FROM token_events WHERE ts < ?", (cutoff,))
                conn.commit()


# Singleton
global_watchdog = TokenWatchdog()


def record_tokens(provider: str, input_tokens: int, output_tokens: int, session_id: str = "default") -> None:
    global_watchdog.record(provider, input_tokens, output_tokens, session_id)


if __name__ == "__main__":
    global_watchdog.start()
    global_watchdog.record("agt_github", 500, 200)
    global_watchdog.record("agt_hf", 1000, 800)
    print(global_watchdog.get_usage("agt_github"))
    print("throttle agt_github:", global_watchdog.should_throttle("agt_github"))
    time.sleep(2)
