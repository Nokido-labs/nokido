"""tests/test_forge_swarm_context.py — ForgeSwarm M1 : contexte stérile.

Critère d'acceptation `test_sterile_context` : un worker confiné au fichier A
n'a AUCUN accès (lecture ni écriture) au fichier B via son module de contexte.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_swarm_context import (  # noqa: E402
    ScopeViolation,
    assert_writable,
    build_worker_context,
    sterile_read,
)


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text("def f_a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "SECRET = 42\n\n\ndef f_b(x: int) -> int:\n    '''interface b'''\n    return x + SECRET\n",
        encoding="utf-8",
    )
    return tmp_path


# ── test_sterile_context : le cœur du M1 ─────────────────────────────────────
def test_sterile_context_read(tmp_path: Path):
    root = _setup(tmp_path)
    # worker scopé sur a.py : lit a.py
    assert "f_a" in sterile_read("a.py", ["a.py"], root)
    # mais PAS b.py (hors périmètre) -> ScopeViolation
    with pytest.raises(ScopeViolation):
        sterile_read("b.py", ["a.py"], root)


def test_sterile_context_write(tmp_path: Path):
    root = _setup(tmp_path)
    assert_writable("a.py", ["a.py"], root)  # autorisé, ne lève pas
    with pytest.raises(ScopeViolation):
        assert_writable("b.py", ["a.py"], root)  # écriture hors cible -> interdit


def test_no_path_traversal(tmp_path: Path):
    root = _setup(tmp_path)
    with pytest.raises(ScopeViolation):
        sterile_read("../../etc/passwd", ["a.py"], root)
    with pytest.raises(ScopeViolation):
        assert_writable("../escape.py", ["a.py"], root)


def test_missing_file_is_violation(tmp_path: Path):
    root = _setup(tmp_path)
    with pytest.raises(ScopeViolation):
        sterile_read("ghost.py", ["ghost.py"], root)


# ── contexte 3 niveaux : cible complète + référence (interface seule) ────────
def test_context_three_tiers(tmp_path: Path):
    root = _setup(tmp_path)
    ctx = build_worker_context(target_files=["a.py"], reference_files=["b.py"], root=root)
    assert "CIBLE" in ctx and "RÉFÉRENCE" in ctx  # structure 3 niveaux
    assert "f_a" in ctx  # cible = contenu complet
    assert "a.py" in ctx and "b.py" in ctx  # les deux référencés


def test_target_missing_file_marked_new(tmp_path: Path):
    root = _setup(tmp_path)
    ctx = build_worker_context(target_files=["new_module.py"], reference_files=None, root=root)
    assert "nouveau fichier" in ctx  # création = corps vide annoncé
