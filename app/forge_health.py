# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_health
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_health.py — Tests outils au démarrage + monitoring mémoire (v16.5)
=========================================================================
Vérifie toute la chaîne NR au lancement :
  1. Imports modules clés (pas de NameError latent)
  2. REGISTRY complet + handlers async
  3. DB accessible + schéma valide
  4. Modules externalisés (forge_ssh, forge_ui_widgets, etc.)
  5. Mémoire baseline + détection fuites

Intégré dans on_mount via :
  asyncio.create_task(run_startup_checks(app))

Monitoring continu :
  MemoryWatcher — alerte si croissance > seuil en MB
"""

import asyncio
import gc
import inspect
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# _g resolver
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Résultat d'un check
# ─────────────────────────────────────────────────────────────────────────────


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str = "", duration_ms: float = 0) -> None:
        """Init.

        Args:
            name: Description.
            ok: Description.
            detail: Description.
            duration_ms: Description.
        """
        self.name = name
        self.ok = ok
        self.detail = detail
        self.duration_ms = duration_ms

    def __repr__(self) -> object:
        """Repr."""
        icon = "✅" if self.ok else "❌"
        d = f" ({self.duration_ms:.0f}ms)" if self.duration_ms > 5 else ""
        return f"{icon} {self.name}{d}" + (f": {self.detail}" if self.detail and not self.ok else "")


# ─────────────────────────────────────────────────────────────────────────────
# Checks individuels
# ─────────────────────────────────────────────────────────────────────────────


def _timed(fn) -> Tuple[Any, float]:
    """Timed.

    Args:
        fn: Description.
    """
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000


def check_imports() -> List[CheckResult]:
    """Vérifie que tous les modules externalisés s'importent sans erreur."""
    results = []
    modules = [
        "forge_dispatch",
        "forge_handlers",
        "forge_dispatch_ai",
        "forge_dispatch_network",
        "forge_collab_modes",
        "forge_task_bus",
        "forge_timecode",
        "forge_llm",
        "forge_litellm_bridge",
        "forge_ssh",
        "forge_ui_widgets",
        "forge_settings",
        "forge_rag_mixin",
        "forge_disco",
        "forge_loop",
        "forge_startup",
    ]
    for mod in modules:
        t0 = time.perf_counter()
        try:
            __import__(mod)
            ms = (time.perf_counter() - t0) * 1000
            results.append(CheckResult(f"import.{mod}", True, "", ms))
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            results.append(CheckResult(f"import.{mod}", False, str(e)[:80], ms))
    return results


def check_registry() -> List[CheckResult]:
    """Vérifie le REGISTRY : 26+ cmds, tous async."""
    results = []
    try:
        from nokido_agent.app import forge_dispatch as fd

        cmds = set()
        for k in fd.REGISTRY:
            cmds.update(k) if isinstance(k, tuple) else cmds.add(k)
        results.append(CheckResult("registry.count", len(cmds) >= 26, f"{len(cmds)} cmds"))
        all_async = all(inspect.iscoroutinefunction(fn) for fn in fd.REGISTRY.values())
        results.append(CheckResult("registry.async", all_async))
        # Vérifier les cmds critiques
        for cmd in ["@audit", "@scan", "@collab", "@mode", "@rag", "@tools"]:
            results.append(CheckResult(f"registry.{cmd}", cmd in cmds))
    except Exception as e:
        results.append(CheckResult("registry", False, str(e)[:80]))
    return results


def check_database() -> List[CheckResult]:
    """Vérifie que la DB SQLite est accessible et le schéma valide."""
    results = []
    try:
        import sqlite3

        db = Path(__file__).parent.parent / "RAG" / "embeddings.db"
        if not db.exists():
            return [CheckResult("db.exists", False, str(db))]
        con = sqlite3.connect(str(db))
        con.execute("PRAGMA journal_mode=WAL")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required_tables = {"agent_tasks", "event_log", "rag_chunks", "shared_prompt_log", "global_sequence"}
        missing = required_tables - tables
        results.append(
            CheckResult("db.tables", not missing, f"missing: {missing}" if missing else f"{len(tables)} tables")
        )
        # Test rapide R/W
        con.execute("SELECT COUNT(*) FROM agent_tasks")
        results.append(CheckResult("db.read", True))
        con.close()
    except Exception as e:
        results.append(CheckResult("db", False, str(e)[:80]))
    return results


