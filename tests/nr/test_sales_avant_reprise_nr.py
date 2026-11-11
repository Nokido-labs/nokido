"""NR -- l'etat « sale avant la tache » est pris a la PREMIERE ouverture et reutilise a la reprise."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("sales_reprise_exec_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["sales_reprise_exec_nr"] = m
    spec.loader.exec_module(m)
    return m


def _git(d, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(d), *a],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _depot(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "base.txt").write_text("b\n")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")


def test_reprise_ne_commit_pas_le_sale_d_avant(ex, tmp_path):
    _depot(tmp_path)
    (tmp_path / "ancien.txt").write_text("avant la tache\n")
    premiere = ex._sales_avant_de(tmp_path)
    assert "ancien.txt" in premiere
    (tmp_path / "travail.txt").write_text("travail de la tache\n")
    k = str(tmp_path.resolve())
    ex._WT_REPRIS.add(k)
    try:
        avant = ex._sales_avant_de(tmp_path)
        assert "ancien.txt" in avant and "travail.txt" not in avant
        note = ex._committer_pour_agent(str(tmp_path), "t1", "fait", "CLAUDE_HEADLESS", exclus=avant)
    finally:
        ex._WT_REPRIS.discard(k)
    tracked = _git(tmp_path, "ls-files").stdout.split()
    assert "travail.txt" in tracked and "ancien.txt" not in tracked, (note, tracked)


def test_reprise_sans_etat_conserve_est_refusee_sans_perdre_le_travail(ex, tmp_path):
    _depot(tmp_path)
    (tmp_path / "ancien.txt").write_text("x\n")
    (tmp_path / "travail.txt").write_text("y\n")
    k = str(tmp_path.resolve())
    ex._WT_REPRIS.add(k)
    try:
        avant = ex._sales_avant_de(tmp_path)
        note = ex._committer_pour_agent(str(tmp_path), "t2", "fait", "CLAUDE_HEADLESS", exclus=avant)
    finally:
        ex._WT_REPRIS.discard(k)
    assert note and "commit executeur REFUSE rc=" in note, note
    assert (tmp_path / "travail.txt").exists()
    assert "travail.txt" not in _git(tmp_path, "ls-files").stdout.split()
