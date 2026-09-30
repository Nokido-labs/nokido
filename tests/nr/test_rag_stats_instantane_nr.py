"""NR -- /api/rag/stats (page /rag du portail) sert l'instantane de la phase health, pas 17 s de comptages.

Mesure du 2026-09-25 : campagne ui-acceptance VIOLEE sur /rag (« chunks total », « vectoris »
absents) ; les 3 comptages de `_rag_db_stats` coutaient 0,09 + 6,72 + 10,67 s a CHAQUE chargement
(index partiel de 6,6 M lignes sans vecteur, GROUP BY domaine sur 8,25 M lignes). La phase health
ecrit deja ces valeurs dans sandbox/health_diagnostic.json.

Garde : le chemin lu EST celui du producteur ; avec un instantane, la route ne touche PAS la base
et rend source + age ; sans instantane, le repli se DECLARE « comptage direct ».
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app.web_hub import wired_routes as wr  # noqa: E402


def _appeler():
    return json.loads(asyncio.run(wr.rag_stats()).body)


def test_le_chemin_lu_est_celui_du_producteur():
    from nokido_agent.app import forge_health_diagnostic as hd
    assert Path(hd.OUT_JSON).resolve() == wr._INSTANTANE_HEALTH.resolve()


def test_avec_instantane_aucune_requete_sur_la_base(monkeypatch, tmp_path):
    snap = tmp_path / "health_diagnostic.json"
    ts = (datetime.now() - timedelta(minutes=3)).isoformat()
    snap.write_text(json.dumps({"ts": ts, "rag_chunks": {
        "total": 8251604, "non_vectorized": 6643103,
        "top_domains": [{"domain": "sdk_gitingest", "count": 6354665}]}}), encoding="utf-8")
    monkeypatch.setattr(wr, "_INSTANTANE_HEALTH", snap)

    def interdit(*a, **k):
        raise AssertionError("la route a ouvert la base alors que l'instantane existe")
    monkeypatch.setattr(sqlite3, "connect", interdit)
    d = _appeler()
    assert d["total"] == 8251604 and d["no_embedding"] == 6643103
    assert d["domains"] == [{"name": "sdk_gitingest", "chunks": 6354665}] and d["domaines_partiels"] is True
    assert d["source"] == "instantane phase health" and 150 <= d["age_s"] <= 400


def test_sans_instantane_le_repli_se_declare(monkeypatch, tmp_path):
    monkeypatch.setattr(wr, "_INSTANTANE_HEALTH", tmp_path / "absent.json")
    monkeypatch.setattr(wr, "_rag_db_stats", lambda: {"total": 3, "no_embedding": 1, "domains": [], "tiktoken_ok": False})
    d = _appeler()
    assert d["total"] == 3 and d["source"].startswith("comptage direct")
