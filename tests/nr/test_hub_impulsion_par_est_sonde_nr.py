"""NR -- le hub compte l'impulsion avec le MEME classifieur que le hook de Claude (`hook_capability_gate.est_sonde`).

Mesure 18/10 : le hook ne compte plus les ACTES (commit, run_job, ecriture) depuis 4ce670728, mais le compteur du hub
(app/forge_mcp_registry.py, dispatch `run`) comptait encore toute action python/shell/job_status : un `git commit` lance
par `run action=shell` faisait crier « 3e tour de sondes » cote hub et pas cote hook. Deux classifieurs = deux
verdicts pour le meme appel (derogation owner 18/10 pour toucher le registre).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_capability_gate as G  # noqa: E402

SRC = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")


def _bloc_impulsion() -> str:
    debut = SRC.index("# IMPULSION comptee par le HUB")
    return SRC[debut:SRC.index("_brk3.impulsion(", debut) + 200]


def test_le_dispatch_classe_par_est_sonde():
    bloc = _bloc_impulsion()
    assert re.search(r"import est_sonde as (\w+)", bloc) and re.search(r"if _?est_sonde\w*\(\"run\"", bloc), \
        "le hub doit classer la sonde par hook_capability_gate.est_sonde"
    assert not re.search(r'in \("python", "shell", "job_status"\)', bloc), "second classifieur encore present"


def test_un_acte_n_est_pas_une_sonde_et_une_lecture_l_est():
    assert not G.est_sonde("run", {"action": "shell", "code": "git -c safe.directory=* commit -m x"})
    assert G.est_sonde("run", {"action": "python", "code": "print(open('x.log').read())"})
    assert G.est_sonde("run", {"action": "job_status"})
    assert not G.est_sonde("run", {"action": "run_job", "script": "tools/x.py"})
