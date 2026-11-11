"""NR Chantier 5 : reparer le rappel [memoire:longue] du hook.

Pannes traitees :
1. Syntax error FTS sur ponctuation (?, .) et masquage de panne en « corpus, pas panne ».
2. Fiches memoire (`memory:*`) presentes dans rag_chunks_fts mais absentes de rag_fts.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.forge_keeper_base as fkb
from app.forge_memoire_active import _longue

try:
    import nokido_agent.app.forge_keeper_base as nk_fkb
except Exception:
    nk_fkb = None


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    db_path = tmp_path / "embeddings.db"
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE rag_chunks (
            id TEXT PRIMARY KEY,
            source TEXT,
            text TEXT,
            domain TEXT
        )
    """)
    con.execute("""
        CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(
            source,
            text,
            content='rag_chunks',
            content_rowid='rowid'
        )
    """)
    con.execute("""
        CREATE VIRTUAL TABLE rag_fts USING fts5(
            source,
            text,
            domain
        )
    """)
    con.commit()
    con.close()

    monkeypatch.setattr(fkb, "_DB", db_path)
    if nk_fkb is not None:
        monkeypatch.setattr(nk_fkb, "_DB", db_path)

    return db_path


def test_phrase_avec_ponctuation_pas_d_erreur(fake_db):
    """Cas 1 : phrase avec ? et . = pas d'erreur FTS5 syntax error."""
    con = sqlite3.connect(str(fake_db))
    # `_longue` exige TOUS les mots sur rag_fts (OR mesure a 1,5-15 s le 5/11) : le texte les porte tous.
    texte = "alors tu apprends des choses ici"
    con.execute("INSERT INTO rag_chunks(rowid, id, source, text, domain) VALUES (1, 'c1', 'docs/test.md', ?, 'docs')", (texte,))
    con.execute("INSERT INTO rag_chunks_fts(rowid, source, text) VALUES (1, 'docs/test.md', ?)", (texte,))
    con.execute("INSERT INTO rag_fts(source, text, domain) VALUES ('docs/test.md', ?, 'docs')", (texte,))
    con.execute("INSERT INTO rag_fts(source, text, domain) VALUES ('docs/test2.md', 'service.test alors en marche', 'docs')")
    con.commit()
    con.close()

    entrees, err = _longue("alors tu apprends des choses ?")
    assert err is None
    assert len(entrees) >= 1
    assert any("apprend" in e["texte"] for e in entrees)

    entrees_pt, err_pt = _longue("service.test alors ?")
    assert err_pt is None


def test_find_erreur_rend_message_echec_jamais_corpus_pas_panne(fake_db, monkeypatch):
    """Cas 2 : find qui rend une erreur = message d'echec, jamais « corpus, pas panne »."""
    err_dict = [{"error": "OperationalError: fts5: syntax error near \"?\""}]
    monkeypatch.setattr(fkb, "find", lambda *a, **k: err_dict)
    monkeypatch.setattr(fkb, "find_fiches", lambda *a, **k: [])
    if nk_fkb is not None:
        monkeypatch.setattr(nk_fkb, "find", lambda *a, **k: err_dict)
        monkeypatch.setattr(nk_fkb, "find_fiches", lambda *a, **k: [])

    entrees, err = _longue("alors tu apprends des choses ?")
    assert entrees == []
    assert err == "rappel lexical en echec (OperationalError)"
    assert "corpus, pas panne" not in (err or "")


def test_interruption_plafond_distinguee_de_syntaxe(fake_db, monkeypatch):
    """Cas 2b : interruption plafond distinguee dans le libelle d'echec."""
    err_dict = [{"error": "OperationalError: interrupted"}]
    monkeypatch.setattr(fkb, "find", lambda *a, **k: err_dict)
    monkeypatch.setattr(fkb, "find_fiches", lambda *a, **k: [])
    if nk_fkb is not None:
        monkeypatch.setattr(nk_fkb, "find", lambda *a, **k: err_dict)
        monkeypatch.setattr(nk_fkb, "find_fiches", lambda *a, **k: [])

    entrees, err = _longue("permissions read write")
    assert entrees == []
    assert err == "rappel lexical en echec (interrompu (plafond))"
    assert "corpus, pas panne" not in (err or "")


