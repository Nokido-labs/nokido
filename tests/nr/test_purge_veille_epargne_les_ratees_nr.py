# -*- coding: utf-8 -*-
"""NR — la retention ne purge QUE les veilles PROUVEES reussies ; une veille ratee survit.

Mesure du 2026-09-23 : `watch_jobs` 24 lignes pour MAX(rowid)=281, `agent_chain_nodes`
168 pour 1 967 ; des veilles du 23/08 vues a 00h20 avaient disparu a 01h15, dont une
`completed_partial` dont le budget avait ete epuise -- jamais rattrapee. La purge
supprimait tout ce qui n'etait ni `pending` ni `running` : une LISTE NOIRE, qui range
`failed`, `stalled`, `degraded`, `completed_partial` et `completed_empty` du cote
« termine, jetable ».

Decision owner : « la purge ne doit pas tuer les veilles ratees ». Liste BLANCHE : n'est
purgeable qu'une veille `completed`/`completed_dedup` dont TOUS les nodes sont
`completed`. Tout le reste attend son rattrapage.
"""
import importlib
import sqlite3
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.61)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
R = importlib.import_module("forge_log_retention")

VIEUX = "2026-01-01T00:00:00+00:00"


def _base(tmp_path):
    (tmp_path / "RAG").mkdir()
    c = sqlite3.connect(str(tmp_path / "RAG" / "embeddings.db"))
    c.execute("CREATE TABLE watch_jobs (id TEXT PRIMARY KEY, theme TEXT, status TEXT, created_at TEXT)")
    c.execute("CREATE TABLE agent_chain_nodes (id TEXT PRIMARY KEY, chain_id TEXT, status TEXT, created_at TEXT)")
    c.execute("CREATE TABLE agent_chain_context (chain_id TEXT PRIMARY KEY, updated_at TEXT)")
    return c


def _veille(c, cid, job_status, nodes):
    c.execute("INSERT INTO watch_jobs VALUES (?,?,?,?)", (cid, "t", job_status, VIEUX))
    c.execute("INSERT INTO agent_chain_context VALUES (?,?)", (cid, VIEUX))
    for i, s in enumerate(nodes):
        c.execute("INSERT INTO agent_chain_nodes VALUES (?,?,?,?)", ("%s_%d" % (cid, i), cid, s, VIEUX))


def _restants(c, table, col="id"):
    return {r[0] for r in c.execute("SELECT %s FROM %s" % (col, table))}


def test_seule_la_veille_reussie_est_purgee(tmp_path, monkeypatch):
    c = _base(tmp_path)
    _veille(c, "ok", "completed", ["completed"] * 3)
    _veille(c, "dedup", "completed_dedup", ["completed"] * 3)
    _veille(c, "partiel", "completed_partial", ["completed", "completed", "failed"])
    _veille(c, "echec", "failed", ["completed", "failed"])
    _veille(c, "vide", "completed_empty", ["completed"] * 3)
    _veille(c, "cale", "en_cours", ["completed", "stalled"])
    _veille(c, "degrade", "completed", ["completed", "degraded"])
    c.commit()
    c.close()
    monkeypatch.setattr(R, "ROOT", tmp_path)
    R._purge_watch_chains(dry=False)
    c = sqlite3.connect(str(tmp_path / "RAG" / "embeddings.db"))
    jobs = _restants(c, "watch_jobs")
    chaines = _restants(c, "agent_chain_nodes", "chain_id")
    assert jobs == {"partiel", "echec", "vide", "cale", "degrade"}, jobs
    assert chaines == {"partiel", "echec", "vide", "cale", "degrade"}, chaines
    assert _restants(c, "agent_chain_context", "chain_id") == chaines


def test_le_dry_run_compte_sans_rien_toucher(tmp_path, monkeypatch):
    c = _base(tmp_path)
    _veille(c, "ok", "completed", ["completed"] * 2)
    _veille(c, "echec", "failed", ["failed"])
    c.commit()
    c.close()
    monkeypatch.setattr(R, "ROOT", tmp_path)
    r = R._purge_watch_chains(dry=True)
    assert r["watch_jobs_purged"] == 1 and r["chains_purged"] == 1, r
    c = sqlite3.connect(str(tmp_path / "RAG" / "embeddings.db"))
    assert _restants(c, "watch_jobs") == {"ok", "echec"}
