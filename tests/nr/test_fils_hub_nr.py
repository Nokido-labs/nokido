# -*- coding: utf-8 -*-
"""NR owner 4/11 (« Introspection dans le hub ») : le hub lit ~35 Mo toutes les ~10 s (sonde e9a90d767), hors
regulation (60 s) et hors requetes ; ni le compte de confiance ni py-spy n'atteignent son processus. Le hub lit ses
PROPRES fils (sys._current_frames) : chaque fil nomme, son haut de pile, et ceux qui sont dans SQLite."""
import importlib
import sqlite3
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
F = importlib.import_module("nokido_agent.app.forge_fils_hub")


def test_un_fil_de_fond_est_nomme_avec_sa_pile():
    arret = threading.Event()

    def boucle_qui_lit():
        while not arret.is_set():
            time.sleep(0.01)
    t = threading.Thread(target=boucle_qui_lit, name="boucle-test-lecture", daemon=True)
    t.start()
    try:
        r = F.echantillonner_fils(n=2, pas_s=0.05)
    finally:
        arret.set()
    fils = {f["nom"]: f for e in r["echantillons"] for f in e["fils"]}
    assert "boucle-test-lecture" in fils
    assert any("boucle_qui_lit" in c for c in fils["boucle-test-lecture"]["pile"])


def test_un_fil_dans_sqlite_est_signale(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db))
    con.execute("create table t(x)")
    con.executemany("insert into t values (?)", [(i,) for i in range(200000)])
    con.commit()
    con.close()
    arret = threading.Event()

    def balaye_la_base():
        c = sqlite3.connect(str(db))
        while not arret.is_set():
            c.execute("select sum(x) from t t1, (select 1 from t limit 50)").fetchone()
    t = threading.Thread(target=balaye_la_base, name="balayeur-test", daemon=True)
    t.start()
    try:
        time.sleep(0.2)
        r = F.echantillonner_fils(n=3, pas_s=0.05)
    finally:
        arret.set()
    assert "balayeur-test" in r["dans_sqlite"], "un fil dont la pile passe par sqlite3 est SIGNALE"


def test_reserve_aux_rings_de_confiance():
    assert F.autorise(0) and F.autorise(1)
    assert not F.autorise(2) and not F.autorise(4)
