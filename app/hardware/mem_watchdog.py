# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_mem_watchdog
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_mem_watchdog.py — Watchdog mémoire intelligent
=====================================================
Stratégie production :
  - tracemalloc OFF par défaut (zéro overhead)
  - Activation automatique si RAM > seuil
  - Snapshot périodique en background
  - Dump complet si RAM > seuil critique
  - Stack depth=10 (sweet spot : contexte utile sans overhead)

Usage :
    from forge_mem_watchdog import MemWatchdog
    watchdog = MemWatchdog(warn_mb=300, dump_mb=500)
    watchdog.start()                    # démarre le monitoring
    watchdog.checkpoint("after_rag")   # snapshot nommé manuel
    watchdog.stop()
"""


import gc
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.MemWatchdog")

_ROOT = Path(__file__).resolve().parent.parent.parent  # app/hardware/ → LaForge/
_LOGS_DIR = _ROOT / "logs"

# ── Constantes ────────────────────────────────────────────────────────────────

STACK_DEPTH = 10  # frames tracemalloc — sweet spot prod
POLL_INTERVAL = 30  # secondes entre chaque check RSS
WARN_MB = int(os.environ.get("LAFORGE_MEM_WARN_MB", "300"))
DUMP_MB = int(os.environ.get("LAFORGE_MEM_DUMP_MB", "500"))
SNAPSHOT_COUNT = 20  # top-N lignes dans le dump


# ── Helpers RSS ───────────────────────────────────────────────────────────────


def _rss_mb() -> float:
    """Mémoire RSS du process courant en MB — sans dépendance externe."""
    try:
        import resource  # Linux/macOS

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        pass
    try:
        # Windows
        import ctypes, ctypes.wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize / 1024 / 1024
    except Exception:
        return 0.0


# ── MemWatchdog ───────────────────────────────────────────────────────────────


class MemWatchdog:
    """
    Watchdog mémoire production.
    tracemalloc activé UNIQUEMENT si RAM dépasse le seuil.
    """

    __slots__ = (
        "warn_mb",
        "dump_mb",
        "poll_interval",
        "_active",
        "_tracing",
        "_thread",
        "_snapshots",
        "_baseline",
    )

    def __init__(
        self,
        warn_mb: float = WARN_MB,
        dump_mb: float = DUMP_MB,
        poll_interval: float = POLL_INTERVAL,
    ):
        self.warn_mb = warn_mb
        self.dump_mb = dump_mb
        self.poll_interval = poll_interval
        self._active = False
        self._tracing = False
        self._thread: Optional[threading.Thread] = None
        self._snapshots: list = []
        self._baseline: float = 0.0

    # ── API publique ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Démarre le watchdog en thread daemon."""
        self._active = True
        self._baseline = _rss_mb()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="LaForge-MemWatchdog",
        )
        self._thread.start()
        logger.debug(
            f"[MemWatchdog] Démarré — baseline={self._baseline:.0f}MB warn={self.warn_mb}MB dump={self.dump_mb}MB"
        )

    def stop(self) -> None:
        """Arrête le watchdog et désactive tracemalloc."""
        self._active = False
        self._stop_tracing()
        logger.debug("[MemWatchdog] Arrêté")

    def checkpoint(self, label: str) -> dict:
        """
        Snapshot manuel nommé.
        Si tracemalloc est actif → compare avec le dernier snapshot.
        Retourne un résumé.
        """
        rss = _rss_mb()
        result = {"label": label, "rss_mb": rss, "delta_mb": rss - self._baseline}

        if self._tracing:
            import tracemalloc

            snap = tracemalloc.take_snapshot()
            self._snapshots.append((label, snap))
            if len(self._snapshots) > 1:
                prev_label, prev_snap = self._snapshots[-2]
                stats = snap.compare_to(prev_snap, "lineno")[:5]
                top = [
                    f"{Path(s.traceback[0].filename).name}:{s.traceback[0].lineno} +{s.size_diff / 1024:.1f}KB"
                    for s in stats
                    if s.size_diff > 0
                ]
                result["top_allocs"] = top
                logger.info(f"[MemWatchdog] checkpoint '{label}' RSS={rss:.0f}MB | {' | '.join(top[:3])}")
            else:
                logger.info(f"[MemWatchdog] checkpoint '{label}' RSS={rss:.0f}MB")
        else:
            logger.debug(f"[MemWatchdog] checkpoint '{label}' RSS={rss:.0f}MB (tracing off)")

        return result

    def status(self) -> dict:
        """Retourne l'état courant."""
        rss = _rss_mb()
        return {
            "rss_mb": rss,
            "baseline": self._baseline,
            "delta_mb": rss - self._baseline,
            "tracing": self._tracing,
            "warn_mb": self.warn_mb,
            "dump_mb": self.dump_mb,
            "snapshots": len(self._snapshots),
        }

    # ── Loop interne ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Thread daemon — poll RSS toutes les N secondes."""
        while self._active:
            time.sleep(self.poll_interval)
            if not self._active:
                break
            self._check()

    def _check(self) -> None:
        """Vérifie la RAM et active/désactive tracemalloc selon les seuils."""
        rss = _rss_mb()

        if rss >= self.dump_mb:
            # Seuil critique — activer tracing si pas encore actif ET dump immédiat
            if not self._tracing:
                self._start_tracing()
            self._dump(rss, level="CRITICAL")
            # GC forcé
            gc.collect()
            logger.error(f"[MemWatchdog] 🚨 RAM CRITIQUE {rss:.0f}MB >= {self.dump_mb}MB — dump généré, GC forcé")

        elif rss >= self.warn_mb:
            # Seuil warn — activer tracing pour comprendre
            if not self._tracing:
                self._start_tracing()
                logger.warning(
                    f"[MemWatchdog] ⚠️  RAM={rss:.0f}MB >= warn={self.warn_mb}MB "
                    f"→ tracemalloc activé (depth={STACK_DEPTH})"
                )
            else:
                # Snapshot périodique
                self.checkpoint(f"auto_{datetime.now().strftime('%H%M%S')}")

        else:
            # RAM OK — désactiver tracing si actif (économie overhead)
            if self._tracing:
                self._stop_tracing()
                logger.info(
                    f"[MemWatchdog] ✅ RAM revenue à {rss:.0f}MB < warn={self.warn_mb}MB → tracemalloc désactivé"
                )

    def _start_tracing(self) -> None:
        """Active tracemalloc avec stack depth=10."""
        try:
            import tracemalloc

            if not tracemalloc.is_tracing():
                tracemalloc.start(STACK_DEPTH)  # depth=10 — sweet spot prod
                baseline_snap = tracemalloc.take_snapshot()
                self._snapshots = [("baseline", baseline_snap)]
            self._tracing = True
        except Exception as e:
            logger.warning(f"[MemWatchdog] tracemalloc start: {e}")

    def _stop_tracing(self) -> None:
        """Désactive tracemalloc."""
        try:
            import tracemalloc

            if tracemalloc.is_tracing():
                tracemalloc.stop()
            self._tracing = False
            self._snapshots = []
        except Exception:
            pass

    def _dump(self, rss: float, level: str = "WARN") -> None:
        """Dump complet tracemalloc dans logs/mem_dump_<ts>.txt."""
        try:
            import tracemalloc

            if not tracemalloc.is_tracing():
                return
            snap = tracemalloc.take_snapshot()
            stats = snap.statistics("traceback")[:SNAPSHOT_COUNT]

            _LOGS_DIR.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = _LOGS_DIR / f"mem_dump_{ts}_{level}.txt"

            lines = [
                f"MEMORY DUMP [{level}] — {ts}",
                f"RSS={rss:.0f}MB  baseline={self._baseline:.0f}MB  delta={rss - self._baseline:.0f}MB",
                "=" * 60,
            ]
            for i, stat in enumerate(stats):
                kb = stat.size / 1024
                lines.append(f"\n#{i + 1:02d}  {kb:.1f} KB total")
                for frame in stat.traceback:
                    lines.append(f"    {frame.filename}:{frame.lineno}")

            out_path.write_text("\n".join(lines), encoding="utf-8")
            logger.warning(f"[MemWatchdog] Dump → {out_path.name}")

        except Exception as e:
            logger.warning(f"[MemWatchdog] dump failed: {e}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_watchdog: Optional[MemWatchdog] = None


def get_watchdog(warn_mb: float = WARN_MB, dump_mb: float = DUMP_MB) -> MemWatchdog:
    """Retourne le watchdog singleton."""
    global _watchdog
    if _watchdog is None:
        _watchdog = MemWatchdog(warn_mb=warn_mb, dump_mb=dump_mb)
    return _watchdog


def mem_checkpoint(label: str) -> dict:
    """Raccourci global."""
    return get_watchdog().checkpoint(label)
