"""tests/test_docker_audit_error_logging.py - Test error path non-muet dans forge_docker_agent._audit."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from app.forge_docker_agent import _audit


def test_docker_agent_audit_error_not_silent(tmp_path, monkeypatch):
    # Set AUDIT to a directory path so open() raises IsADirectoryError or PermissionError
    monkeypatch.setattr("app.forge_docker_agent.AUDIT", tmp_path)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    _audit({"test": "record"})
    output = stderr_buf.getvalue()
    assert "[docker_agent] audit write failed:" in output
