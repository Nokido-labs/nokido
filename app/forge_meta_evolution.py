from __future__ import annotations

"""
forge_meta_evolution.py — Meta-boucle evolutive (Phase H)
Surveille les boucles autonomes (homeostasis, hebbian, immune, etc.)
et detecte stagnation / derive / overfit pour suggerer adaptations.
Organe: meta-cortex — surveillance des surveillants.
#FORGE:[score:85|agent:claude-sonnet-4-6|temp:0.00|color:GREEN|attempt:1]
"""

import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("Nokido.MetaEvolution")

SANDBOX = ROOT / "sandbox"
DB = ROOT / "RAG" / "embeddings.db"

# Heartbeats surveilles
WATCHED_DAEMONS = [
    "homeostasis_orchestrator",
    "gemini_poll_daemon",
    "health_diagnostic",
    "hebbian_linker",
]

HEARTBEAT_MAX_AGE_S = 600  # daemon considered stale if heartbeat > 10min old
STAGNATION_CYCLES = 5  # N cycles sans amelioration = stagnation


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DaemonHealth:
    name: str
    last_beat: datetime | None
    age_s: float
    status: str  # alive|stale|missing
    last_metric: dict = field(default_factory=dict)


@dataclass
class MetaSignal:
    signal_type: str  # stagnation|drift|overfit|anomaly|healthy
    daemon: str
    confidence: float
    evidence: str
    suggestion: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Heartbeat reader
# ─────────────────────────────────────────────────────────────────────────────


