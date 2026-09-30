"""forge_python_runtime.py - Python runtime introspection (3.12 / 3.13 / 3.14 / 3.14t).

Single source of truth for Nokido code that needs to adapt to the active interpreter:
- free-threaded build (PEP 703 / 3.14t no-GIL) -> use more threads, drop ProcessPool overhead
- GIL build -> single-process / asyncio bound
- minor version gates for syntax features (PEP 695 generics, except* groups, type stmt)

Cheap to import. No side effects. Safe in hot paths.
"""

from __future__ import annotations

import os
import sys
from typing import Final

PY_VERSION: Final[tuple[int, int]] = sys.version_info[:2]
PY_312: Final[bool] = PY_VERSION >= (3, 12)
PY_313: Final[bool] = PY_VERSION >= (3, 13)
PY_314: Final[bool] = PY_VERSION >= (3, 14)

# PEP 703 free-threaded build detection.
# 3.13t / 3.14t exposes sys._is_gil_enabled(); GIL build returns True, no-GIL build False.
# Older interpreters lack the attr -> assume GIL on (safe default).
IS_FREE_THREADED: Final[bool] = (
    hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
)

# Convenience alias (3.14t is the dominant Nokido target for parallel embed/agent loops).
IS_NOGIL: Final[bool] = IS_FREE_THREADED


def runtime_summary() -> dict:
    """Return diagnostic snapshot for /health endpoints + logs."""
    return {
        "version": f"{PY_VERSION[0]}.{PY_VERSION[1]}",
        "version_full": sys.version.split()[0],
        "implementation": sys.implementation.name,
        "free_threaded": IS_FREE_THREADED,
        "executable": sys.executable,
        "platform": sys.platform,
    }


def recommended_worker_count(
    io_bound: bool = False,
    model_size_gb: float = 0.0,
    ram_safety_factor: float = 0.75,
) -> int:
    """Suggested thread/process count for parallel workloads.

    Args:
        io_bound: True for IO-bound (network/disk) work. Threads useful even with GIL.
        model_size_gb: per-worker RAM footprint (e.g. 2.5 for BGE-M3 ONNX). 0 = no cap.
        ram_safety_factor: fraction of total RAM allowed (default 0.75 = keep 25% for OS).

    Heuristic:
        - free-threaded + CPU-bound:  min(cores, 8, ram_budget // model)
        - GIL + CPU-bound:            1 (use multiprocessing instead)
        - GIL + IO-bound:             os.cpu_count()
        - free-threaded + IO-bound:   min(cores*2, 16)  (extra threads for IO wait)

    Per Gemini Web 2026-05-29: in ThreadPool no-GIL mode, RAM is the limiter,
    not CPU. Capping by ram_total_gb / model_size_gb prevents OOM crashes when
    spawning N candidates that each load a multi-GB model.
    """
    import os

    cores = os.cpu_count() or 1

    # GIL build paths
    if not IS_NOGIL:
        return cores if io_bound else 1

    # Free-threaded paths
    if io_bound:
        base = min(cores * 2, 16)
    else:
        base = min(cores, 8)

    if model_size_gb > 0:
        try:
            import psutil

            ram_gb = psutil.virtual_memory().total / (1024**3)
            ram_budget = max(1, int((ram_gb * ram_safety_factor) // model_size_gb))
            base = min(base, ram_budget)
        except Exception:
            pass

    return max(1, base)


def check_gil_state(strict: bool = False) -> dict:
    """Re-probe GIL state after extensions loaded.

    On 3.14t, a C extension that hasn't declared free-threading safety
    (Py_mod_gil = Py_MOD_GIL_NOT_USED) will silently re-enable the GIL
    at import time. Call after main imports to detect this regression.

    Args:
        strict: raise RuntimeError if GIL got re-enabled vs startup expectation.

    Returns:
        {"build_supports_nogil": bool, "currently_no_gil": bool, "regressed": bool,
         "warning": str|None}
    """
    build_supports = hasattr(sys, "_is_gil_enabled")
    currently = build_supports and not sys._is_gil_enabled()
    regressed = build_supports and IS_FREE_THREADED and not currently
    warning = None
    if regressed:
        warning = (
            "GIL re-enabled at runtime by a C extension without Py_MOD_GIL_NOT_USED. "
            "Force-disable via env PYTHON_GIL=0 or -Xgil=0 (at your own risk). "
            "Identify culprit with PYTHONWARNINGS=always::RuntimeWarning."
        )
        if strict:
            raise RuntimeError(warning)
    return {
        "build_supports_nogil": build_supports,
        "currently_no_gil": currently,
        "regressed": regressed,
        "warning": warning,
    }


def install_runtime_audit(deny_events: tuple = ()) -> None:
    """Install a lightweight audit hook that denies sensitive Python 3.14 events.

    Complements forge_workspace_guard.build_run_guard_header (which targets
    sandboxed subprocesses). This one is for the main Nokido process.

    Default deny list = empty (opt-in). Pass tuple of event names to block:
        install_runtime_audit(("os.add_dll_directory", "winreg.SetValue"))
    """
    if not deny_events:
        return

    deny = frozenset(deny_events)

    def _hook(event: str, args) -> None:
        if event in deny:
            raise PermissionError(f"LAFORGE_AUDIT: event {event!r} denied")

    sys.addaudithook(_hook)


# ─────────────────────────────────────────────────────────────────────────────
# Per-service Python env map (hybrid runtime per Gemini Web 2026-05-29).
# Hybrid OK = ZMQ/HTTP/MCP cross-version. NEVER pickle across env boundaries.
# Source of truth = proxy_deno/core/services.toml [vars].
# ─────────────────────────────────────────────────────────────────────────────

ENV_MAP: Final[dict] = {
    "PYTHON":      os.path.expanduser("~/miniforge3/python.exe"),
    "PY314":       os.path.expanduser("~/miniforge3/envs/laforge_py314/python.exe"),
    "PY314T":      os.path.expanduser("~/miniforge3/envs/laforge_py314t/python.exe"),
    "PY312_RYZEN": os.path.expanduser("~/miniforge3/envs/ryzen-ai-final/python.exe"),
}

# Service tier -> recommended env. Updated by Acte 5 trigger when wheels ready.
TIER_ENV: Final[dict] = {
    "hub":          "PY314",       # MCP hub, bridges -- mature 3.14 GIL
    "cortex":       "PY314",       # Hebbian, graph, homeostasis
    "daemon_io":    "PY314",       # Poll daemons (gemini, supervisor)  -> migrer PY314T quand wheels OK
    "embed_worker": "PY312_RYZEN", # ONNX NPU Ryzen AI SDK exclusif 3.12
    "legacy":       "PYTHON",      # one-shot migrations, scripts compat
}


def current_env_alias() -> str:
    """Return ENV_MAP key matching sys.executable, or 'unknown'."""
    exe = os.path.normpath(sys.executable).replace("\\", "/").lower()
    for alias, path in ENV_MAP.items():
        if os.path.normpath(path).replace("\\", "/").lower() == exe:
            return alias
    return "unknown"


def env_path(alias: str) -> str:
    """Return absolute python.exe path for an alias. Raise KeyError on unknown."""
    return ENV_MAP[alias]


def recommended_env_for_tier(tier: str) -> str:
    """Return alias of recommended env for a service tier (e.g. 'hub', 'embed_worker')."""
    return TIER_ENV.get(tier, "PYTHON")
