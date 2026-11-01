"""NR du 27/10 : porte 1 -- le banc rend les BORNES de debit par moteur de chaque candidat.

Proposition owner : rejeter un candidat sur ses bornes AVANT tout reaccord (3 700 essais). Les bornes se
lisent sur le programme : valu+alu/8 a 7,5/cycle, load a 2/cycle, flow a 1/cycle (pause exclue).
"""
from __future__ import annotations

import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N / "tools"))
import forge_bench_takehome as J  # noqa: E402


def test_bornes_par_moteur():
    prog = [{"flow": [["pause"]]},
            {"valu": [["^", 0, 1, 2]] * 6, "alu": [["+", 0, 1, 2]] * 12, "load": [["load", 0, 1]] * 2,
             "flow": [["vselect", 0, 1, 2, 3]]},
            {"valu": [["^", 0, 1, 2]] * 3, "flow": [["pause"]]}]
    b = J.bornes(prog)
    assert b["valu"] == 9 and b["alu"] == 12 and b["load"] == 2 and b["flow"] == 1
    assert b["borne_calcul"] == 2  # ceil((9 + 12/8) / 7.5) = ceil(1.4) = 2
    assert b["borne_load"] == 1 and b["borne_flow"] == 1
    assert b["borne"] == max(b["borne_calcul"], b["borne_load"], b["borne_flow"])