def check_modules_externalized() -> List[CheckResult]:
    """Vérifie que les modules externalisés exportent bien leurs symboles."""
    results = []
    checks = [
        ("forge_ssh", ["SSHManager", "PTYTerminal", "SSHWizardScreen", "handle_ssh"]),
        ("forge_ui_widgets", ["RoleLightPanel", "VSplitter", "AgentSelector", "MetricsPanel"]),
        ("forge_settings", ["Settings", "_ROOT_DIR", "_DATA_DIR", "create_settings"]),
        ("forge_rag_mixin", ["rag_self_warmup", "index_self_in_rag"]),
        ("forge_disco", ["handle_disco"]),
        ("forge_loop", ["post_loop_safe_check", "propagate_patch"]),
        ("forge_dispatch_ai", ["dispatch_ai"]),
    ]
    for mod_name, symbols in checks:
        try:
            mod = __import__(mod_name)
            for sym in symbols:
                has = hasattr(mod, sym)
                results.append(CheckResult(f"{mod_name}.{sym}", has, "" if has else "manquant"))
        except Exception as e:
            results.append(CheckResult(f"{mod_name}", False, str(e)[:60]))
    return results


def check_no_bare_globals() -> List[CheckResult]:
    """Vérifie statiquement qu'aucun global brut ne traîne dans les modules externalisés."""
    import re as _re

    results = []
    files = {
        "forge_handlers.py": ["version_manager", "rag_engine", "prefect_manager"],
        "forge_dispatch_network.py": ["self"],
        "forge_dispatch_ai.py": ["self"],
    }
    app_dir = Path(__file__).parent
    for fname, bad_names in files.items():
        fpath = app_dir / fname
        if not fpath.exists():
            results.append(CheckResult(f"globals.{fname}", False, "absent"))
            continue
        src = fpath.read_text(encoding="utf-8", errors="ignore")
        # Exclure commentaires et définitions
        body = src[src.find("async def _handle_") :]  # après les handlers
        for name in bad_names:
            pattern = r"(?<!_g\()(?<!\')(?<!\")(?<![_\w])\b" + name + r'\b(?![_\w\'"(])'
            hits = len(_re.findall(pattern, body))
            ok = hits == 0
            results.append(CheckResult(f"globals.{fname}.{name}", ok, f"{hits}x brut" if not ok else ""))
    return results


def check_wrappers() -> List[CheckResult]:
    """Vérifie que les wrappers Nokido.py ont bien try/except."""
    results = []
    import re as _re

    lf_path = Path(__file__).parent / "Nokido.py"
    if not lf_path.exists():
        return [CheckResult("wrappers.Nokido.py", False, "absent")]
    lf = lf_path.read_text(encoding="utf-8", errors="ignore")
    for name in [
        "_handle_audit",
        "_handle_rag",
        "_handle_loop",
        "_handle_mode",
        "_handle_role",
        "_dispatch_ai",
        "_rag_self_warmup",
        "_handle_disco",
    ]:
        m = _re.search(rf"def {_re.escape(name)}\(self[^)]*\):(.*?)(?=\n        (?:async )?def )", lf, _re.DOTALL)
        if m:
            body = m.group(1)
            has_try = "try:" in body
            has_except = "except" in body
            results.append(
                CheckResult(
                    f"wrapper.{name}", has_try and has_except, "" if has_try and has_except else "no try/except"
                )
            )
        else:
            results.append(CheckResult(f"wrapper.{name}", False, "non trouvé"))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Monitoring mémoire
# ─────────────────────────────────────────────────────────────────────────────


