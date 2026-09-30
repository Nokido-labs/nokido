"""Tests résurrection v13 — pty_widget + session_context + pty_adapter."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


# ── forge_session_context ───────────────────────────────────────────────────

def test_session_creates_with_uuid():
    from forge_session_context import SessionContext
    ctx = SessionContext(name="t")
    assert len(ctx.session_id) >= 8
    assert ctx.name == "t"
    assert ctx.messages == []


def test_session_add_message():
    from forge_session_context import SessionContext
    ctx = SessionContext(name="t")
    m = ctx.add_message("user", "hello")
    assert m.role == "user"
    assert m.text == "hello"
    assert len(ctx.messages) == 1


def test_session_ring_buffer_cap():
    from forge_session_context import SessionContext
    ctx = SessionContext(name="t", max_messages=5)
    for i in range(10):
        ctx.add_message("user", f"m{i}")
    assert len(ctx.messages) == 5
    # 1er gardé + 4 derniers
    assert ctx.messages[0].text == "m0"
    assert ctx.messages[-1].text == "m9"


def test_session_summarize_truncates():
    from forge_session_context import SessionContext
    ctx = SessionContext(name="t")
    for i in range(30):
        ctx.add_message("user", "x" * 200)
    s = ctx.summarize(max_chars=300)
    assert len(s) <= 300
    assert s.endswith("...")


def test_session_save_load_roundtrip(tmp_path, monkeypatch):
    import forge_session_context as fsc
    monkeypatch.setattr(fsc, "SANDBOX", tmp_path)
    ctx = fsc.SessionContext(name="rt")
    ctx.add_message("user", "hello")
    ctx.add_message("assistant", "pong")
    p = ctx.save()
    assert p is not None and p.exists()
    loaded = fsc.SessionContext.load(p)
    assert loaded is not None
    assert loaded.session_id == ctx.session_id
    assert len(loaded.messages) == 2
    assert loaded.messages[0].role == "user"


def test_session_active_singleton():
    import forge_session_context as fsc
    ctx = fsc.SessionContext(name="active_test")
    fsc.set_active_session(ctx)
    assert fsc.get_active_session() is ctx


# ── forge_pty_widget ────────────────────────────────────────────────────────

def test_pty_widget_imports_or_skips():
    """PTYSession a besoin de pyte+asyncssh. Si absents, instance lève RuntimeError clair."""
    import forge_pty_widget as fpw
    if fpw.HAS_PYTE and fpw.HAS_ASYNCSSH:
        sess = fpw.PTYSession("127.0.0.1", 22, "test")
        assert sess.host == "127.0.0.1"
        assert sess.is_connected is False
    else:
        with pytest.raises(RuntimeError):
            fpw.PTYSession("127.0.0.1", 22, "test")


def test_pty_widget_get_display_empty():
    import forge_pty_widget as fpw
    if not (fpw.HAS_PYTE and fpw.HAS_ASYNCSSH):
        pytest.skip("pyte/asyncssh manquants")
    sess = fpw.PTYSession("127.0.0.1", 22, "test")
    disp = sess.get_display()
    assert isinstance(disp, list)
    # Écran vierge = 24 lignes par défaut, toutes blanches
    assert len(disp) == 24


def test_pty_ring_allowed_unknown_entity():
    import forge_pty_widget as fpw
    ok, reason = fpw._ring_allowed("ghost_entity")
    assert ok is False or "rbac unavailable" in reason


def test_pty_ring_allowed_no_entity():
    """entity_id vide = humain TUI ring 0 = allowed."""
    import forge_pty_widget as fpw
    ok, _ = fpw._ring_allowed("")
    assert ok is True


# ── pty_adapter ─────────────────────────────────────────────────────────────

def test_pty_adapter_session_info_closed():
    from tui_adapters import pty_adapter as pa
    pa._session = None
    info = pa.session_info()
    assert info == {"open": False}


def test_pty_adapter_snapshot_closed():
    from tui_adapters import pty_adapter as pa
    pa._session = None
    snap = pa.snapshot()
    assert snap == ["[no PTY session]"]


def test_pty_adapter_inject_no_session():
    from tui_adapters import pty_adapter as pa
    pa._session = None
    r = asyncio.run(pa.inject_async("ls"))
    assert r is False


def test_pty_adapter_is_open_false():
    from tui_adapters import pty_adapter as pa
    pa._session = None
    assert pa.is_open() is False


def test_pty_adapter_open_async_widget_missing():
    """Si forge_pty_widget importe pas (pyte/asyncssh absent), open retourne False+reason."""
    from tui_adapters import pty_adapter as pa
    with patch.object(pa, "_import_widget", return_value=None):
        ok, reason = asyncio.run(pa.open_async("127.0.0.1", 22, "test"))
    assert ok is False
    assert "indisponible" in reason


def test_pty_adapter_close_no_op_no_session():
    from tui_adapters import pty_adapter as pa
    pa._session = None
    asyncio.run(pa.close_async())  # ne doit pas raise