def test_fiche_seulement_dans_rag_chunks_fts_trouvee(fake_db):
    """Cas 3 : fiche seulement dans rag_chunks_fts = trouvee."""
    con = sqlite3.connect(str(fake_db))
    # Inserer la fiche UNIQUEMENT dans rag_chunks et rag_chunks_fts, PAS dans rag_fts
    con.execute("INSERT INTO rag_chunks(rowid, id, source, text, domain) VALUES (10, 'c_nssm', 'memory:nssm_daemon', 'configuration du service nssm pour Nokido', 'memory')")
    con.execute("INSERT INTO rag_chunks_fts(rowid, source, text) VALUES (10, 'memory:nssm_daemon', 'configuration du service nssm pour Nokido')")
    con.commit()
    con.close()

    entrees, err = _longue("nssm")
    assert err is None
    assert len(entrees) >= 1
    # Doit etre formatee comme une fiche memoire : [[stem]] apercu
    assert entrees[0]["texte"].startswith("[[nssm_daemon]]")


def test_depot_github_jamais_pris_pour_une_fiche(fake_db):
    """Cas 4 : depot github:x/mcp-memory-service = jamais pris pour une fiche."""
    con = sqlite3.connect(str(fake_db))
    con.execute("INSERT INTO rag_chunks(rowid, id, source, text, domain) VALUES (20, 'c_gh', 'github:x/mcp-memory-service', 'un service tiers de memoire externe', 'sdk_github')")
    con.execute("INSERT INTO rag_chunks_fts(rowid, source, text) VALUES (20, 'github:x/mcp-memory-service', 'un service tiers de memoire externe')")
    con.execute("INSERT INTO rag_fts(source, text, domain) VALUES ('github:x/mcp-memory-service', 'un service tiers de memoire externe', 'sdk_github')")
    con.commit()
    con.close()

    # find_fiches ne doit jamais ramener ce depot
    fiches = fkb.find_fiches("service")
    assert not any(f.get("source", "").startswith("github:") for f in fiches)

    # Et si _longue est appele, il ne doit jamais le formater en [[stem]]
    entrees, err = _longue("service")
    for e in entrees:
        assert not e["texte"].startswith("[[mcp-memory-service]]")
        assert not e["texte"].startswith("[[github:")


def test_fragment_fantome_pas_d_erreur(fake_db):
    """Cas 5 : fragment fantome (ligne fts sans contenu) = pas d'erreur missing row."""
    con = sqlite3.connect(str(fake_db))
    # Inserer dans rag_chunks_fts avec un rowid fantome SANS ligne correspondante dans rag_chunks
    con.execute("INSERT INTO rag_chunks_fts(rowid, source, text) VALUES (9999, 'memory:phantom_fiche', 'fragment fantome sans ligne rag_chunks')")
    con.commit()
    con.close()

    # Ne doit pas lever OperationalError missing row
    res = fkb.find_fiches("fantome")
    assert isinstance(res, list)
    # L'entree fantome n'est pas retournee car absente de rag_chunks
    assert res == []

    entrees, err = _longue("fantome")
    # Pas de crash ni d'erreur de base
    assert err == "aucun rappel sur ces termes (corpus, pas panne)"


def test_aucun_resultat_reel_corpus_pas_panne(fake_db):
    """Cas 6 : aucun resultat reel = bien « corpus, pas panne »."""
    entrees, err = _longue("terme_completement_inconnu_introuvable")
    assert entrees == []
    assert err == "aucun rappel sur ces termes (corpus, pas panne)"
