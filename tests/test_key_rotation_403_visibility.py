"""tests/test_key_rotation_403_visibility.py - Test visibility et eviction 403 provider pool + research_agent."""
import io
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_key_rotation as kr
from app.forge_research_agent import _groq


def test_key_rotation_eviction_logging_and_groq(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_HEALTH", tmp_path / "h.json")
    monkeypatch.setattr(kr, "_pool", lambda e: [("GROQ_API_KEY", "KEY_BAD_123")])

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    # Mark key as 403
    kr.mark_http("GROQ_API_KEY", "KEY_BAD_123", 403)
    out_mark = stderr_buf.getvalue()
    assert "[key_rotation] GROQ_API_KEY" in out_mark
    assert "sortie du pool sain" in out_mark

    # Resolve should log pool exhaustion and return managed=True, key=None
    stderr_buf.truncate(0)
    stderr_buf.seek(0)
    managed, key = kr.resolve("GROQ_API_KEY")
    assert managed is True and key is None
    out_resolve = stderr_buf.getvalue()
    assert "toutes les clés du pool sont invalides" in out_resolve

    # _groq should return ERR:key_pool_exhausted when pool is exhausted
    res = _groq("test prompt")
    assert res == "ERR:key_pool_exhausted"
