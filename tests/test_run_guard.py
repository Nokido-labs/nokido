# -*- coding: utf-8 -*-
"""
test_run_guard.py — WorkspaceGuard audit-hook fs-zone (tool `run`)
==================================================================
Vérifie que le header généré par forge_workspace_guard.build_run_guard_header
confine bien les écritures d'un agent non-superviseur à sa zone, sans gêner
les lectures. Régression : trou `run` python = exec arbitraire = write partout.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.27)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_workspace_guard import build_run_guard_header  # noqa: E402


def _run(code: str) -> subprocess.CompletedProcess:
    """Exécute `code` dans un sous-processus Python frais (comme _run_isolated)."""
    fd, tmp = tempfile.mkstemp(suffix=".py", prefix="trg_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        return subprocess.run(
            [sys.executable, tmp], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def test_write_inside_zone_allowed(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    target = allowed / "f.txt"
    hdr = build_run_guard_header([str(allowed)])
    r = _run(hdr + f"\nopen({str(target)!r}, 'w').write('x')\nprint('DONE')\n")
    assert r.returncode == 0, r.stderr
    assert "DONE" in r.stdout
    assert target.read_text() == "x"


def test_write_outside_zone_blocked(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    forbidden = tmp_path / "evil.txt"
    hdr = build_run_guard_header([str(allowed)])
    r = _run(hdr + f"\nopen({str(forbidden)!r}, 'w').write('x')\n")
    assert r.returncode != 0
    assert "WORKSPACE_GUARD" in r.stderr
    assert not forbidden.exists()


def test_read_outside_zone_allowed(tmp_path):
    """Lecture hors zone autorisée — seules les mutations sont confinées."""
    allowed = tmp_path / "ok"
    allowed.mkdir()
    src = tmp_path / "src.txt"
    src.write_text("payload")
    hdr = build_run_guard_header([str(allowed)])
    r = _run(hdr + f"\nprint(open({str(src)!r}).read())\n")
    assert r.returncode == 0, r.stderr
    assert "payload" in r.stdout


def test_os_remove_outside_zone_blocked(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    hdr = build_run_guard_header([str(allowed)])
    r = _run(hdr + f"\nimport os\nos.remove({str(victim)!r})\n")
    assert r.returncode != 0
    assert victim.exists()


def test_subprocess_spawn_blocked(tmp_path):
    """Un agent zone-restreint ne peut pas s'évader via un sous-processus."""
    allowed = tmp_path / "ok"
    allowed.mkdir()
    hdr = build_run_guard_header([str(allowed)])
    r = _run(hdr + "\nimport subprocess\nsubprocess.run([__import__('sys').executable, '-c', 'pass'])\n")
    assert r.returncode != 0
    assert "WORKSPACE_GUARD" in r.stderr


def test_supervisor_confined_to_root(tmp_path):
    """Superviseur (ring 0) : libre DANS le projet, bloqué au-dehors.
    Ring 0 ne donne PAS le disque entier."""
    from forge_workspace_guard import run_guard_header_for
    hdr = run_guard_header_for("CLAUDE", 0, tmp_path)
    assert hdr, "le superviseur doit aussi etre confine (jamais de header vide)"
    inside = tmp_path / "sub" / "x.txt"
    outside = tmp_path.parent / "escape_sup.txt"
    r1 = _run(hdr + f"\nimport os\nos.makedirs({str(tmp_path / 'sub')!r}, exist_ok=True)\n"
                    f"open({str(inside)!r}, 'w').write('ok')\nprint('IN')\n")
    assert r1.returncode == 0, r1.stderr
    assert inside.read_text() == "ok"
    r2 = _run(hdr + f"\nopen({str(outside)!r}, 'w').write('x')\n")
    assert r2.returncode != 0
    assert not outside.exists()


def test_empty_zone_blocks_all_writes(tmp_path):
    """Zone vide (INSPECTOR/SERVICES) = aucune écriture autorisée."""
    forbidden = tmp_path / "x.txt"
    hdr = build_run_guard_header([])
    r = _run(hdr + f"\nopen({str(forbidden)!r}, 'w').write('x')\n")
    assert r.returncode != 0
    assert not forbidden.exists()
