"""NR 27/10 : le harness worker bat PENDANT un job long, pas seulement entre deux passes.

Mesure : relance a 09 h 14, job Vibe pris a 09 h 17, pouls fige a 03 h 04 pendant 16 min alors que
le worker TRAVAILLAIT -- `_watch` n'appelait `_heartbeat()` qu'apres `_run_pending()` complet. Un
pouls fige pendant un travail borne par le watchdog se lit comme une mort (STALE pris pour DEAD) par
l'executeur, qui reaffectait alors toute delegation Vibe / claude -p."""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger():
    spec = importlib.util.spec_from_file_location("forge_harness_worker_nr", ROOT / "tools" / "forge_harness_worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_pouls_bat_pendant_un_job_long(tmp_path, monkeypatch):
    hw = _charger()
    monkeypatch.setattr(hw, "JOBS", tmp_path)
    monkeypatch.setattr(hw, "_POULS_PENDANT_JOB_S", 0.05)
    battements = []
    monkeypatch.setattr(hw, "_heartbeat", lambda **extra: battements.append(dict(extra)))

    def job_long(job):
        time.sleep(0.4)
        return {"ok": True, "output": "fini"}

    monkeypatch.setattr(hw, "process_job", job_long)
    (tmp_path / "MISTRAL_job_1.json").write_text(json.dumps({"agent": "vibe", "timeout": 60}), encoding="utf-8")
    assert hw._run_pending() == 1
    pendant = [b for b in battements if b.get("job_en_cours") == "MISTRAL_job_1"]
    assert len(pendant) >= 2, battements
    assert (tmp_path / "MISTRAL_job_1.done").exists()


def test_le_battement_s_arrete_avec_le_job(tmp_path, monkeypatch):
    hw = _charger()
    monkeypatch.setattr(hw, "JOBS", tmp_path)
    monkeypatch.setattr(hw, "_POULS_PENDANT_JOB_S", 0.05)
    battements = []
    monkeypatch.setattr(hw, "_heartbeat", lambda **extra: battements.append(dict(extra)))
    monkeypatch.setattr(hw, "process_job", lambda job: {"ok": False, "error": "x"})
    (tmp_path / "MISTRAL_job_2.json").write_text("{}", encoding="utf-8")
    hw._run_pending()
    n = len(battements)
    time.sleep(0.3)
    assert len(battements) == n  # aucun battement fantome apres la fin du job
