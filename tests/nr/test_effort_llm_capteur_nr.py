"""NR 18/10 -- capteur d'effort LLM de l'hypothalamus (p1_coeur_suit_effort_llm_20261013).

La source vivante existe enfin (token_events emise par le routeur, 6d0e68942). Contrat : effort sur la derniere
fenetre de 5 min RELATIF a la mediane des tranches ACTIVES de 24 h (jamais un absolu : lecon TSH saturee) ; base
illisible ou aucune tranche active = ratio INCONNU, jamais 0 ; l'hypothalamus libere ADRENALINE_HUB_PRESSURE
GRADUEE (niveau = 1 - 1/ratio, aucun seuil invente) a TTL court (180 s) seulement si l'effort depasse sa mediane.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_health_diagnostic as HD  # noqa: E402

T0 = datetime(2026, 10, 18, 12, 0, 0)


def _db(tmp_path, lignes):
    db = tmp_path / "token_usage.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE token_events (ts TEXT, provider TEXT, session_id TEXT, input_tok INT, output_tok INT, cost REAL)")
    con.executemany("INSERT INTO token_events VALUES (?,?,?,?,?,?)",
                    [((T0 - d).isoformat(), "groq", "s", e, s, 0.0) for d, e, s in lignes])
    con.commit()
    con.close()
    return db


def test_effort_relatif_a_la_mediane_des_tranches_actives(tmp_path):
    passe = [(timedelta(minutes=10 + 5 * i), 80, 20) for i in range(10)]          # 10 tranches a 100 jetons
    courant = [(timedelta(minutes=1), 150, 50), (timedelta(minutes=2), 150, 50)]  # 400 jetons, 2 appels
    e = HD.effort_llm(_db(tmp_path, passe + courant), maintenant=T0)
    assert e["jetons_fenetre"] == 400 and e["appels_fenetre"] == 2
    assert e["mediane_24h"] == 100 and e["ratio"] == 4.0


def test_inconnu_n_est_pas_zero(tmp_path):
    assert HD.effort_llm(_db(tmp_path, [(timedelta(minutes=1), 10, 0)]), maintenant=T0)["ratio"] is None
    assert HD.effort_llm(tmp_path / "absente.db", maintenant=T0)["ratio"] is None


def _audit(ratio):
    return {"rag_chunks": {"pct_vectorized": 95.0, "non_vectorized": 0},
            "messages": {"agent_messages_pct_unread": 0, "agent_messages_total": 0},
            "effort_llm": {"ratio": ratio}}


def _endocrine(monkeypatch):
    emis = []
    faux = types.ModuleType("nokido_agent.app.forge_endocrine")
    faux.release = lambda h, level, **k: emis.append((h, round(level, 3), k.get("ttl_s"))) or {"hormone": h}
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_endocrine", faux)
    return emis


def test_adrenaline_graduee_ttl_court_au_dessus_de_la_mediane(monkeypatch):
    emis = _endocrine(monkeypatch)
    HD._release_hormones_from_audit(_audit(4.0))
    assert ("ADRENALINE_HUB_PRESSURE", 0.75, 180) in emis


def test_pas_d_adrenaline_sous_la_mediane_ni_sur_l_inconnu(monkeypatch):
    for ratio in (None, 1.0, 0.5):
        emis = _endocrine(monkeypatch)
        HD._release_hormones_from_audit(_audit(ratio))
        assert not [x for x in emis if x[0] == "ADRENALINE_HUB_PRESSURE"], ratio
