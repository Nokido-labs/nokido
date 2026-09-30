# -*- coding: utf-8 -*-
"""
app/forge_python_bin.py — Source de vérité pour l'interpréteur Python
======================================================================
Garantit que tout subprocess Python utilise miniforge3 (l'env Nokido),
pas un `python` ambigu du PATH.

Usage :
    from forge_python_bin import LAFORGE_PYTHON, run_python
    run_python(["-m", "py_compile", "foo.py"], cwd=ROOT)

Override via env (rare, ex: tests CI) :
    LAFORGE_PYTHON_BIN=/path/to/python.exe
"""

from __future__ import annotations

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:python-bin|risk:0.10|color:GREEN]"

import os
import subprocess
import sys
from typing import Sequence

# Source de vérité : env var override > sys.executable du process actuel
LAFORGE_PYTHON: str = os.environ.get("LAFORGE_PYTHON_BIN") or sys.executable


def run_python(args: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run([LAFORGE_PYTHON, *args], **kwargs) avec RÈGLE REMPART."""
    # RÈGLE REMPART ENFANT : forcer UTF-8 dans l'env du child. Sans ça, le python
    # enfant garde stdout cp1252 (console Win FR) et imprime des octets cp1252 que
    # le parent (décodant utf-8 ci-dessous) relit en mojibake ('Ã©levÃ©' au lieu de
    # 'élevé', vu dans les session-logs). cf app/forge_utf8_bootstrap.py.
    try:
        from nokido_agent.app.forge_utf8_bootstrap import child_env
        kwargs["env"] = child_env(kwargs.get("env"))
    except Exception:
        pass
    # RÈGLE REMPART : Gestion d'encodage robuste sur Windows
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        if "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
        if "errors" not in kwargs:
            kwargs["errors"] = "replace"

    try:
        return subprocess.run([LAFORGE_PYTHON, *args], **kwargs)
    except UnicodeDecodeError:
        # Fallback CP1252 si UTF-8 échoue sur Windows
        if sys.platform == "win32" and kwargs.get("encoding") == "utf-8":
            kwargs["encoding"] = "cp1252"
            return subprocess.run([LAFORGE_PYTHON, *args], **kwargs)
        raise


def popen_python(args: Sequence[str], **kwargs) -> subprocess.Popen:
    """subprocess.Popen([LAFORGE_PYTHON, *args], **kwargs)."""
    # Même REMPART ENFANT que run_python : UTF-8 hérité par le child (anti-mojibake).
    try:
        from nokido_agent.app.forge_utf8_bootstrap import child_env
        kwargs["env"] = child_env(kwargs.get("env"))
    except Exception:
        pass
    return subprocess.Popen([LAFORGE_PYTHON, *args], **kwargs)
