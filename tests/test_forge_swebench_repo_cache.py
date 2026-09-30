"""Tests forge_swebench_repo_cache - cache idempotence + manifest."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))


def test_module_loadable():
    import forge_swebench_repo_cache  # noqa
    assert hasattr(forge_swebench_repo_cache, "prepare_instance")
    assert hasattr(forge_swebench_repo_cache, "load_cached_markdown")
    assert hasattr(forge_swebench_repo_cache, "clear_cache")


def test_cache_dir_naming():
    from forge_swebench_repo_cache import _instance_cache_dir
    d = _instance_cache_dir("astropy/astropy-12907")
    # Slash -> underscore
    assert "_" in d.name
    assert "/" not in d.name


def test_load_cached_returns_none_for_missing():
    from forge_swebench_repo_cache import (
        cached_repo_path, load_cached_manifest, load_cached_markdown,
    )
    iid = "nonexistent__instance_99999"
    assert load_cached_markdown(iid) is None
    assert load_cached_manifest(iid) is None
    assert cached_repo_path(iid) is None


def test_clear_cache_idempotent():
    from forge_swebench_repo_cache import clear_cache
    # Clear sur instance jamais cache = False (rien a faire)
    assert clear_cache("never_cached_xyz_99999") is False


def test_build_and_save_maps_creates_files(monkeypatch):
    """Mock build_repo_map pour eviter clone reel."""
    import forge_swebench_repo_cache as c
    from forge_repo_map import Symbol

    fake_map = {
        "root": "/tmp/fake_repo",
        "files": 2,
        "symbols": [
            Symbol(name="f", kind="function", file="mod1/a.py", lineno=1),
            Symbol(name="g", kind="function", file="mod2/b.py", lineno=5),
        ],
    }

    monkeypatch.setattr(c, "build_repo_map", lambda *a, **kw: fake_map)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        manifest = c._build_and_save_maps(
            repo_path=td_path / "fake_repo",
            cache_dir=td_path / "cache",
            instance_id="test__inst_1",
            base_commit="abc123",
            repo_name="user/test",
        )
        assert (td_path / "cache" / "repo_map.md").exists()
        assert (td_path / "cache" / "manifest.json").exists()
        assert (td_path / "cache" / "domain_maps").exists()
        # 2 sub-domains (mod1, mod2)
        assert manifest["symbols"] == 2
        assert manifest["base_commit"] == "abc123"
        assert "mod1" in manifest["domains"]
        assert "mod2" in manifest["domains"]


def test_prepare_instance_skips_if_manifest_matches(monkeypatch):
    """Si manifest cache match base_commit -> cached=True sans rebuild."""
    import forge_swebench_repo_cache as c
    with tempfile.TemporaryDirectory() as td:
        cache_root = Path(td)
        monkeypatch.setattr(c, "CACHE_ROOT", cache_root)
        monkeypatch.setattr(
            c, "_instance_cache_dir",
            lambda iid: cache_root / iid.replace("/", "_"))
        iid = "test__inst_skip"
        cache_dir = cache_root / iid.replace("/", "_")
        cache_dir.mkdir(parents=True)
        # Manifest pre-existant
        (cache_dir / "manifest.json").write_text(
            json.dumps({"base_commit": "match_commit", "files": 10}),
            encoding="utf-8")
        called = {"build": 0}

        def fake_build(*a, **kw):
            called["build"] += 1
            return {"symbols": [], "files": 0}

        monkeypatch.setattr(c, "build_repo_map", fake_build)
        r = c.prepare_instance(
            {"instance_id": iid, "base_commit": "match_commit",
             "repo": "user/test"})
        assert r["cached"] is True
        assert called["build"] == 0  # PAS rebuild
