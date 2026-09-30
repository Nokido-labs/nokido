# -*- coding: utf-8 -*-
"""
forge_system_mood.py — Système endocrinien de Nokido (Sprint C)

ANALOGIE BIOLOGIQUE (Damasio, "The Feeling of What Happens", 1999) :
  Le système endocrinien régule l\'organisme de façon lente, globale, par diffusion.
  Ce n\'est pas le cortex (décision rapide) mais l\'humeur de fond qui colore
  toutes les décisions — timeouts, verbosité, agressivité du cache, tolérance aux erreurs.

FONCTIONNEMENT :
  - MoodState : dataclass avec 4 dimensions (energy, curiosity, fatigue, immune_alert)
  - update_mood() : recalcule l\'état depuis les métriques système toutes les 60s
  - broadcast_mood() : publie sur EventBus topic="system.mood" → tous les modules lisent
  - get_mood() : lecture non bloquante depuis le cache mémoire (pas de DB)

INTÉGRATION :
  Les modules qui s\'adaptent au mood lisent via get_mood() et ajustent :
  - forge_llm_router : timeout selon energy (bas → timeout court → fallback rapide)
  - forge_rag_engine : verbosité chunks selon curiosity
  - forge_mcp_security : seuil d\'alerte selon immune_alert
  - forge_biblio_worker : intervalle poll selon fatigue

CYCLE DE VIE :
  start_mood_daemon() → thread daemon 60s loop → update + broadcast
  Pas de NSSM séparé — s\'attache au process hub principal.
"""

from __future__ import annotations
import logging, os, threading, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.SystemMood")

# ── MoodState ────────────────────────────────────────────────────────────────


@dataclass
class MoodState:
    """
    État global diffus de l\'organisme Nokido.
    Valeurs normalisées [0.0 … 1.0] sauf fatigue [0.0 … ∞ heures].

    energy       : 1.0 = pleine forme (CPU/RAM OK), 0.0 = surcharge
    curiosity    : 1.0 = beaucoup de nouvelles requêtes, 0.0 = inactivité
    fatigue      : heures d\'uptime continu (croît, reset au restart)
    immune_alert : 0.0 = calme, 1.0 = attaque en cours (patterns suspects)
    ts           : timestamp UTC de la dernière mise à jour
    """

    energy: float = 1.0
    curiosity: float = 0.5
    fatigue: float = 0.0
    immune_alert: float = 0.0
    ts: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    def is_stressed(self) -> bool:
        return self.energy < 0.3 or self.immune_alert > 0.7

    def is_idle(self) -> bool:
        return self.curiosity < 0.1 and self.fatigue > 4.0

    def recommended_timeout(self, base_s: float = 30.0) -> float:
        """Timeout LLM adaptatif selon l\'énergie."""
        factor = max(0.3, self.energy)
        return round(base_s * factor, 1)

    def recommended_verbosity(self) -> str:
        """Niveau de log adaptatif."""
        if self.immune_alert > 0.5:
            return "DEBUG"
        if self.curiosity > 0.7:
            return "INFO"
        if self.is_idle():
            return "WARNING"
        return "INFO"


# ── Cache mémoire (thread-safe) ───────────────────────────────────────────────

_mood_lock = threading.Lock()
_mood_state = MoodState()
_start_time = time.time()


def get_mood() -> MoodState:
    """Lecture non bloquante — toujours disponible."""
    with _mood_lock:
        return _mood_state


def _set_mood(new_state: MoodState) -> None:
    global _mood_state
    with _mood_lock:
        _mood_state = new_state


# ── Collecte métriques ────────────────────────────────────────────────────────


