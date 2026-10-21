"""NR -- py7zr est une dependance DECLAREE (decision owner 19/10, choix multiple).

Constat 14/10 (item p1_archive_chiffree_flux_2026-10-14) : tools/forge_backup_hotswap.py utilisait py7zr sans qu'il soit
declare nulle part (requirements, pyproject, locks) -- present seulement dans le Python de base. Depuis l'integration de
l'archive chiffree en flux (19/10), c'est une dependance de la sauvegarde : extra `sauvegarde` du pyproject + epingle dans
requirements.txt, vue par le garde de licences (LGPL-2.1 : copyleft faible, non refusee, comme paramiko). Le lock du
runtime (laforge_py314) n'est PAS touche : il reflete l'env du hub, ou py7zr n'est pas installe.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_license_guard as L  # noqa: E402


def test_extra_sauvegarde_et_epingle():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    extra = re.search(r"^sauvegarde\s*=\s*\[(.*?)\]", pyproject, re.M | re.S)
    assert extra and "py7zr" in extra.group(1), "extra `sauvegarde` portant py7zr attendu"
    assert re.search(r"^py7zr==\d", (ROOT / "requirements.txt").read_text(encoding="utf-8"), re.M)


def test_le_garde_de_licences_voit_py7zr():
    assert "py7zr" in {L._norme(k) for k in L.dependances_declarees(ROOT)}
    assert L.classify("py7zr", "lgpl-2.1-or-later") != "deny"
