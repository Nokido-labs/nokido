"""tests/test_forge_swarm_patch.py — ForgeSwarm : S/R applier + VFS overlay."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_swarm_patch import (  # noqa: E402
    PatchError,
    VFSOverlay,
    apply_sr,
    parse_sr_blocks,
)

_SR = """<<<<<<< SEARCH
def f():
    return 1
=======
def f():
    return 2
>>>>>>> REPLACE
"""


# ── parse + apply S/R ────────────────────────────────────────────────────────
def test_parse_sr_block():
    blocks = parse_sr_blocks(_SR)
    assert len(blocks) == 1
    search, replace = blocks[0]
    assert "return 1" in search and "return 2" in replace


def test_parse_malformed_raises():
    with pytest.raises(PatchError):
        parse_sr_blocks("<<<<<<< SEARCH\nfoo\n>>>>>>> REPLACE\n")  # pas de =======
    with pytest.raises(PatchError):
        parse_sr_blocks("aucun bloc ici")


def test_apply_sr_exact():
    out = apply_sr("def f():\n    return 1\n", parse_sr_blocks(_SR))
    assert "return 2" in out and "return 1" not in out


def test_apply_sr_anchor_not_found():
    # ancre absente -> rejet (jamais d'application floue)
    with pytest.raises(PatchError):
        apply_sr("def autre():\n    pass\n", parse_sr_blocks(_SR))


# ── VFS overlay : ops + isolation disque ─────────────────────────────────────
def test_overlay_edit_no_disk_write(tmp_path: Path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    ov.apply({"op": "edit_sr", "target": "m.py", "text": _SR})
    assert "return 2" in ov.read("m.py")  # overlay patché
    assert "return 1" in (tmp_path / "m.py").read_text()  # DISQUE intact


def test_overlay_create_delete_rename(tmp_path: Path):
    (tmp_path / "old.py").write_text("x = 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    ov.apply({"op": "create", "target": "new.py", "content": "y = 2\n"})
    assert ov.exists("new.py") and ov.read("new.py") == "y = 2\n"
    ov.apply({"op": "rename", "target": "old.py", "new_path": "renamed.py"})
    assert ov.exists("renamed.py") and not ov.exists("old.py")
    ov.apply({"op": "delete", "target": "renamed.py"})
    assert not ov.exists("renamed.py")
    ov.apply({"op": "noop"})  # ne lève pas


def test_overlay_ast_check_rejects_broken_py(tmp_path: Path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    with pytest.raises(PatchError):
        ov.apply({"op": "create", "target": "broken.py", "content": "def f(\n"})  # syntaxe cassée


# ── cascade séquentielle = fix "état fantôme" (point 1 de l'audit) ───────────
def test_overlay_sequential_cascade(tmp_path: Path):
    # T1 modifie m.py ; T2 (dépendant) DOIT lire la version patchée, pas le disque.
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    ov.apply({"op": "edit_sr", "target": "m.py", "text": _SR})  # T1
    seen_by_t2 = ov.read("m.py")
    assert "return 2" in seen_by_t2  # T2 voit le patch de T1 (pas la version disque)


# ── atomicité : commit écrit tout ; discard = rollback ──────────────────────
def test_commit_writes_all(tmp_path: Path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    ov.apply({"op": "edit_sr", "target": "m.py", "text": _SR})
    ov.apply({"op": "create", "target": "n.py", "content": "z = 3\n"})
    touched = ov.commit()
    assert "return 2" in (tmp_path / "m.py").read_text()
    assert (tmp_path / "n.py").read_text() == "z = 3\n"
    assert len(touched) == 2


def test_discard_is_rollback(tmp_path: Path):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ov = VFSOverlay(tmp_path)
    ov.apply({"op": "edit_sr", "target": "m.py", "text": _SR})
    ov.discard()
    # rien committé -> disque intact
    assert "return 1" in (tmp_path / "m.py").read_text()
    assert ov.commit() == []  # overlay vide
