# -*- coding: utf-8 -*-
"""NR : Délégations parallèles bornées dans TaskExecutor (owner 30/10).

Vérifie que :
1. Deux délégations tournent en même temps dans le ThreadPoolExecutor.
2. Une troisième délégation n'est pas réclamée tant que la limite LAFORGE_TASK_PARALLEL est atteinte.
3. Une exception dans un thread de délégation est journalisée et ne tue pas la boucle principale.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "forge_task_executor.py"


def _charger_executor():
    spec = importlib.util.spec_from_file_location("forge_task_executor_nr", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # run_loop tourne ici dans un THREAD : signal.signal y leve ValueError (thread principal seulement)
    import types as _types
    mod.signal = _types.SimpleNamespace(signal=lambda *a, **k: None, SIGINT=None, SIGTERM=None)
    # run_loop passe le garde-orphelins au demarrage (30/10) : un test ne touche JAMAIS le vrai
    # nokido_worktrees/taches (mesure : ce NR a tente d'effacer les reliquats reels).
    mod._wt_orphelins = lambda *a, **k: []
    return mod


# schema REEL de sandbox/tasks.db (lu le 30/10), pas un schema suppose
SCHEMA_TASKS = (
    "CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT DEFAULT 'pending', "
    "result TEXT, created_at TEXT, updated_at TEXT, job_id TEXT, from_agent TEXT, scorecard_json TEXT, "
    "lease_until TEXT, attempt INTEGER DEFAULT 0, checkpoint TEXT DEFAULT '{}', progress_at TEXT, from_ring INTEGER, "
    "reaffectations TEXT, reports INTEGER DEFAULT 0, taille TEXT, modele TEXT, effort TEXT, cout_usd REAL, "
    "cout_etat TEXT, verdict_effet TEXT, exec_pid INTEGER, exec_cree REAL)")


@pytest.fixture(autouse=True)
def _pouls_factice(monkeypatch):
    """Le pouls de run_loop ne doit pas ecrire dans le vrai sandbox."""
    import types as _types
    faux = _types.ModuleType("nokido_agent.app.forge_heartbeat")
    faux.beat_daemon = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_heartbeat", faux)


def _isoler_pouls(monkeypatch, tmp_path):
    """`beat_daemon` ecrit sous `_ROOT/sandbox` : sans ceci le test deposait `hb.heartbeat` (agent « * »)
    dans le VRAI sandbox (07/11, orphelin mesure)."""
    from nokido_agent.app import forge_heartbeat as _FH
    monkeypatch.setattr(_FH, "beat_daemon", lambda nom, **extra: True)


def test_delegations_paralleles_et_limite(tmp_path, monkeypatch):
    """2 délégations tournent en même temps, la 3e n'est pas réclamée tant que la limite est atteinte."""
    TE = _charger_executor()

    db_path = tmp_path / "tasks.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA_TASKS)
    # 3 tâches assignées à ANTIGRAVITY
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO tasks (id, agent, description, status) VALUES (?, 'ANTIGRAVITY', ?, 'pending')",
            (f"task_{i}", f"Description {i}"),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(TE, "TASKS_DB", db_path)  # le vrai _db (row_factory=Row) lit ce chemin
    monkeypatch.setattr(TE, "LAFORGE_TASK_PARALLEL", 2)
    monkeypatch.setattr(TE, "_load_token", lambda: "fake_token")
    monkeypatch.setattr(TE, "_hb_file", lambda ag: tmp_path / "hb")
    _isoler_pouls(monkeypatch, tmp_path)
    monkeypatch.setattr(TE, "reclaim_expired", lambda: {"reprises": 0, "abandonnees": 0})
    monkeypatch.setattr(TE, "requalifier_orphelines", lambda ag: {"requalifiees": [], "abstenues": []})
    monkeypatch.setattr(TE, "_palier_pression", lambda: "CALME")
    monkeypatch.setattr(TE, "_reclamation_permise", lambda palier: True)
    monkeypatch.setattr(TE, "_peut_lancer_agy", lambda: (True, "disponible"))
    monkeypatch.setattr(TE, "_executeur_suspendu", lambda ag: None)

    # Events de synchronisation
    event_start_1 = threading.Event()
    event_start_2 = threading.Event()
    event_release = threading.Event()

    en_cours = []
    lock_test = threading.Lock()

    def faux_preparer_worktree(agent, task_id):
        pass

    def faux_avec_worktree_tache(agent, task, token, action):
        action()

    def faux_delegate_to_agy(task, token):
        tid = task["id"]
        with lock_test:
            en_cours.append(tid)
            if tid == "task_1":
                event_start_1.set()
            elif tid == "task_2":
                event_start_2.set()
        # Attend que le test autorise la fin de la délégation
        event_release.wait(timeout=10)

    monkeypatch.setattr(TE, "_preparer_worktree", faux_preparer_worktree)
    monkeypatch.setattr(TE, "_avec_worktree_tache", faux_avec_worktree_tache)
    monkeypatch.setattr(TE, "_delegate_to_agy", faux_delegate_to_agy)

    # Lance un tick avec once=True
    # Le batch retourne les 3 tâches.
    # task_1 et task_2 doivent être soumises et en vol (limite = 2).
    # task_3 ne doit PAS être réclamée tant que la limite est atteinte.
    # instance DEDIEE : l'executeur generique (sans --agent) ne prend pas les taches ANTIGRAVITY
    t_loop = threading.Thread(target=lambda: TE.run_loop(agent_filter="ANTIGRAVITY", once=True))
    t_loop.start()

    assert event_start_1.wait(timeout=5), "task_1 n'a pas démarré"
    assert event_start_2.wait(timeout=5), "task_2 n'a pas démarré"

    # Vérifie que les 2 délégations tournent bien en même temps
    with lock_test:
        assert set(en_cours) == {"task_1", "task_2"}

    # Vérifie dans tasks.db que task_3 est restée 'pending' (non réclamée)
    conn_verif = sqlite3.connect(str(db_path))
    row_t3 = conn_verif.execute("SELECT status FROM tasks WHERE id='task_3'").fetchone()
    conn_verif.close()
    assert row_t3[0] == "pending", f"task_3 aurait dû rester pending mais a le statut: {row_t3[0]}"

    # Libère les 2 délégations
    event_release.set()
    t_loop.join(timeout=10)
    assert not t_loop.is_alive(), "run_loop ne s'est pas terminée proprement"