def _read_heartbeat(name: str) -> DaemonHealth:
    hb_path = SANDBOX / f"{name}.heartbeat"
    if not hb_path.exists():
        return DaemonHealth(name=name, last_beat=None, age_s=9999.0, status="missing")

    try:
        data = json.loads(hb_path.read_text(encoding="utf-8"))
        ts_str = data.get("ts") or data.get("timestamp", "")
        last_beat = datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
        age_s = (datetime.now() - last_beat).total_seconds()
        # use daemon's own interval_s (×2 grace) if higher than global threshold
        daemon_interval = data.get("interval_s", 0)
        max_age = max(HEARTBEAT_MAX_AGE_S, daemon_interval * 2)
        status = "alive" if age_s < max_age else "stale"
        return DaemonHealth(name=name, last_beat=last_beat, age_s=round(age_s, 1), status=status, last_metric=data)
    except Exception as e:
        return DaemonHealth(name=name, last_beat=None, age_s=9999.0, status="missing", last_metric={"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# RAG evolution trend
# ─────────────────────────────────────────────────────────────────────────────


def _rag_trend(window_hours: int = 24) -> dict:
    """Compte nouveaux chunks RAG sur la fenetre (signal d apprentissage)."""
    try:
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        conn = sqlite3.connect(str(DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        new_chunks = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE ingested_at > ?", (cutoff,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        antibodies = 0
        try:
            antibodies = conn.execute("SELECT COUNT(*) FROM immune_antibodies").fetchone()[0]
        except Exception:
            pass
        conn.close()
        return {"new_chunks_24h": new_chunks, "total_chunks": total, "antibodies": antibodies}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Signal detectors
# ─────────────────────────────────────────────────────────────────────────────


def _detect_stagnation(health: list[DaemonHealth], rag: dict) -> list[MetaSignal]:
    signals: list[MetaSignal] = []

    # Tous les daemons stales = homeostasis overactive (sleep too aggressive)
    stale = [h for h in health if h.status == "stale"]
    if len(stale) >= len(health) * 0.5:
        signals.append(
            MetaSignal(
                signal_type="stagnation",
                daemon="homeostasis",
                confidence=0.75,
                evidence=f"{len(stale)}/{len(health)} daemons stales",
                suggestion="Verifier NokidoHomeostasis — seuil RAM trop bas ou grace period insuffisant",
            )
        )

    # RAG stagnation: 0 nouveaux chunks depuis 24h
    if rag.get("new_chunks_24h", 1) == 0:
        signals.append(
            MetaSignal(
                signal_type="stagnation",
                daemon="rag_engine",
                confidence=0.65,
                evidence="0 nouveaux chunks RAG en 24h",
                suggestion="Verifier forge_post_commit.py + forge_conv_indexer.py",
            )
        )

    return signals


def _detect_drift(health: list[DaemonHealth]) -> list[MetaSignal]:
    signals: list[MetaSignal] = []
    # Daemon revient souvent (restarts eleves = crash loop)
    for h in health:
        restarts = h.last_metric.get("restart_count", 0) or h.last_metric.get("restarts", 0)
        if isinstance(restarts, (int, float)) and restarts > 10:
            signals.append(
                MetaSignal(
                    signal_type="drift",
                    daemon=h.name,
                    confidence=0.80,
                    evidence=f"restart_count={restarts}",
                    suggestion=f"Investiguer logs sandbox/{h.name}.log — crash loop potentiel",
                )
            )
    return signals


def _detect_anomaly(health: list[DaemonHealth]) -> list[MetaSignal]:
    signals: list[MetaSignal] = []
    missing = [h for h in health if h.status == "missing"]
    for h in missing:
        signals.append(
            MetaSignal(
                signal_type="anomaly",
                daemon=h.name,
                confidence=0.90,
                evidence=f"heartbeat absent: sandbox/{h.name}.heartbeat",
                suggestion=f"Waker via /supervisor/wake/{h.name} ou verifier NSSM",
            )
        )
    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Entry points MCP
# ─────────────────────────────────────────────────────────────────────────────


def forge_meta_scan() -> dict:
    """
    MCP-callable. Scan global: heartbeats + RAG + signaux.
    Retourne tableau de bord meta-evolution.
    """
    t0 = time.monotonic()

    health = [_read_heartbeat(name) for name in WATCHED_DAEMONS]
    rag = _rag_trend(window_hours=24)

    signals: list[MetaSignal] = []
    signals += _detect_stagnation(health, rag)
    signals += _detect_drift(health)
    signals += _detect_anomaly(health)

    # Score global sante (0=critique, 1=parfait)
    alive_ratio = sum(1 for h in health if h.status == "alive") / max(1, len(health))
    critical = [s for s in signals if s.confidence >= 0.80]
    health_score = round(alive_ratio * (1.0 - 0.2 * len(critical)), 3)

    result = {
        "ts": datetime.now().isoformat(),
        "health_score": health_score,
        "daemons": [{"name": h.name, "status": h.status, "age_s": h.age_s} for h in health],
        "rag": rag,
        "signals": [
            {
                "type": s.signal_type,
                "daemon": s.daemon,
                "confidence": round(s.confidence, 2),
                "evidence": s.evidence,
                "suggestion": s.suggestion,
            }
            for s in signals
        ],
        "elapsed_s": round(time.monotonic() - t0, 3),
    }

    # Anchor si signaux critiques detectes
    if critical:
        try:
            from nokido_agent.app.forge_self_correction import anchor_error

            for s in critical[:2]:
                anchor_error(
                    error_msg=f"meta_evolution: {s.signal_type} {s.daemon}",
                    context=s.evidence,
                    solution=s.suggestion,
                    domain="systeme",
                )
        except Exception:
            pass

    logger.info(f"MetaEvolution scan: score={health_score} signals={len(signals)}")
    return result


def forge_meta_suggest(scan_result: dict) -> list[str]:
    """MCP-callable. Liste des actions suggeres a partir d un scan."""
    return [s["suggestion"] for s in scan_result.get("signals", []) if s.get("suggestion")]


if __name__ == "__main__":
    result = forge_meta_scan()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    suggestions = forge_meta_suggest(result)
    if suggestions:
        print("\nSuggestions:")
        for s in suggestions:
            print(f"  - {s}")
