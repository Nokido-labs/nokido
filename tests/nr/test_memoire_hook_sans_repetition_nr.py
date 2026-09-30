# -*- coding: utf-8 -*-
"""NR — le hook de debut de tour ne reinjecte pas une strate memoire inchangee.

Mesure du 2026-09-24 : 58 blocs [memoire:immediate] identiques (memes dettes de
75,9 et 69 jours, meme score proprioceptif) dans un seul transcript Claude Code,
payes a chaque prompt et re-factures dans l'historique.

Contrat de `claude_inbox_tick._sans_repetition` :
  1. premier tour de la session : tout est montre ;
  2. section identique, dans la fenetre : retiree ;
  3. section qui CHANGE : montree ;
  4. au-dela de la fenetre de rappel : re-montree (une compaction a pu l'effacer) ;
  5. sans identifiant de session : rien n'est retire (on ne devine pas).
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

TEXTE = ("[memoire:immediate] DETTES OUVERTES (elles reclament)\n  - dette_a (75.9 j) - x\n"
         "[memoire:proprioceptive] ETAT DU CORPS\n  - score 82/100")


@pytest.fixture
def tick():
    spec = importlib.util.spec_from_file_location("claude_inbox_tick_nr", ROOT / "tools" / "claude_inbox_tick.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_premier_tour_puis_silence(tick, tmp_path):
    assert tick._sans_repetition(TEXTE, "s1", 1000.0, tmp_path) == TEXTE
    assert tick._sans_repetition(TEXTE, "s1", 1001.0, tmp_path) is None


def test_seule_la_section_changee_revient(tick, tmp_path):
    tick._sans_repetition(TEXTE, "s1", 1000.0, tmp_path)
    change = TEXTE.replace("82/100", "70/100")
    sortie = tick._sans_repetition(change, "s1", 1001.0, tmp_path)
    assert "70/100" in sortie and "DETTES OUVERTES" not in sortie


def test_rappel_apres_la_fenetre(tick, tmp_path):
    tick._sans_repetition(TEXTE, "s1", 1000.0, tmp_path)
    tard = 1000.0 + tick._RAPPEL_MEMOIRE_S + 1
    assert tick._sans_repetition(TEXTE, "s1", tard, tmp_path) == TEXTE


def test_sans_session_rien_n_est_retire(tick, tmp_path):
    tick._sans_repetition(TEXTE, "", 1000.0, tmp_path)
    assert tick._sans_repetition(TEXTE, "", 1001.0, tmp_path) == TEXTE


def test_sessions_independantes(tick, tmp_path):
    tick._sans_repetition(TEXTE, "s1", 1000.0, tmp_path)
    assert tick._sans_repetition(TEXTE, "s2", 1001.0, tmp_path) == TEXTE
