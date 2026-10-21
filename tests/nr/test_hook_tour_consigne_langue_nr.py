"""NR -- le hook de chaque tour (tools/claude_inbox_tick.py) rappelle la LANGUE en dernier, toujours (owner 2026-10-20).

Le 20/10, cinq rappels de l'owner en une heure (« parle en français ! » ... « en FRANCAIS bordel !!! ancre le ») :
le plugin tiers « caveman » injecte a chaque message une consigne en ANGLAIS, et la sortie derivait vers sa langue
malgre la consigne permanente et une fiche memoire. Une fiche ne m'arrete pas ; un hook qui parle a chaque tour, si.

Ce qui est garde : la consigne de langue est la DERNIERE ligne emise (le texte le plus recent pese le plus), elle est
emise meme quand le hook n'a rien d'autre a dire, et elle est en francais.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module(monkeypatch, sense="", inbox=(), postal=(), skills=(), memoire=""):
    spec = importlib.util.spec_from_file_location("inbox_tick_langue_nr", RACINE / "tools" / "claude_inbox_tick.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    class _Conn:
        def close(self):
            pass
    monkeypatch.setattr(m, "_intention", lambda: "")
    monkeypatch.setattr(m, "_sense", lambda: sense)
    monkeypatch.setattr(m, "_db", lambda: _Conn())
    monkeypatch.setattr(m, "_inbox", lambda conn: list(inbox))
    monkeypatch.setattr(m, "_postal", lambda: list(postal))
    monkeypatch.setattr(m, "_skills_du_tour", lambda: list(skills))
    monkeypatch.setattr(m, "_memoire", lambda intention: memoire)
    monkeypatch.setattr(m, "_sans_repetition", lambda texte, session, *a, **k: texte)
    return m


def test_la_langue_est_rappelee_meme_quand_le_hook_n_a_rien_a_dire(monkeypatch, capsys):
    _module(monkeypatch).main()
    lignes = capsys.readouterr().out.strip().splitlines()
    assert lignes, "le hook doit parler a chaque tour"
    assert "FRANÇAIS" in lignes[-1] and "caveman" in lignes[-1]


def test_la_langue_est_la_derniere_ligne_emise(monkeypatch, capsys):
    _module(monkeypatch, sense="[sense] ok", inbox=["[inbox] un message"], memoire="[memoire] un rappel").main()
    lignes = capsys.readouterr().out.strip().splitlines()
    assert lignes[0] == "[sense] ok"
    assert "FRANÇAIS" in lignes[-1], lignes