class MemoryWatcher:
    """
    Surveille la mémoire RSS du process toutes les `interval` secondes.
    Alerte dans le chat si la croissance dépasse `leak_threshold_mb` MB
    par rapport à la baseline.
    """

    def __init__(
        self,
        interval: float = 60.0,
        leak_threshold_mb: float = 400.0,  # alerte si +400MB depuis baseline
        gc_collect: bool = True,
    ) -> None:
        """Init.

        Args:
            interval: Description.
            leak_threshold_mb: Description.
            gc_collect: Description.
        """
        self.interval = interval
        self.leak_threshold_mb = leak_threshold_mb
        self.gc_collect = gc_collect
        self._baseline_mb: Optional[float] = None
        self._task: Optional[asyncio.Task] = None
        self._history: List[Tuple[float, float]] = []  # (timestamp, mb)

    def _rss_mb(self) -> Optional[float]:
        """Rss mb."""
        try:
            import psutil, os

            return psutil.Process(os.getpid()).memory_info().rss / 1_048_576
        except ImportError:
            # Fallback sans psutil
            try:
                import resource, os

                ru = resource.getrusage(resource.RUSAGE_SELF)
                return ru.ru_maxrss / 1024  # Linux: KB → MB
            except Exception:
                return None

    def start(self, app) -> None:
        """Lance le watcher en arrière-plan."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._watch(app))
        logger.info(f"[MemoryWatcher] démarré (interval={self.interval}s, seuil={self.leak_threshold_mb}MB)")

    def stop(self) -> None:
        """Stop."""
        if self._task and not self._task.done():
            self._task.cancel()

    async def _watch(self, app) -> None:
        """Watch.

        Args:
            app: Description.
        """
        while True:
            await asyncio.sleep(self.interval)
            if self.gc_collect:
                gc.collect()
            mb = self._rss_mb()
            if mb is None:
                continue
            ts = time.monotonic()
            self._history.append((ts, mb))
            # Garder 1h d'historique max
            cutoff = ts - 3600
            self._history = [(t, m) for t, m in self._history if t > cutoff]

            if self._baseline_mb is None:
                self._baseline_mb = mb
                logger.info(f"[MemoryWatcher] baseline={mb:.1f}MB")
                continue

            growth = mb - self._baseline_mb
            logger.debug(f"[MemoryWatcher] RSS={mb:.1f}MB (+{growth:.1f}MB depuis baseline)")

            if growth > self.leak_threshold_mb:
                msg = (
                    f"[bold yellow]⚠ Fuite mémoire détectée[/] "
                    f"RSS={mb:.0f}MB (+{growth:.0f}MB depuis démarrage)\n"
                    f"[dim]→ @tools run gc-collect pour forcer un GC[/]"
                )
                try:
                    app._chat_log().write(msg)
                except Exception:
                    pass
                logger.warning(f"[MemoryWatcher] ALERTE fuite: +{growth:.1f}MB")

    def report(self) -> Dict:
        """Report."""
        mb = self._rss_mb()
        return {
            "current_mb": round(mb, 1) if mb else None,
            "baseline_mb": round(self._baseline_mb, 1) if self._baseline_mb else None,
            "growth_mb": round(mb - self._baseline_mb, 1) if mb and self._baseline_mb else None,
            "history_len": len(self._history),
        }


# Singleton
_watcher: Optional[MemoryWatcher] = None


def get_memory_watcher(interval: float = 60.0) -> MemoryWatcher:
    """Get memory watcher.

    Args:
        interval: Description.
    """
    global _watcher
    if _watcher is None:
        _watcher = MemoryWatcher(interval=interval)
    return _watcher


# ─────────────────────────────────────────────────────────────────────────────
# Suite complète au démarrage
# ─────────────────────────────────────────────────────────────────────────────


async def run_startup_checks(app, verbose: bool = False) -> bool:
    """
    Lance tous les checks au démarrage.
    Affiche un résumé dans le chat si des erreurs sont trouvées.
    Retourne True si tout passe.
    """
    await asyncio.sleep(2)  # Laisser la TUI s'initialiser

    all_results: List[CheckResult] = []

    # Lancer chaque suite dans le thread courant (tout sync sauf l'attente)
    suites = [
        ("imports", check_imports),
        ("registry", check_registry),
        ("database", check_database),
        ("externalized", check_modules_externalized),
        ("globals", check_no_bare_globals),
        ("wrappers", check_wrappers),
    ]

    suite_summary = []
    for suite_name, fn in suites:
        try:
            results = fn()
            all_results.extend(results)
            n_ok = sum(1 for r in results if r.ok)
            n_fail = sum(1 for r in results if not r.ok)
            suite_summary.append((suite_name, n_ok, n_fail))
            if n_fail > 0:
                logger.warning(f"[startup] {suite_name}: {n_fail} échec(s)")
            else:
                logger.debug(f"[startup] {suite_name}: {n_ok} OK")
        except Exception as e:
            logger.error(f"[startup] suite {suite_name}: {e}", exc_info=True)
            suite_summary.append((suite_name, 0, 1))

    # Compter les échecs
    total_fail = sum(n for _, _, n in suite_summary)
    total_ok = sum(n for _, n, _ in suite_summary)

    # Démarrer le watcher mémoire
    watcher = get_memory_watcher()
    watcher.start(app)

    # Écrire dans le chat uniquement si échecs OU verbose
    chat = None
    try:
        chat = app._chat_log()
    except Exception:
        pass

    if chat and (total_fail > 0 or verbose):
        lines_out = [
            f"[bold {'red' if total_fail else 'green'}]"
            f"{'❌' if total_fail else '✅'} Startup checks: "
            f"{total_ok} OK / {total_fail} FAIL[/]"
        ]
        for suite_name, n_ok, n_fail in suite_summary:
            icon = "✅" if n_fail == 0 else "❌"
            lines_out.append(f"  {icon} {suite_name:<18} {n_ok:>2} OK  {n_fail:>2} FAIL")
        if total_fail > 0:
            lines_out.append("\n[bold red]Détails des échecs :[/]")
            for r in all_results:
                if not r.ok:
                    lines_out.append(f"  [red]✗ {r.name}[/] {r.detail}")
        chat.write("\n".join(lines_out))

    # Log complet dans le fichier
    log_path = Path(__file__).parent.parent / "logs" / "startup_checks.log"
    try:
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            from datetime import datetime

            f.write(f"Nokido startup checks — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"{'=' * 60}\n")
            for r in all_results:
                f.write(f"{'OK  ' if r.ok else 'FAIL'} {r.name}: {r.detail}\n")
            f.write(f"\nTotal: {total_ok} OK / {total_fail} FAIL\n")
    except Exception as e:
        logger.warning(f"[startup] log write: {e}")

    if total_fail > 0:
        logger.error(f"[startup] {total_fail} check(s) échoué(s) — voir logs/startup_checks.log")
    else:
        logger.info(f"[startup] tous les checks OK ({total_ok})")

    return total_fail == 0


# ─────────────────────────────────────────────────────────────────────────────
# GC tool pour autotools
# ─────────────────────────────────────────────────────────────────────────────


def force_gc() -> str:
    """Force un GC complet et retourne le rapport mémoire."""
    before = get_memory_watcher()._rss_mb()
    collected = gc.collect()
    after = get_memory_watcher()._rss_mb()
    report = get_memory_watcher().report()
    lines = [
        f"GC forcé : {collected} objets collectés",
        f"  Avant  : {before:.1f}MB" if before else "  Avant  : N/A",
        f"  Après  : {after:.1f}MB" if after else "  Après  : N/A",
    ]
    if before and after:
        freed = before - after
        lines.append(f"  Libéré : {freed:.1f}MB")
    if report.get("growth_mb") is not None:
        lines.append(f"  Croissance depuis démarrage : +{report['growth_mb']:.1f}MB")
    return "\n".join(lines)


def memory_report() -> str:
    """Rapport mémoire détaillé."""
    report = get_memory_watcher().report()
    if report["current_mb"] is None:
        return "Mémoire non disponible (psutil absent — pip install psutil)"
    lines = [
        "Mémoire process :",
        f"  Actuelle  : {report['current_mb']} MB",
        f"  Baseline  : {report['baseline_mb']} MB",
        f"  Croissance: +{report['growth_mb']} MB",
        f"  Historique: {report['history_len']} points",
    ]
    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────────
# get_vitals() — snapshot unifié pour la jauge TUI + /metrics HTTP
# ───────────────────────────────────────────────────────────────────────────────


# Socket ZMQ réutilisable — évite la création/destruction à chaque ping
_zmq_ping_socket = None
_zmq_ping_lock = None


def _ping_brain(port: int = 5557, timeout_ms: int = 500) -> bool:
    """Ping brain_worker ZMQ :5557 — socket persistant, timeout réduit à 500ms."""
    global _zmq_ping_socket, _zmq_ping_lock
    import threading

    if _zmq_ping_lock is None:
        _zmq_ping_lock = threading.Lock()
    try:
        import zmq

        with _zmq_ping_lock:
            # Créer un nouveau socket DEALER (non bloquant) à chaque test
            # REQ bloque si la réponse précédente n'est pas reçue
            ctx = zmq.Context.instance()
            s = ctx.socket(zmq.REQ)
            s.setsockopt(zmq.LINGER, 0)
            s.setsockopt(zmq.RCVTIMEO, timeout_ms)
            s.setsockopt(zmq.SNDTIMEO, 200)
            s.connect(f"tcp://127.0.0.1:{port}")
            try:
                s.send_json({"cmd": "ping"})
                rep = s.recv_json()
                return rep.get("data") == "pong" or "pong" in str(rep)
            finally:
                s.close()
    except Exception:
        return False


def _get_windows_vram() -> Optional[str]:
    """
    Récupère la VRAM totale de l'adaptateur vidéo via WMIC (Windows).
    Retourne une string lisible (ex: "8192 MB") ou None si indisponible.

    Note : c'est la VRAM totale de la carte, pas la charge temps réel.
    Pour la charge réelle DirectML, il faudrait les Performance Counters
    Windows (équivalent de nvidia-smi pour AMD/Intel), non exposés sans
    pilote spécifique. On retourne donc la capacité max, suffisant pour
    le health-check (« ma carte a-t-elle assez de VRAM pour le modèle ? »).
    """
    import sys as _sys

    if _sys.platform != "win32":
        return None
    try:
        import subprocess

        out = subprocess.check_output(
            ["wmic", "path", "Win32_VideoController", "get", "AdapterRAM", "/format:value"],
            timeout=3,
            text=True,
            stderr=subprocess.DEVNULL,
        errors="replace")
        for line in out.splitlines():
            if "AdapterRAM=" in line:
                raw = line.split("=", 1)[1].strip()
                if raw.isdigit():
                    mb = int(raw) // (1024 * 1024)
                    return f"{mb} MB"
    except Exception:
        pass
    return None


def _rag_cache_stats() -> dict:
    """Stats du RagCache singleton sans l'importer au top-level."""
    try:
        from nokido_agent.app.forge_rag_cache import get_rag_cache

        cache = get_rag_cache()
        st = cache.status()
        return {
            "loaded": st.get("loaded", False),
            "n_total": st.get("n_total", 0),
            "n_l1": st.get("n_l1", 0),
            "n_l2": st.get("n_l2", 0),
            "ram_kb": st.get("ram_kb", 0),
            "load_ms": st.get("load_ms", 0),
        }
    except Exception:
        return {"loaded": False, "n_total": 0, "n_l1": 0, "n_l2": 0, "ram_kb": 0}


