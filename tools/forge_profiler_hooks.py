#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_profiler_hooks.py — profilers SUR ÉVÉNEMENT / À LA DEMANDE (jamais continu).

Câble les profilers existants sur des DÉCLENCHEURS (pas de boucle qui sature) :

  Point 3 :
  - profile_if_slow(threshold_s) : décorateur sync/async -> si l'op dépasse le seuil,
    py-spy DUMP le process PENDANT le hang (capture la stack qui bloque l'event-loop
    asyncio ; après-coup serait trop tard). Hook latence.
  - treesitter_gate(code, lang) : valide la STRUCTURE avant écriture disque -> rejette
    un patch swarm cassé sans toucher au fichier. Hook pre-write.
  - uprof_snapshot(seconds) : compteurs APU AMD (RAM unifiée/thermique) à la demande.

  Point 4 :
  - viztrace(output) : context manager timeline asyncio (VizTracer) à la demande.
  - scalene_cmd(script) : commande profil CPU+mem+GPU ligne-à-ligne (Scalene).

Tout FAIL-OPEN : un profileur absent/cassé ne casse JAMAIS l'op profilée.
Installs point 4 (host, hors hub fragile) : pip install viztracer scalene.
"""
from __future__ import annotations

import asyncio
import functools
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
OUT = os.path.join(ROOT, "sandbox", "profiles")
LAFORGE_PY = __import__("os").path.expanduser(r"~\miniforge3\python.exe")


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _ensure_out() -> None:
    try:
        os.makedirs(OUT, exist_ok=True)
    except Exception:
        pass


def _is_coro(fn) -> bool:
    return asyncio.iscoroutinefunction(fn)


# ── Point 3a — py-spy sur hook latence ────────────────────────────────────
def _fire_pyspy_dump(pid: int, label: str) -> None:
    """Dump py-spy d'un process (détaché, fail-open) -> sandbox/profiles/."""
    try:
        _ensure_out()
        out = os.path.join(OUT, f"pyspy_{_ts()}_{label[:20]}_pid{pid}.txt")
        with open(out, "w") as fh:
            subprocess.Popen(
                [LAFORGE_PY, os.path.join(TOOLS, "forge_pyspy_profiler.py"), "dump", str(pid)],
                stdout=fh, stderr=subprocess.STDOUT,
            )
    except Exception:
        pass


def profile_if_slow(threshold_s: float = 10.0, label: str = ""):
    """Décorateur sync/async : arme un dump py-spy si l'op dépasse threshold_s
    (capture la stack PENDANT le hang -> voit QUI bloque l'event-loop)."""

    def deco(fn):
        lbl = label or getattr(fn, "__name__", "op")

        def _arm():
            t = threading.Timer(threshold_s, _fire_pyspy_dump, args=(os.getpid(), lbl))
            t.daemon = True
            t.start()
            return t

        if _is_coro(fn):
            @functools.wraps(fn)
            async def awrap(*a, **k):
                t = _arm()
                try:
                    return await fn(*a, **k)
                finally:
                    t.cancel()
            return awrap

        @functools.wraps(fn)
        def wrap(*a, **k):
            t = _arm()
            try:
                return fn(*a, **k)
            finally:
                t.cancel()
        return wrap

    return deco


# ── Point 3b — tree-sitter sur hook pre-write ─────────────────────────────
def treesitter_gate(code: str, lang: str | None = None, path: str | None = None) -> dict:
    """Valide la structure AVANT écriture. {ok, errors|skipped}. Fail-open."""
    try:
        if TOOLS not in sys.path:
            sys.path.insert(0, TOOLS)
        from nokido_agent.tools.forge_treesitter_validate import validate

        return validate(code, lang=lang, path=path)
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "skipped": f"treesitter indispo: {e}"}


# ── Point 3c — uProf APU à la demande ─────────────────────────────────────
def uprof_snapshot(seconds: int = 20) -> dict:
    """Compteurs APU AMD (détaché) -> sandbox/profiles/. Fail-open."""
    try:
        _ensure_out()
        out = os.path.join(OUT, f"uprof_{_ts()}.log")
        with open(out, "w") as fh:
            subprocess.Popen(
                [LAFORGE_PY, os.path.join(TOOLS, "forge_uprof_apu.py"),
                 "collect", "--seconds", str(seconds)],
                stdout=fh, stderr=subprocess.STDOUT,
            )
        return {"ok": True, "out": out}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ── Point 4 — VizTracer / Scalene à la demande ────────────────────────────
def viztrace(output: str | None = None):
    """Context manager timeline asyncio (VizTracer). Fail-open (nullcontext si absent).
    Install : pip install viztracer."""
    try:
        from viztracer import VizTracer
    except Exception:
        import contextlib

        return contextlib.nullcontext()
    _ensure_out()
    return VizTracer(output_file=output or os.path.join(OUT, f"viztrace_{_ts()}.json"))


def scalene_cmd(script: str, python: str | None = None) -> list[str]:
    """Commande Scalene (CPU+mem+GPU ligne-à-ligne). À lancer host.

    ⚠️ Profile avec l'interpréteur qui porte À LA FOIS scalene ET les deps de la
    CIBLE. Défaut = `sys.executable` (l'interpréteur courant) : profiler depuis un
    process Nokido (env `laforge_py314`) profile CE même env. `LAFORGE_PY`
    (miniforge base) est MINIMAL — il n'a ni faiss ni litellm : y lancer scalene
    sur un script Nokido plante à l'import, pas à cause de scalene mais de l'env.
    Mesure 2026-08-19 : scalene installé dans base ET laforge_py314 (build py314),
    seul laforge_py314 peut profiler le Nokido complet. `python=` force un interp.
    """
    return [python or sys.executable, "-m", "scalene", script]


if __name__ == "__main__":
    print("treesitter_gate ok-code :", treesitter_gate("def f():\n    return 1\n", "python"))
    print("treesitter_gate broken  :", treesitter_gate("def f(:\n  pass", "python"))
    print("uprof_snapshot          :", uprof_snapshot(5))
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    try:
        from nokido_agent.tools.forge_pyspy_profiler import find_pyspy

        print("py-spy                  :", find_pyspy() or "ABSENT (pip install py-spy)")
    except Exception as e:  # noqa: BLE001
        print("py-spy import err       :", e)
