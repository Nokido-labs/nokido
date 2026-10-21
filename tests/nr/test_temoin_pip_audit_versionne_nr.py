# -*- coding: utf-8 -*-
"""NR : le pre-controle DIT quand le temoin pip-audit qu'il juge n'est pas versionne.

p2_precontrole_temoin_pip_audit_non_versionne_2026-10-14 : le gate pip-audit du PRE-CONTROLE se disait supplee
par un temoin NON versionne (sandbox/...) alors que la CI de REFERENCE (worktree au sha) ne voit que le versionne
-> pre-controle vert, reference rc=1 (gate critique NON MESURE). Recidive mesuree le 26/09 et le 14/10 (une CI de
reference perdue, ~25 min). Forme executable : le detail du gate le DIT, sans changer le verdict de fraicheur.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402


def test_un_fichier_suivi_est_versionne_un_fichier_hors_git_ne_l_est_pas(tmp_path):
    assert ci_local._temoin_versionne(ROOT / "tools" / "ci_local.py") is True
    hors = tmp_path / "pip_audit_2026-10-18.json"
    hors.write_text("[]", encoding="utf-8")
    assert ci_local._temoin_versionne(hors) is False


def test_le_gate_dit_qu_un_temoin_frais_non_versionne_echappera_a_la_reference(tmp_path, monkeypatch):
    temoin = tmp_path / ("pip_audit_%s.json" % time.strftime("%Y-%m-%d"))
    temoin.write_text("[]", encoding="utf-8")
    faux = types.ModuleType("forge_deps_reconcilier")
    faux.rapport_courant = lambda: str(temoin)
    faux.date_du_nom = lambda p: time.time()
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_deps_reconcilier", faux)
    frais, detail = ci_local._mesure_pip_audit_deportee()
    assert frais is True, detail                       # le verdict de fraicheur ne change pas
    assert "NON versionne" in detail and "reference" in detail, detail
