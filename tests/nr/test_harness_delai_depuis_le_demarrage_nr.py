"""NR -- l'executeur compte sa borne depuis le DEMARRAGE du job par le harness, pas depuis son depot (17/10).

Mesure 17/10 (branche spool, tache job_d8f73edb) : job depose 13:28:19, pris par le harness SEQUENTIEL vers 13:31 (file
d'attente), resultat ok ecrit a 13:56:46 ; l'executeur, qui comptait 1 680 s depuis le DEPOT, avait abandonne a 13:56:19
(« harness MUET ») -- 27 s trop tot. L'attente en file n'est pas du silence : un job jamais demarre se dit OCCUPE, un job
demarre puis sans resultat dans sa borne se dit MUET (None).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def _poser_plus_tard(chemin: Path, delai: float, contenu: str = "1"):
    def _f():
        time.sleep(delai)
        chemin.write_text(contenu, encoding="utf-8")
    t = threading.Thread(target=_f, daemon=True)
    t.start()
    return t


def test_la_borne_court_depuis_le_demarrage(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.05)
    job = tmp_path / "vibe_x.json"
    job.write_text("{}", encoding="utf-8")
    _poser_plus_tard(job.with_suffix(".started"), 0.4)                       # pris apres 0,4 s de file
    _poser_plus_tard(job.with_suffix(".result.json"), 0.9, '{"ok": true, "output": "fait"}')
    _poser_plus_tard(job.with_suffix(".done"), 1.0)                          # 1,0 s apres depot, 0,6 s apres demarrage
    res = E._attendre_harness(job, 0.8, attente_file_s=5)                     # 0,8 s depuis le DEPOT aurait abandonne
    assert res and res.get("ok") is True, res


def test_un_job_jamais_demarre_se_dit_occupe(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.05)
    job = tmp_path / "vibe_y.json"
    job.write_text("{}", encoding="utf-8")
    res = E._attendre_harness(job, 5, attente_file_s=0.3)
    assert res and res.get("ok") is False and "OCCUPE" in str(res.get("error")), res


def test_un_job_demarre_sans_resultat_reste_muet(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.05)
    job = tmp_path / "vibe_z.json"
    job.write_text("{}", encoding="utf-8")
    job.with_suffix(".started").write_text("1", encoding="utf-8")
    assert E._attendre_harness(job, 0.3, attente_file_s=5) is None


def test_le_harness_pose_le_demarrage_avant_de_traiter(tmp_path, monkeypatch):
    import forge_harness_worker as H

    monkeypatch.setattr(H, "JOBS", tmp_path)
    job = tmp_path / "vibe_w.json"
    job.write_text('{"agent": "vibe"}', encoding="utf-8")
    vus = []
    monkeypatch.setattr(H, "process_job", lambda j: vus.append(job.with_suffix(".started").exists()) or {"ok": True})
    assert H._run_pending() == 1
    assert vus == [True], "le marqueur .started doit exister AVANT process_job"
