# -*- coding: utf-8 -*-
"""
PR-2 AXE 8 — évaluateur d'issue de dialogue (succès/échec) + câblage récompense.
RED-first. Voir docs/specs/axe8_persona_unifiee_plan.md §0.bis.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app import forge_dialogue_outcome as fdo  # noqa: E402

GOOD = (
    "Le bug vient du check d'expiration du token : il utilise `<` au lieu de `<=`. "
    "Corrige en remplaçant l'opérateur dans auth_middleware.py ligne 42."
)


def test_user_correction_is_failure():
    out = fdo.evaluate_exchange("fix le bug", GOOD, next_user_msg="non c'est faux, ça marche pas")
    assert out.success is False
    assert any("correction" in s for s in out.signals)


def test_user_approval_is_success():
    out = fdo.evaluate_exchange("fix le bug", GOOD, next_user_msg="parfait merci, exact")
    assert out.success is True
    assert any("approval" in s for s in out.signals)


def test_no_reaction_good_response_is_success():
    out = fdo.evaluate_exchange("fix le bug", GOOD, next_user_msg="")
    assert out.success is True


def test_no_reaction_refusal_response_is_failure():
    refusal = "Je ne peux pas faire ça en tant qu'IA."
    out = fdo.evaluate_exchange("fix le bug", refusal, next_user_msg="")
    assert out.success is False


def test_topic_defaults_to_general():
    out = fdo.evaluate_exchange("x", GOOD)
    assert out.topic == "general"


def test_record_outcome_success_calls_reward(monkeypatch):
    calls = {}
    monkeypatch.setattr(fdo, "_reward", lambda method, time_s, n_steps, success, target="": calls.setdefault("reward", method))
    monkeypatch.setattr(fdo, "_punish", lambda method, error="", target="": calls.setdefault("punish", method))
    out = fdo.Outcome(success=True, score=0.9, signals=[], topic="auth")
    fdo.record_outcome(out)
    assert calls.get("reward") == "persona:dialogue:auth"
    assert "punish" not in calls


def test_record_outcome_failure_calls_punish(monkeypatch):
    calls = {}
    monkeypatch.setattr(fdo, "_reward", lambda method, time_s, n_steps, success, target="": calls.setdefault("reward", method))
    monkeypatch.setattr(fdo, "_punish", lambda method, error="", target="": calls.setdefault("punish", method))
    out = fdo.Outcome(success=False, score=0.1, signals=["user_correction:1"], topic="auth")
    fdo.record_outcome(out)
    assert calls.get("punish") == "persona:dialogue:auth"
    assert "reward" not in calls


def test_score_session_turns_uses_next_user_reaction(monkeypatch):
    rec = []
    monkeypatch.setattr(fdo, "_reward", lambda *a, **k: rec.append("r"))
    monkeypatch.setattr(fdo, "_punish", lambda *a, **k: rec.append("p"))
    persisted = []
    monkeypatch.setattr(fdo, "_persist_exemplar", lambda u, a, topic="general": persisted.append(topic))
    turns = [
        ("user", "fix le bug"),
        ("assistant", GOOD),            # suivi d'une correction → échec
        ("user", "non c'est faux, marche pas"),
        ("assistant", GOOD),            # suivi d'une approbation → succès + exemplar
        ("user", "parfait merci exact"),
    ]
    outs = fdo.score_session_turns(turns)
    assert len(outs) == 2
    assert outs[0].success is False
    assert outs[1].success is True
    assert rec == ["p", "r"]
    assert persisted  # l'échange approuvé est persisté comme exemplar


def test_persist_exemplar_best_effort(tmp_path):
    # DB inexistante → ne crashe pas, retourne ""
    cid = fdo._persist_exemplar("u", "a", "t", db_path=str(tmp_path / "nope.db"))
    assert isinstance(cid, str)


def test_score_session_start_index_and_require_next(monkeypatch):
    rec = []
    monkeypatch.setattr(fdo, "_reward", lambda *a, **k: rec.append("r"))
    monkeypatch.setattr(fdo, "_punish", lambda *a, **k: rec.append("p"))
    monkeypatch.setattr(fdo, "_persist_exemplar", lambda *a, **k: "")
    turns = [("user", "q1"), ("assistant", GOOD), ("user", "parfait"), ("assistant", GOOD)]
    # require_next : le dernier assistant (idx3) sans réaction → non scoré ; seul idx1
    outs = fdo.score_session_turns(turns, require_next=True)
    assert len(outs) == 1
    # watermark au-delà de tout → rien
    assert fdo.score_session_turns(turns, start_index=4) == []
