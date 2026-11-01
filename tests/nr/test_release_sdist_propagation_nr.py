# -*- coding: utf-8 -*-
"""NR -- 1/11, release v0.20.16 : la preuve linux-x64 a echoue sur « sdist installable » -- `No matching distribution
found for nokido-agent==0.20.16` : l'index TestPyPI listait encore 0.20.15 quelques secondes apres l'upload (la roue,
elle, venait d'etre telechargee ; macOS et Windows, passes plus tard, etaient verts). La preuve attend la propagation
de l'index (essais espaces) ; tout AUTRE refus de pip reste un echec immediat (un sdist casse ne doit jamais passer)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "release.yml"


def test_le_workflow_reste_un_yaml_valide():
    assert yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]


def test_la_preuve_sdist_attend_la_propagation_et_seulement_elle():
    src = WF.read_text(encoding="utf-8")
    debut = src.index('"--no-binary", "nokido-agent"')
    bloc = src[debut - 600:debut + 900]
    assert "for _essai in range(" in bloc and "time.sleep(" in bloc
    assert '"No matching distribution found" not in r.stderr' in bloc   # seul ce motif est re-essaye
