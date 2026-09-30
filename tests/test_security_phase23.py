"""Phase 23A security tests — minimal sans HTTP."""
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────
# Fix 4 : forge_sandbox_exec creds cache purge
# ─────────────────────────────────────────────────────────────────────────

def test_sandbox_purge_creds_cache_clears_globals():
    """purge_creds_cache() doit effacer _creds_cache + reset ts."""
    try:
        import forge_sandbox_exec as fse
    except ImportError:
        pytest.skip("pywin32 dependency missing on test env")
    # Setup cache artificiel
    fse._creds_cache = {"LaForgeSbxOnline": "fakepwd123"}
    fse._creds_cache_ts = 999999.0
    assert fse._creds_cache is not None
    # Purge
    fse.purge_creds_cache()
    assert fse._creds_cache is None
    assert fse._creds_cache_ts == 0.0


def test_sandbox_purge_creds_cache_idempotent():
    try:
        import forge_sandbox_exec as fse
    except ImportError:
        pytest.skip("pywin32 missing")
    fse._creds_cache = None
    fse.purge_creds_cache()  # ne doit pas raise
    assert fse._creds_cache is None


# ─────────────────────────────────────────────────────────────────────────
# Fix 5 : LATS worktree reject pre-existing symlink
# ─────────────────────────────────────────────────────────────────────────

def test_worktree_create_rejects_pre_existing_path(tmp_path, monkeypatch):
    """Si wt_path pre-existe (symlink ou dir), _worktree_create refuse."""
    import forge_agent_lats as lats
    # Force WORKTREE_ROOT vers tmp_path test
    monkeypatch.setattr(lats, "WORKTREE_ROOT", tmp_path / "lats_test")
    monkeypatch.setattr(lats, "uuid", _FakeUUID())  # uuid deterministe
    monkeypatch.setattr(lats, "_git", lambda *a, **kw: (0, "", ""))  # git no-op
    # Pre-create le chemin que _worktree_create essaiera
    (tmp_path / "lats_test").mkdir()
    collide = tmp_path / "lats_test" / "agt-deadbeef"
    collide.mkdir()
    with pytest.raises(RuntimeError, match="pre-exists"):
        lats._worktree_create("agt")


def test_worktree_root_symlink_refused(tmp_path, monkeypatch):
    """Si WORKTREE_ROOT lui-meme est un symlink, refuse."""
    import forge_agent_lats as lats
    import os
    target = tmp_path / "real_dir"
    target.mkdir()
    link = tmp_path / "lats_link"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privilege on Windows")
    monkeypatch.setattr(lats, "WORKTREE_ROOT", link)
    monkeypatch.setattr(lats, "uuid", _FakeUUID())
    monkeypatch.setattr(lats, "_git", lambda *a, **kw: (0, "", ""))
    with pytest.raises(RuntimeError, match="symlink"):
        lats._worktree_create("agt")


class _FakeUUID:
    """Mock uuid pour rendre deterministe les noms worktree dans les tests."""
    @staticmethod
    def uuid4():
        class _H:
            hex = "deadbeefcafebabe"
        return _H()