def _npu_status() -> dict:
    """Statut NPU/DML via le singleton NPUEmbedder."""
    try:
        from nokido_agent.app.forge_npu_embedder import get_npu_embedder

        npu = get_npu_embedder()
        if npu and npu.available:
            return {
                "available": True,
                "provider": npu.provider,
                "ep": npu.session.get_providers()[0] if npu.session else "none",
            }
        return {"available": False, "provider": "none", "ep": "none"}
    except Exception:
        return {"available": False, "provider": "error", "ep": "none"}


# Cache TTL 5s — evite N recomputes pour N requetes HTTP simultanees
_vitals_cache: dict = {}
_vitals_ts: float = 0.0
_VITALS_TTL: float = 5.0


def get_vitals() -> dict:
    """
    Snapshot unifié de l'état système — conçu pour :
      - La jauge TUI (consommé toutes les N secondes via asyncio)
      - L'endpoint GET /metrics (forge_mcp_http.py)
      - Le watchdog autotools

    Structure stable : si un sous-système est absent, son dict
    contient des valeurs neutres, pas d'exception.

    Approx. 15ms d'exécution (ZMQ ping = 1ms si brain online, 800ms timeout sinon).
    Appeler en thread ou avec asyncio.to_thread() depuis la TUI.
    Cache TTL 5s — silencieux si appele plusieurs fois par seconde.
    """
    global _vitals_cache, _vitals_ts
    import time as _t

    if _t.monotonic() - _vitals_ts < _VITALS_TTL and _vitals_cache:
        return _vitals_cache

    import os

    # ── Système (psutil) ─────────────────────────────────────────────
    sys_info: dict = {"rss_mb": None, "cpu_pct": None, "threads": None, "open_handles": None, "gc_counts": None}
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        sys_info["rss_mb"] = round(proc.memory_info().rss / 1_048_576, 1)
        sys_info["cpu_pct"] = proc.cpu_percent(interval=None)  # non-bloquant
        sys_info["threads"] = proc.num_threads()
        sys_info["open_handles"] = (
            proc.num_handles() if hasattr(proc, "num_handles") else proc.num_fds() if hasattr(proc, "num_fds") else None
        )
        sys_info["gc_counts"] = list(gc.get_count())
    except Exception:
        pass

    # ── Mémoire watcher ─────────────────────────────────────────────
    mem_report = get_memory_watcher().report()
    sys_info["growth_mb"] = mem_report.get("growth_mb")
    sys_info["baseline_mb"] = mem_report.get("baseline_mb")

    # ── Bus ZMQ + Circuit Breaker ─────────────────────────────────
    zmq_cb = get_zmq_circuit_breaker()
    zmq_ok = zmq_cb.ping()
    bus_info = {
        "zmq_online": zmq_ok,
        "zmq_port": 5557,
        "zmq_cb_state": zmq_cb.state,
        "zmq_fail_streak": zmq_cb.fail_streak,
        "mcp_transport": "stdio",
    }

    # ── Moteur NPU + RagCache ─────────────────────────────────────
    npu = _npu_status()
    cache = _rag_cache_stats()
    engine_info = {
        "npu_available": npu["available"],
        "npu_provider": npu["provider"],
        "npu_ep": npu["ep"],
        "vram_total": _get_windows_vram(),
        "rag_loaded": cache["loaded"],
        "rag_n_total": cache["n_total"],
        "rag_n_l1": cache["n_l1"],
        "rag_n_l2": cache["n_l2"],
        "rag_ram_kb": cache["ram_kb"],
        "rag_load_ms": cache["load_ms"],
    }

    # ── DB SQLite ───────────────────────────────────────────────────
    db_path = Path(__file__).parent.parent / "RAG" / "embeddings.db"
    db_info: dict = {"exists": db_path.exists(), "size_mb": None, "wal": False}
    if db_path.exists():
        db_info["size_mb"] = round(db_path.stat().st_size / 1_048_576, 1)
        db_info["wal"] = Path(str(db_path) + "-wal").exists()

    from datetime import datetime, timezone

    _result = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": sys_info,
        "bus": bus_info,
        "engine": engine_info,
        "db": db_info,
    }
    import time as _t2

    _vitals_cache = _result
    _vitals_ts = _t2.monotonic()
    return _result


