"""
forge_watch_agent_worker.py — daemon supervisor pour la veille active.

Wraps `ChainExecutor.execute_pending()` dans un loop poll. Pick tous les
nodes pending de `agent_chain_nodes` (créés par `forge_watch_agent.create_job`)
et les drive séquentiellement étape par étape.

Architecture :
  client (Claude/Gemini/skill) → push_job via /api/watch/create
                              → INSERT watch_jobs + agent_chain_nodes (status=pending)
  ce daemon                   → poll all 30s, exécute chaque node
                              → ingest RAG, store biblio_raw
  client (au besoin)          → poll /api/watch/status/<chain_id>

Ségrégation organes : le daemon ne pilote pas le client. Le client n'orchestre
pas la veille. La queue SQLite (agent_chain_nodes) = membrane découplée.
Heartbeat sandbox/watch_agent_worker.heartbeat lu par supervisor.

Cf [[roadmap-supervisor-autodiagnostic]] pour la future surface métrique.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# stdout/stderr UTF-8 forcé : évite UnicodeEncodeError cp1252 sur les logs
# (incident 2026-06-02 : caractère '→' -> fatal 'charmap' codec, worker mort).
# Couvre TOUS les chemins de lancement (service, run_job, manuel), au-delà de
# PYTHONIOENCODING/PYTHONUTF8 qui ne sont pas garantis selon le launcher.
# JAMAIS sous pytest : reconfigurer le flux de CAPTURE le referme pour les tests
# suivants du meme worker xdist (mesure 2026-09-04). Le worker reel, lui, en a
# besoin -- d'ou la garde plutot que la suppression.
if "pytest" not in sys.modules:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from nokido_agent.app.forge_chain_executor import ChainExecutor  # noqa: E402

DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
HEARTBEAT = SANDBOX / "watch_agent_worker.heartbeat"
INTERVAL_S = 30

_STOP = False


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(f"[{_ts()}] watch_worker: {msg}", flush=True)


def _heartbeat(state: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps({"ts": _ts(), "pid": os.getpid(), **state}, indent=2),
        encoding="utf-8",
    )


def _queue_stats() -> dict:
    """Snapshot état queue agent_chain_nodes pour heartbeat."""
    try:
        conn = sqlite3.connect(str(DB), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
            ).fetchall()
            by_status = {s: c for s, c in rows}
            pending_chains = conn.execute(
                "SELECT COUNT(DISTINCT chain_id) FROM agent_chain_nodes WHERE status='pending'"
            ).fetchone()[0]
            return {"by_status": by_status, "pending_chains": pending_chains}
        finally:
            conn.close()
    except Exception as e:
        return {"error": str(e)[:200]}


def _handle_signal(signum, _frame):
    global _STOP
    _STOP = True
    _log(f"signal {signum} reçu -> stop demandé")


def _check_deps() -> dict:
    """Healthcheck deps optionnelles (searxng, ollama). Log warning si down,
    PAS de crash : pipeline degrade gracieusement (search renvoie [], LLM
    fallback Groq, etc)."""
    import urllib.request as _ur

    out = {}
    for name, url in (
        ("searxng", "http://127.0.0.1:8080/"),
        ("ollama", "http://127.0.0.1:11434/api/version"),
    ):
        try:
            with _ur.urlopen(url, timeout=3) as _:
                out[name] = "ok"
        except Exception as e:
            out[name] = f"DOWN ({type(e).__name__})"
            _log(f"WARN dep {name} down: pipeline degradera ce step (continue)")
    return out


# SANTE DU WORKER et CAPACITE DE VEILLE sont deux choses distinctes, et les
# confondre a une consequence precise : le daemon ecrivait `health: ok` des lors
# que `execute_pending` n'avait pas leve, moteur de recherche a terre ou non.
# Pire, mesure 2026-08-30 : `_check_deps` n'etait appele QU'UNE FOIS, au demarrage
# de la boucle. Une dependance tombee APRES le boot n'etait donc jamais revue, et
# le worker pouvait tourner des jours en se declarant sain. On mesure desormais a
# intervalle borne, et on publie la capacite A COTE de la sante, jamais dedans.
_CAP_INTERVALLE_S = 300
_cap_dernier_ts = 0.0
_cap_etat: dict = {"capacite": "inconnue", "deps": {}}


def _capacite_veille(force: bool = False) -> dict:
    """Etat des dependances de veille, re-mesure au plus toutes les 5 minutes.

    TROIS etats, jamais deux : `complete` (toutes joignables), `reduite` (au moins
    une a terre) et `inconnue` (jamais mesuree). Une capacite qu'on n'a pas pu
    mesurer n'est pas une capacite intacte.

    `reduite` et non `aveugle` : SearXNG a terre, `_call_search` interroge encore
    l'academique OpenAlex/arXiv, qui ne depend pas de Docker. La veille voit moins,
    elle ne cesse pas de voir -- c'est cette nuance qui interdit de bloquer la
    chaine des qu'une dependance tombe.
    """
    global _cap_dernier_ts, _cap_etat
    if force or (time.time() - _cap_dernier_ts) >= _CAP_INTERVALLE_S:
        deps = _check_deps()
        _cap_dernier_ts = time.time()
        _cap_etat = {
            "capacite": "complete" if all(v == "ok" for v in deps.values()) else "reduite",
            "deps": deps,
        }
    return {**_cap_etat,
            "capacite_mesuree_il_y_a_s": round(time.time() - _cap_dernier_ts, 1)}


async def _loop():
    executor = ChainExecutor(db_path=DB)
    cap = _capacite_veille(force=True)
    _log(f"watch_agent_worker UP — interval {INTERVAL_S}s, db={DB}, "
         f"capacite={cap['capacite']} deps={cap['deps']}")
    iter_ = 0
    while not _STOP:
        try:
            import sys
            sys.path.insert(0, "app")
            from nokido_agent.app.forge_endocrine_system import should_pause_worker, get_delay_multiplier
            if should_pause_worker("forge_watch_agent_worker", "background"):
                for _ in range(int(INTERVAL_S * get_delay_multiplier("forge_watch_agent_worker", "background"))):
                    if _STOP:
                        break
                    await asyncio.sleep(1)
                continue
        except Exception:
            pass
        iter_ += 1
        stats_before = _queue_stats()
        t0 = time.time()
        try:
            await executor.execute_pending()
            elapsed = time.time() - t0
            stats_after = _queue_stats()
            _heartbeat(
                {
                    "iter": iter_,
                    "elapsed_s": round(elapsed, 2),
                    "before": stats_before,
                    "after": stats_after,
                    # SANTE DU WORKER : la boucle a tourne, `execute_pending` n'a
                    # pas leve. Ne dit RIEN de ce que la veille peut voir.
                    "health": "ok",
                    # CAPACITE DE VEILLE : publiee a cote, jamais fondue dedans.
                    **_capacite_veille(),
                }
            )
            # Log seulement si quelque chose a bougé
            if stats_before.get("by_status") != stats_after.get("by_status"):
                _log(f"iter={iter_} elapsed={elapsed:.1f}s queue={stats_after}")
        except Exception as e:
            _log(f"execute_pending failed iter={iter_}: {e}")
            _heartbeat({"iter": iter_, "health": "degraded", "error": str(e)[:200],
                        **_capacite_veille()})
        # sleep interruptible
        for _ in range(INTERVAL_S):
            if _STOP:
                break
            await asyncio.sleep(1)
    _log("loop stop")


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        asyncio.run(_loop())
        return 0
    except KeyboardInterrupt:
        _log("KeyboardInterrupt")
        return 0
    except Exception as e:
        _log(f"fatal: {e}")
        _heartbeat({"health": "crit", "fatal": str(e)[:300]})
        return 1


if __name__ == "__main__":
    sys.exit(main())
