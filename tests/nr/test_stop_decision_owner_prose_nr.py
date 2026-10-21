"""NR -- une decision owner en attente se POSE en choix multiple, jamais en prose (owner 18/10, 2e recidive 19/10).

« pour les roadmaps partiel attendant 11 decisions owner, je t'ai deja demande [...] listes a choix multiples
systematiquement, je vais pas le repeter » : la fiche memoire existait, la regle n'arretait rien. Ce qui peut
m'arreter : le hook Stop (`hook_stop_attente_passive`) lit aussi les OUTILS du tour ; un message qui evoque une
decision owner en attente sans `AskUserQuestion` dans le tour est un ecart.
Decision owner 19/10 : OBSERVATION d'abord -- journalise, ne bloque pas ; bloquant seulement par l'interrupteur
NOKIDO_GARDE_DECISION_PROSE=bloquant, apres mesure du bruit.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import hook_stop_attente_passive as h  # noqa: E402


def test_decision_owner_en_prose_sans_question_est_un_ecart():
    assert h.decider_decision_prose("PARTIEL : 25 libres, 11 owner, 7 serie.", []) is not None
    assert h.decider_decision_prose("Il reste 2 decisions owner a trancher.", ["Read"]) is not None


def test_question_posee_dans_le_tour_tait_le_garde():
    assert h.decider_decision_prose("11 decisions owner : je te les pose.", ["AskUserQuestion"]) is None


def test_message_sans_decision_owner_ne_dit_rien():
    assert h.decider_decision_prose("CI verte, commit 1234abc pousse en local.", []) is None


def _transcript(tmp_path, texte, outils):
    lignes = [{"type": "user", "message": {"role": "user", "content": "point ?"}},
              {"type": "assistant", "message": {"role": "assistant", "content": [
                  *[{"type": "tool_use", "name": o, "input": {}} for o in outils],
                  {"type": "text", "text": texte}]}}]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    return p


def test_observation_journalise_sans_bloquer(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NOKIDO_GARDE_DECISION_PROSE", raising=False)
    monkeypatch.setattr(h, "JOURNAL_PROSE", tmp_path / "prose.jsonl")
    p = _transcript(tmp_path, "Portes : 11 owner, 25 libres.", [])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(p)})))
    assert h.main() == 0
    assert "block" not in capsys.readouterr().out
    assert len((tmp_path / "prose.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_interrupteur_bloquant_bloque(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NOKIDO_GARDE_DECISION_PROSE", "bloquant")
    monkeypatch.setattr(h, "JOURNAL_PROSE", tmp_path / "prose.jsonl")
    p = _transcript(tmp_path, "Portes : 11 owner, 25 libres.", [])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(p)})))
    h.main()
    assert '"block"' in capsys.readouterr().out
