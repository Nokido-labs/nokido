# -*- coding: utf-8 -*-
"""forge_provider_watcher.py — Daemon surveillance providers (on-demand) Session 5"""

from __future__ import annotations
import asyncio, time, json, sqlite3, threading
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
_DB_DEFAUT = ROOT / "RAG" / "embeddings.db"
DB = _DB_DEFAUT  # repli seulement : le chemin vivant vient de forge_db_path (_chemin_db) ; une REDIRECTION explicite de DB prime


def _chemin_db() -> Path:
    """Base RAG resolue A CHAQUE appel par l'interrupteur unique forge_db_path (audit Z.ai verifie 8/11, geste 3 :
    `DB` code en dur ignorait toute redirection). Interrupteur illisible -> repli DB, et le DIRE.
    Une redirection EXPLICITE de `DB` (test, appelant) prime : sans elle, un test qui redirigeait DB ecrirait dans la base
    VIVANTE (mesure 8/11 : test_provider_watcher_transport_pas_capacite_nr)."""
    if Path(DB) != _DB_DEFAUT:
        return Path(DB)
    try:
        try:
            from forge_db_path import db_path
        except ImportError:
            from nokido_agent.app.forge_db_path import db_path
        return Path(db_path())
    except Exception as e:  # noqa: BLE001 - interrupteur illisible : repli explicite, jamais muet
        import logging
        logging.getLogger("forge_provider_watcher").warning(
            "forge_db_path illisible (%s) -- repli %s", type(e).__name__, DB)
        return DB

_PROVIDERS_TO_WATCH = [
    {"name": "github_gpt41_mini", "url": "https://models.github.ai/inference/health", "headers": {}},
    {"name": "openrouter_gpt_oss", "url": "https://openrouter.ai/api/v1/models", "headers": {}},
    {"name": "groq_fast", "url": "https://api.groq.com/openai/v1/models", "headers": {}},
    {"name": "ollama_local", "url": "http://127.0.0.1:11434/api/tags", "headers": {}},
    {"name": "llamacpp_local", "url": "http://127.0.0.1:1234/v1/models", "headers": {}},
]

_running = False
_thread = None


def _write_scores(results: dict):
    try:
        conn = sqlite3.connect(str(_chemin_db()), timeout=5)
        # Schéma géré par nokido_hub.py — ne pas recréer
        for name, r in results.items():
            # 21/10 : ces URL sont des CATALOGUES (/api/tags, /v1/models) -- une reponse prouve le TRANSPORT, jamais la
            # CAPACITE (ollama rendait /api/tags en 32 ms sans pouvoir generer). `ok` reste reserve a une generation
            # reelle (forge_llm_router_dt.update_provider_health). NR test_provider_watcher_transport_pas_capacite_nr.
            ok = r.get("ok", False)
            ttft = r.get("ttft_ms") or 9999
            grade = "T" if ok else "F"
            status = "transport" if ok else "down"
            conn.execute(
                "INSERT OR REPLACE INTO provider_scores "
                "(provider, agent_id, ttft_ms, grade, status, measured_at, priority) "
                "VALUES (?,?,?,?,?,datetime('now'),?)",
                (name, "watcher", ttft, grade, status, 5),
            )
        conn.commit()
        conn.close()
        try:
            from nokido_agent.app.forge_trust_score import TrustScoreRegistry

            reg = TrustScoreRegistry.get()
            for name, r in results.items():
                if r.get("ok") and r.get("ttft_ms"):
                    reg.record_success(name, r["ttft_ms"])
                elif not r.get("ok"):
                    reg.record_failure(name)
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_provider_watcher.py', 58, exc_info=True)
    except Exception as e:
        print(f"[watcher] DB: {e}")


def _run_watch():
    global _running
    import sys as _s, os as _o

    _s.path.insert(0, str(ROOT / "app"))
    from nokido_agent.app.forge_ping_monitor import ping_all_providers

    while _running:
        try:
            results = asyncio.run(ping_all_providers(_PROVIDERS_TO_WATCH, timeout=5.0))
            _write_scores(results)
            ok = sum(1 for r in results.values() if r.get("ok"))
            print(f"[watcher] {ok}/{len(results)} UP — {list(results.keys())}")
        except Exception as e:
            print(f"[watcher] {e}")
        time.sleep(300)


def start():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_run_watch, daemon=True, name="provider_watcher")
    _thread.start()
    print("[watcher] démarré")


def stop():
    global _running
    _running = False


if __name__ == "__main__":
    start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop()
