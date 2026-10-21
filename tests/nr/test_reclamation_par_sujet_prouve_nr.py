"""NR -- une tache se RECLAME par le sujet prouve de l'executeur, jamais par qui la voit le premier.

Mesures 2026-10-17 ~16:16 (logs/task_executor.log) :
1. L'executeur GENERIQUE (sans --agent) a rafle job_479c8ebe (agent OPENCODE_GPTOSS) et l'a servi par groq : un texte
   inventant un commit (9f2c1e7b4a6d3e8f9b0c1d2e3f4a5b6c7d8e9f0a, absent de la branche) clos OK_DONE SUCCESS, sans juge.
   Cause : _fetch_batch(None) filtre par liste NOIRE (NOT IN les CLI interactifs) -- toute cible nouvelle tombe chez lui.
2. Le meme generique et l'instance dediee OPENCODE_NEMOTRON ont pris job_dcaa1a81 ensemble : _mark_running fait un
   UPDATE sans `status='pending'`, deux executeurs « reclament » la meme tache.
3. `Boucle erreur: 'sqlite3.Row' object has no attribute 'get'` chaque minute : _reaffecter fait task.get(...) sur la
   Row que rend _fetch_batch -- la reaffectation (« le corps debloque les surfaces », owner 17/10) ne marche jamais.

Owner 17/10 : « les jetons devraient identifier convenablement les cibles des CLI si tu appliques les RFC ». Contrat :
- liste BLANCHE : le generique ne sert que les agents qu'il sait servir (PROVIDER_CHAIN, hors agents delegues) ;
- RFC 7519 `sub` : un claim n'est autorise que si le sujet PROUVE de l'executeur est l'agent cible ; non prouve = refus
  (UNKNOWN n'est pas OUI) ;
- RFC 8693 `act` : l'acteur (le process executeur) est trace a cote du sujet, jamais substitue a lui ;
- le claim est ATOMIQUE : `pending` -> `running` une seule fois.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402

COLONNES = ("id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT, created_at TEXT, "
            "updated_at TEXT, job_id TEXT, from_agent TEXT, scorecard_json TEXT, lease_until TEXT, attempt INTEGER, "
            "checkpoint TEXT, progress_at TEXT, from_ring INTEGER")


def _bus(tmp_path, monkeypatch, taches):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (%s)" % COLONNES)
    for i, agent in enumerate(taches):
        c.execute("INSERT INTO tasks (id, description, agent, status, created_at) VALUES (?,?,?,?,?)",
                  ("t%d_%s" % (i, agent.lower()), "consigne de test assez longue pour etre extraite", agent, "pending",
                   "2026-10-17T16:%02d:00" % i))
    c.commit()
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", db)
    return db


def test_la_reaffectation_accepte_la_vraie_row_du_bus(tmp_path, monkeypatch):
    """_reaffecter recoit la Row que rend _fetch_batch (pas un dict de test) : elle doit la lire, pas planter."""
    _bus(tmp_path, monkeypatch, ["CODEX"])
    monkeypatch.setattr(T, "_executeur_bat", lambda a: a == T._ORDRE_REPLI[0])
    conn = T._db()
    row = T._fetch_batch(conn, "CODEX")[0]
    conn.close()
    assert isinstance(row, sqlite3.Row)
    vers = T._reaffecter(row, "quota Codex du jour atteint (test)")
    assert vers == T._ORDRE_REPLI[0] or (T._ORDRE_REPLI[0] == "CODEX" and vers is None)


def test_le_generique_ne_sert_que_sa_liste_blanche(tmp_path, monkeypatch):
    """Sans --agent, l'executeur ne prend QUE les agents qu'il sait servir par fournisseur texte. Une instance dediee
    (OPENCODE_*), un agent delegue (CODEX, MISTRAL -> Vibe, AGY) ou un agent INCONNU reste pending pour son executeur."""
    _bus(tmp_path, monkeypatch, ["GROQ", "OPENCODE_GPTOSS", "CODEX", "MISTRAL", "ANTIGRAVITY", "INCONNU_X"])
    conn = T._db()
    pris = sorted((r["agent"] or "").upper() for r in T._fetch_batch(conn, None))
    conn.close()
    assert pris == ["GROQ"], pris
    assert "OPENCODE_GPTOSS" not in T._servables_par_le_generique()
    assert "MISTRAL" not in T._servables_par_le_generique()


def test_le_claim_exige_le_sujet_prouve_de_l_agent_cible():
    """RFC 7519 `sub` : seul l'executeur dont le sujet PROUVE est l'agent cible peut reclamer ; RFC 8693 `act` trace
    l'acteur sans le substituer au sujet."""
    ok, pourquoi = T._autoriser_reclamation("OPENCODE_GPTOSS", {"sub": "OPENCODE_GPTOSS", "prouve": True,
                                                                 "act": "TASK_EXECUTOR"})
    assert ok is True, pourquoi
    ok, pourquoi = T._autoriser_reclamation("OPENCODE_GPTOSS", {"sub": "TASK_EXECUTOR", "prouve": True})
    assert ok is False and "OPENCODE_GPTOSS" in pourquoi
    ok, pourquoi = T._autoriser_reclamation("OPENCODE_GPTOSS", {"sub": "OPENCODE_GPTOSS", "prouve": False})
    assert ok is False and "prouv" in pourquoi.lower()
    ok, pourquoi = T._autoriser_reclamation("OPENCODE_GPTOSS", {})
    assert ok is False


def test_le_claim_est_atomique_un_seul_executeur_gagne(tmp_path, monkeypatch):
    """pending -> running une seule fois : le second executeur qui voit la meme tache perd, et le sait."""
    _bus(tmp_path, monkeypatch, ["OPENCODE_NEMOTRON"])
    ident = {"sub": "OPENCODE_NEMOTRON", "prouve": True, "act": "TASK_EXECUTOR"}
    c1, c2 = T._db(), T._db()
    try:
        assert T._reclamer(c1, "t0_opencode_nemotron", "OPENCODE_NEMOTRON", ident) is True
        assert T._reclamer(c2, "t0_opencode_nemotron", "OPENCODE_NEMOTRON", ident) is False
        assert c1.execute("SELECT status FROM tasks WHERE id='t0_opencode_nemotron'").fetchone()[0] == "running"
    finally:
        c1.close()
        c2.close()


def test_un_sujet_etranger_ne_reclame_pas_meme_s_il_voit_la_tache(tmp_path, monkeypatch):
    """Le generique (sujet TASK_EXECUTOR) qui verrait une tache OPENCODE_GPTOSS ne peut pas la passer running."""
    _bus(tmp_path, monkeypatch, ["OPENCODE_GPTOSS"])
    c = T._db()
    try:
        assert T._reclamer(c, "t0_opencode_gptoss", "OPENCODE_GPTOSS",
                           {"sub": "TASK_EXECUTOR", "prouve": True}) is False
        assert c.execute("SELECT status FROM tasks WHERE id='t0_opencode_gptoss'").fetchone()[0] == "pending"
    finally:
        c.close()
