"""NR -- une suspension DECIDEE est une suspension CABLEE : le repli ne choisit jamais un executeur suspendu.

Mesure 2026-10-17 16:28-16:35 : MISTRAL (Vibe) suspendu au SSoT (bb:mistral_suspendu_0_livraison_20261017, 0 livraison
sur 3) mais son executeur bat ; la reaffectation (« le corps debloque les surfaces », enfin effective depuis b202705bd)
lui a passe les 2 taches CODEX en quota (R3 et SearXNG) -> 2 echecs, 0 commit, 5/5 pour Vibe. Une decision ecrite au
tableau noir et lue par personne n'est pas une decision : elle se DECLARE au registre (config/agent_identities.json,
`suspendu: {depuis, motif}`) et le repli la lit.
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
REGISTRE = {"agents": {"MISTRAL": {"suspendu": {"depuis": "2026-10-17", "motif": "0 livraison sur 5 (Vibe)"}},
                       "WORKER_CODE": {"mode": "autonomous"}}}


def _une_tache(tmp_path, monkeypatch, agent):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (%s)" % COLONNES)
    c.execute("INSERT INTO tasks (id, description, agent, status, created_at) VALUES (?,?,?,?,?)",
              ("t_quota", "consigne de test assez longue pour etre extraite", agent, "pending", "2026-10-17T16:00:00"))
    c.commit()
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", db)
    conn = T._db()
    row = T._fetch_batch(conn, agent)[0]
    conn.close()
    return row


def test_la_suspension_se_lit_au_registre_et_se_dit(monkeypatch):
    monkeypatch.setattr(T, "_lire_registre", lambda: REGISTRE)
    assert "0 livraison" in (T._executeur_suspendu("MISTRAL") or "")
    assert T._executeur_suspendu("WORKER_CODE") is None
    assert T._executeur_suspendu("INCONNU") is None


def test_le_repli_saute_un_executeur_suspendu_meme_s_il_bat(tmp_path, monkeypatch):
    row = _une_tache(tmp_path, monkeypatch, "CODEX")
    monkeypatch.setattr(T, "_lire_registre", lambda: REGISTRE)
    monkeypatch.setattr(T, "_ORDRE_REPLI", ("MISTRAL", "WORKER_CODE"))
    monkeypatch.setattr(T, "_executeur_bat", lambda a, *k: True)
    assert T._reaffecter(row, "quota Codex du jour atteint (test)") == "WORKER_CODE"


def test_le_registre_reel_garde_l_historique_de_la_suspension_de_vibe():
    # 17/10 : MISTRAL suspendu (0 livraison sur 5). 20/10, decision owner : reactive pour un essai mesurable. La
    # suspension n'agit plus, mais son historique reste au registre (geler, jamais effacer) -- s'il ne livre pas, elle
    # se re-pose sur la meme entree.
    assert T._executeur_suspendu("MISTRAL") is None, "MISTRAL reactive par l'owner le 20/10"
    spec = (T._lire_registre().get("agents") or {}).get("MISTRAL") or {}
    hist = spec.get("suspension_levee") or {}
    assert "mistral_suspendu_0_livraison_20261017" in hist.get("motif", "") and hist.get("levee_le") == "2026-10-20"
