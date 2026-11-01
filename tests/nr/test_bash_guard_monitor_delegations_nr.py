"""NR -- Monitor admet le suivi des delegations (owner 22/10, choix multiple « Oui, l'ajouter »).

`forge_job_watch_cli.py --delegations [--de AGENT]` (lecture seule, meme script git-tracke) doit pouvoir reveiller la
boucle comme --job/--task/--pair ; la forme reste CLOSE : un identifiant d'agent, jamais un chemin ni une substitution.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GARDE = ROOT / "tools" / "bash_guard.py"
PY = '"%USERPROFILE%/miniforge3/python.exe"'
CLI = '"%NOKIDO_ROOT%/tools/forge_job_watch_cli.py"'


def _bloque(commande: str) -> bool:
    entree = json.dumps({"tool_name": "Monitor", "tool_input": {"command": commande}})
    r = subprocess.run([sys.executable, str(GARDE)], input=entree, capture_output=True, text=True, errors="replace", timeout=60)
    return "BLOCKED" in (r.stderr or "") or r.returncode == 2


def test_delegations_admis():
    assert not _bloque(f"{PY} {CLI} --delegations")
    assert not _bloque(f"{PY} {CLI} --delegations --de CLAUDE --intervalle 30 --gel 900")


def test_forme_toujours_close():
    assert _bloque(f"{PY} {CLI} --delegations --de C:/chemin")
    assert _bloque(f"{PY} {CLI} --delegations $(whoami)")
    assert _bloque(f"{PY} {CLI} --delegations && del x")


def test_formes_existantes_inchangees():
    assert not _bloque(f"{PY} {CLI} --job job_abc123")
    assert _bloque(f"{PY} {CLI} job_abc123")
