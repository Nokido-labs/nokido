"""NR -- RED7 cote harness : le `.result.json` d'un job CLI ne porte JAMAIS un jeton (output, screen, error).

Plan certifie 60d8ed546 RED7 (`test_cli_harness_jeton_mcp_never_logged_nor_empty`) ; enquete AGY job_194ae927 :
le harness (tools/forge_harness_worker.py) ecrivait la sortie BRUTE de l'agent -- dont l'environnement porte
FORGE_TOKEN_<AGENT> -- dans sandbox/harness_jobs/*.result.json, relu puis persiste par l'executeur. Le redacteur
existant (tools/forge_log_redact.redact) est branche avant l'ecriture. Assertions BOOLEENNES (--tb=no).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_harness_worker as W  # noqa: E402

TEMOIN = "ghp_" + "Zq7" * 12   # fabrique a l'execution, jamais un litteral


def test_le_resultat_ecrit_est_caviarde(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "JOBS", tmp_path)
    (tmp_path / "job_temoin.json").write_text(json.dumps({"agent": "cmd"}), encoding="utf-8")
    monkeypatch.setattr(W, "process_job", lambda job: {
        "ok": False, "output": "Authorization: Bearer " + TEMOIN, "screen": "token=" + TEMOIN,
        "error": "RuntimeError('Bearer %s')" % TEMOIN})
    assert W._run_pending() == 1
    ecrit = (tmp_path / "job_temoin.result.json").read_text(encoding="utf-8")
    assert TEMOIN not in ecrit and json.loads(ecrit)["ok"] is False
