# -*- coding: utf-8 -*-
"""NR 2026-11-04 (owner : « 16 % de contexte au demarrage ») -- l'inbox du SessionStart injectait les faits
`presence_arrival_*` du tableau noir (8 sur 12 le 4/11) : un pouls d'arrivee n'est pas un message, il prend
la place des vrais (soins, debats). Contrat : fetch_blackboard_inbox les ecarte, garde les autres."""
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
import claude_session_start as S  # noqa: E402


def test_presence_ecartee_soin_garde(tmp_path, monkeypatch):
    (tmp_path / "RAG").mkdir()
    db = tmp_path / "RAG" / "swarm.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE swarm_blackboard (zone TEXT, key TEXT, value TEXT, worker_id TEXT, updated_at REAL)")
    t = time.time()
    c.executemany("INSERT INTO swarm_blackboard VALUES (?,?,?,?,?)", [
        ("discovered_facts", "presence_arrival_ORGAN_PULSE", "ORGAN_PULSE present (arrived)", "forge_presence", t),
        ("discovered_facts", "self_care_91e887bbc099", "SOIN requis [medium]", "epistemic_daemon", t - 1),
    ])
    c.commit()
    c.close()
    monkeypatch.setattr(S, "ROOT", tmp_path)
    cles = [m["preview"].split(" -- ")[0] for m in S.fetch_blackboard_inbox()]
    assert "self_care_91e887bbc099" in cles, cles
    assert not any(k.startswith("presence_") for k in cles), cles
