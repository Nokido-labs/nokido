"""NR 27/10 : un job harness ABANDONNE par l'executeur avant son demarrage sort de la file.

Mesure : worker mort de 03 h 04 a 09 h 14 ; les jobs Vibe deposes a 05 h 06 (eec0f153) et 06 h 07
(a5971348) ont ete abandonnes par l'executeur (« harness OCCUPE ») mais laisses dans
sandbox/harness_jobs. Relance a 09 h 14 : le worker les a executes (~25 min chacun) pour personne,
et le job VIVANT (6d0c4c2a, methode C) attendait derriere eux."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

import forge_task_executor as te  # noqa: E402


def test_l_abandon_avant_demarrage_marque_le_job_fini(tmp_path):
    job = tmp_path / "vibe_job_x.json"
    job.write_text("{}", encoding="utf-8")
    res = te._attendre_harness(job, delai_s=1, attente_file_s=0.05)
    assert res and res.get("ok") is False and "OCCUPE" in res.get("error", "")
    assert job.with_suffix(".done").exists()
    r = json.loads(job.with_suffix(".result.json").read_text(encoding="utf-8"))
    assert r.get("ok") is False and "abandonne" in r.get("error", "")


def test_un_job_demarre_n_est_pas_marque_abandonne(tmp_path):
    job = tmp_path / "vibe_job_y.json"
    job.write_text("{}", encoding="utf-8")
    job.with_suffix(".started").write_text("1", encoding="utf-8")
    assert te._attendre_harness(job, delai_s=0.05, attente_file_s=0.05) is None
    assert not job.with_suffix(".done").exists()