# ───────────────────────────────────────────────────────────────────────────────
# ZMQ Circuit Breaker — basculement RagCache local si brain absent
# ───────────────────────────────────────────────────────────────────────────────


class ZmqCircuitBreaker:
    """
    Circuit Breaker pour la connexion brain_worker ZMQ :5557.

    États :
      closed   → fonctionnel, pings normaux
      open     → 3 échecs consécutifs → RagCache bascule en fallback local
      half_open→ après recovery_s secondes, teste à nouveau

    Comportement :
      - open   : _embed_texts() saute le ZMQ, utilise singleton NPU local directement
      - halert  : log CRITICAL + alerte TUI au passage closed → open
    """

    FAIL_THRESHOLD = 3
    RECOVERY_S = 120  # 2 min entre tentatives (évite spam)

    def __init__(self) -> None:
        """Init."""
        self.state = "closed"  # closed | open | half_open
        self.fail_streak = 0
        self._opened_at = 0.0
        self._lock = __import__("threading").Lock()

    def ping(self) -> bool:
        """Ping brain_worker et met à jour l'état du circuit."""
        with self._lock:
            if self.state == "open":
                if time.monotonic() - self._opened_at >= self.RECOVERY_S:
                    self.state = "half_open"
                    logger.info("[ZmqCB] half_open — test de reconnexion")
                else:
                    return False  # circuit ouvert, ne pas tenter

            ok = _ping_brain()

            if ok:
                if self.state in ("half_open", "open"):
                    logger.info("[ZmqCB] brain_worker reconnecte — circuit closed (streak=%d)", self.fail_streak)
                self.state = "closed"
                self.fail_streak = 0
                self._logged_open = False
                return True
            else:
                self.fail_streak += 1
                if self.fail_streak >= self.FAIL_THRESHOLD and self.state != "open":
                    self.state = "open"
                    self._opened_at = time.monotonic()
                    # Log une seule fois — pas de spam toutes les 3s
                    if not getattr(self, "_logged_open", False):
                        self._logged_open = True
                        logger.warning(
                            "[ZmqCB] Circuit ouvert (%d echecs) — fallback local. Silencieux jusqu'a reconnexion.",
                            self.fail_streak,
                        )
                        try:
                            from nokido_agent.app.forge_rag_cache import get_rag_cache

                            get_rag_cache().invalidate()
                        except Exception:
                            pass
                return False

    @property
    def is_open(self) -> bool:
        """Is open."""
        return self.state == "open"


