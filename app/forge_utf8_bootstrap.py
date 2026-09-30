# -*- coding: utf-8 -*-
"""forge_utf8_bootstrap.py — bootstrap UTF-8 process-wide (Windows), import-first.

PROBLÈME (mesuré) : le `sys.stdout.reconfigure("utf-8")` éparpillé dans Nokido
(forge_python_bin, forge_homeostasis_orchestrator, mcp_server_tools, …) fixe
l'affichage du PROCESS COURANT, mais NE propage PAS l'encodage aux PROCESS
ENFANTS. Un python enfant lancé par un hook/subprocess garde stdout en cp1252
(console Windows FR) → il imprime des octets cp1252 que le parent (qui décode
utf-8) relit en mojibake : « Ã©levÃ© » au lieu de « élevé » (vu dans les
session-logs Nokido / sorties de hooks).

FIX (motif `hermes_bootstrap`, NousResearch/hermes-agent ; cf veille 2026-06-17) :
poser PYTHONUTF8=1 + PYTHONIOENCODING=utf-8 dans os.environ — HÉRITÉS par TOUS
les enfants — AVANT tout spawn, et reconfigurer le stdio courant. À importer
EN PREMIER dans chaque entrypoint/hook (avant tout import qui print/ouvre des
fichiers).

Idempotent. No-op hors Windows (POSIX est déjà UTF-8). Complète (ne remplace pas)
forge_python_bin.run_python, qui injecte aussi child_env() explicitement.
"""
from __future__ import annotations

import os
import sys

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:88|agent:utf8-bootstrap|risk:0.08|color:GREEN]"

_applied = False


def apply() -> bool:
    """Pose l'env UTF-8 process-wide + reconfigure le stdio courant.

    Idempotent (les appels suivants sont no-op). Retourne True si on est sur
    Windows (donc qu'un fix était pertinent), False sinon.
    """
    global _applied
    if _applied:
        return sys.platform == "win32"
    _applied = True
    if sys.platform != "win32":
        return False
    # 1) env hérité par TOUS les enfants — le vrai fix du mojibake subprocess.
    #    setdefault : on ne casse pas un override explicite déjà posé.
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # 2) stdio du process courant — fixe print("é") sans re-exec (-X utf8).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    return True


def child_env(env: dict | None = None) -> dict:
    """Retourne un env (copie d'os.environ, ou de `env` si fourni) avec
    PYTHONUTF8/PYTHONIOENCODING forcés.

    Pour les subprocess qui passent un env EXPLICITE (donc n'héritent pas
    d'os.environ) : garantit que l'enfant imprime/lit en UTF-8.
    """
    e = dict(os.environ if env is None else env)
    e.setdefault("PYTHONUTF8", "1")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


# Auto-apply à l'import : ce module est conçu pour être importé EN PREMIER.
apply()
