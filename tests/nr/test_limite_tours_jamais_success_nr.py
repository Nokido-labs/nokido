# -*- coding: utf-8 -*-
"""NR 7/11 (job_342863a9) : `claude -p` a fini en `error_max_turns` (`"is_error":true`, `"subtype":"error_max_turns"`,
aucun message final) et la tache s'est affichee `done [SUCCESS]` parce que des commits existaient.

Une sortie du harness en erreur n'est jamais SUCCESS : A_REVOIR (livraison partielle a relire) si des commits
existent, FAILURE nomme sinon, cause LIMITE_TOURS. Le verdict se lit dans le CHAMP JSON, pas dans la prose de
l'agent : une reponse qui CITE `error_max_turns` ne doit rien declencher.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402

SORTIE_MAX_TOURS = json.dumps({
    "type": "result", "subtype": "error_max_turns", "is_error": True,
    "result": None, "total_cost_usd": 0.1,
})


def _effet(commits: int) -> str:
    return "[effet observe] commits produits : %d (a..b) ; fichiers non commites : 0" % commits


def _avec_marque(commits: int) -> str:
    return "%s ; %s error_max_turns" % (_effet(commits), T._MARQUE_LIMITE_TOURS)


def _git(wt: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True)


def _depot(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "a@b.c")
    _git(wt, "config", "user.name", "t")
    (wt / "a.txt").write_text("x", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "init")
    return wt


def _preparer(monkeypatch, tmp_path: Path, wt: Path):
    """Doublures du chemin reel `_delegate_to_claude` : harness simule, budget et base neutralises."""
    monkeypatch.setenv("LAFORGE_CARTE_DELEGATION", "0")
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(T, "_workdir_claude", lambda: wt)
    monkeypatch.setattr(T, "_harness_attente_oubli", lambda task_id: None)
    monkeypatch.setattr(T, "precharger_corps_consigne", lambda consigne, workdir=None, max_caracteres=0: consigne)
    monkeypatch.setattr(T, "_config_mcp_claude", lambda *a, **k: None)
    monkeypatch.setattr(T, "_battement_delegation", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "")
    monkeypatch.setattr(T, "_consommer_budget_claude", lambda *a, **k: "")
    monkeypatch.setattr(T, "ecrire_trace_tache", lambda *a, **k: None)
    monkeypatch.setattr(T, "_finaliser_effet", lambda tid, ok, effet: ok)
    monkeypatch.setattr(T, "_reaffecter", lambda *a, **k: None)
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_consigner_verdict_auto", lambda *a, **k: None)
    clos = []
    monkeypatch.setattr(T, "_clore_delegation",
                        lambda tid, tok, ok, detail, intent=None: clos.append((ok, detail)))
    return clos


# --- lecture du CHAMP JSON -----------------------------------------------------------------------------------------

def test_limite_de_tours_lue_dans_le_champ_json():
    assert T._limite_de_tours(SORTIE_MAX_TOURS) == "error_max_turns"
    assert T._limite_de_tours('bruit\n{"type":"result","subtype":"success","is_error":false}\n') is None
    assert T._limite_de_tours(json.dumps({"type": "result", "subtype": "success", "is_error": True})) == "is_error"


def test_prose_qui_cite_error_max_turns_ne_declenche_pas():
    prose = "l'agent ecrit error_max_turns dans sa reponse, sans que le harness soit en erreur"
    assert T._limite_de_tours(prose) is None
    assert T._statut_livraison(True, _effet(1) + " | " + prose) == "SUCCESS"


# --- statut : jamais SUCCESS --------------------------------------------------------------------------------------

def test_statut_limite_de_tours_a_revoir_si_des_commits_existent():
    assert T._statut_livraison(True, _avec_marque(1)) == "A_REVOIR"


def test_statut_limite_de_tours_failure_si_aucun_commit():
    assert T._statut_livraison(True, _avec_marque(0)) == "FAILURE"


def test_clore_delegation_nomme_la_cause_limite_de_tours(monkeypatch):
    vus, marques = [], []
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(":memory:"))
    monkeypatch.setattr(T, "_mark_done", lambda conn, tid, res, o, workdir=None: marques.append(o))
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_noter_cause_echec", lambda conn, tid, cause: vus.append(cause))
    T._clore_delegation("t-tours", "jeton", True, _avec_marque(1) + " | prose agent")
    assert vus == ["LIMITE_TOURS"] and marques == [False]


# --- chemin reel de la delegation claude ---------------------------------------------------------------------------

def _deleguer(monkeypatch, tmp_path: Path, commits: int):
    wt = _depot(tmp_path)
    clos = _preparer(monkeypatch, tmp_path, wt)

    def _harness(job, delai_s, attente_file_s=None, task_id=None):
        if commits:
            (wt / "livre.txt").write_text("travail partiel", encoding="utf-8")
            _git(wt, "add", "-A")
            _git(wt, "commit", "-qm", "travail partiel")
        return {"ok": True, "output": SORTIE_MAX_TOURS}

    monkeypatch.setattr(T, "_attendre_harness", _harness)
    T._delegate_to_claude({"id": "job_tours", "agent": "CLAUDE_HEADLESS", "description": "Fais le travail"}, "jeton")
    assert clos, "la delegation doit clore la tache"
    return clos[-1]


def test_delegation_claude_max_tours_avec_commits_est_a_revoir(monkeypatch, tmp_path):
    ok, detail = _deleguer(monkeypatch, tmp_path, commits=1)
    assert T._MARQUE_LIMITE_TOURS in detail
    assert T._statut_livraison(ok, detail) == "A_REVOIR"


def test_delegation_claude_max_tours_sans_commit_est_failure(monkeypatch, tmp_path):
    ok, detail = _deleguer(monkeypatch, tmp_path, commits=0)
    assert T._MARQUE_LIMITE_TOURS in detail
    assert T._statut_livraison(ok, detail) == "FAILURE"
    assert T._statut_livraison(ok, detail) != "SUCCESS"
