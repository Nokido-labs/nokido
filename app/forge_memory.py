"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_memory
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_memory.py — Monitoring et optimisation mémoire pour La Forge.

Composants :
  1. MemoryMonitor  : Suivi temps réel RAM/VRAM avec historique
  2. MemoryProfiler : Profilage par composant (RAG, LLM, PTY, etc.)
  3. MemoryOptimizer: gc.collect, slots, générateurs, nettoyage caches
  4. @memory command : Affichage TUI

Usage :
  from forge_memory import mem_monitor, mem_profiler, mem_optimizer
  mem_monitor.snapshot()       # capture un point mémoire
  mem_profiler.report()        # rapport par composant
  mem_optimizer.optimize()     # libère la mémoire inutilisée
"""

import gc
import sys
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)

# =============================================================================
# 1. MEMORY MONITOR — Suivi temps réel
# =============================================================================


@dataclass
class MemSnapshot:
    timestamp: float
    rss_mb: float  # Resident Set Size (RAM réelle du process)
    vms_mb: float  # Virtual Memory Size
    python_mb: float  # Objets Python trackés par gc
    chunks_count: int  # Nombre de chunks RAG
    chunks_mb: float  # Taille estimée des chunks
    ollama_models: int  # Modèles chargés dans Ollama
    ollama_gb: float  # VRAM estimée Ollama


class MemoryMonitor:
    """Suivi mémoire avec historique circulaire (max 100 snapshots)."""

    def __init__(self, max_history: int = 100) -> None:
        """Init.

        Args:
            max_history: Description.
        """
        self._history: deque = deque(maxlen=max_history)
        self._peak_rss: float = 0.0
        self._baseline_rss: float = 0.0
        self._has_psutil = False
        try:
            import psutil

            self._has_psutil = True
        except ImportError:
            pass

    def snapshot(self, rag_engine=None, mem_mgr=None) -> MemSnapshot:
        """Capture un snapshot mémoire."""
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        rag_engine = _ac.rag_engine
        rss, vms = 0.0, 0.0
        if self._has_psutil:
            try:
                import psutil

                proc = psutil.Process()
                info = proc.memory_info()
                rss = info.rss / (1024 * 1024)
                vms = info.vms / (1024 * 1024)
            except Exception:
                pass
        else:
            # Fallback sans psutil (Windows)
            try:
                import ctypes

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
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
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)
                rss = pmc.WorkingSetSize / (1024 * 1024)
                vms = pmc.PagefileUsage / (1024 * 1024)
            except Exception:
                pass

        # Python gc tracked objects — tracemalloc si disponible, fallback gc
        python_mb = 0.0
        try:
            import tracemalloc

            if tracemalloc.is_tracing():
                _, peak = tracemalloc.get_traced_memory()
                python_mb = round(peak / (1024 * 1024), 1)
            else:
                # Démarrer tracemalloc pour les snapshots futurs
                tracemalloc.start()
                # Fallback : estimation gc sur un échantillon représentatif
                # On prend 2000 objets répartis uniformément (pas juste les 1000 premiers)
                all_objs = gc.get_objects()
                n = len(all_objs)
                if n > 0:
                    step = max(1, n // 2000)
                    sample = all_objs[::step]
                    sampled_size = sum(sys.getsizeof(o) for o in sample)
                    python_mb = round((sampled_size / len(sample)) * n / (1024 * 1024), 1)
                del all_objs, sample
        except Exception:
            pass

        # RAG chunks
        chunks_count = 0
        chunks_mb = 0.0
        if rag_engine and hasattr(rag_engine, "chunks"):
            chunks_count = len(rag_engine.chunks)
            # Estimation : chaque chunk ~4Ko (texte) + ~4Ko (embedding 1024 floats)
            chunks_mb = chunks_count * 8 / 1024

        # Ollama
        ollama_models = 0
        ollama_gb = 0.0

        snap = MemSnapshot(
            timestamp=time.time(),
            rss_mb=round(rss, 1),
            vms_mb=round(vms, 1),
            python_mb=round(python_mb, 1),
            chunks_count=chunks_count,
            chunks_mb=round(chunks_mb, 1),
            ollama_models=ollama_models,
            ollama_gb=ollama_gb,
        )
        self._history.append(snap)
        if rss > self._peak_rss:
            self._peak_rss = rss
        if not self._baseline_rss:
            self._baseline_rss = rss
        return snap

    @property
    def current(self) -> Optional[MemSnapshot]:
        """Current."""
        return self._history[-1] if self._history else None

    @property
    def peak_rss_mb(self) -> float:
        """Peak rss mb."""
        return round(self._peak_rss, 1)

    @property
    def growth_mb(self) -> float:
        """Growth mb."""
        if not self._history or not self._baseline_rss:
            return 0.0
        return round(self._history[-1].rss_mb - self._baseline_rss, 1)

    def trend(self, last_n: int = 10) -> str:
        """Retourne la tendance mémoire : ↑ ↓ →"""
        if len(self._history) < 2:
            return "→"
        recent = list(self._history)[-last_n:]
        if len(recent) < 2:
            return "→"
        delta = recent[-1].rss_mb - recent[0].rss_mb
        if delta > 10:
            return "↑"
        elif delta < -10:
            return "↓"
        return "→"

    def format_status(self) -> str:
        """Ligne de status pour la TUI."""
        s = self.current
        if not s:
            return "RAM: --"
        trend = self.trend()
        return (
            f"RAM {s.rss_mb:.0f}Mo {trend} "
            f"(pic={self.peak_rss_mb:.0f} +{self.growth_mb:.0f}) "
            f"RAG={s.chunks_count}ch/{s.chunks_mb:.0f}Mo"
        )


# =============================================================================
# 2. MEMORY PROFILER — Profilage par composant
# =============================================================================


class MemoryProfiler:
    """Profile mémoire par composant."""

    @staticmethod
    def profile_components(rag_engine=None) -> Dict[str, float]:
        """Retourne la taille estimée par composant en Mo."""
        components = {}

        # RAG chunks
        if rag_engine and hasattr(rag_engine, "chunks"):
            text_size = sum(len(c.get("text", "")) for c in rag_engine.chunks)
            emb_size = sum(
                len(c.get("embedding", [])) * 4  # float32 = 4 bytes
                for c in rag_engine.chunks
                if c.get("embedding")
            )
            components["rag_text"] = round(text_size / (1024 * 1024), 2)
            components["rag_embeddings"] = round(emb_size / (1024 * 1024), 2)

            # Embedding cache
            if hasattr(rag_engine, "emb_cache"):
                cache_size = sum(
                    len(v) * 4 if isinstance(v, list) else sys.getsizeof(v) for v in rag_engine.emb_cache.values()
                )
                components["rag_emb_cache"] = round(cache_size / (1024 * 1024), 2)

            # Session contexts
            if hasattr(rag_engine, "session_ctxs"):
                sess_size = sum(
                    sum(len(m.get("content", "")) for m in ctx.messages)
                    for ctx in rag_engine.session_ctxs.values()
                    if hasattr(ctx, "messages")
                )
                components["rag_sessions"] = round(sess_size / (1024 * 1024), 2)

        # gc stats
        gc_stats = gc.get_stats()
        components["gc_gen0"] = gc_stats[0].get("collected", 0)
        components["gc_gen1"] = gc_stats[1].get("collected", 0)
        components["gc_gen2"] = gc_stats[2].get("collected", 0)

        # Modules chargés
        components["loaded_modules"] = len(sys.modules)

        return components

    @staticmethod
    def find_leaks(threshold_mb: float = 1.0) -> List[Tuple[str, int, float]]:
        """Trouve les types d'objets les plus gros en mémoire.
        Limité à 10 000 objets pour éviter de freezer l'event loop.
        """
        type_sizes: dict = {}
        all_objs = gc.get_objects()
        # Échantillon plafonné — priorité aux gros objets via tri par taille
        sample = all_objs[:10_000] if len(all_objs) > 10_000 else all_objs
        scale = len(all_objs) / max(len(sample), 1)  # facteur d'extrapolation

        for obj in sample:
            t = type(obj).__name__
            s = sys.getsizeof(obj)
            if t not in type_sizes:
                type_sizes[t] = [0, 0]
            type_sizes[t][0] += 1
            type_sizes[t][1] += s

        del all_objs, sample

        results = [
            (t, int(count * scale), (size_b * scale) / (1024 * 1024))
            for t, (count, size_b) in type_sizes.items()
            if (size_b * scale) > threshold_mb * 1024 * 1024
        ]
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:20]


# =============================================================================
# 3. MEMORY OPTIMIZER — Libération active
# =============================================================================


class MemoryOptimizer:
    """Stratégies de libération mémoire."""

    @staticmethod
    def gc_collect() -> int:
        """Force un garbage collection complet."""
        collected = 0
        for gen in range(3):
            collected += gc.collect(gen)
        return collected

    @staticmethod
    def clear_caches(rag_engine=None) -> object:
        """Vide les caches non essentiels."""
        cleared = []

        # Embedding cache (le plus gros consommateur)
        if rag_engine and hasattr(rag_engine, "emb_cache"):
            n = len(rag_engine.emb_cache)
            if n > 50:  # garder les 50 plus récents
                while len(rag_engine.emb_cache) > 50:
                    rag_engine.emb_cache.popitem(last=False)
                cleared.append(f"emb_cache: {n}→50")

        # TTLCache des agents
        # (les TTLCache se vident automatiquement, mais on force)
        cleared.append(f"gc: {MemoryOptimizer.gc_collect()} objets")

        return cleared

    @staticmethod
    def trim_rag_sessions(rag_engine=None, max_sessions: int = 5, max_messages: int = 20) -> object:
        """Réduit les sessions RAG en mémoire."""
        if not rag_engine or not hasattr(rag_engine, "session_ctxs"):
            return 0
        trimmed = 0
        ctxs = rag_engine.session_ctxs
        # Garder seulement les N dernières sessions
        if len(ctxs) > max_sessions:
            keys = list(ctxs.keys())
            for k in keys[:-max_sessions]:
                del ctxs[k]
                trimmed += 1
        # Tronquer les messages par session
        for ctx in ctxs.values():
            if hasattr(ctx, "messages") and len(ctx.messages) > max_messages:
                trimmed += len(ctx.messages) - max_messages
                ctx.messages = ctx.messages[-max_messages:]
        return trimmed

    @staticmethod
    def optimize(rag_engine=None, aggressive: bool = False) -> Dict:
        """Optimisation complète."""
        report = {"actions": []}

        # 1. Trim sessions
        n = MemoryOptimizer.trim_rag_sessions(rag_engine)
        if n:
            report["actions"].append(f"sessions trimmed: {n}")

        # 2. Clear caches
        cleared = MemoryOptimizer.clear_caches(rag_engine)
        report["actions"].extend(cleared)

        # 3. GC
        collected = MemoryOptimizer.gc_collect()
        report["actions"].append(f"gc final: {collected}")

        # 4. Aggressive: clear BM25/FAISS index (rebuilt on next search)
        if aggressive and rag_engine:
            if hasattr(rag_engine, "bm25_index") and rag_engine.bm25_index:
                rag_engine.bm25_index = None
                report["actions"].append("bm25 index cleared")
            if hasattr(rag_engine, "faiss_index") and rag_engine.faiss_index:
                rag_engine.faiss_index = None
                report["actions"].append("faiss index cleared")

        return report


def allocator_stats() -> dict:
    """Introspection de l'allocateur mémoire CPython et gc."""
    import gc
    import sys
    import tracemalloc

    current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, None)
    
    return {
        "allocated_blocks": sys.getallocatedblocks() if hasattr(sys, "getallocatedblocks") else 0,
        "gc_stats": gc.get_stats() if hasattr(gc, "get_stats") else [],
        "gc_counts": gc.get_count(),
        "tracemalloc": (current, peak) if tracemalloc.is_tracing() else None,
    }


# =============================================================================
# SINGLETONS
# =============================================================================

mem_monitor = MemoryMonitor()
mem_profiler = MemoryProfiler()
mem_optimizer = MemoryOptimizer()

__all__ = [
    "MemoryMonitor",
    "MemoryProfiler",
    "MemoryOptimizer",
    "mem_monitor",
    "mem_profiler",
    "mem_optimizer",
    "MemSnapshot",
    "allocator_stats",
]
