# -*- coding: utf-8 -*-
"""NR -- les hooks et le veilleur de jobs ecrivent en UTF-8, pas en cp1252 (audit des prompts, 15/10).

Sous Windows, un flux redirige (pipe) prend l'encodage de la console : cp1252. Les refus des hooks
passent par stderr, la sortie du veilleur de jobs est lue par Monitor : l'agent lisait « D�PORT
conseill� » et « TERMINE rc=0 � le rc ». Chaque point d'entree reconfigure stdout ET stderr.

Chemin REEL : le script est execute en `__main__` dans un sous-processus SANS PYTHONIOENCODING ni
PYTHONUTF8 ; un `atexit` du lanceur ecrit un texte accentue sur les deux flux APRES le script, et les
octets recus doivent se decoder en UTF-8 strict. Sans la reconfiguration, ce sont des octets cp1252.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ["tools/forge_tool_gate.py", "tools/hook_recon_first.py", "tools/forge_job_watch_cli.py"]
TEMOIN = "ÉTAT éprouvé à l'arrêt"

_LANCEUR = (
    "import atexit, runpy, sys\n"
    "def _temoin():\n"
    "    for f in (sys.stdout, sys.stderr):\n"
    "        f.write(%r + '\\n'); f.flush()\n"
    "atexit.register(_temoin)\n"
    "sys.argv = [sys.argv[1]]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n" % TEMOIN
)


@pytest.mark.skipif(sys.platform != "win32", reason="l'encodage par defaut d'un pipe n'est cp1252 que sous Windows")
@pytest.mark.parametrize("script", SCRIPTS)
def test_sortie_utf8_stricte(script):
    chemin = ROOT / script
    if not chemin.exists():
        pytest.skip("%s absent" % script)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONUTF8"] = "0"
    p = subprocess.run([sys.executable, "-c", _LANCEUR, str(chemin)], input=b"", capture_output=True,
                       env=env, cwd=str(ROOT), timeout=90)
    for nom, octets in (("stdout", p.stdout), ("stderr", p.stderr)):
        texte = octets.decode("utf-8")          # leve UnicodeDecodeError sur des octets cp1252
        assert TEMOIN in texte, "%s de %s sans le temoin : %r" % (nom, script, texte[-300:])
