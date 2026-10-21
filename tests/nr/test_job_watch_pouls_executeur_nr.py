# -*- coding: utf-8 -*-
"""NR : le guetteur de tache lit le POULS de l'executeur (P2_guetteur_lit_progres_et_pouls_20261017).

Mesure du 2026-10-18 : une surveillance `--task` a expire 30 min SANS UN evenement pendant que l'executeur
travaillait sur la tache (pouls `travail_en_cours`, `tache` = la tache, `travail_depuis_s` = 1200) : le statut
de la table ne bougeait pas, le guetteur ne lisait que lui. Un executeur qui DECLARE travailler sur CETTE tache
n'est pas un gel (STALE n'est pas DEAD) ; et le client doit le VOIR, pas deviner.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_job_watch_cli as W  # noqa: E402  -- import DUR : un module absent doit rougir, jamais sauter

TACHE = "job_test_pouls_1"


def _db(tmp_path, statut="pending"):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, result TEXT, progress_at TEXT)")
    c.execute("INSERT INTO tasks VALUES (?, ?, '', NULL)", (TACHE, statut))
    c.commit()
    c.close()
    return db


def _pouls(dossier, tache, en_cours=True, depuis=600):
    dossier.mkdir(exist_ok=True)
    (dossier / "task_executor_opencode_test.heartbeat").write_text(json.dumps(
        {"ts": "2026-10-18T00:00:00", "agent": "OPENCODE_TEST", "travail_en_cours": en_cours,
         "travail_depuis_s": depuis, "tache": tache}), encoding="utf-8")


def _courir(db, pouls_dir, gel_s=300, max_s=3000):
    t = [0.0]
    lignes = []
    W.surveiller_tache(TACHE, gel_s=gel_s, max_s=max_s, intervalle=60, ecrire=lignes.append, db=db,
                       horloge=lambda: t[0], dormir=lambda s: t.__setitem__(0, t[0] + s), pouls_dir=pouls_dir)
    return lignes


def test_un_executeur_qui_travaille_sur_la_tache_n_est_pas_un_gel_et_se_voit(tmp_path):
    db = _db(tmp_path)
    _pouls(tmp_path / "hb", TACHE)
    lignes = _courir(db, tmp_path / "hb")
    assert not any("FIGEE" in l for l in lignes), lignes
    pouls = [l for l in lignes if "pouls de l'executeur" in l]   # pas « pouls » seul : l'id de la tache le contient
    assert pouls, lignes
    # visible sans inonder : au plus une ligne de pouls par 10 min sur ~51 min
    assert len(pouls) <= 6, lignes


def test_le_pouls_d_une_autre_tache_ne_protege_pas_du_gel(tmp_path):
    db = _db(tmp_path)
    _pouls(tmp_path / "hb", "job_autre_tache")
    lignes = _courir(db, tmp_path / "hb")
    assert any("FIGEE" in l for l in lignes), lignes


def test_un_pouls_illisible_est_ignore_sans_planter(tmp_path):
    db = _db(tmp_path)
    (tmp_path / "hb").mkdir()
    (tmp_path / "hb" / "task_executor_x.heartbeat").write_text("{pas du json", encoding="utf-8")
    lignes = _courir(db, tmp_path / "hb")
    assert any("FIGEE" in l for l in lignes), lignes
