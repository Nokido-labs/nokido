# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_startup_logger
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_startup_logger.py — Logger structuré boot + tracemalloc + __slots__
==========================================================================
Alimente le RAG avec les événements du boot.
Snapshot préventif avant toute écriture RAG.
Profiling mémoire optionnel via tracemalloc.

Usage :
    from forge_startup_logger import boot_step, boot_finalize
    boot_step("settings",   ok=True,  detail="Ring=1 DEV")
    boot_step("rag_engine", ok=True,  detail="2461 chunks")
    boot_step("onnx",       ok=False, error="ONNX absent")
    boot_finalize()
"""


import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.StartupLogger")

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "laforge_rag.db"
_SNAP_DIR = _ROOT / "data" / "snapshots"


# ── BootStep avec __slots__ ───────────────────────────────────────────────────


class BootStep:
    """Étape de boot — __slots__ pour minimiser la RAM."""

    __slots__ = ("name", "ok", "detail", "error", "ms")

    def __init__(self, name: str, ok: bool = True, detail: str = "", error: str = "", ms: float = 0.0) -> None:
        """Init.

        Args:
            name: Description.
            ok: Description.
            detail: Description.
            error: Description.
            ms: Description.
        """
        self.name = name
        self.ok = ok
        self.detail = detail
        self.error = error
        self.ms = ms

    def icon(self) -> str:
        """Icon."""
        if self.ok:
            return "✅"
        if self.error:
            return "❌"
        return "⚠️"

    def to_line(self) -> str:
        """To line."""
        parts = [f"{self.icon()} {self.name}"]
        if self.detail:
            parts.append(f"({self.detail})")
        if self.error:
            parts.append(f"— ERR: {self.error[:60]}")
        if self.ms > 0:
            parts.append(f"[{self.ms:.0f}ms]")
        return " ".join(parts)

    def __repr__(self) -> str:
        """Repr."""
        return f"BootStep({self.name!r}, ok={self.ok})"


# ── StartupLogger avec __slots__ ─────────────────────────────────────────────


class StartupLogger:
    """Collecte les étapes boot, ancre dans le RAG, profile la mémoire."""

    __slots__ = ("session_id", "steps", "_t0", "_mem_enabled", "_mem_snapshot_start")

    def __init__(self, enable_mem_profiling: bool = False) -> None:
        """Init.

        Args:
            enable_mem_profiling: Description.
        """
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.steps: list = []
        self._t0 = time.perf_counter()
        self._mem_enabled = enable_mem_profiling
        self._mem_snapshot_start = None

        if enable_mem_profiling:
            try:
                import tracemalloc

                tracemalloc.start()
                self._mem_snapshot_start = tracemalloc.take_snapshot()
                logger.debug("[Boot] tracemalloc actif")
            except Exception as e:
                logger.debug(f"[Boot] tracemalloc non disponible: {e}")

    def step(self, name: str, ok: bool = True, detail: str = "", error: str = "") -> "StartupLogger":
        """Enregistre une étape du boot."""
        ms = (time.perf_counter() - self._t0) * 1000
        s = BootStep(name=name, ok=ok, detail=detail, error=error, ms=ms)
        self.steps.append(s)

        # Log immédiat structuré
        if ok:
            logger.debug(f"[Boot] {s.icon()} {name}" + (f" — {detail}" if detail else ""))
        else:
            lvl = logging.ERROR if error else logging.WARNING
            logger.log(lvl, f"[Boot] {s.icon()} {name}" + (f" — {error}" if error else f" — {detail}"))
        return self

    def finalize(self, ring: int = 1) -> dict:
        """
        Finalise le boot :
        1. Snapshot mémoire tracemalloc (si activé)
        2. Snapshot SQLite préventif
        3. Insert chunk health RAG
        4. anchor_error() sur les échecs
        """
        total = len(self.steps)
        n_ok = sum(1 for s in self.steps if s.ok)
        n_warn = sum(1 for s in self.steps if not s.ok and not s.error)
        n_err = sum(1 for s in self.steps if not s.ok and s.error)
        elapsed = (time.perf_counter() - self._t0) * 1000

        # ── 1. Profil mémoire tracemalloc ─────────────────────────────────
        mem_summary = ""
        if self._mem_enabled and self._mem_snapshot_start is not None:
            mem_summary = self._collect_mem_profile()
            if mem_summary:
                self.step("mem_profile", ok=True, detail=mem_summary[:80])

        summary = (
            f"BOOT {datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"[{self.session_id}] — "
            f"✅{n_ok} ⚠️{n_warn} ❌{n_err}/{total} "
            f"({elapsed:.0f}ms)"
        )
        lines = [summary] + ["  " + s.to_line() for s in self.steps]
        if mem_summary:
            lines.append(f"  📊 MEM: {mem_summary[:120]}")
        full_text = "\n".join(lines)

        logger.info(f"[Boot] === BOOT COMPLETE ===\n{full_text}")

        # ── 2. Snapshot SQLite préventif ──────────────────────────────────
        self._safe_snapshot()

        # ── 3. Insert RAG health ──────────────────────────────────────────
        self._insert_rag(full_text, ring)

        # ── 4. Ancrer erreurs ─────────────────────────────────────────────
        for s in self.steps:
            if not s.ok and s.error:
                self._anchor_error(s)

        return {
            "ok": n_ok,
            "warn": n_warn,
            "err": n_err,
            "total": total,
            "elapsed_ms": elapsed,
            "session_id": self.session_id,
            "mem_summary": mem_summary,
        }

    # ── Profiling mémoire ─────────────────────────────────────────────────────

    def _collect_mem_profile(self) -> str:
        """Collecte le top-10 tracemalloc et retourne un résumé."""
        try:
            import tracemalloc

            snap_end = tracemalloc.take_snapshot()
            tracemalloc.stop()

            stats = snap_end.compare_to(self._mem_snapshot_start, "lineno")
            top3 = stats[:3]

            lines = []
            for stat in top3:
                kb = stat.size_diff / 1024
                frame = stat.traceback[0] if stat.traceback else None
                loc = f"{Path(frame.filename).name}:{frame.lineno}" if frame else "?"
                lines.append(f"{loc} +{kb:.1f}KB")

            total_kb = sum(s.size_diff for s in stats) / 1024
            summary = f"total+{total_kb:.0f}KB | " + " | ".join(lines)
            logger.info(f"[Boot/MEM] {summary}")

            # Sauvegarder le rapport complet dans logs/
            self._save_mem_report(stats)
            return summary

        except Exception as e:
            logger.debug(f"[Boot/MEM] tracemalloc collect: {e}")
            return ""

    def _save_mem_report(self, stats) -> None:
        """Sauvegarde le rapport mémoire complet dans logs/boot_mem_<ts>.txt."""
        try:
            log_dir = _ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            out_path = log_dir / f"boot_mem_{self.session_id}.txt"
            lines = [f"BOOT MEMORY PROFILE — {self.session_id}", "=" * 60]
            for i, stat in enumerate(stats[:20]):
                kb = stat.size_diff / 1024
                lines.append(f"#{i + 1:02d}  {kb:+8.1f} KB  {stat.traceback[0]}")
            out_path.write_text("\n".join(lines), encoding="utf-8")
            logger.debug(f"[Boot/MEM] rapport → {out_path.name}")
        except Exception as e:
            logger.debug(f"[Boot/MEM] save report: {e}")

    # ── Storage ───────────────────────────────────────────────────────────────

    def _safe_snapshot(self) -> bool:
        """Snapshot SQLite préventif avant écriture RAG."""
        try:
            if not _DB_PATH.exists():
                return False
            _SNAP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = _SNAP_DIR / f"rag_boot_{ts}.db"
            shutil.copy2(str(_DB_PATH), str(snap_path))

            # Garder seulement les 10 derniers snapshots boot
            snaps = sorted(_SNAP_DIR.glob("rag_boot_*.db"), key=lambda f: f.stat().st_mtime)
            for old in snaps[:-10]:
                try:
                    old.unlink()
                except Exception:
                    pass

            logger.debug(f"[Boot] Snapshot RAG → {snap_path.name}")
            return True
        except Exception as e:
            logger.warning(f"[Boot] Snapshot échoué: {e}")
            return False

    def _insert_rag(self, text: str, ring: int) -> bool:
        """Insert chunk health dans le RAG."""
        try:
            if not _DB_PATH.exists():
                return False
            import json

            conn = sqlite3.connect(str(_DB_PATH), timeout=5)
            # 2026-09-12 : borne des 13 896 chunks coupes pile a 2000, et INSERT
            # sans `id` (TEXT PRIMARY KEY) laissant la clef NULLE.
            from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

            _src = f"startup_logger:{self.session_id}"
            conn.execute(
                "INSERT INTO rag_chunks (id, text, source, domain, role_hint, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _cid(_src, text),
                    text,
                    _src,
                    "monitoring",
                    "metric",
                    json.dumps(
                        {
                            "ring": ring,
                            "tags": ["boot", "health", "monitoring"],
                            "session": self.session_id,
                        }
                    ),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"[Boot] RAG insert: {e}")
            return False

    def _anchor_error(self, step: BootStep) -> None:
        """Ancre l'erreur boot dans forge_self_correction."""
        try:
            from nokido_agent.app.forge_self_correction import anchor_error

            anchor_error(
                error_msg=f"[Boot/{step.name}] {step.error}",
                context=f"startup_logger session={self.session_id} ({step.ms:.0f}ms)",
                solution=f"Vérifier {step.name} au démarrage (régression boot auto-détectée)",
                domain="systeme",
            )
        except Exception:
            pass


