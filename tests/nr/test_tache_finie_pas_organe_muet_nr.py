"""NR -- un organe qui a FINI sa tache (pouls `fini: true`) n'est pas un « organe silencieux cense tourner ».

Mesure 20/10 00:22 (bb discovered_facts/self_care_8639de7c522d, persistant 13 cycles) : « Organes silencieux CENSES
TOURNER : ['memory_consolidator', 'modal_campagne', 'skill_enricher'] ». Le dernier pouls de modal_campagne (01/10
19:09) dit {"faits": 67935, "vise": 67935, "fini": true} : la campagne est TERMINEE, pas muette. Le diagnostic lisait
l'age du pouls sans lire ce qu'il dit -- STALE n'est pas DEAD, et FINI n'est ni l'un ni l'autre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tests" / "nr")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_health_diagnostic as hd  # noqa: E402
from test_keeper_organe_nr import _audit  # noqa: E402


def test_une_tache_finie_n_est_pas_un_organe_muet():
    workers = {
        "modal_campagne": {"present": True, "alive": False, "age_s": 99999, "declare": False,
                           "eteint_par_decision": None, "fini": True},
        "vrai_muet": {"present": True, "alive": False, "age_s": 99999, "declare": False,
                      "eteint_par_decision": None},
    }
    _score, gaps = hd.compute_score_and_gaps(_audit(workers))
    muets = [g for g in gaps if "CENSES TOURNER" in g]
    assert muets and "vrai_muet" in muets[0] and "modal_campagne" not in muets[0], gaps
    assert any("TERMINEE" in g and "modal_campagne" in g for g in gaps), gaps


def test_le_pouls_fini_est_lu(tmp_path, monkeypatch):
    (tmp_path / "modal_campagne.heartbeat").write_text(
        json.dumps({"ts": "2026-10-01T19:09:48", "faits": 67935, "vise": 67935, "fini": True}), encoding="utf-8")
    monkeypatch.setattr(hd, "SANDBOX", tmp_path)
    w = hd.audit_workers_heartbeat()
    assert w["modal_campagne"]["fini"] is True
