"""NR 18/10 -- ratio d'efficacite metabolique (REM) de l'auto-amelioration (chantier 4b de bb P1_preparation_takehome).

Owner : REM = gains valides / (jetons + CPU) ; s'il baisse 3 cycles, l'exploration ralentit. Le denominateur
« jetons » a enfin une source vivante (token_events, emise par le routeur depuis 6d0e68942). Contrat : une fenetre
au cout illisible a un REM INCONNU (None), jamais 0 ; la decision de ralentir exige 3 fenetres CONNUES en baisse
stricte -- jamais une decision sur de l'inconnu. Et convergence_rsi lit l'orientation enregistree (MIN : une
baisse de cycles est un gain).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_regulation_efficacy as RE  # noqa: E402


def test_rem_par_fenetre_inconnu_n_est_pas_zero():
    serie = RE.rem_serie([(2, 1_000_000, 100.0), (0, 500_000, 50.0), (1, None, 10.0)])
    assert serie[0] > 0 and serie[1] == 0 and serie[2] is None


def test_ralentir_exige_trois_fenetres_connues_en_baisse_stricte():
    assert RE.ralentir_exploration([3.0, 2.0, 1.0]) is True
    assert RE.ralentir_exploration([3.0, 3.0, 1.0]) is False
    assert RE.ralentir_exploration([2.0, 1.0]) is False
    assert RE.ralentir_exploration([3.0, None, 1.0]) is False, "pas de decision sur de l'inconnu"


def test_jetons_lus_dans_token_events(tmp_path):
    db = tmp_path / "token_usage.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE token_events (ts TEXT, provider TEXT, session_id TEXT, input_tok INT, output_tok INT, cost REAL)")
    con.executemany("INSERT INTO token_events VALUES (?,?,?,?,?,?)",
                    [("2026-10-18T10:00:00", "groq", "s", 100, 50, 0.0), ("2026-10-18T12:00:00", "groq", "s", 10, 5, 0.0)])
    con.commit()
    con.close()
    assert RE.jetons_token_events(db, depuis="2026-10-18T11:00:00") == 15
    assert RE.jetons_token_events(db) == 165
    assert RE.jetons_token_events(tmp_path / "absente.db") is None


def test_convergence_lit_l_orientation_min():
    post = {"kind": "post_application", "niveau": "L1", "ts": "2026-10-18T10:00:00", "verdict": "CONSERVE",
            "cible": "param:x", "application": {"nouvelle": 2}, "reference": {"cycles": 100},
            "apres": {"cycles": 80}, "bruit": {"cycles": 0}, "orientation": {"cycles": "MIN"}}
    assert RE.convergence_rsi([post], [])["ameliorations_validees"] == 1
