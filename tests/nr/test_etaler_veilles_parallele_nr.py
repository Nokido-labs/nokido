"""NR du 27/10 : l'etalement des veilles laisse passer N chaines simultanees et DIT pourquoi les autres attendent.

Mesure : 8 veilles lancees, aucune executee -- RAM en satiete (81 %), motif journalise en INFO, invisible dans le
journal du worker (il paraissait mort). Et une seule veille a la fois : l'ingestion d'une chaine retardait toutes les
autres (owner : « la suite du workflow d'ingestion ne doit pas empecher le restant d'avancer »).
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import forge_chain_executor as CE  # noqa: E402


def _executeur(en_cours=()):
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("create table agent_chain_nodes (chain_id text, status text)")
    for c in en_cours:
        db.execute("insert into agent_chain_nodes values (?, 'running')", (c,))
    ex = object.__new__(CE.ChainExecutor)

    class _Conn:  # close() ne doit pas fermer la base memoire partagee
        def execute(self, *a):
            return db.execute(*a)

        def close(self):
            pass

    ex._get_conn = lambda: _Conn()
    return ex


def _attente(*ids):
    return {c: [{"chain_id": c}] for c in ids}


def test_deux_veilles_partent_ensemble_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_VEILLES_MAX", raising=False)
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: False)
    sortie = _executeur()._etaler_veilles(_attente("wj_a", "wj_b", "wj_c", "autre_x"))
    assert set(sortie) == {"wj_a", "wj_b", "autre_x"}


def test_une_veille_en_cours_laisse_une_place(monkeypatch):
    monkeypatch.setenv("LAFORGE_VEILLES_MAX", "2")
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: False)
    sortie = _executeur(en_cours=["wj_z"])._etaler_veilles(_attente("wj_a", "wj_b"))
    assert set(sortie) == {"wj_a"}


def _base_departs(lignes):
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("create table agent_chain_nodes (chain_id text, status text, started_at text)")
    db.executemany("insert into agent_chain_nodes values (?,?,?)", lignes)
    ex = object.__new__(CE.ChainExecutor)

    class _Conn:
        def execute(self, *a):
            return db.execute(*a)

        def close(self):
            pass

    ex._get_conn = lambda: _Conn()
    return ex


def test_veille_retenue_en_attente_n_a_pas_de_budget_qui_court():
    # 27/10 : 4 veilles retenues 30 min par la satiete ont ete soldees `stalled` a leur sortie d'attente.
    ex = _base_departs([("wj_a", "pending", None)] * 7)
    vieux = "2020-01-01T00:00:00+00:00"
    assert ex._age_chaine([{"chain_id": "wj_a", "created_at": vieux}]) is None


def test_budget_compte_depuis_le_premier_depart():
    from datetime import datetime, timedelta, timezone
    depart = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    ex = _base_departs([("wj_a", "completed", depart), ("wj_a", "pending", None)])
    age = ex._age_chaine([{"chain_id": "wj_a", "created_at": "2020-01-01T00:00:00+00:00"}])
    assert age is not None and 100 < age < 600


def test_satiete_ram_bloque_et_le_dit_en_warning(monkeypatch, caplog):
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: True)
    monkeypatch.setattr(CE, "_DERNIER_MOTIF_VEILLES", {}, raising=False)
    with caplog.at_level(logging.WARNING):
        sortie = _executeur()._etaler_veilles(_attente("wj_a", "autre_x"))
    assert set(sortie) == {"autre_x"}
    assert any("satiete" in r.getMessage().lower() and r.levelno >= logging.WARNING for r in caplog.records)
