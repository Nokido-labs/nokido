"""Tests forge_repo_map_tools - view/edit/insert/restore deterministes."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_repo_map_tools import (  # noqa
    edit_file_block, insert_at_line, restore_backup, view_file_content,
)


def _tmpfile(content: str) -> str:
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(content)
        return f.name


# === view_file_content =======================================================

def test_view_full_file():
    p = _tmpfile("line1\nline2\nline3\n")
    try:
        r = view_file_content(p)
        assert r["ok"] is True
        assert "line1" in r["content"]
        assert "line3" in r["content"]
        assert r["lines"] == 3
    finally:
        Path(p).unlink(missing_ok=True)


def test_view_window():
    p = _tmpfile("a\nb\nc\nd\ne\n")
    try:
        r = view_file_content(p, start_line=2, end_line=4)
        assert r["ok"] is True
        assert r["content"] == "b\nc\nd"
        assert r["lines"] == 3
    finally:
        Path(p).unlink(missing_ok=True)


def test_view_missing_file():
    r = view_file_content("/nonexistent/path/file.py")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_view_truncate():
    p = _tmpfile("x" * 100_000)
    try:
        r = view_file_content(p, max_chars=1000)
        assert r["truncated"] is True
        assert len(r["content"]) == 1000
    finally:
        Path(p).unlink(missing_ok=True)


# === edit_file_block =========================================================

def test_edit_unique_match_replaces():
    p = _tmpfile("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    try:
        r = edit_file_block(p, "return 1", "return 99", backup=False)
        assert r["ok"] is True
        assert r["replaced"] is True
        assert r["matches"] == 1
        new = Path(p).read_text(encoding="utf-8")
        assert "return 99" in new
        assert "return 2" in new  # autres preserves
    finally:
        Path(p).unlink(missing_ok=True)


def test_edit_non_unique_fails_by_default():
    p = _tmpfile("a = 1\nb = 1\nc = 1\n")
    try:
        r = edit_file_block(p, "= 1", "= 2")
        assert r["ok"] is False
        assert r["matches"] == 3
        assert "not unique" in r["error"]
        # Fichier intact
        assert Path(p).read_text(encoding="utf-8") == "a = 1\nb = 1\nc = 1\n"
    finally:
        Path(p).unlink(missing_ok=True)


def test_edit_not_found():
    p = _tmpfile("hello world\n")
    try:
        r = edit_file_block(p, "missing pattern", "replacement")
        assert r["ok"] is False
        assert r["matches"] == 0
        assert "not found" in r["error"]
    finally:
        Path(p).unlink(missing_ok=True)


def test_edit_non_unique_allowed_explicit():
    p = _tmpfile("x=1\nx=1\n")
    try:
        r = edit_file_block(p, "x=1", "x=2", expect_unique=False, backup=False)
        assert r["ok"] is True
        # Premier match seulement remplace
        new = Path(p).read_text(encoding="utf-8")
        assert new == "x=2\nx=1\n"
    finally:
        Path(p).unlink(missing_ok=True)


def test_edit_creates_backup():
    p = _tmpfile("foo\n")
    try:
        r = edit_file_block(p, "foo", "bar", backup=True)
        assert r["ok"] is True
        assert r["backup_path"] is not None
        assert Path(r["backup_path"]).exists()
        assert Path(r["backup_path"]).read_text(encoding="utf-8") == "foo\n"
    finally:
        Path(p).unlink(missing_ok=True)
        if r.get("backup_path"):
            Path(r["backup_path"]).unlink(missing_ok=True)


# === insert_at_line ==========================================================

def test_insert_at_top():
    p = _tmpfile("def main():\n    pass\n")
    try:
        r = insert_at_line(p, 0, "import os", backup=False)
        assert r["ok"] is True
        new = Path(p).read_text(encoding="utf-8")
        assert new.startswith("import os\n")
    finally:
        Path(p).unlink(missing_ok=True)


def test_insert_at_end():
    p = _tmpfile("line1\nline2\n")
    try:
        r = insert_at_line(p, 2, "line3", backup=False)
        assert r["ok"] is True
        new = Path(p).read_text(encoding="utf-8")
        assert new.endswith("line3\n")
    finally:
        Path(p).unlink(missing_ok=True)


def test_insert_out_of_range():
    p = _tmpfile("just one line\n")
    try:
        r = insert_at_line(p, 99, "X")
        assert r["ok"] is False
        assert "out of range" in r["error"]
    finally:
        Path(p).unlink(missing_ok=True)


# === restore_backup ==========================================================

def test_restore_backup_roundtrip():
    p = _tmpfile("original content\n")
    try:
        r1 = edit_file_block(p, "original", "modified", backup=True)
        assert r1["ok"]
        backup = r1["backup_path"]
        # Confirm changed
        assert "modified" in Path(p).read_text(encoding="utf-8")
        # Restore
        r2 = restore_backup(backup)
        assert r2["ok"] is True
        # Original back
        assert Path(p).read_text(encoding="utf-8") == "original content\n"
    finally:
        Path(p).unlink(missing_ok=True)
        if r1.get("backup_path"):
            Path(r1["backup_path"]).unlink(missing_ok=True)


def test_restore_invalid_name():
    r = restore_backup("/some/path/not_a_backup.txt")
    assert r["ok"] is False
    assert "not found" in r["error"] or "invalid" in r["error"]