def _collect_metrics() -> dict:
    """Collecte les métriques système sans dépendances lourdes."""
    metrics = {"cpu": 0.5, "ram": 0.5, "uptime_h": 0.0, "req_per_min": 0.0}
    try:
        import psutil

        metrics["cpu"] = psutil.cpu_percent(interval=0.5) / 100.0
        metrics["ram"] = psutil.virtual_memory().percent / 100.0
    except ImportError:
        # Fallback sans psutil — estimation depuis /proc si dispo
        pass

    metrics["uptime_h"] = (time.time() - _start_time) / 3600.0

    # Requêtes récentes : lire les dernières lignes du network_log
    try:
        from pathlib import Path as _P
        import sqlite3 as _sq

        db = os.environ.get("LAFORGE_DB_PATH", str(_P(__file__).resolve().parent.parent / "RAG" / "embeddings.db"))
        conn = _sq.connect(db, timeout=2)
        one_min_ago = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0).isoformat()[:-6]
        count = conn.execute(
            "SELECT COUNT(*) FROM network_log WHERE ts > ? AND direction='IN'", (one_min_ago,)
        ).fetchone()[0]
        conn.close()
        metrics["req_per_min"] = float(count)
    except Exception:
        pass

    return metrics


def update_mood() -> MoodState:
    """Recalcule MoodState depuis les métriques système."""
    m = _collect_metrics()

    energy = max(0.0, 1.0 - m["cpu"] * 0.6 - m["ram"] * 0.4)
    curiosity = min(1.0, m["req_per_min"] / 20.0)  # seuil 20 req/min = curiosity max
    fatigue = m["uptime_h"]
    immune_alert = 0.0  # mis à jour par forge_mcp_security via set_immune_alert()

    # Conserver l\'immune_alert existant (géré séparément)
    with _mood_lock:
        immune_alert = _mood_state.immune_alert

    new_state = MoodState(
        energy=round(energy, 3),
        curiosity=round(curiosity, 3),
        fatigue=round(fatigue, 2),
        immune_alert=round(immune_alert, 3),
        ts=datetime.now(tz=timezone.utc).isoformat(),
    )
    _set_mood(new_state)
    return new_state


def set_immune_alert(level: float) -> None:
    """Appelé par forge_mcp_security en cas de pattern suspect détecté."""
    level = max(0.0, min(1.0, level))
    with _mood_lock:
        _mood_state.immune_alert = level
    logger.info(f"[SystemMood] immune_alert → {level:.2f}")
    print(f"[SYSTEM_MOOD] immune_alert={level:.2f}", flush=True)


# ── Broadcast EventBus ────────────────────────────────────────────────────────


def broadcast_mood(mood: MoodState) -> None:
    """Trace l'état mood en stdout (EventBus forge_event_bus supprimé)."""

    print(
        f"[SYSTEM_MOOD] e={mood.energy:.2f} c={mood.curiosity:.2f} "
        f"f={mood.fatigue:.1f}h ia={mood.immune_alert:.2f} "
        f"stress={'YES' if mood.is_stressed() else 'no'}",
        flush=True,
    )


# ── Daemon thread ─────────────────────────────────────────────────────────────

_daemon_started = False
_daemon_lock = threading.Lock()
MOOD_INTERVAL = int(os.environ.get("LAFORGE_MOOD_INTERVAL", "60"))


def start_mood_daemon(interval: int = MOOD_INTERVAL) -> threading.Thread:
    """Lance le thread daemon de mise à jour du mood. Idempotent."""
    global _daemon_started
    with _daemon_lock:
        if _daemon_started:
            return None
        _daemon_started = True

    def _loop():
        logger.info(f"[SystemMood] daemon démarré interval={interval}s")
        print(f"[SYSTEM_MOOD] daemon start interval={interval}s", flush=True)
        while True:
            try:
                mood = update_mood()
                broadcast_mood(mood)
            except Exception as exc:
                logger.error(f"[SystemMood] loop error: {exc}")
            time.sleep(interval)

    t = threading.Thread(target=_loop, name="SystemMoodDaemon", daemon=True)
    t.start()
    return t


# ── API publique ──────────────────────────────────────────────────────────────


def mood_summary() -> str:
    """Résumé texte pour TUI/logs."""
    m = get_mood()
    state = "STRESSED" if m.is_stressed() else ("IDLE" if m.is_idle() else "OK")
    return (
        f"[{state}] energy={m.energy:.2f} curiosity={m.curiosity:.2f} "
        f"fatigue={m.fatigue:.1f}h immune={m.immune_alert:.2f} "
        f"timeout_rec={m.recommended_timeout():.0f}s"
    )
