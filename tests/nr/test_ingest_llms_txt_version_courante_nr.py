"""NR 2026-10-01 : une page re-ingeree ne garde que sa version COURANTE, et les agregats
`llms-full.txt` ne sont plus ingeres comme des pages.

Mesure qui l'a motive : `claude_docs:platform.claude.com/llms-full.txt` portait trois lots
actifs (40 261 chunks le 20/08, 45 965 le 24/09, 44 691 le 01/10) -- la concatenation de
tout le site, re-ingeree a chaque rafraichissement, sans que la version precedente soit
jamais retiree. Rien n'est supprime : `active=0` + `superseded_by`.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_ingest_llms_txt_version_nr", ROOT / "tools" / "forge_ingest_llms_txt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Base:
    """Base en memoire au schema utile : active / superseded_by + FTS externe, avec les
    triggers d'INSERTION de prod releves dans `sqlite_master` le 2026-10-01 (jamais
    reconstruits de memoire)."""

    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.executescript("""
        CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, domain TEXT,
                                 created_at TEXT, active INTEGER DEFAULT 1, superseded_by TEXT);
        CREATE TABLE rag_fts (chunk_id TEXT, text TEXT, source TEXT, domain TEXT);
        CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain,
                                 content='rag_chunks', content_rowid='rowid');
        CREATE TRIGGER rag_chunks_fts_bi BEFORE INSERT ON rag_chunks BEGIN
          INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
          SELECT 'delete', rowid, text, source, domain FROM rag_chunks
          WHERE id = new.id;
        END;
        CREATE TRIGGER rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN
          INSERT INTO rag_chunks_fts(rowid, text, source, domain)
          VALUES (new.rowid, new.text, new.source, new.domain);
        END;
        """)

    def lexical(self, mot):
        return self.c.execute("SELECT COUNT(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ?",
                              (mot,)).fetchone()[0]

    def execute(self, *a):
        return self.c.execute(*a)

    def commit(self):
        self.c.commit()

    def close(self):
        pass

    def etat(self, source):
        return self.c.execute("SELECT id, active, superseded_by FROM rag_chunks WHERE source = ?",
                              (source,)).fetchall()


class _Reponse:
    def __init__(self, corps):
        self.corps = corps

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.corps


def _servir(monkeypatch, m, texte):
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: _Reponse(texte.encode()))


V1 = "# Guide\n\n" + "La version un de cette page decrit l'ancien comportement. " * 30
V2 = "# Guide\n\n" + "La version deux remplace entierement le texte precedent. " * 30
PAGE = [("guide", "https://doc.example/guide.md")]
SOURCE = "doc_nr:doc.example/guide.md"


def test_une_page_modifiee_retire_sa_version_precedente(monkeypatch):
    m = _module()
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)

    _servir(monkeypatch, m, V1)
    r1 = m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    v1 = {cid for cid, actif, _s in base.etat(SOURCE)}
    assert r1["pages_ok"] == 1 and v1, r1

    _servir(monkeypatch, m, V2)
    r2 = m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    lignes = base.etat(SOURCE)
    actifs = {cid for cid, actif, _s in lignes if actif == 1}
    retires = {cid: s for cid, actif, s in lignes if actif == 0}

    assert set(retires) == v1, "la version 1 doit etre retiree en entier : %r" % lignes
    assert all(s == SOURCE for s in retires.values()), "superseded_by nomme la source"
    assert actifs and not (actifs & v1), "seule la version 2 reste active"
    assert r2["anciens_retires"] == len(v1), r2
    assert r2["retrait_impossible"]["n"] == 0, r2


def test_une_page_inchangee_ne_retire_rien(monkeypatch):
    m = _module()
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    _servir(monkeypatch, m, V1)
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    r = m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    assert r["anciens_retires"] == 0, r
    assert all(actif == 1 for _c, actif, _s in base.etat(SOURCE))


def test_une_page_inchangee_garde_son_entree_lexicale(monkeypatch):
    """Le trigger BEFORE INSERT retirait l'entree FTS d'un id existant AVANT que
    l'INSERT OR IGNORE soit ignore : rafraichir une page inchangee la rendait
    introuvable en lexical (mesure du 2026-10-01 sur les triggers de prod)."""
    m = _module()
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    _servir(monkeypatch, m, V1)
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    avant = base.lexical("ancien")
    assert avant > 0
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    assert base.lexical("ancien") == avant, "le rafraichissement a vide l'index lexical"


def test_une_page_modifiee_sort_du_lexical(monkeypatch):
    m = _module()
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    _servir(monkeypatch, m, V1)
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    _servir(monkeypatch, m, V2)
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    assert base.lexical("ancien") == 0, "la version retiree reste cherchable en lexical"
    assert base.lexical("remplace") > 0


def test_une_page_en_echec_ne_retire_rien(monkeypatch):
    m = _module()
    base = _Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    _servir(monkeypatch, m, V1)
    m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)

    def _panne(*a, **k):
        raise OSError("reseau coupe")
    monkeypatch.setattr(m.urllib.request, "urlopen", _panne)
    monkeypatch.setattr(m, "crawl_url", lambda *a, **k: "")
    r = m.ingerer(PAGE, "doc_nr", pause=0, timeout=5)
    assert r["pages_ok"] == 0 and r["anciens_retires"] == 0, r
    assert all(actif == 1 for _c, actif, _s in base.etat(SOURCE)), "un fetch rate ne retire rien"


def test_le_point_d_entree_ecarte_les_agregats_et_le_dit(monkeypatch, capsys):
    m = _module()
    index = ("# Doc\n- [Guide](https://doc.example/guide.md)\n"
             "- [Tout](https://doc.example/llms-full.txt)\n"
             "- [Ctx](https://doc.example/llms-ctx.txt)\n")
    vues = {}
    monkeypatch.setattr(m, "recuperer_index", lambda url, timeout=30: index)

    def _capturer(pages, domain, pause, timeout, paralleles=None):
        vues["pages"] = [u for _t, u in pages]
        return {"pages_total": len(pages)}
    monkeypatch.setattr(m, "ingerer", _capturer)
    monkeypatch.setattr(sys, "argv", ["forge_ingest_llms_txt.py", "--url",
                                      "https://doc.example/llms.txt", "--domain", "doc_nr"])

    assert m.main() == 0
    assert vues["pages"] == ["https://doc.example/guide.md"], vues
    sortie = capsys.readouterr().out
    assert "llms-full.txt" in sortie and "ECARTES" in sortie, "un filtre qui ecarte le DIT"