# ── Hub exec namespace improvement ───────────────────────────────────────────
# Remplace l'exec() dynamique du Hub par un worker queue → moins d'AMSI scans
# Voir forge_hub_worker.py pour l'implémentation

# ── API globale ───────────────────────────────────────────────────────────────

_boot_logger: Optional[StartupLogger] = None


def get_boot_logger(enable_mem: bool = False) -> StartupLogger:
    """Get boot logger.

    Args:
        enable_mem: Description.
    """
    global _boot_logger
    if _boot_logger is None:
        # Activer le profiling mémoire si LAFORGE_MEM_PROFILE=1
        mem = enable_mem or os.environ.get("LAFORGE_MEM_PROFILE") == "1"
        _boot_logger = StartupLogger(enable_mem_profiling=mem)
    return _boot_logger


def boot_step(name: str, ok: bool = True, detail: str = "", error: str = "") -> None:
    """Boot step.

    Args:
        name: Description.
        ok: Description.
        detail: Description.
        error: Description.
    """
    get_boot_logger().step(name, ok=ok, detail=detail, error=error)


def boot_finalize(ring: int = 1) -> dict:
    """Finalise le boot et démarre le watchdog mémoire."""
    # Démarrer le watchdog AVANT finalize pour capturer les allocs du boot
    try:
        from nokido_agent.app.forge_mem_watchdog import get_watchdog

        _wd = get_watchdog()
        _wd.start()
        get_boot_logger().step("mem_watchdog", ok=True, detail=f"warn={_wd.warn_mb}MB dump={_wd.dump_mb}MB")
    except Exception as _we:
        get_boot_logger().step("mem_watchdog", ok=False, error=str(_we)[:60])
    result = get_boot_logger().finalize(ring=ring)
    # Reset pour la prochaine session
    global _boot_logger
    _boot_logger = None
    return result
