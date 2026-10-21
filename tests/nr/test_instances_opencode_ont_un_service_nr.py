"""NR -- toute instance OpenCode declaree a son service d'executeur, et inversement (owner 18/10 : « multiplie les
executeurs, le plus possible tant que ca passe »).

GPTOSS (modele par defaut d'OpenCode, sans cle) est l'executeur le plus fiable ; on en ajoute des instances. Une
instance sans service ne recoit jamais de tache (elle attend en silence) ; un service sans instance tourne sans worktree.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _instances():
    d = json.loads((ROOT / "config" / "opencode_instances.json").read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if k.startswith("OPENCODE_")}


def _agents_des_services():
    svc = tomllib.loads((ROOT / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"))["service"]
    out = {}
    for s in svc:
        a = s.get("args") or []
        if any(str(x).endswith("forge_task_executor.py") for x in a) and "--agent" in a:
            ag = a[a.index("--agent") + 1]
            if ag.startswith("OPENCODE_"):
                out[ag] = s
    return out


def test_chaque_instance_a_son_service_et_inversement():
    inst, svc = _instances(), _agents_des_services()
    assert set(inst) == set(svc), "instances sans service %s ; services sans instance %s" % (
        sorted(set(inst) - set(svc)), sorted(set(svc) - set(inst)))


def test_les_instances_defaut_multipliees_existent_et_ont_un_worktree_propre():
    inst = _instances()
    defaut = sorted(k for k in inst if re.fullmatch(r"OPENCODE_DEFAUT\d+", k))
    assert len(defaut) >= 4, defaut
    wts = [inst[k]["worktree"] for k in inst]
    assert len(wts) == len(set(wts)), "deux instances partagent un worktree"
