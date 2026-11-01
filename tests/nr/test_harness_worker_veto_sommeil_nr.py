# -*- coding: utf-8 -*-
"""NR (28/10) : le harness worker pose un VETO DE SOMMEIL pendant chaque job, le renouvelle, le leve a la fin.

Mesure 28/10 : `ctl status NokidoHarnessWorker` -> `sleeping`, pid null. Le worker avait ete ENDORMI pendant
un job claude_api (10:06:31, RAM ~86 %) : 34 min de delegations closes « non lance », puis le job rejoue
en double a la relance. La primitive existait (forge_resource_manager.poser_veto_sommeil, utilisee par
l'executeur) ; le worker ne la posait pas.
"""
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_harness_worker as hw  # noqa: E402


def test_veto_pose_pendant_le_job_et_leve_apres(monkeypatch, tmp_path):
    journal = []
    monkeypatch.setattr(hw, "JOBS", tmp_path)
    monkeypatch.setattr(hw, "_poser_veto", lambda nom, duree_s: journal.append(("pose", nom)))
    monkeypatch.setattr(hw, "_lever_veto", lambda: journal.append(("leve",)))
    monkeypatch.setattr(hw, "_armer_chien", lambda d: None)
    monkeypatch.setattr(hw, "_heartbeat", lambda **kw: None)

    def job(j):
        journal.append(("job",))
        return {"ok": True}

    monkeypatch.setattr(hw, "process_job", job)
    (tmp_path / "claude_job_x.json").write_text(json.dumps({"agent": "claude_api", "timeout": 60}), encoding="utf-8")
    assert hw._run_pending() == 1
    assert journal[0] == ("pose", "claude_job_x"), journal
    assert journal.index(("job",)) < journal.index(("leve",))


def test_le_pouls_pendant_job_renouvelle_le_veto(monkeypatch):
    poses = []
    fin = threading.Event()
    monkeypatch.setattr(hw, "_heartbeat", lambda **kw: None)
    monkeypatch.setattr(hw, "_POULS_PENDANT_JOB_S", 0.01)

    def poser(nom, duree_s):
        poses.append(nom)
        if len(poses) >= 2:
            fin.set()

    monkeypatch.setattr(hw, "_poser_veto", poser)
    t = threading.Thread(target=hw._battre_tant_que, args=(fin, "job_long"), daemon=True)
    t.start()
    t.join(5)
    assert poses[:2] == ["job_long", "job_long"]
