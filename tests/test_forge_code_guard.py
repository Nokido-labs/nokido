import pytest
from app.forge_code_guard import DangerGuard, DangerLevel, is_dangerous_code, scan

def test_guard_rm_rf():
    guard = DangerGuard()
    check = guard.check("rm -rf /")
    assert check.level == DangerLevel.FATAL
    assert not check.is_safe

def test_guard_safe_command():
    guard = DangerGuard()
    check = guard.check("ls -la /var/log")
    assert check.level == DangerLevel.SAFE
    assert check.is_safe

def test_is_dangerous_code_eval():
    dangerous, reason = is_dangerous_code("x = eval('1+1')")
    assert dangerous is True
    assert "eval" in reason

def test_scan_code_safe():
    res = scan("def hello():\n    print('world')")
    assert res["safe"] is True
    assert len(res["issues"]) == 0
