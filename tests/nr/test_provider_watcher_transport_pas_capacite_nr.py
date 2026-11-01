# -*- coding: utf-8 -*-
"""NR — un ping de CATALOGUE prouve le TRANSPORT, jamais la CAPACITÉ : le veilleur n'écrit plus `status='ok'`.

__FORGE_COLOR__ = "immunitaire/guard : non-regression transport != capacite dans provider_scores"

CE QUI A ÉTÉ PAYÉ (21/10). Ollama refusait TOUTE génération depuis au moins 11 h 56 (« llama-server binary not
found », 1 235 échecs dans logs/supervisor/NokidoOllama.log) ; `whoami` le présentait pourtant « vivant prouvé »,
grade A, 32 ms. Source : app/forge_provider_watcher.py ping /api/tags et /v1/models (des catalogues) et écrivait
`status='ok'`, grade A. Or tous les lecteurs rangent `status='ok'` en ÉLIGIBLE : whoami (forge_mcp_registry
l. 5110), `memory context` (l. 6168), ROUTE:BEST (tools/forge_broker_base.py l. 389, qui pouvait même router vers
l'agent_id « watcher »), le débat (tools/forge_debate_job.py l. 356). Contrat : le veilleur écrit `status='transport'`
quand le catalogue répond, `down` sinon ; seule une génération réelle (forge_llm_router_dt.update_provider_health)
écrit `ok`. Constitution : TRANSPORT ≠ APPLICATIF ≠ CAPACITÉ.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _watcher(monkeypatch, db: Path):
    spec = importlib.util.spec_from_file_location("forge_provider_watcher_nr", ROOT / "app" / "forge_provider_watcher.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_provider_watcher_nr", mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DB", db)
    return mod


def _base(tmp_path) -> Path:
    db = tmp_path / "scores.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE provider_scores (provider TEXT PRIMARY KEY, agent_id TEXT, ttft_ms REAL, grade TEXT, "
              "status TEXT, measured_at TEXT, priority INTEGER)")
    c.commit()
    c.close()
    return db


def _lignes(db: Path) -> dict:
    c = sqlite3.connect(db)
    try:
        return {p: (s, g) for p, s, g in c.execute("SELECT provider, status, grade FROM provider_scores")}
    finally:
        c.close()


def test_catalogue_qui_repond_vaut_transport_pas_ok(monkeypatch, tmp_path):
    db = _base(tmp_path)
    w = _watcher(monkeypatch, db)
    w._write_scores({"ollama_local": {"ok": True, "ttft_ms": 32.7, "status": 200}})
    statut, grade = _lignes(db)["ollama_local"]
    assert statut == "transport", "un ping de catalogue a ete ecrit %r : il serait lu ELIGIBLE" % statut
    assert grade != "A", grade


def test_catalogue_muet_reste_down(monkeypatch, tmp_path):
    db = _base(tmp_path)
    w = _watcher(monkeypatch, db)
    w._write_scores({"groq_fast": {"ok": False, "ttft_ms": None, "error": "timeout"}})
    assert _lignes(db)["groq_fast"][0] == "down"


def test_aucun_lecteur_ne_voit_le_transport_comme_eligible(monkeypatch, tmp_path):
    db = _base(tmp_path)
    w = _watcher(monkeypatch, db)
    w._write_scores({"ollama_local": {"ok": True, "ttft_ms": 32.7, "status": 200}})
    c = sqlite3.connect(db)
    try:  # la requete exacte de whoami (forge_mcp_registry l. 5110) et de ROUTE:BEST (forge_broker_base l. 389)
        assert c.execute("SELECT provider FROM provider_scores WHERE status='ok'").fetchall() == []
    finally:
        c.close()
