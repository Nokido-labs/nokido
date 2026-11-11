"""NR : une alerte dit sa cause, et une session ouverte peut la lire sans rien marquer.

Mesure 6/11 : `[COAGULATION][ESCALADE] algedonic:delivery_integrity sev=high — haute sévérité non classée — prudence`
ne nommait aucune cause, et `alertes_en_attente` ne sert que le demarrage et le tray.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "tools"))

import forge_coagulation as FC  # noqa: E402
from nokido_agent.app import forge_critical_events as CE  # noqa: E402

# Forme ecrite par forge_homeostasis_orchestrator.py:816
_PAYLOAD_REEL = {"detail": "ci_en_echec : 7 consecutifs", "tick": 12, "vsm_action": "escalate"}


def test_cause_lue_dans_le_payload_reel_dict_ou_json():
    for p in (_PAYLOAD_REEL, json.dumps(_PAYLOAD_REEL)):
        assert FC._cause_escalade({"kind": "algedonic:delivery_integrity", "payload": p}) == "ci_en_echec : 7 consecutifs"


def test_cause_absente_se_dit_illisible_sans_deviner():
    assert FC._cause_escalade({"kind": "x"}) == "cause: ILLISIBLE"
    assert FC._cause_escalade({"kind": "x", "payload": "pas du json"}) == "cause: ILLISIBLE"
    assert FC._cause_escalade({"kind": "x", "payload": {"tick": 1}}) == "cause: ILLISIBLE"


def test_cause_longue_bornee_et_le_depassement_se_dit():
    c = FC._cause_escalade({"kind": "x", "payload": {"detail": "a" * 500}})
    assert len(c) < 200
    assert "340" in c  # ce qui est coupe se compte


def _base(tmp_path, monkeypatch):
    monkeypatch.setattr(CE, "DB_PATH", tmp_path / "critical.db")
    # 7/11 (CI job_11992f495544, `no such table: alertes_owner`) : `_init_db` ne s'execute qu'une fois par PROCESSUS
    # (`_INITIALIZED`) ; un test anterieur du meme worker l'avait pose sur SA base, celle-ci restait vide. Rejoue
    # deterministe (sonde qui initialise une autre base, puis ce fichier) ; meme remise a zero que les voisins
    # (test_alertes_owner_nr, test_sense_info_pas_une_alerte_nr, test_forge_critical_events).
    monkeypatch.setattr(CE, "_INITIALIZED", False)
    CE._init_db()
    c = CE._conn()
    with c:
        for i in range(3):
            c.execute("INSERT INTO alertes_owner(ts, sujet, gravite, detail, emetteur) VALUES (?,?,?,?,?)",
                      (1000.0 + i, f"sujet{i}", "high", "d" * 30, "TEST"))
    c.close()


def _contenu(tmp_path):
    c = sqlite3.connect(tmp_path / "critical.db")
    try:
        return c.execute("SELECT * FROM alertes_owner ORDER BY id").fetchall()
    finally:
        c.close()


def test_lecture_nécrit_rien_et_borne_en_comptant(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    avant = _contenu(tmp_path)
    monkeypatch.setattr(CE, "DB_PATH", tmp_path / "critical.db")
    r = CE.alertes_recentes(limit=2)
    assert _contenu(tmp_path) == avant
    assert r["etat"] == "OK" and r["total"] == 3 and r["coupees"] == 1
    assert [a["sujet"] for a in r["alertes"]] == ["sujet2", "sujet1"]


def test_hub_action_alertes_par_le_handler_et_dans_le_schema():
    import asyncio
    from unittest.mock import MagicMock

    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    reg = ToolRegistry(root_dir=RACINE)
    reg._event_bus = MagicMock()
    hub = next(t for t in reg._all_tools() if t["name"] == "hub")
    assert "alertes" in hub["inputSchema"]["properties"]["action"]["enum"]
    d = json.loads(asyncio.run(reg.handle_hub({"action": "alertes", "limit": 1}, agent="agt_test", ring=1)))
    assert d["etat"] in ("OK", "ILLISIBLE")
    d2 = json.loads(asyncio.run(reg.handle_hub({"action": "alertes", "limit": "x"}, agent="agt_test", ring=1)))
    assert d2["etat"] == "ILLISIBLE"


def test_source_injoignable_est_illisible_jamais_vide(tmp_path, monkeypatch):
    monkeypatch.setattr(CE, "_conn", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("verrou")))
    r = CE.alertes_recentes()
    assert r["etat"] == "ILLISIBLE" and "alertes" not in r
