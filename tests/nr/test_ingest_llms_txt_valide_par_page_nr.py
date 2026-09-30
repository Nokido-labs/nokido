# -*- coding: utf-8 -*-
"""NR — l'ingestion d'un site de doc valide PAGE PAR PAGE, elle ne tient pas le verrou RAG.

Constat du 2026-09-24, avant d'ingerer la doc de Claude Code (208 pages) puis celle de
l'API (638) : `forge_ingest_llms_txt.ingerer` ouvrait UNE transaction d'ecriture et ne la
validait qu'a la fin. Le verrou d'ecriture de embeddings.db restait donc pris de la premiere
insertion a la derniere page, et tout autre ecrivain attendait ou expirait — exactement le P0
« on retire des ecrivains du verrou RAG ».

Chemin reel : `ingerer()` est appelee telle quelle ; seuls le reseau et la base sont
remplaces (base en memoire, pages servies localement).
"""

import importlib.util
import io
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class _Base:
    """Connexion en memoire qui COMPTE ses validations."""

    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT,"
                       " domain TEXT, created_at TEXT)")
        self.c.execute("CREATE TABLE rag_fts (chunk_id TEXT, text TEXT, source TEXT, domain TEXT)")
        self.validations = 0

    def execute(self, *a):
        return self.c.execute(*a)

    def commit(self):
        self.validations += 1
        self.c.commit()

    def close(self):
        pass


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_une_validation_par_page(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "forge_ingest_llms_txt_nr", ROOT / "tools" / "forge_ingest_llms_txt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    corps = ("# Titre\n\n" + "Une phrase de documentation suffisamment longue. " * 20).encode()
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: _Reponse(corps))
    pages = [("p%d" % i, "https://doc.example/p%d.md" % i) for i in range(3)]

    rapport = m.ingerer(pages, "doc_nr", pause=0, timeout=5)

    assert rapport["pages_ok"] == 3, rapport
    assert base.validations >= 3, (
        "%d validation(s) pour 3 pages : le verrou d'ecriture est tenu sur tout le site"
        % base.validations)
