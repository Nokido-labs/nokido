"""
tests/nr/test_hub_envfile.py - NR loader .env minimal.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("TEST_A", "TEST_B", "TEST_C", "TEST_QUOTED", "TEST_EMPTY",
              "SECRET_KEY", "VALID_KEY", "APP.VERSION", "TEST_123",
              "SENTINEL_NOT_LOADED"):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


# ===================================================================
# TestParse
# ===================================================================
class TestParse:
    def test_simple(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("KEY=value") == ("KEY", "value")

    def test_double_quotes(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line('KEY="hello world"') == ("KEY", "hello world")

    def test_single_quotes(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("KEY='single quoted'") == ("KEY", "single quoted")

    def test_inline_comment_stripped(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("KEY=value # inline comment") == ("KEY", "value")

    def test_inline_hash_in_quoted_preserved(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line('KEY="value with # inside"') == ("KEY", "value with # inside")

    def test_full_line_comment(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("# full comment") is None
        assert _parse_line("   # indented comment") is None

    def test_empty_line(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("") is None
        assert _parse_line("   ") is None

    def test_orphan_equals(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("=orphan") is None

    def test_empty_value_ok(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("KEY=") == ("KEY", "")

    def test_invalid_key_chars(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("KE Y=value") is None
        assert _parse_line(" =value") is None

    def test_no_equals(self, clean_env):
        from app.web_hub.envfile import _parse_line
        assert _parse_line("justatext") is None


# ===================================================================
# TestLoad
# ===================================================================
class TestLoad:
    def test_override_false_preserves_shell(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        env_file.write_text("TEST_A=from_file\nTEST_B=from_file_b\n",
                           encoding="utf-8")
        clean_env.setenv("TEST_A", "from_shell")
        load_env_file(env_file, override=False)
        assert os.environ["TEST_A"] == "from_shell"
        assert os.environ["TEST_B"] == "from_file_b"

    def test_override_true_clobbers(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        env_file.write_text("TEST_A=from_file\n", encoding="utf-8")
        clean_env.setenv("TEST_A", "from_shell")
        load_env_file(env_file, override=True)
        assert os.environ["TEST_A"] == "from_file"

    def test_nonexistent_returns_empty(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        r = load_env_file(tmp_path / "nope.env")
        assert r == {}

    def test_returns_shadowed_keys_not_values(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        env_file.write_text("SECRET_KEY=supersecret\n", encoding="utf-8")
        r = load_env_file(env_file)
        assert "SECRET_KEY" in r
        assert r["SECRET_KEY"] == "***"
        # SECURITE : la valeur "supersecret" ne doit JAMAIS apparaitre dans r
        assert "supersecret" not in str(r)

    def test_multiple_keys(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        content_env = (
            "# commented\n"
            "TEST_A=a\n"
            "TEST_B=b\n"
            "\n"
            'TEST_QUOTED="has spaces"\n'
            "TEST_EMPTY=\n"
        )
        env_file.write_text(content_env, encoding="utf-8")
        load_env_file(env_file)
        assert os.environ["TEST_A"] == "a"
        assert os.environ["TEST_B"] == "b"
        assert os.environ["TEST_QUOTED"] == "has spaces"
        assert os.environ["TEST_EMPTY"] == ""

    def test_malformed_lines_skipped(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        content_env = (
            "TEST_A=ok\n"
            "garbage without equals\n"
            "=orphan\n"
            "TEST_B=also_ok\n"
        )
        env_file.write_text(content_env, encoding="utf-8")
        load_env_file(env_file)
        assert os.environ["TEST_A"] == "ok"
        assert os.environ["TEST_B"] == "also_ok"


# ===================================================================
# TestSecurity
# ===================================================================
class TestSecurity:
    def test_no_interpolation(self, clean_env, tmp_path):
        """Pas d expansion ${OTHER} qui pourrait leak env."""
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        env_file.write_text("TEST_A=${HOME}/bin\n", encoding="utf-8")
        load_env_file(env_file)
        assert os.environ["TEST_A"] == "${HOME}/bin"

    def test_no_code_execution_on_import(self):
        """Import de envfile = pas d injection auto."""
        for m in list(sys.modules):
            if m.endswith("envfile"):
                del sys.modules[m]
        os.environ.pop("SENTINEL_NOT_LOADED", None)
        import app.web_hub.envfile as ef  # noqa: F401
        assert "SENTINEL_NOT_LOADED" not in os.environ

    def test_keys_with_dots_and_underscores_ok(self, clean_env, tmp_path):
        from app.web_hub.envfile import load_env_file
        env_file = tmp_path / "x.env"
        content_env = (
            "VALID_KEY=1\n"
            "APP.VERSION=2.0\n"
            "TEST_123=3\n"
        )
        env_file.write_text(content_env, encoding="utf-8")
        load_env_file(env_file)
        assert os.environ["VALID_KEY"] == "1"
        assert os.environ["APP.VERSION"] == "2.0"
        assert os.environ["TEST_123"] == "3"
