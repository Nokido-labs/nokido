# -*- coding: utf-8 -*-
"""NR — le SkillCurator qui trouve une instance VIVANTE le DIT par un code de sortie dédié, pas par un 0.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la sortie volontaire d'instance unique"

CE QUI A ÉTÉ PAYÉ (2026-10-20, docs/enquete_skill_curator_faux_crash.md). Une instance saine tournait (pid 19412) ; le
superviseur en a relancé une seconde, qui sortait en 70 ms par son garde d'instance unique avec `return 0`. Le
superviseur a compté chaque sortie comme un échec rapide : quarantaine 5 min, puis 1 h, après 19 relances. Un 0 ne
distingue pas « une autre instance vit » de « rien à faire » : la propriété se DEMANDE à l'organe. Le code vit dans
le contrat `config/codes_sortie_organes.json`, lu aussi par le superviseur.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRAT = ROOT / "config" / "codes_sortie_organes.json"


def _code_contrat() -> int:
    code = json.loads(CONTRAT.read_text(encoding="utf-8"))["INSTANCE_DEJA_VIVANTE"]
    assert isinstance(code, int) and code not in (0, 1), code
    return code


def _curator(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    spec = importlib.util.spec_from_file_location("forge_skill_curator_nr", ROOT / "app" / "forge_skill_curator.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_skill_curator_nr", mod)  # @dataclass relit son module dans sys.modules
    spec.loader.exec_module(mod)
    return mod


def test_instance_vivante_rend_le_code_du_contrat(monkeypatch, tmp_path):
    mod = _curator(monkeypatch)
    pidfile = tmp_path / "skill_curator.pid"
    pidfile.write_text(str(os.getppid()))  # un pid VIVANT et distinct du notre
    monkeypatch.setattr(mod, "PIDFILE", pidfile)
    monkeypatch.setattr(mod, "_pid_alive_win", lambda pid: pid == os.getppid())
    monkeypatch.setattr(sys, "argv", ["forge_skill_curator.py", "--daemon", "--dry-run"])
    assert mod.main() == _code_contrat()
    assert pidfile.read_text().strip() == str(os.getppid()), "le pidfile de l'instance vivante ne doit pas bouger"
