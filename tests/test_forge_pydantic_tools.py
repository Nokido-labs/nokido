"""Tests forge_pydantic_tools - validation + dispatch deterministe."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_pydantic_tools import (  # noqa
    call_tool_validated, list_tools, validate_args,
)


def test_list_tools_includes_expected_4():
    tools = list_tools()
    names = {t["name"] for t in tools}
    assert "view_file_content" in names
    assert "edit_file_block" in names
    assert "run_pytest" in names
    assert "submit_patch" in names


def test_validate_view_file_ok():
    v = validate_args("view_file_content",
                      {"path": "/some/file.py", "start_line": 1})
    assert v["ok"] is True
    assert v["validated"]["path"] == "/some/file.py"
    assert v["validated"]["start_line"] == 1
    # end_line default None
    assert v["validated"]["end_line"] is None


def test_validate_view_file_missing_path():
    v = validate_args("view_file_content", {"start_line": 1})
    assert v["ok"] is False
    assert any("path" in err["loc"] for err in v["validation_errors"])


def test_validate_view_file_start_line_zero():
    v = validate_args("view_file_content",
                      {"path": "x.py", "start_line": 0})
    assert v["ok"] is False
    # ge=1 violated
    assert any("start_line" in err["loc"] for err in v["validation_errors"])


def test_validate_edit_block_empty_old_rejected():
    v = validate_args("edit_file_block",
                      {"path": "x.py", "old_block": "", "new_block": "Y"})
    assert v["ok"] is False
    assert any("old_block" in err["loc"] for err in v["validation_errors"])


def test_validate_run_pytest_timeout_bounds():
    v = validate_args("run_pytest", {"timeout_s": 3})  # < 5 min
    assert v["ok"] is False
    v2 = validate_args("run_pytest", {"timeout_s": 1000})  # > 600 max
    assert v2["ok"] is False


def test_validate_unknown_tool():
    v = validate_args("nonexistent_tool", {})
    assert v["ok"] is False
    assert "unknown tool" in v["error"]
    assert "available" in v


def test_validate_args_as_json_string():
    import json
    v = validate_args("submit_patch",
                      json.dumps({"diff": "fake diff", "rationale": "fix"}))
    assert v["ok"] is True
    assert v["validated"]["diff"] == "fake diff"


def test_validate_invalid_json_string():
    v = validate_args("view_file_content", "{not valid json}")
    assert v["ok"] is False
    assert "not valid JSON" in v["error"]


# === call_tool_validated end-to-end ==========================================

def test_call_view_file_e2e():
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("hello\nworld\n")
        path = f.name
    try:
        out = call_tool_validated(
            "view_file_content", {"path": path, "start_line": 1, "end_line": 2})
        assert out["ok"] is True
        assert out["result"]["ok"] is True
        assert "hello" in out["result"]["content"]
    finally:
        Path(path).unlink(missing_ok=True)


def test_call_edit_block_e2e():
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def f(): return 1\n")
        path = f.name
    try:
        out = call_tool_validated(
            "edit_file_block",
            {"path": path, "old_block": "return 1",
             "new_block": "return 42", "expect_unique": True})
        assert out["ok"] is True
        assert out["result"]["ok"] is True
        assert "return 42" in Path(path).read_text(encoding="utf-8")
    finally:
        Path(path).unlink(missing_ok=True)


def test_call_validation_error_propagates():
    out = call_tool_validated("view_file_content", {"path": "x", "start_line": 0})
    assert out["ok"] is False
    assert "validation_errors" in out