_zmq_cb: Optional[ZmqCircuitBreaker] = None


def get_zmq_circuit_breaker() -> ZmqCircuitBreaker:
    """Get zmq circuit breaker."""
    global _zmq_cb
    if _zmq_cb is None:
        _zmq_cb = ZmqCircuitBreaker()
    return _zmq_cb


# ───────────────────────────────────────────────────────────────────────────────
# Loguru — audit MASTER_OVERRIDE uniquement
# Philosophie : stdlib QueueHandler pour tout le reste, loguru pour les
# événements Master uniquement (JSON natif + rotation automatiquée).
# ───────────────────────────────────────────────────────────────────────────────

_master_logger_ready = False
_master_logger_path = Path(__file__).parent.parent / "logs" / "master_audit.jsonl"


def get_master_logger() -> object:
    """
    Logger loguru dédié aux actions MASTER_OVERRIDE.
    Init lazy — loguru n'est chargé qu'au premier appel Master.
    Rotation : 10 MB, 5 fichiers max, compression gzip.
    Format : JSON pur (parseable par tout analyseur de logs).
    """
    global _master_logger_ready
    try:
        from loguru import logger as _lu

        if not _master_logger_ready:
            _master_logger_path.parent.mkdir(exist_ok=True)
            # Supprimer handler par défaut loguru (stderr)
            _lu.remove()
            _lu.add(
                str(_master_logger_path),
                format="{message}",  # JSON brut — on format en amont
                rotation="10 MB",
                retention=5,
                compression="gz",
                serialize=False,  # on gère le JSON nous-mêmes
                enqueue=True,  # non-bloquant (thread séparé)
            )
            _master_logger_ready = True
        return _lu
    except ImportError:
        return None


