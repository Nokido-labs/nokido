# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `tools/forge_epistemic_recompute.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`
ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs
de chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la
metrique `couverture prouvee` — le marqueur en tete sert exactement a l'en
exclure. Le remplacer par un vrai test de comportement est un progres ; le
supprimer sans le remplacer rend le module non mesurable.
"""

import importlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    assert importlib.import_module("forge_epistemic_recompute") is not None


def _temoin(tmp_path, n=3):
    """Base TEMOIN au schema reel (index active + ingested_at), jamais la vivante."""
    db = tmp_path / "temoin.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, author TEXT,"
        " domain TEXT, ingested_at TEXT, updated_at TEXT, active INTEGER,"
        " epistemic_weight REAL, last_validated_at TEXT)"
    )
    conn.execute("CREATE INDEX idx_rag_chunks_active ON rag_chunks(active)")
    conn.execute("CREATE INDEX idx_rag_chunks_ingested_at ON rag_chunks(ingested_at)")
    for i in range(n):
        _ajoute(conn, f"c{i}")
    conn.commit()
    conn.close()
    return db


def _ajoute(conn, cid):
    conn.execute(
        "INSERT INTO rag_chunks (id, source, domain, ingested_at, active)"
        " VALUES (?, 'https://arxiv.org/abs/1', 'watch_veille', '2026-01-01T00:00:00Z', 1)",
        (cid,),
    )


def _passe(mod, tmp_path, db):
    return mod.recompute(db_path=db, state_path=tmp_path / "etat.json")


def test_etat_absent_passage_complet_dit(tmp_path):
    mod = importlib.import_module("forge_epistemic_recompute")
    res = _passe(mod, tmp_path, _temoin(tmp_path))
    assert res["mode"] == "full_initial"
    assert res["processed"] == 3


def test_second_passage_sans_modification_relit_zero(tmp_path):
    mod = importlib.import_module("forge_epistemic_recompute")
    db = _temoin(tmp_path)
    _passe(mod, tmp_path, db)
    res = _passe(mod, tmp_path, db)
    assert res["mode"] == "incremental"
    assert res["processed"] == 0


def test_un_element_nouveau_un_seul_recalcule(tmp_path):
    mod = importlib.import_module("forge_epistemic_recompute")
    db = _temoin(tmp_path)
    _passe(mod, tmp_path, db)
    conn = sqlite3.connect(str(db))
    _ajoute(conn, "c_new")
    conn.commit()
    conn.close()
    res = _passe(mod, tmp_path, db)
    assert res["processed"] == 1


def test_plan_sans_balayage_massif(tmp_path):
    mod = importlib.import_module("forge_epistemic_recompute")
    conn = sqlite3.connect(str(_temoin(tmp_path)))
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + mod.SELECT_SQL, (0, 10)))
    conn.close()
    assert "SEARCH" in plan
    assert "TEMP B-TREE" not in plan
    assert "idx_rag_chunks_active" not in plan
