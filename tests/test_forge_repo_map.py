"""Tests forge_repo_map - extraction signatures + markdown render."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_repo_map import (  # noqa
    Symbol, build_repo_map, file_skeleton, find_symbol,
    parse_file_symbols, render_markdown, symbols_to_jsonl,
)


def _make_repo(files: dict[str, str]) -> Path:
    """Create a temp repo dir with given {relpath: content}."""
    d = Path(tempfile.mkdtemp())
    for rel, code in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
    return d


def test_parse_function_signatures():
    repo = _make_repo({"x.py":
        "def add(a, b):\n    return a+b\n\ndef mul(x, y, z):\n    return x*y*z\n"
    })
    try:
        syms = parse_file_symbols(repo / "x.py", repo)
        names = {s.name: s for s in syms}
        assert "add" in names
        assert "mul" in names
        assert names["add"].args == ["a", "b"]
        assert names["mul"].args == ["x", "y", "z"]
        assert names["add"].kind == "function"
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def test_parse_class_with_methods():
    repo = _make_repo({"c.py":
        'class Foo:\n    """class doc"""\n    def __init__(self, x): self.x = x\n'
        "    def bar(self, y): return y\n"
        "    def _private(self): pass\n"
    })
    try:
        syms = parse_file_symbols(repo / "c.py", repo)
        kinds = {s.kind for s in syms}
        names = {s.name for s in syms}
        assert "Foo" in names
        assert "bar" in names
        assert "__init__" in names
        assert "_private" not in names  # private skipped
        assert "class" in kinds
        assert "method" in kinds
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def test_build_repo_map_counts():
    repo = _make_repo({
        "a.py": "def f(): pass\ndef g(): pass\n",
        "sub/b.py": "class B:\n    def m(self): pass\n",
        "__pycache__/junk.py": "broken",  # exclude
    })
    try:
        rm = build_repo_map(repo)
        names = {s.name for s in rm["symbols"]}
        assert "f" in names
        assert "g" in names
        assert "B" in names
        assert "m" in names
        # exclusion __pycache__ - junk pas dans symbols
        for s in rm["symbols"]:
            assert "__pycache__" not in s.file
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def test_render_markdown_format():
    repo = _make_repo({
        "main.py": "def entry():\n    pass\n",
        "lib/util.py": 'class Helper:\n    """helper doc"""\n    def run(self, opts): pass\n',
    })
    try:
        rm = build_repo_map(repo)
        md = render_markdown(rm)
        assert "main.py" in md
        assert "lib/util.py" in md
        assert "class Helper" in md
        assert "helper doc" in md
        assert "def run(self, opts)" in md
        assert "def entry()" in md
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def test_find_symbol():
    repo = _make_repo({"x.py": "def needle(): pass\ndef hay(): pass\n"})
    try:
        rm = build_repo_map(repo)
        matches = find_symbol(rm, "needle")
        assert len(matches) == 1
        assert matches[0].name == "needle"
        assert find_symbol(rm, "nonexistent") == []
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def test_symbols_to_jsonl_roundtrip():
    repo = _make_repo({"a.py": "def f(): pass\n"})
    out = Path(tempfile.mktemp(suffix=".jsonl"))
    try:
        rm = build_repo_map(repo)
        n = symbols_to_jsonl(rm, out)
        assert n >= 1
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n
        import json as _j
        first = _j.loads(lines[0])
        assert "name" in first
        assert "file" in first
        assert "lineno" in first
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)
        out.unlink(missing_ok=True)


def test_file_skeleton_masks_method_bodies():
    repo = _make_repo({"k.py":
        "import os\n"
        "from pathlib import Path\n\n"
        "class Foo:\n"
        '    """doc"""\n'
        "    def m(self, x):\n"
        "        for i in range(100):\n"
        "            x += i\n"
        "        return x\n\n"
        "def top(a, b):\n"
        "    z = a + b\n"
        "    return z * 2\n"
    })
    try:
        sk = file_skeleton(repo / "k.py", repo)
        # imports preserves
        assert "import os" in sk
        assert "from pathlib import Path" in sk
        # signatures preserves
        assert "class Foo:" in sk
        assert "def m(self, x): ..." in sk
        assert "def top(a, b): ..." in sk
        # body interieur masque (for/return absents)
        assert "range(100)" not in sk
        assert "z * 2" not in sk
        # docstring preserve
        assert '"""doc"""' in sk
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)
