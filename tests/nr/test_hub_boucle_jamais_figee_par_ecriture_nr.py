# -*- coding: utf-8 -*-
"""NR — une ecriture SQLite ne fige plus la boucle du hub quand un tiers tient le verrou.

Mesure du 27/09 (hub vu « instable » par le tray) : 1 257 s de boucle figee en une soiree.
Le profileur par tool (`forge_promcp_profiler.record`, a CHAQUE appel de tool) et le journal
d'intentions (`forge_intention_journal.record` -> `forge_timecode`) ecrivaient dans
embeddings.db DEPUIS la boucle, avec 5 a 10 s d'attente de verrou. Des qu'un job nocturne
tenait l'ecriture, chaque appel gelait tout le hub.

Les tests reproduisent le MECANISME : un tiers prend le verrou (`BEGIN IMMEDIATE`) et l'appel
se fait depuis une boucle asyncio. Avant : ~5 s (profileur) / ~10 s (journal). Apres : un
`put_nowait`, puis l'ecriture aboutit dans le fil dedie des que le verrou est rendu.
"""
import asyncio
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_intention_journal as ij  # noqa: E402
from nokido_agent.app import forge_promcp_profiler as pp  # noqa: E402
from nokido_agent.app import forge_timecode as tc  # noqa: E402
from nokido_agent.app.forge_bounded_queue import EcrivainDiffere  # noqa: E402

BORNE_S = 0.3  # une boucle saine ne paie qu'un put_nowait


def _verrou_tiers(db):
    """Un tiers tient le verrou d'ecriture, comme le job nocturne du 27/09."""
    c = sqlite3.connect(str(db), timeout=1, isolation_level=None)
    c.execute("BEGIN IMMEDIATE")
    return c


def _rendre(c):
    c.execute("ROLLBACK")
    c.close()


def _chrono_sur_boucle(fn):
    async def scenario():
        t0 = time.perf_counter()
        r = fn()
        return r, time.perf_counter() - t0
    return asyncio.run(scenario())


def test_ecrivain_rend_la_main_et_garde_l_ordre():
    e = EcrivainDiffere("nr_ordre", capacity=100)
    vu = []

    def soumettre_tout():
        e.soumettre(lambda: time.sleep(0.5))  # une ecriture lente (verrou attendu)
        for i in range(5):
            e.soumettre(lambda i=i: vu.append(i))
        return e.sur_une_boucle()

    sur_boucle, duree = _chrono_sur_boucle(soumettre_tout)
    assert sur_boucle and duree < BORNE_S
    assert e.vider(10) and vu == [0, 1, 2, 3, 4]
    assert not e.sur_une_boucle()


def test_file_pleine_abandonne_et_le_compte_sans_bloquer():
    e = EcrivainDiffere("nr_pleine", capacity=1)
    libre = threading.Event()
    e.soumettre(libre.wait)  # occupe le fil
    fin = time.monotonic() + 5
    while e.stats()["current"] and time.monotonic() < fin:
        time.sleep(0.01)
    assert e.soumettre(lambda: None) is True   # la file (1 place) accueille
    assert e.soumettre(lambda: None) is False  # pleine : abandon, pas d'attente
    libre.set()
    assert e.vider(5) and e.stats()["rejected"] == 1


def test_le_profileur_ne_fige_plus_la_boucle_sous_verrou(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    monkeypatch.setattr(pp, "DB", db)
    pp._conn().close()  # schema pose hors boucle
    tiers = _verrou_tiers(db)
    try:
        _, duree = _chrono_sur_boucle(lambda: pp.record("outil_nr", 12.0))
        assert duree < BORNE_S, "record a attendu le verrou %.2f s SUR la boucle" % duree
    finally:
        _rendre(tiers)
    assert pp._ECRIVAIN.vider(15)
    con = sqlite3.connect(str(db))
    n = con.execute("SELECT COUNT(*) FROM promcp_tool_metrics WHERE tool='outil_nr'").fetchone()[0]
    con.close()
    assert n == 1  # l'ecriture a abouti, differee


def test_le_profileur_hors_boucle_ecrit_sur_place(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    monkeypatch.setattr(pp, "DB", db)
    pp.record("outil_cli", 3.0)
    con = sqlite3.connect(str(db))
    n = con.execute("SELECT COUNT(*) FROM promcp_tool_metrics WHERE tool='outil_cli'").fetchone()[0]
    con.close()
    assert n == 1  # sans vider : ecrit immediatement, comme avant


def test_le_journal_d_intentions_ne_fige_plus_la_boucle_sous_verrou(tmp_path, monkeypatch):
    db = tmp_path / "timecode.db"
    monkeypatch.setattr(tc, "_engine", tc.TimecodeEngine(db))
    tiers = _verrou_tiers(db)
    try:
        r, duree = _chrono_sur_boucle(lambda: ij.record("NR", "nr_verrou", target="x"))
        assert duree < BORNE_S, "record a attendu le verrou %.2f s SUR la boucle" % duree
        assert r == {"ok": True, "differe": True}
    finally:
        _rendre(tiers)
    assert ij._ECRIVAIN.vider(25)
    con = sqlite3.connect(str(db))
    n = con.execute("SELECT COUNT(*) FROM event_log WHERE event_type='intention:nr_verrou'").fetchone()[0]
    con.close()
    assert n == 1


def test_le_schema_du_timecode_n_est_pose_qu_une_fois(tmp_path, monkeypatch):
    appels = []
    orig = tc.TimecodeEngine._ensure_schema
    monkeypatch.setattr(tc.TimecodeEngine, "_ensure_schema",
                        lambda self: (appels.append(1), orig(self))[1])
    db = tmp_path / "schema.db"
    tc.TimecodeEngine(db)
    tc.TimecodeEngine(db)
    assert len(appels) == 1
