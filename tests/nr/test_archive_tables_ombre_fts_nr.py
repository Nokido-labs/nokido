"""NR -- l'archive chiffree n'ecarte QUE les tables d'ombre FTS, jamais une table ordinaire au nom voisin.

Releve en relecture le 19/10 avant integration (preserve/opencode_gptoss -> alpha) : `tables_a_exporter` ecartait toute
table dont le nom commence par celui d'une table virtuelle + « _ ». Une table ORDINAIRE nommee `rag_fts_sauvegarde`
(a cote de la table FTS `rag_fts`) aurait donc disparu de l'archive EN SILENCE -- une sauvegarde qui perd des donnees
sans le dire. Seuls les suffixes d'ombre de SQLite FTS3/4/5 sont internes.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_backup_hotswap as H  # noqa: E402


def test_une_table_ordinaire_au_nom_voisin_d_une_fts_est_exportee(tmp_path):
    con = sqlite3.connect(tmp_path / "b.db")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(texte)")
    con.execute("CREATE TABLE rag_fts_sauvegarde (id INTEGER PRIMARY KEY, note TEXT)")
    con.execute("CREATE TABLE ordinaire (id INTEGER PRIMARY KEY)")
    con.commit()
    schema, ordinaires, virtuelles = H.tables_a_exporter(con)
    assert virtuelles == ["rag_fts"]
    assert "rag_fts_sauvegarde" in ordinaires and "ordinaire" in ordinaires
    for ombre in ("rag_fts_data", "rag_fts_idx", "rag_fts_content", "rag_fts_docsize", "rag_fts_config"):
        assert ombre not in ordinaires, ombre
        assert not any(ombre in s for s in schema), ombre
