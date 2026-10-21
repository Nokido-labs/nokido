# -*- coding: utf-8 -*-
"""NR HAMILTON : un run_job est DIFFERABLE dans sa fiche (carte AGY d50229242, 19/10).

`run action=run_job` et POST /admin/run_job n'atteignent PAS spawn_as_sandbox (launch_job ->
spawn_as_sandbox_detached) : le gate de classe de spawn_as_sandbox ne les voit jamais. Le hub les qualifie
deja de lourds (admettre_lancement : check_ressources(heavy=True) en dur) ; doctrine Hamilton : run_job heavy
= DIFFERABLE. La classe est donc DECIDEE COTE HUB, sans parametre client, et ecrite dans la fiche que
reconcile_jobs lit (RED_4 : survivant DIFFERABLE sous saturation = A_SUSPENDRE).
Aucun process lance : spawn_as_sandbox_detached est substitue.
"""
import importlib
import json

import pytest


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_job_runner")
    monkeypatch.setattr(mod, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(mod, "_root", lambda: tmp_path)
    import nokido_agent.app.forge_sandbox_exec as sx
    monkeypatch.setattr(sx, "spawn_as_sandbox_detached", lambda cmd, log, err, online=False: {"pid": 4242})
    return mod


def test_la_fiche_d_un_run_job_porte_la_classe_differable(runner, tmp_path):
    script = tmp_path / "cible.py"
    script.write_text("print('x')\n", encoding="utf-8")
    res = runner.launch_job(str(script), lane="ci")
    assert res["ok"], res
    fiche = json.loads((runner.JOBS_DIR / (res["job_id"] + ".json")).read_text(encoding="utf-8"))
    assert fiche["classe"] == "DIFFERABLE"
