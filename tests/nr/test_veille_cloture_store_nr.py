"""NR -- un job de veille se CLOT a la fin de son etape store (P2 du 14/10).

MESURE QUI L'A DECLENCHE. 7 jobs `en_cours` dans watch_jobs, dont 3 depuis le 07/09 et 594, 351, 89 fragments
ingeres le 13/10 : TOUTES leurs etapes etaient terminees. Cause : `_step_store` ecrivait le verdict pendant que
son propre noeud `store` etait encore `running` (run_node ne le marque termine qu'apres) -> `verdict_chaine`
rendait `en_cours`, et plus rien ne le recalculait. Le widget de veille du portail lisait donc « aucune donnee ».

Chemin REEL : `_step_store` du module, sur une base SQLite en memoire portant son propre schema.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_watch_agent as W  # noqa: E402


def _base(etats: dict) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(W.DDL_WATCH)
    c.execute("CREATE TABLE IF NOT EXISTS agent_chain_nodes (chain_id TEXT, step_name TEXT, status TEXT)")
    c.execute("INSERT INTO watch_jobs (id, theme, status, step, n_ingested, created_at, updated_at) "
              "VALUES ('wj_t', 'theme', 'en_cours', 'store', 594, '2026-10-13T10:59', '2026-10-13T11:10')")
    c.executemany("INSERT INTO agent_chain_nodes VALUES ('wj_t', ?, ?)", list(etats.items()))
    c.commit()
    return c


def test_le_job_se_clot_quand_store_est_sa_derniere_etape(monkeypatch):
    monkeypatch.setattr(W, "_broadcast", lambda evt: None)
    c = _base({"search": "completed", "ingest": "completed", "store": "running"})
    W._step_store(c, "wj_t", "theme", [], "v")
    statut, erreur = c.execute("SELECT status, error FROM watch_jobs WHERE id='wj_t'").fetchone()
    assert statut == "completed_empty", statut          # rien retenu, aucune etape cassee : un vide ASSUME
    assert erreur and erreur.startswith("RETENTION_ZERO") and "594 chunks ingeres" in erreur


def test_une_autre_etape_encore_vivante_garde_le_job_en_cours(monkeypatch):
    """On ne force QUE l'etape store qui s'execute : une chaine qui a encore du travail reste `en_cours`."""
    monkeypatch.setattr(W, "_broadcast", lambda evt: None)
    c = _base({"search": "completed", "ingest": "pending", "store": "running"})
    W._step_store(c, "wj_t", "theme", [], "v")
    assert c.execute("SELECT status FROM watch_jobs WHERE id='wj_t'").fetchone()[0] == "en_cours"
