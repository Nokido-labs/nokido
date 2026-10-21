# -*- coding: utf-8 -*-
"""NR — le guetteur de TACHE lit le progres declare avant de crier « FIGEE » (P2 du 17/10).

Mesure 17/10 : `forge_job_watch_cli --task` disait « FIGEE — statut running inchange depuis 30 min » pendant qu'une
delegation OpenCode/AGY travaillait : le statut ne bouge pas pendant un tour long, mais l'executeur touche
`tasks.progress_at` (battement de delegation, `_PROGRES_TOUTES_S`). STALE n'est pas DEAD : un progres qui avance
repousse le gel ; quand le gel est declare, le dernier progres declare est DIT (ou ILLISIBLE).
"""
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_job_watch_cli_nr_progres", ROOT / "tools" / "forge_job_watch_cli.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _base(tmp_path, progres):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, result TEXT, progress_at TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'running', '', ?)", (progres,))
    c.commit()
    c.close()
    return db


class Horloge:
    def __init__(self, db, avance):
        self.t, self.db, self.avance, self.n = 1000.0, db, avance, 0

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s
        if self.avance:
            self.n += 1
            c = sqlite3.connect(self.db)
            c.execute("UPDATE tasks SET progress_at = ? WHERE id = 't1'", ("2026-10-17T18:%02d:00" % self.n,))
            c.commit()
            c.close()


def test_un_progres_qui_avance_repousse_le_gel(tmp_path):
    m = _module()
    db = _base(tmp_path, "2026-10-17T18:00:00")
    h = Horloge(db, avance=True)
    lignes = []
    m.surveiller_tache("t1", gel_s=120, max_s=600, intervalle=60, ecrire=lignes.append, db=db, horloge=h, dormir=h.dormir)
    assert not any("FIGEE" in l for l in lignes), lignes
    assert any("TOUJOURS EN COURS" in l for l in lignes), lignes


def test_un_gel_declare_dit_le_dernier_progres(tmp_path):
    m = _module()
    db = _base(tmp_path, "2026-10-17T18:00:00")
    h = Horloge(db, avance=False)
    lignes = []
    m.surveiller_tache("t1", gel_s=120, max_s=600, intervalle=60, ecrire=lignes.append, db=db, horloge=h, dormir=h.dormir)
    gel = [l for l in lignes if "FIGEE" in l]
    assert gel, lignes
    assert "2026-10-17T18:00:00" in gel[0], gel[0]


def test_sans_progres_lisible_le_gel_le_dit(tmp_path):
    m = _module()
    db = _base(tmp_path, None)
    h = Horloge(db, avance=False)
    lignes = []
    m.surveiller_tache("t1", gel_s=120, max_s=600, intervalle=60, ecrire=lignes.append, db=db, horloge=h, dormir=h.dormir)
    gel = [l for l in lignes if "FIGEE" in l]
    assert gel and "progres ILLISIBLE" in gel[0], lignes
