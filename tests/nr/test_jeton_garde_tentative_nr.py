"""7/11 : jeton de garde par tentative. Un worker zombie (tentative perimee) ne doit plus ecrire apres la reprise de sa
tache par le meme agent. Chemin reel : cible_ecriture + les VRAIES voies de remise en pending (reclaim_expired,
requalifier_orphelines) + le VRAI claim (_reclamer)."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402
import forge_worktree as W  # noqa: E402

T1 = "job_aaaaaaaa_1_x"


def _arbre(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: x\n", encoding="utf-8")
    return d


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    racine = tmp_path / "nokido_worktrees"
    _arbre(racine / "claude_headless")
    _arbre(racine / "taches" / ("claude_headless_%s" % W.court_tache(T1)))
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, result TEXT, updated_at TEXT, created_at TEXT, "
              "exec_pid INTEGER, exec_cree TEXT)")
    c.execute("INSERT INTO tasks (id, agent, status, updated_at) VALUES (?,?,?,?)",
              (T1, "CLAUDE_HEADLESS", "pending", "2020-01-01T00:00:00"))
    c.commit()
    c.close()

    def _db():
        k = sqlite3.connect(db)
        k.row_factory = sqlite3.Row
        return k

    monkeypatch.setattr(E, "_db", _db)
    monkeypatch.setattr(E, "_publier_tache", lambda *a, **k: None)
    monkeypatch.setattr(E, "_estampiller_proprietaire", lambda *a, **k: None)
    return racine, db, _db


def _prendre(db, _db):
    """Claim reel, puis la tentative que le jeton court signerait."""
    conn = _db()
    try:
        assert E._reclamer(conn, T1, "CLAUDE_HEADLESS", None, enforce=False) is True
    finally:
        conn.close()
    return W.tentative_courante(T1, tasks_db=db)


def _ecrire(racine, db, tentative):
    return W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db, tache=T1, tentative=tentative)


def test_tentative_courante_acceptee(banc):
    racine, db, _db = banc
    t = _prendre(db, _db)
    assert _ecrire(racine, db, t)["cible"] == "WORKTREE"


def test_perimee_apres_reclaim_expired_refusee(banc):
    racine, db, _db = banc
    zombie = _prendre(db, _db)
    c = sqlite3.connect(db)
    c.execute("UPDATE tasks SET progress_at='2020-01-01T00:00:00' WHERE id=?", (T1,))
    c.commit()
    c.close()
    assert E.reclaim_expired(timeout_s=1)["reprises"] == 1
    courante = _prendre(db, _db)  # reprise par le MEME agent
    assert courante != zombie
    r = _ecrire(racine, db, zombie)
    assert r["cible"] == "REFUS" and "tentative perimee" in r["raison"]
    assert _ecrire(racine, db, courante)["cible"] == "WORKTREE"


def test_perimee_apres_pid_mort_refusee(banc):
    racine, db, _db = banc
    zombie = _prendre(db, _db)
    c = sqlite3.connect(db)
    c.execute("UPDATE tasks SET exec_pid=999999, exec_cree='x' WHERE id=?", (T1,))
    c.commit()
    c.close()
    out = E.requalifier_orphelines("CLAUDE_HEADLESS", vivacite=lambda pid, cree: False)
    assert out["requalifiees"] == [T1]
    courante = _prendre(db, _db)
    assert courante != zombie
    assert _ecrire(racine, db, zombie)["cible"] == "REFUS"
    assert _ecrire(racine, db, courante)["cible"] == "WORKTREE"


def test_pid_mort_ne_consomme_pas_le_quota_de_reprises(banc):
    racine, db, _db = banc
    for _ in range(E._LEASE_MAX_ATTEMPTS + 2):
        _prendre(db, _db)
        c = sqlite3.connect(db)
        c.execute("UPDATE tasks SET exec_pid=999999, exec_cree='x' WHERE id=?", (T1,))
        c.commit()
        c.close()
        E.requalifier_orphelines("CLAUDE_HEADLESS", vivacite=lambda pid, cree: False)
    c = sqlite3.connect(db)
    att = c.execute("SELECT COALESCE(attempt,0) FROM tasks WHERE id=?", (T1,)).fetchone()[0]
    c.close()
    assert att == 0


def test_tentative_absente_du_jeton_refus_distinct(banc):
    racine, db, _db = banc
    _prendre(db, _db)
    r = _ecrire(racine, db, None)
    assert r["cible"] == "REFUS" and "absente du jeton" in r["raison"]
    assert "perimee" not in r["raison"]


def _etat(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT status, result FROM tasks WHERE id=?", (T1,)).fetchone()
    finally:
        c.close()


def _reprendre(db):
    c = sqlite3.connect(db)
    c.execute("UPDATE tasks SET progress_at='2020-01-01T00:00:00' WHERE id=?", (T1,))
    c.commit()
    c.close()
    assert E.reclaim_expired(timeout_s=1)["reprises"] == 1


def test_cloture_normale_reussit(banc):
    racine, db, _db = banc
    E._TENTATIVE_PRISE.clear()
    _prendre(db, _db)
    conn = _db()
    E._mark_done(conn, T1, "fini", True)
    conn.close()
    assert _etat(db) == ("completed", "fini")


def test_zombie_ne_cloture_pas_la_tache_reprise(banc):
    racine, db, _db = banc
    E._TENTATIVE_PRISE.clear()
    _prendre(db, _db)                       # tentative 0 (zombie)
    zombie_att = dict(E._TENTATIVE_PRISE)
    _reprendre(db)                          # -> pending, attempt=1
    _prendre(db, _db)                       # repreneur, tentative 1
    c = sqlite3.connect(db)
    c.execute("UPDATE tasks SET result='travail du repreneur' WHERE id=?", (T1,))
    c.commit()
    c.close()
    E._TENTATIVE_PRISE.clear()
    E._TENTATIVE_PRISE.update(zombie_att)   # le zombie ne retient que sa tentative 0
    assert E._TENTATIVE_PRISE[T1] == 0
    conn = _db()
    E._mark_done(conn, T1, "ecrase par le zombie", False)
    conn.close()
    assert _etat(db) == ("running", "travail du repreneur")


def test_base_illisible_echec_ferme(banc, tmp_path):
    racine, _db_, _ = banc
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=tmp_path / "absente.db", tache=T1, tentative=1)
    assert r["cible"] == "REFUS"
