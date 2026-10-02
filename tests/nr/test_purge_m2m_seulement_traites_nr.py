# -*- coding: utf-8 -*-
"""NR -- on ne purge QUE ce qui est traite, et le postal dit ce qui l'est (owner 2026-10-01).

Le purgeur des messages est forge_log_retention (NokidoLogRetention) : il EXPORTE en jsonl.gz
rejouable puis supprime. Mesure : il supprimait aussi 'read' (lu, pas traite) et 'archived'
(courrier NON LU d'un agent mort), et dans le courrier riche les 'dead' (jamais livres) SANS
export. Desormais : listes BLANCHES du postal -- M2M 'done', courrier 'acked' ; la cellule
pluripotente ne fait que rapporter (pas de second systeme sur la meme table). Bases jetables.
"""
import gzip
import importlib
import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VIEUX, RECENT = "2026-01-01 00:00:00", "2099-01-01 00:00:00"
LIGNES = [("v_done", "B", "done", VIEUX), ("v_arch", "B", "archived", VIEUX), ("v_read", "B", "read", VIEUX),
          ("v_pend", "B", "pending", VIEUX), ("v_unread", "B", "unread", VIEUX),
          ("v_quar", "B", "quarantaine", VIEUX), ("v_null", "B", None, VIEUX),
          ("v_capt", "cli_capture", "unread", VIEUX), ("r_done", "B", "done", RECENT)]


def _m2m(chemin: Path) -> Path:
    c = sqlite3.connect(str(chemin))
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.executemany("INSERT INTO agent_messages (id, from_agent, to_agent, method, status, created_at) "
                  "VALUES (?, 'A', ?, 'm', ?, ?)", LIGNES)
    c.commit()
    c.close()
    return chemin


def _ids(chemin: Path, table="agent_messages", col="id") -> set:
    c = sqlite3.connect(str(chemin))
    try:
        return {r[0] for r in c.execute("SELECT %s FROM %s" % (col, table))}
    finally:
        c.close()


@pytest.fixture
def lr(tmp_path, monkeypatch):
    m2m = _m2m(tmp_path / "m2m.db")
    dbp = importlib.import_module("nokido_agent.app.forge_db_path")
    monkeypatch.setattr(dbp, "m2m_path", lambda: str(m2m))
    spec = importlib.util.spec_from_file_location("log_retention_nr", ROOT / "tools" / "forge_log_retention.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    return m, m2m, tmp_path


def test_le_purgeur_unique_ne_supprime_que_le_traite_apres_export(lr):
    m, m2m, t = lr
    r = m._purge_agent_messages(False)
    assert r.get("deleted") == 2, r  # v_done + la telemetrie cli_capture
    assert _ids(m2m) == {"v_arch", "v_read", "v_pend", "v_unread", "v_quar", "v_null", "r_done"}
    archive = next((t / "logs" / "archive").glob("agent_messages_*.jsonl.gz"))
    exportes = gzip.open(archive, "rt", encoding="utf-8").read()
    assert '"v_done"' in exportes and '"v_capt"' in exportes, "exporte AVANT de supprimer"


def test_le_courrier_ne_perd_que_l_acquitte(lr):
    m, _m2m_db, t = lr
    (t / "RAG").mkdir()
    db = t / "RAG" / "postal.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE mail (id TEXT PRIMARY KEY, ts_queued REAL, status TEXT)")
    vieux = time.time() - 365 * 86400
    c.executemany("INSERT INTO mail VALUES (?, ?, ?)",
                  [("m_ack", vieux, "acked"), ("m_dead", vieux, "dead"), ("m_q", vieux, "queued")])
    c.commit()
    c.close()
    r = m._purge_mail(False)
    assert r.get("mail_purged") == 1, r
    assert _ids(db, "mail") == {"m_dead", "m_q"}, "un courrier jamais livre n'a pas ete traite"


def test_la_cellule_pluripotente_ne_supprime_rien(lr):
    _m, m2m, t = lr
    pw = importlib.import_module("nokido_agent.app.forge_pluripotent_workers")
    r = pw._action_mailbox_purger()
    assert r["ok"] and r["rapport_seulement"] is True and r["vises"] == 1, r
    assert _ids(m2m) == {i for i, *_x in LIGNES}


def test_le_postal_dit_ce_qui_est_traite():
    postal = importlib.import_module("nokido_agent.app.forge_postal")
    assert postal.ETATS_M2M_TRAITES == frozenset({"done"})
    assert postal.ETATS_COURRIER_TRAITES == frozenset({"acked"})
