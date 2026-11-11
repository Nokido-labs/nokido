"""NR — hook_recon_first v2 : task assign ne bloque plus sur sa consigne.

Prouve :
1. `task assign` citant nokidotaskexecutorantigravity, delivery_integrity, tmp_path,
   nokidoepistemicsoif, pointer_ref, from_agent ne bloque pas (rc == 0).
   Supporte les variantes de noms MCP : `mcp__nokido-oauth__task`, `mcp__laforge-sovereign-hub__task`, etc.
2. `run` sur un terme a pieges anterieurs bloque toujours (rc == 2).
3. Consultation fraiche avant creation de module neuf toujours exigee (rc == 2).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_recon_first as HRF  # noqa: E402


def _simuler_hook(event: dict, monkeypatch, tmp_path: Path) -> tuple[int, str, str]:
    etat_file = tmp_path / "recon_first_state.json"
    monkeypatch.setattr(HRF, "ETAT", etat_file)
    monkeypatch.setattr(HRF, "ROOT", tmp_path)

    stdin_data = io.StringIO(json.dumps(event))
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    monkeypatch.setattr(sys, "stdin", stdin_data)
    monkeypatch.setattr(sys, "stdout", stdout_capture)
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    rc = HRF.main()
    return rc, stdout_capture.getvalue(), stderr_capture.getvalue()


def test_task_assign_ne_bloque_plus(monkeypatch, tmp_path):
    """Prouve que task assign citant des mots a pieges/domaines ne bloque pas."""
    consigne = (
        "Execution deleguee avec nokidotaskexecutorantigravity, delivery_integrity "
        "sous tmp_path avec nokidoepistemicsoif, pointer_ref et from_agent. "
        "Verifier aussi le domaine agy et npu."
    )
    # Test avec differents noms d'outils reels
    for tool_name in (
        "mcp__nokido-oauth__task",
        "mcp__laforge-sovereign-hub__task",
        "__task",
        "task",
    ):
        event = {
            "session_id": "test_sess_001",
            "tool_name": tool_name,
            "tool_input": {
                "action": "assign",
                "agent": "ANTIGRAVITY",
                "prompt": consigne,
                "context": {"from_agent": "MAIN", "pointer_ref": "ref123"},
            },
        }
        rc, _, _ = _simuler_hook(event, monkeypatch, tmp_path)
        assert rc == 0, f"task assign a bloque avec rc={rc} pour tool_name={tool_name}"


def test_task_status_ne_bloque_pas_sur_task_id(monkeypatch, tmp_path):
    event = {
        "session_id": "test_sess_002",
        "tool_name": "mcp__nokido-oauth__task",
        "tool_input": {"action": "status", "task_id": "job_x", "explanation": "task_id updated_at"},
    }
    rc, _, _ = _simuler_hook(event, monkeypatch, tmp_path)
    assert rc == 0


def _index_piege(monkeypatch, jeton):
    from nokido_agent.tools import forge_symptom_index as FSI
    monkeypatch.setattr(FSI, "charger_index", lambda: {"sessions": [{
        "session": "sess_ancienne", "date": "2026-07-26", "jetons": [jeton], "n_pieges": 1,
        "pieges": [{"extrait": "piege", "jetons": [jeton]}], "origine": "partage"}]})


def test_identifiants_et_explanation_de_run_ne_bloquent_pas(monkeypatch, tmp_path):
    _index_piege(monkeypatch, "piege_testant")
    event = {"session_id": "s3", "tool_name": "mcp__nokido-oauth__run",
             "tool_input": {"action": "job_status", "job_id": "piege_testant", "task_id": "piege_testant",
                            "explanation": "lire piege_testant", "lane": "piege_testant"}}
    assert _simuler_hook(event, monkeypatch, tmp_path)[0] == 0


def test_run_bloque_toujours_sur_piege_anterieur(monkeypatch, tmp_path):
    """Prouve que run sur un symptome avec pieges anterieurs bloque (rc == 2)."""
    # Schema reel attendu par forge_symptom_index.demander et charger_index
    faux_index = {
        "sessions": [
            {
                "session": "sess_ancienne",
                "date": "2026-07-26",
                "jetons": ["piege_testant"],
                "n_pieges": 1,
                "pieges": [
                    {
                        "extrait": "Attention au piege_testant dans ce composant.",
                        "jetons": ["piege_testant"],
                    }
                ],
                "origine": "partage",
            }
        ],
        "sources": ["partage:1"],
        "illisibles": [],
        "n_sessions": 1,
    }

    # Le hook importe ce module sous ce nom : doubler `forge_symptom_index` nu ne l'atteindrait pas.
    from nokido_agent.tools import forge_symptom_index as FSI
    monkeypatch.setattr(FSI, "charger_index", lambda: faux_index)

    event = {
        "session_id": "sess_actuelle",
        "tool_name": "mcp__nokido-oauth__run",
        "tool_input": {
            "action": "shell",
            "command": "python script.py --check piege_testant",
        },
    }
    rc, _, stderr = _simuler_hook(event, monkeypatch, tmp_path)
    assert rc == 2
    assert "STOP" in stderr
    assert "piege_testant" in stderr


def test_creation_module_exige_consultation_fraiche(monkeypatch, tmp_path):
    """Prouve que la creation d'un module forge_* sans consultation fraiche bloque."""
    event = {
        "session_id": "sess_test",
        "tool_name": "mcp__nokido-oauth__governed_edit",
        "tool_input": {
            "action": "write",
            "path": "app/forge_nouveau_module_test.py",
            "content": "# code neuf\n",
        },
    }
    rc, _, stderr = _simuler_hook(event, monkeypatch, tmp_path)
    assert rc == 2
    assert "STOP" in stderr
    assert "forge_nouveau_module_test.py" in stderr
