# -*- coding: utf-8 -*-
"""NR - les jobs detaches (run_job) SURVIVENT au restart full-stack (rappel owner 2026-09-26).

Doctrine : run_job = « detache, survit au restart ». Rien, dans `nokido_stop.ps1`, ne le
garantissait. Mesure du 2026-09-26 sur une CI de reference en cours (job_d802af896e1f) :
les 6 process du job tournent sous LaForgeSbxOffline ; 3 portent 'Nokido' dans leur ligne
de commande -- le wrapper `sandbox\\jobs\\job_<id>_wrap.py` et les pytest sous
`nokido_proof` -- et tombaient donc dans le reaping des « orphelins Python ». Le mode
-GarderHub n'epargnait que la descendance du hub COURANT : un job lance par un hub
precedent aurait ete abattu.

Contrat : chaque wrapper run_job ET toute sa descendance sont epargnes, dans tous les
modes, pour les python comme pour les node (playwright des gates UI).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus powershell (code appele, Windows)
#   (l.87)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
STOP = ROOT / "tools" / "nokido_stop.ps1"
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PS = shutil.which("powershell") or shutil.which("pwsh")

# Lignes de commande MESUREES le 2026-09-26 (chemins reels, compte LaForgeSbxOffline).
WRAPPER = (r"%USERPROFILE%\miniforge3\envs\laforge_py314\python.exe "
           r"%NOKIDO_ROOT%\sandbox\jobs\job_d802af896e1f_wrap.py")
PAS_UN_WRAPPER = [
    r"%USERPROFILE%\miniforge3\envs\laforge_py314\python.exe -u tools/ci_local.py --reference fdf3349a1",
    r"%USERPROFILE%\miniforge3\python.exe %NOKIDO_ROOT%\tools\nokido_hub.py",
    r"python.exe %NOKIDO_ROOT%\sandbox\jobs\job_d802af896e1f.log",
]


def _src() -> str:
    return STOP.read_text(encoding="utf-8", errors="replace")


def _motif_wrapper() -> str:
    m = re.search(r"\$wrappers = .*?-match '([^']+)'", _src(), re.S)
    assert m, "motif des wrappers run_job introuvable dans nokido_stop.ps1"
    return m.group(1)


def test_le_motif_reconnait_le_wrapper_mesure_et_rien_d_autre():
    motif = re.compile(_motif_wrapper())  # regex .NET et Python : meme syntaxe ici
    assert motif.search(WRAPPER)
    assert motif.search(WRAPPER.replace("\\", "/")), "un chemin a barres obliques reste un wrapper"
    for cl in PAS_UN_WRAPPER:
        assert not motif.search(cl), cl


def test_la_descendance_des_wrappers_est_retiree_des_orphelins_python():
    s = _src()
    i_orph = s.index("$orphans = Get-CimInstance")
    i_jobs = s.index("$jobsGardes = @{}")
    i_kill = s.index("if ($orphans) {", i_orph)
    assert i_orph < i_jobs < i_kill, "la garde des jobs doit filtrer $orphans AVANT le kill"
    bloc = s[i_jobs:i_kill]
    assert "Get-NokidoDescendants -RootPids @($wrappers" in bloc
    assert "$orphans = @($orphans | Where-Object { -not $jobsGardes.ContainsKey" in bloc


def test_la_garde_des_jobs_ne_depend_pas_du_mode_garder_hub():
    s = _src()
    bloc = s[s.index("$jobsGardes = @{}"):s.index("if ($GarderHub -and $orphans)")]
    assert "$GarderHub" not in bloc, "les jobs survivent aussi a l'arret complet"


def test_les_node_d_un_job_sont_gardes_aussi():
    s = _src()
    i_extra = s.index("$extra = Get-CimInstance")
    i_kill = s.index("foreach ($p in @($extra)", i_extra)
    assert "-not $jobsGardes.ContainsKey([int]$_.ProcessId)" in s[i_extra:i_kill]


@pytest.mark.skipif(not _PS, reason="powershell absent de cette machine")
def test_le_stop_parse():
    gate = pytest.importorskip("forge_git_gate")
    assert gate._ps1_parse_gate(["tools/nokido_stop.ps1"]) == 0
