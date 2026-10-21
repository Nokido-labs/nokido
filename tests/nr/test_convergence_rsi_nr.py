"""NR 18/10 -- elargissement RSI n°1 (decision owner) : mesurer si Nokido APPREND d'un cycle a l'autre, pas le volume.

Le registre grossissait (1 164 lignes) sans qu'aucun indicateur ne dise si la boucle converge. `convergence_rsi` (dans
l'organe d'efficacite de la regulation, a cote de la metrique de la boucle A) rend :
  * `taux_repetition` : part des actes L1 juges dont la valeur cible avait DEJA ete jugee sans gain (doit tendre vers 0) ;
  * `essais_par_amelioration` : (actes L1 juges + tentatives L2 de production) / ameliorations validees
    (L1 CONSERVE -- un gain hors bruit depuis le 18/10 -- et L2 AMELIORE de production) ;
  * `conversion_triage_juge` : dossiers A_TRAITER parvenus au juge / dossiers A_TRAITER.
Rien de mesurable = None, jamais 0 (illisible n'est pas nul).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_regulation_efficacy as fre  # noqa: E402


def _post(valeur, verdict, ts, ref=50.0, apres=50.0):
    return {"kind": "post_application", "niveau": "L1", "cible": "param:x", "verdict": verdict, "ts": ts,
            "application": {"param": "x", "nouvelle": valeur},
            "reference": {"tps": ref}, "apres": {"tps": apres}, "bruit": {"tps": 5.0}}


REGISTRE = [
    _post(40, "SURVIT_SANS_GAIN", "2026-10-18T01:00:00"),
    _post(40, "SURVIT_SANS_GAIN", "2026-10-18T07:00:00"),     # repetition d'un essai deja juge sans gain
    _post(24, "CONSERVE", "2026-10-18T13:00:00", ref=50.0, apres=58.0),   # gain HORS bruit : compte
    # CONSERVE de l'ANCIENNE regle (gain dans le bruit, 15/10) : ne compte PAS comme amelioration validee
    _post(16, "CONSERVE", "2026-10-15T09:15:43", ref=49.148, apres=50.847),
    {"kind": "triage", "dossier": "d1", "reexamen": {"verdict": "A_TRAITER"}},
    {"kind": "triage", "dossier": "d2", "reexamen": {"verdict": "A_TRAITER"}},
    {"kind": "triage", "dossier": "d3", "reexamen": {"verdict": "RESOLU"}},
]
LEDGER = [
    {"verdict": "AMELIORE", "ts": "2026-10-18T14:00:00", "origine": "production", "dossier": "d1"},
    {"verdict": "MEURT", "ts": "2026-10-18T15:00:00", "origine": "qualification", "dossier": "d2"},   # banc : exclu
]


def test_convergence_sur_registre_et_ledger_synthetiques():
    c = fre.convergence_rsi(REGISTRE, LEDGER)
    assert c["actes_l1_juges"] == 4 and c["repetitions_sans_gain"] == 1, c
    assert abs(c["taux_repetition"] - 1 / 4) < 1e-9, c
    assert c["ameliorations_validees"] == 2, c   # 1 L1 au gain HORS bruit + 1 L2 AMELIORE ; le CONSERVE du 15/10 non
    assert c["essais_par_amelioration"] == 2.5, c               # (4 actes L1 + 1 tentative L2 prod) / 2
    assert c["a_traiter"] == 2 and c["a_traiter_juges"] == 1 and c["conversion_triage_juge"] == 0.5, c


def test_rien_de_mesurable_rend_none_jamais_zero():
    c = fre.convergence_rsi([], [])
    assert c["taux_repetition"] is None and c["essais_par_amelioration"] is None
    assert c["conversion_triage_juge"] is None