def test_exception_delegation_ne_tue_pas_la_boucle(tmp_path, monkeypatch):
    """Une exception dans un thread de délégation ne tue pas la boucle principale."""
    TE = _charger_executor()

    db_path = tmp_path / "tasks_exc.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA_TASKS)
    conn.execute("INSERT INTO tasks (id, agent, description, status) VALUES ('task_err', 'ANTIGRAVITY', 'test', 'pending')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(TE, "TASKS_DB", db_path)  # le vrai _db (row_factory=Row) lit ce chemin
    monkeypatch.setattr(TE, "LAFORGE_TASK_PARALLEL", 2)
    monkeypatch.setattr(TE, "_load_token", lambda: "fake_token")
    monkeypatch.setattr(TE, "_hb_file", lambda ag: tmp_path / "hb")
    _isoler_pouls(monkeypatch, tmp_path)
    monkeypatch.setattr(TE, "reclaim_expired", lambda: {"reprises": 0, "abandonnees": 0})
    monkeypatch.setattr(TE, "requalifier_orphelines", lambda ag: {"requalifiees": [], "abstenues": []})
    monkeypatch.setattr(TE, "_palier_pression", lambda: "CALME")
    monkeypatch.setattr(TE, "_reclamation_permise", lambda palier: True)
    monkeypatch.setattr(TE, "_peut_lancer_agy", lambda: (True, "disponible"))
    monkeypatch.setattr(TE, "_executeur_suspendu", lambda ag: None)

    event_done = threading.Event()

    appels_preparer = []

    def faux_preparer_worktree(agent, task_id):
        appels_preparer.append(task_id)
        raise RuntimeError("Erreur simulatee dans preparer_worktree")

    monkeypatch.setattr(TE, "_preparer_worktree", faux_preparer_worktree)

    # run_loop ne doit pas lever et doit terminer normalement après le batch (once=True)
    TE.run_loop(agent_filter="ANTIGRAVITY", once=True)
    TE._pool_delegations.shutdown(wait=True)  # la delegation tourne dans le pool : attendre sa fin

    assert appels_preparer, "la delegation n'a jamais ete lancee : le test passerait a vide"
    # Le compteur de délégations en vol doit être retombé à 0
    with TE._lock_delegations:
        assert TE._delegations_en_vol == 0
