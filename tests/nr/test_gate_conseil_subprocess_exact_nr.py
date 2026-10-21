# -*- coding: utf-8 -*-
"""NR -- le capability-gate ne pretend plus que `run action=python` interdit subprocess (mesure owner 18/10).

Mesure du 18/10 ~23 h 30 (question owner « c'est vraiment une securite ou une contrainte ? ») : sous
`run action=python`, le code tourne sous le compte bac a sable LaForgeSbxOffline et `subprocess.run(["whoami"])`
PASSE. app/forge_workspace_guard.py (L264-315) ne refuse le sous-processus que HORS du compte bac a sable (pool du
hub, gVisor), ou l'audit hook in-process serait contourne ; sous SANDBOX_EXEC c'est la parite avec `run shell`
(27/09). Le conseil du gate, inconditionnel, m'a fait changer de forme sans raison le soir meme : un garde qui
crie a faux se fait desarmer -- on corrige le faux positif.

Contrat (chemin reel : le hook en sous-processus) : un `run action=python` qui contient subprocess.run ne recoit plus
« INTERDIT subprocess » ; le conseil, s'il en reste un, dit la condition (compte bac a sable / pool du hub).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
HOOK = RACINE / "tools" / "hook_capability_gate.py"


def test_le_conseil_subprocess_dit_sa_condition(tmp_path):
    entree = {"tool_name": "mcp__laforge-sovereign-hub__run",
              "tool_input": {"action": "python", "code": "import subprocess\nsubprocess.run(['whoami'])"}}
    env = {**os.environ, "NOKIDO_GATE_ETAT": str(tmp_path / "etat.json"), "NOKIDO_GATE_JOURNAL": str(tmp_path / "j.jsonl"),
           "NOKIDO_GATE_JOBS": str(tmp_path / "jobs"), "PYTHONNOUSERSITE": "1"}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(entree), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, errors="replace", env=env, timeout=60)
    sortie = r.stdout + r.stderr
    assert "INTERDIT subprocess" not in sortie
    if "subprocess" in sortie:
        assert "bac a sable" in sortie or "LaForgeSbx" in sortie
