# -*- coding: utf-8 -*-
"""NR -- wal_bloat : le corps SOIGNE un fichier WAL surdimensionne mais fusionne ; seule une retention reelle est une embolie.

Alerte owner 2026-11-08 « ANTI-EMBOLIE wal_bloat, tu n'as toujours pas regle ce probleme ».
Mesure (C:/tmp/diag_wal_execution_traces_20261108.py) : RAG/execution_traces.db-wal = 0,81 Go,
mais checkpoint PASSIVE = (busy 0, 1008 trames, 1008 fusionnees) : rien n'etait retenu, SQLite ne
TRONQUE simplement jamais le fichier apres checkpoint. Le diagnostic « WAL non checkpointe » etait
faux et rien ne soignait. Contrat de _check_wal_bloat : au-dessus du seuil -> wal_checkpoint(TRUNCATE) ;
fichier revenu sous le seuil = CLEAR (« soigne ») ; toujours au-dessus (lecteur qui retient) = EMBOLIE.
"""
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _op():
    spec = importlib.util.spec_from_file_location("op_nr_wal", ROOT / "tools" / "forge_organ_pulse.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_TENEURS = []  # connexion inactive gardee ouverte (comme le hub) : sinon la fermeture supprime le WAL


def _gros_wal(dossier: Path) -> Path:
    db = dossier / "traces.db"
    c = sqlite3.connect(str(db))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t (x BLOB)")
    for _ in range(300):
        c.execute("INSERT INTO t VALUES (?)", (b"x" * 4000,))
    c.commit()
    c.execute("PRAGMA wal_checkpoint(PASSIVE)")  # fusionne SANS tronquer : le cas mesure
    _TENEURS.append(c)
    return db


def _prepare(tmp_path, monkeypatch):
    op = _op()
    rag = tmp_path / "RAG"
    rag.mkdir()
    (tmp_path / "sandbox").mkdir()
    db = _gros_wal(rag)
    monkeypatch.setattr(op, "RAG_DB", rag / "embeddings.db")
    monkeypatch.setattr(op, "ROOT", tmp_path)
    monkeypatch.setattr(op, "WAL_BLOAT_GB", 0.0005)  # 500 Ko
    assert Path(str(db) + "-wal").stat().st_size >= 0.0005 * 1e9
    return op, db


def _pulse_par_chemin():
    spec = importlib.util.spec_from_file_location(
        "_organ_pulse_lag_nr", Path(__file__).resolve().parents[2] / "tools" / "forge_organ_pulse.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _journal_lag(tmp_path, m, lags_ms, monkeypatch):
    import time
    f = tmp_path / "loop_lag.log"
    now = time.time()
    lignes = []
    for i, lag in enumerate(lags_ms):
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 30 * (len(lags_ms) - i)))
        lignes += ["  File \"x.py\", line 1 in gen", "=== %s lag=%dms (stack AU-DESSUS = coupable mid-block) ===" % (t, lag),
                   "--- [loop-lag] 2026-01-01T00:00:00.000Z lag=%dms (dump ci-dessus) ---" % lag]
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    monkeypatch.setattr(m, "LAG_LOG", f)


def test_pic_de_lag_isole_n_est_pas_une_embolie(tmp_path, monkeypatch):
    """11/11, alerte owner #687 : UN pic a 1841 ms (seuil 1800), resorbe seul -> alerte high au tray, sans aucune
    decision possible (owner : « qu'est-ce que tu veux que j'en fasse »). Un pic isole = WARN, coupable pointe."""
    m = _pulse_par_chemin()
    _journal_lag(tmp_path, m, [400, 500, m.LAG_MS + 41], monkeypatch)
    verdict, detail = m._check_event_loop()
    assert verdict == m.WARN, (verdict, detail)
    assert "isol" in detail and "loop_lag.log" in detail


def test_lag_repete_ou_massif_reste_une_embolie(tmp_path, monkeypatch):
    """La protection n'est pas relachee : 2 pics graves dans la fenetre, ou un pic >= 2x le seuil, alertent."""
    m = _pulse_par_chemin()
    _journal_lag(tmp_path, m, [m.LAG_MS + 10, 300, m.LAG_MS + 200], monkeypatch)
    assert m._check_event_loop()[0] == m.EMBOLIE
    _journal_lag(tmp_path, m, [2 * m.LAG_MS + 1], monkeypatch)
    assert m._check_event_loop()[0] == m.EMBOLIE
    _journal_lag(tmp_path, m, [200, 300], monkeypatch)
    assert m._check_event_loop()[0] == m.WARN


def test_wal_fusionne_surdimensionne_est_soigne(tmp_path, monkeypatch):
    op, db = _prepare(tmp_path, monkeypatch)
    etat, detail = op._check_wal_bloat()
    assert etat == op.CLEAR, (etat, detail)
    assert "soign" in detail.lower()
    assert Path(str(db) + "-wal").stat().st_size < 0.0005 * 1e9


def test_wal_retenu_par_un_lecteur_reste_embolie(tmp_path, monkeypatch):
    op, db = _prepare(tmp_path, monkeypatch)
    lecteur = sqlite3.connect(str(db))
    lecteur.execute("BEGIN")
    lecteur.execute("SELECT count(*) FROM t").fetchone()  # instantane de lecture tenu
    ecrivain = _TENEURS[-1]
    for _ in range(300):  # trames APRES l'instantane : le lecteur les empeche d'etre tronquees
        ecrivain.execute("INSERT INTO t VALUES (?)", (b"y" * 4000,))
    ecrivain.commit()
    try:
        etat, detail = op._check_wal_bloat()
    finally:
        lecteur.close()
    assert etat == op.EMBOLIE, (etat, detail)
