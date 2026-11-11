# -*- coding: utf-8 -*-
"""NR (3/11, bilan de sante) : « alerte de budget quotidien NON EMISE (TypeError) » a chaque bilan.

daily_report() sommait SUM(cost_usd) : un fournisseur dont le cout n'est pas renseigne rend NULL -> sum()/round(None)
levent TypeError, et l'alerte de budget cloud ne partait plus du tout. Un cout INCONNU n'est pas un cout NUL
(UNKNOWN != NO) : le rapport somme le connu, compte les appels sans cout et le DIT (cout_partiel).
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_token_monitor as T  # noqa: E402


def _base(tmp_path, lignes):
    db = tmp_path / "tokens.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE token_usage (provider TEXT, model TEXT, prompt_tokens INT, completion_tokens INT, "
              "total_tokens INT, cost_usd REAL, latency_ms REAL, ts TEXT)")
    c.executemany("INSERT INTO token_usage VALUES (?,?,?,?,?,?,?,datetime('now'))", lignes)
    c.commit()
    c.close()
    return db


def test_un_cout_inconnu_ne_casse_pas_le_rapport_et_est_dit(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "DB", _base(tmp_path, [("groq", "m", 10, 5, 15, None, 100.0),
                                                  ("mistral", "m", 10, 5, 15, 0.25, 80.0)]))
    r = T.daily_report()
    assert r["daily_cost_usd"] == 0.25
    assert r["cout_partiel"] is True and r["appels_sans_cout"] == 1
    inconnu = [b for b in r["breakdown"] if b["provider"] == "groq"][0]
    assert inconnu["cost_usd"] is None                       # inconnu reste inconnu, pas 0


def test_tous_les_couts_connus_rapport_complet(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "DB", _base(tmp_path, [("mistral", "m", 10, 5, 15, 0.25, 80.0)]))
    r = T.daily_report()
    assert r["daily_cost_usd"] == 0.25 and r["cout_partiel"] is False and r["appels_sans_cout"] == 0
