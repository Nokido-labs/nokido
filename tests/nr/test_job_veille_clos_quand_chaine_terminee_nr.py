# -*- coding: utf-8 -*-
"""NR -- le verdict d'un job de veille se recalcule quand sa chaine termine (mesure du 15/10).

Lecture de %NOKIDO_DATA%\\embeddings.db le 15/10 : la veille `wj_fc7e31285b` a ses 7 etapes `completed`, mais son job reste
`running` depuis le 07/09 -- la ligne a ete ecrite deux secondes AVANT la fin de l'ingest. `run_node` ne touchait
jamais `watch_jobs` : une etape qui finit apres `store` ou apres le solde du budget laissait le job fige.

Contrat, sur le CHEMIN REEL (`run_node`, base temporaire, agent factice) :
  1. la derniere etape qui termine fait passer le job a son verdict (`verdict_chaine`), et efface la trace
     d'echec perimee quand le verdict est un succes ;
  2. tant qu'une etape attend ou tourne, le job n'est pas touche ;
  3. un `completed_dedup` deja ecrit n'est pas degrade en `completed_empty` ;
  4. une chaine sans job de veille n'ecrit rien et ne leve rien.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app.forge_chain_executor import ChainExecutor  # noqa: E402


def _banc(tmp_path, statuts, job=None):
    db = tmp_path / "veille.db"
    ex = ChainExecutor(db_path=db)
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE IF NOT EXISTS watch_jobs (id TEXT PRIMARY KEY, step TEXT, status TEXT, error TEXT, "
              "n_stored INTEGER, updated_at TEXT)")
    for i, (nom, st) in enumerate(statuts):
        c.execute("INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, agent_role, status) "
                  "VALUES (?, 'wj_t', ?, ?, 'IngestAgent', ?)", ("n%d" % i, i, nom, st))
    if job is not None:
        c.execute("INSERT INTO watch_jobs VALUES ('wj_t', ?, ?, ?, ?, '')", job)
    c.commit()
    c.close()

    async def _agent(node, context):
        return [1, 2, 3, 4, 5]

    ex.dispatch_agent = _agent
    return ex, db


def _job(db):
    c = sqlite3.connect(str(db))
    try:
        return c.execute("SELECT step, status, error FROM watch_jobs WHERE id='wj_t'").fetchone()
    finally:
        c.close()


def _noeud(nom, i):
    return {"id": "n%d" % i, "chain_id": "wj_t", "agent_role": "IngestAgent", "output_key": None,
            "step_name": nom, "step_index": i}


def test_la_derniere_etape_clot_le_job_et_efface_la_trace_perimee(tmp_path):
    ex, db = _banc(tmp_path, [("search", "completed"), ("store", "completed"), ("ingest", "pending")],
                   job=("store", "running", "budget de chaine epuise -- etapes non jouees", 5))
    asyncio.run(ex.run_node(_noeud("ingest", 2)))
    assert _job(db) == ("done", "completed", None)


def test_une_etape_en_attente_laisse_le_job_intact(tmp_path):
    ex, db = _banc(tmp_path, [("search", "pending"), ("store", "completed"), ("ingest", "pending")],
                   job=("search", "running", None, 0))
    asyncio.run(ex.run_node(_noeud("ingest", 2)))
    assert _job(db) == ("search", "running", None)


def test_un_dedup_deja_ecrit_n_est_pas_degrade(tmp_path):
    ex, db = _banc(tmp_path, [("search", "completed"), ("ingest", "pending")],
                   job=("store", "completed_dedup", None, 0))
    asyncio.run(ex.run_node(_noeud("ingest", 1)))
    assert _job(db)[1] == "completed_dedup"


def test_une_chaine_sans_job_n_ecrit_rien(tmp_path):
    ex, db = _banc(tmp_path, [("search", "completed"), ("ingest", "pending")])
    asyncio.run(ex.run_node(_noeud("ingest", 1)))
    assert _job(db) is None and ex._clore_job_si_chaine_terminee("wj_t") is None
