# -*- coding: utf-8 -*-
"""NR — le domaine conv remplit `hash` et deduplique a l'insertion (cause racine 2026-10-17).

Mesure du 17/10 : 99 973 / 99 973 fragments conv ont `hash` a NULL — la colonne
que lit `tools/forge_rag_dedup_hash.py` pour grouper les doublons. Sans empreinte,
la deduplication a l'ingestion ne pouvait pas operer : 17,6 % de doublons mesures.

Le chemin REEL est la digestion (`iter_claude_epure`) puis l'ecriture
(`_insert_chunks`) — c'est par la que le hash doit etre pose. Base SQLite
TEMPORAIRE au schema rag_chunks (avec `hash`) : jamais la vraie base.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import forge_conv_indexer as ci  # noqa: E402

TEXTE_HUM = "fais le menu du tray comme convenu, une seule icone et le reste en menu"


def _transcript(tmp_path, nom, texte, jour="2026-10-13"):
    p = tmp_path / ("%s.jsonl" % nom)
    p.write_text(json.dumps(
        {"type": "user", "message": {"content": texte}, "timestamp": "%sT15:58:24Z" % jour}
    ) + "\n", encoding="utf-8")
    return p


def _base(tmp_path):
    db = tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, domain TEXT, "
              "ingested_at TEXT, created_at TEXT, hash TEXT, active INT DEFAULT 1)")
    c.execute("CREATE INDEX idx_rag_source ON rag_chunks(source)")
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id, source, text)")
    c.commit()
    c.close()
    return db


def _fragments(tmp_path, nom, texte):
    """Chemin reel : un transcript est DIGEREE (epuree), puis injecte par _insert_chunks."""
    return list(ci.iter_claude_epure(_transcript(tmp_path, nom, texte), {}))


def test_l_insertion_conv_remplit_le_hash(tmp_path):
    db = _base(tmp_path)
    frags = _fragments(tmp_path, "sess1", TEXTE_HUM)
    assert frags, "le transcript digere ne doit rien rendre : le test ne prouverait rien"
    assert ci._insert_chunks(frags, db) == len(frags)
    c = sqlite3.connect(db)
    lignes = c.execute("SELECT source, text, domain, hash FROM rag_chunks ORDER BY source").fetchall()
    c.close()
    assert len(lignes) == len(frags)
    for source, text, domain, h in lignes:
        assert source.startswith(ci.PREFIXE_EPURE + "/") and domain == "conv"
        assert h, "hash NULL : la deduplication par contenu est impossible (%s)" % source
        assert h == hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16], source


def test_un_texte_identique_n_est_pas_reinsere(tmp_path):
    """Le meme message dans deux sessions : id different (l'identite depend de la session),
    texte identique — un seul exemplaire doit entrer en base."""
    db = _base(tmp_path)
    assert ci._insert_chunks(_fragments(tmp_path, "sessA", TEXTE_HUM), db) == 1
    assert ci._insert_chunks(_fragments(tmp_path, "sessB", TEXTE_HUM), db) == 0, \
        "un second fragment au texte IDENTIQUE a ete reinsere : la dedup par hash ne joue pas"
    c = sqlite3.connect(db)
    n, sources = c.execute("SELECT COUNT(*), GROUP_CONCAT(source) FROM rag_chunks "
                           "WHERE text LIKE ?", ("%" + TEXTE_HUM + "%",)).fetchone()
    c.close()
    assert n == 1, sources