def log_master_action(
    action: str,
    target: str = "",
    details: dict | None = None,
    backup_path: str = "",
    checksum_before: str = "",
) -> None:
    """
    Enregistre une action MASTER_OVERRIDE dans master_audit.jsonl (loguru)
    ET dans event_log SQLite (tracé permanent même si loguru absent).

    Format JSONL :
      {"ts": ISO, "action": str, "target": str, "details": {...},
       "backup_path": str, "checksum_before": str,
       "machine_key": str[:8]}
    """
    import json as _json
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    try:
        from nokido_agent.app.forge_snapshot import get_machine_key

        mk = get_machine_key()[:8]
    except Exception:
        mk = "?"

    entry = {
        "ts": ts,
        "action": action,
        "target": target,
        "details": details or {},
        "backup_path": backup_path,
        "checksum_before": checksum_before,
        "machine_key": mk,
    }

    # ─ loguru JSONL ────────────────────────────────────────
    lu = get_master_logger()
    if lu:
        lu.info(_json.dumps(entry, ensure_ascii=False))

    # ─ event_log SQLite (fallback + persistance garantie) ────────
    try:
        from nokido_agent.app.forge_snapshot import _audit_log

        _audit_log(
            action,
            target,
            {
                **entry,
                "backup_path": backup_path,
                "checksum_before": checksum_before,
            },
        )
    except Exception:
        pass
