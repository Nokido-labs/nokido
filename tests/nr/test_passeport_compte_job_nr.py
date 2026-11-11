# -*- coding: utf-8 -*-
"""NR — repli inscriptible sous sandbox/ sur PermissionError (compte des jobs).

Defaut mesure le 8/11 (swarm job_346b1dc1aa6f, compte des jobs run_job) :
`Permission denied` en ecrivant logs/passeport_appels.jsonl (_ecrire_passeport_fichier)
et logs/ask_block_report.jsonl.
Correctif : sur PermissionError, repli sous sandbox/ journalise une fois, jamais de perte silencieuse.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import pytest

import nokido_agent.app.forge_agent_proxy as P


def test_passeport_repli_sandbox_sur_permission_error(monkeypatch, tmp_path, caplog):
    """Sur PermissionError en ecrivant dans logs/, _ecrire_passeport_fichier se replie sous sandbox/."""
    log_dir = tmp_path / "logs"
    sbx_dir = tmp_path / "sandbox"
    log_file = log_dir / "passeport_appels.jsonl"
    sbx_file = sbx_dir / "passeport_appels.jsonl"

    monkeypatch.setattr(P, "_PASSEPORT_JOURNAL_PATH", str(log_file))
    monkeypatch.setattr(P, "_PASSEPORT_FALLBACK_PATH", str(sbx_file))
    monkeypatch.setattr(P, "_PASSEPORT_REPLI_NOTIFIE", False)

    orig_open = open

    def _simule_open(path, mode="r", *a, **kw):
        if str(log_file) in str(path):
            raise PermissionError("[WinError 5] Access is denied: %s" % path)
        return orig_open(path, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", _simule_open)

    ligne1 = {"agent": "TEST_AGENT_1", "provider": "groq", "ts": 1234567.8}
    ligne2 = {"agent": "TEST_AGENT_2", "provider": "mistral", "ts": 1234568.9}

    with caplog.at_level(logging.WARNING):
        P._ecrire_passeport_fichier(ligne1)
        P._ecrire_passeport_fichier(ligne2)

    assert not log_file.exists(), "logs/ n'aurait pas du etre ecrit suite au PermissionError"
    assert sbx_file.exists(), "sandbox/passeport_appels.jsonl doit contenir les lignes de repli"

    lignes = [json.loads(l) for l in sbx_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 2
    assert lignes[0]["agent"] == "TEST_AGENT_1"
    assert lignes[1]["agent"] == "TEST_AGENT_2"

    # Verifier que l'avertissement de repli a ete emis UNE SEULE FOIS (anti-flood)
    warnings = [rec for rec in caplog.records if "PermissionError" in rec.message and "repli" in rec.message]
    assert len(warnings) == 1, "Le repli doit etre journalise exactement UNE fois"


def test_passeport_nominal_ecrit_dans_logs(monkeypatch, tmp_path):
    """En situation nominale (sans PermissionError), le passeport s'ecrit dans logs/."""
    log_file = tmp_path / "logs" / "passeport_appels.jsonl"
    sbx_file = tmp_path / "sandbox" / "passeport_appels.jsonl"

    monkeypatch.setattr(P, "_PASSEPORT_JOURNAL_PATH", str(log_file))
    monkeypatch.setattr(P, "_PASSEPORT_FALLBACK_PATH", str(sbx_file))
    monkeypatch.setattr(P, "_PASSEPORT_REPLI_NOTIFIE", False)

    ligne = {"agent": "NOMINAL", "provider": "cohere"}
    P._ecrire_passeport_fichier(ligne)

    assert log_file.exists()
    assert not sbx_file.exists()
    assert json.loads(log_file.read_text(encoding="utf-8").strip())["agent"] == "NOMINAL"


def test_ask_block_report_repli_sandbox_sur_permission_error(monkeypatch, tmp_path, caplog):
    """Sur PermissionError en ecrivant logs/ask_block_report.jsonl, repli sous sandbox/."""
    log_file = tmp_path / "logs" / "ask_block_report.jsonl"
    sbx_file = tmp_path / "sandbox" / "ask_block_report.jsonl"

    monkeypatch.setenv("LAFORGE_ASK_BLOCK_FILE", str(log_file))
    monkeypatch.setattr(P, "_ASK_BLOCK_REPLI_NOTIFIE", False)

    orig_open = open

    def _simule_open(path, mode="r", *a, **kw):
        if str(log_file) in str(path):
            raise PermissionError("[WinError 5] Access is denied: %s" % path)
        return orig_open(path, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", _simule_open)

    _rec = {"ts": 1234567.8, "provider": "groq", "model": "llama3", "innermost": "test", "suspended_stack": []}
    _rp = str(log_file)
    _rec_str = json.dumps(_rec, ensure_ascii=False) + "\n"

    with caplog.at_level(logging.WARNING):
        try:
            with open(_rp, "a", encoding="utf-8") as _fh:
                _fh.write(_rec_str)
        except PermissionError as _pe:
            _fb_rp = str(sbx_file)
            if not P._ASK_BLOCK_REPLI_NOTIFIE:
                P._ASK_BLOCK_REPLI_NOTIFIE = True
                P.logger.warning("PermissionError sur %s (%s) -> repli sous %s", _rp, _pe, _fb_rp)
            sbx_file.parent.mkdir(parents=True, exist_ok=True)
            with open(_fb_rp, "a", encoding="utf-8") as _fh:
                _fh.write(_rec_str)

    assert not log_file.exists()
    assert sbx_file.exists()
    assert json.loads(sbx_file.read_text(encoding="utf-8").strip())["provider"] == "groq"
    warnings = [rec for rec in caplog.records if "PermissionError" in rec.message and "repli" in rec.message]
    assert len(warnings) == 1
