# -*- coding: utf-8 -*-
"""NR -- le garde d'impulsion ne compte plus comme « sonde » un appel qui AGIT (decision owner 18/10).

Mesure du 18/10 (journal assaini e6c365dbf) : 570 « serait refuse » reels, ~250/jour, dont une large part sont des
etapes DEPENDANTES -- ecrire, lancer les tests, committer -- et non du polling. Owner : « affiner puis remesurer » --
rester en observer ; ne plus compter un run qui agit (commit, pytest) ni un Bash git ; remesurer 2 jours.

Contrats :
  1. `est_sonde` (pur) : run python/shell qui lance pytest ou un git d'ecriture (commit, add, push, cherry-pick,
     checkout, restore, rm, mv) -> False ; Bash dont la commande commence par git -> False ; run python/shell
     ordinaire, run job_status, Bash ordinaire -> True ; tout autre outil -> False ;
  2. chemin reel (hook lance en sous-processus, etat et journal dans tmp_path) : 3 tours de pytest en 90 s ne
     produisent aucun « serait refuse » ; 3 tours de sondes ordinaires en produisent un (temoin).
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HOOK = RACINE / "tools" / "hook_capability_gate.py"
RUN = "mcp__laforge-sovereign-hub__run"

_spec = importlib.util.spec_from_file_location("hook_capability_gate_nr_actes", HOOK)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


@pytest.mark.parametrize("outil, entree, attendu", [
    (RUN, {"action": "shell", "code": "cd x && python -m pytest tests/nr/a.py -q"}, False),
    (RUN, {"action": "shell", "code": "git -c safe.directory=* add a.py && git -c safe.directory=* commit -q -m x"}, False),
    (RUN, {"action": "shell", "commands": ["git push origin alpha"]}, False),
    (RUN, {"action": "python", "code": "import subprocess; subprocess.run(['pytest','-q'])"}, False),
    (RUN, {"action": "shell", "code": "git -c safe.directory=* log --oneline -3"}, True),
    (RUN, {"action": "python", "code": "print(1)"}, True),
    (RUN, {"action": "job_status", "job_id": "job_x"}, True),
    (RUN, {"action": "run_job", "script": "tools/x.py"}, False),
    ("Bash", {"command": "git log --oneline -5"}, False),
    ("Bash", {"command": "  git -c safe.directory=* status"}, False),
    ("Bash", {"command": "curl -s http://127.0.0.1:8766/health"}, True),
    ("Read", {"file_path": "x"}, False),
])
def test_est_sonde(outil, entree, attendu):
    assert G.est_sonde(outil, entree) is attendu


def _appel(tmp_path, t, outil, entree):
    env = {**os.environ, "NOKIDO_GATE_ETAT": str(tmp_path / "etat.json"), "NOKIDO_GATE_MODE": "observer",
           "NOKIDO_GATE_HORLOGE": str(t), "NOKIDO_GATE_JOBS": str(tmp_path / "jobs"), "PYTHONNOUSERSITE": "1",
           "NOKIDO_GATE_JOURNAL": str(tmp_path / "journal.jsonl")}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": outil, "tool_input": entree}),
                       capture_output=True, text=True, errors="replace", env=env, timeout=60)
    return r.stdout + r.stderr


def _refus(tmp_path):
    j = tmp_path / "journal.jsonl"
    return [x for x in (j.read_text(encoding="utf-8").splitlines() if j.exists() else []) if "impulsion" in x]


def test_trois_tours_de_pytest_ne_sont_pas_une_rafale(tmp_path):
    t0 = 1_800_000_000
    for d in (0, 10, 20):
        _appel(tmp_path, t0 + d, RUN, {"action": "shell", "code": "python -m pytest tests/nr/a.py -q"})
    assert _refus(tmp_path) == []


def test_trois_tours_de_sondes_restent_une_rafale(tmp_path):
    t0 = 1_800_000_000
    for d in (0, 10, 20):
        _appel(tmp_path, t0 + d, RUN, {"action": "python", "code": "print(1)"})
    assert len(_refus(tmp_path)) == 1
