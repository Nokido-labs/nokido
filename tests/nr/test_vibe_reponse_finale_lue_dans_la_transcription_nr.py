"""NR -- le juge lit la reponse FINALE de Vibe, pas sa transcription JSON echappee.

Mesure 19/10 job_da317f97 (essai S en lecture) : Vibe repond JUSTE en 15 s
({"intent":"OK_DONE","pointer_ref":"app/forge_heartbeat.py:83"}, 2 read_file) mais l'executeur juge
« [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable » : `--output json` rend la transcription, ou les guillemets
sont ECHAPPES (\\"pointer_ref\\") -- la recherche du litteral "pointer_ref" ne trouvait jamais rien. Toute reponse de
lecture de Vibe etait donc jugee vide, puis reaffectee.
"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402

FINALE = '{"intent":"OK_DONE","pointer_ref":"app/forge_heartbeat.py:83","commit_message":"lecture seule"}'


def _transcription():
    return json.dumps([
        {"role": "user", "type": "message", "content": [{"type": "text", "text": "consigne avec \"pointer_ref\""}]},
        {"type": "effect", "detail": {"toolName": "file_system.read_file"}},
        {"role": "assistant", "type": "message", "content": [{"type": "text", "text": FINALE}]},
    ], ensure_ascii=False, indent=2)


def test_texte_final_extrait_de_la_transcription():
    assert T._texte_final_vibe(_transcription()) == FINALE


def test_sortie_non_json_rendue_telle_quelle():
    assert T._texte_final_vibe("Error: 429 rate limit") == "Error: 429 rate limit"


def test_une_reponse_de_lecture_juste_n_est_plus_jugee_vide(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_modele_hors_quota", lambda *_a: None)
    monkeypatch.setattr(T, "_workdir_vibe", lambda: tmp_path / "wt")
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(T, "_config_mcp_vibe", lambda _wt: None)
    monkeypatch.setattr(T, "_etat_git", lambda _wt: None)
    monkeypatch.setattr(T, "_chemins_status", lambda _wt: frozenset())
    monkeypatch.setattr(T, "_battement_delegation", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(T, "_attendre_harness", lambda *_a, **_k: {"ok": True, "output": _transcription()})
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *_a, **_k: "")
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, detail, wt, avant: (ok, "commits produits : 0", None))
    monkeypatch.setattr(T, "_consigner_verdict_auto", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_motif_reaffectation_apres", lambda *_a, **_k: None)
    vus = {}
    monkeypatch.setattr(T, "_clore_delegation", lambda task_id, token, ok, detail, intent=None: vus.update(ok=ok,
                                                                                                         detail=detail))
    T._delegate_to_vibe({"id": "job_vibe_lecture_nr", "description": "lis"}, "tok")
    assert vus.get("ok") is True, vus.get("detail", "")[-300:]
    assert "AUCUN EFFET" not in vus.get("detail", "")


def test_transcription_caviardee_reste_lisible():
    """20/10 job_499ed100 : le redacteur du harness lit `\\n@pytest.fixture` (code lu par read_file) comme une adresse
    et laisse `\\[EMAIL_1]` -- un echappement JSON INVALIDE. json.loads echouait, la transcription brute partait au juge :
    le faux « AUCUN EFFET » du 19/10 revenait par le caviardage."""
    from forge_log_redact import redact
    brute = json.dumps([
        {"role": "user", "type": "message", "content": [{"type": "text", "text": "lis"}]},
        {"type": "effect", "state": {"output": {"content": "import pytest\n\n\n@pytest.fixture\ndef agent():\n"}}},
        {"role": "assistant", "type": "message", "content": [{"type": "text", "text": FINALE}]},
    ], ensure_ascii=False, indent=2)
    caviardee = redact(brute)
    try:
        json.loads(caviardee)
        corrompue = False
    except ValueError:
        corrompue = True
    assert corrompue, "precondition : le redacteur ne corrompt plus la transcription -- revoir ce NR"
    assert T._texte_final_vibe(caviardee) == FINALE
