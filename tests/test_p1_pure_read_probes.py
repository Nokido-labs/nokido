"""tests/test_p1_pure_read_probes.py - Test exemption de sondes read-only sous P1 homeostat (dir, tasklist, type, findstr, where)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from app.forge_sandbox_exec import _is_light_probe, _probe_exempt


def test_is_light_probe_pure_read_commands():
    # Pure read commands with or without cmd /c prefix must be recognized as light probes
    assert _is_light_probe("dir") is True
    assert _is_light_probe("cmd /c dir") is True
    assert _is_light_probe("cmd.exe /c dir && dir && dir") is True
    assert _is_light_probe("tasklist") is True
    assert _is_light_probe("cmd /c tasklist") is True
    assert _is_light_probe("type README.md") is True
    assert _is_light_probe("cmd /c type README.md") is True
    assert _is_light_probe("findstr /i test file.txt") is True
    assert _is_light_probe("where git") is True
    assert _is_light_probe("where python") is True
    assert _is_light_probe("dir \"%NOKIDO_WORKSPACE%\"") is True

    # Heavy / malicious commands must be rejected
    assert _is_light_probe("cmd /c python script.py") is False
    assert _is_light_probe("powershell dir") is False
    assert _is_light_probe("cmd /c start calc.exe") is False


def test_probe_exempt_budget():
    assert _probe_exempt("cmd /c dir") is True
