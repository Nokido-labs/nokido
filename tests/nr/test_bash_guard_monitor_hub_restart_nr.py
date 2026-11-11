"""NR 9/11 : `forge_job_watch_cli.py --hub-restart` (80e52d764) était REFUSÉ par la liste blanche
Monitor de bash_guard -- le veilleur de restart livré restait hors de portée (capacité morte),
découvert à l'usage. La forme reste close : même script, option sans argument libre.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "bash_guard.py"
CLI = '"%USERPROFILE%/miniforge3/python.exe" "%NOKIDO_ROOT%/tools/forge_job_watch_cli.py"'


def _verdict(cmd: str) -> int:
    evt = {"tool_name": "Monitor", "tool_input": {"command": cmd}}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(evt), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=30).returncode


def test_hub_restart_admis():
    assert _verdict(CLI + " --hub-restart") == 0
    assert _verdict(CLI + " --hub-restart --max-s 600") == 0


def test_forme_toujours_close():
    assert _verdict(CLI + " --hub-restart; whoami") != 0
    assert _verdict(CLI + " --hub-restart C:/Windows") != 0
    assert _verdict(CLI + " --job abc") == 0


def test_task_id_avec_deux_points_admis():
    """NR 10/11 : `task assign` derive l'id de l'intent, « : » compris
    (job_d6cdabe5_..._ci_local_:_arreter_la_su) -- le Monitor `--task` etait refuse,
    le suivi gratuit d'une delegation devenait impossible."""
    assert _verdict(CLI + " --task job_d6cdabe5_1794340507_oauth_ci_local_:_arreter_la_su") == 0
    # 10/11 : intent « NR faux.py orphelins » -> id avec un point
    assert _verdict(CLI + " --task job_14dbcf8c_1794341480_oauth_nkc_nb_cvt_nr_faux.py_orphelins_tue") == 0
    # toujours un identifiant, jamais un chemin ni un chainage
    assert _verdict(CLI + " --task C:/Windows") != 0
    assert _verdict(CLI + " --task a:b; whoami") != 0
    assert _verdict(CLI + " --task a:..\\b") != 0
