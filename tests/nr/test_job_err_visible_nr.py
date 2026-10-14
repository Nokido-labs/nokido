# -*- coding: utf-8 -*-
"""NR -- la cause d'un job en echec est RENDUE, pas laissee sur le disque (owner 2026-10-13 : « capte-le et
branche-le »).

Mesure du 13/10 : job_status d'un job mort sur `ModuleNotFoundError` rendait rc=1 et un log_tail VIDE -- le
Traceback etait dans `<job>.err`, que read_job ne lisait pas ; et le guet ecrivait « sans motif lisible » pour des
pre-controles rouges dont la gate fautive (❌ golden-rules) etait ecrite noir sur blanc dans le journal.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_job_status_rend_le_stderr_du_job(tmp_path, monkeypatch):
    J = _charger("app/forge_job_runner.py", "forge_job_runner_err_nr")
    monkeypatch.setattr(J, "JOBS_DIR", tmp_path)
    log = tmp_path / "job_x.log"
    log.write_text("", encoding="utf-8")
    (tmp_path / "job_x.rc").write_text("1", encoding="utf-8")
    (tmp_path / "job_x.err").write_text(
        "Traceback (most recent call last):\nModuleNotFoundError: No module named 'nokido_agent'\n", encoding="utf-8")
    (tmp_path / "job_x.json").write_text(json.dumps({
        "rc_file": str(tmp_path / "job_x.rc"), "log": str(log), "status": "done", "timed_out": "FAUX"}),
        encoding="utf-8")
    r = J.read_job("job_x")
    assert r["rc"] == 1 and r["log_tail"] == ""
    assert "ModuleNotFoundError" in r["err_tail"], "la cause etait sur le disque, job_status doit la rendre"
    assert r["err_fichier"].endswith("job_x.err")


def test_le_guet_cite_la_gate_rouge_au_lieu_de_sans_motif():
    W = _charger("tools/forge_job_watch_cli.py", "forge_job_watch_cli_err_nr")
    b = W.lire_bilan("== gates rc=1\n  ✅ ruff critique\n  ❌ golden-rules (cliquet ERROR)\n", "1")
    assert b["etat"] == "ECHEC" and "golden-rules" in b["motif"], b


def test_un_journal_vraiment_muet_le_dit():
    W = _charger("tools/forge_job_watch_cli.py", "forge_job_watch_cli_muet_nr")
    b = W.lire_bilan("", "1")
    assert b["etat"] == "ECHEC" and "sans motif lisible" in b["motif"]
