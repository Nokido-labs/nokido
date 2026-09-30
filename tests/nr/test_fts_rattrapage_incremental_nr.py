"""Non-regression : completer l'index lexical du moteur SANS verrou long, et savoir s'arreter.

Defaut mesure le 2026-09-01. `rag_chunks_fts` -- l'index qu'interroge
`forge_rag_engine._lexical()` -- accusait 702 180 manquants sur 2 030 594 lignes, soit
toute la veille recemment ingeree. Ces chunks n'ayant pas non plus de vecteur, ils
n'etaient atteignables par AUCUN des deux etages de la recherche hybride. Le seul remede
existant est le rebuild complet, arme uniquement en phase NREM3 -- laquelle n'avait pas
tire depuis 3,4 jours.

Le rattrapage incremental comble les manquants par transactions COURTES, donc de jour.
Ces tests portent sur l'EFFET, pas sur les compteurs :

  1. un chunk absent de l'index devient RETROUVABLE par MATCH (un compteur qui monte
     ne prouve pas qu'on peut chercher le texte) ;
  2. l'ecart tombe a zero et le verdict le DIT ;
  3. une ingestion qui demarre EN COURS DE ROUTE arrete le rattrapage -- la garde est
     re-consultee a chaque lot, pas seulement au depart (une source a ete perdue le
     2026-07-25 par un rebuild lance pendant une ingestion) ;
  4. `--dry-run` ne modifie RIEN.

Zero service externe : base SQLite jetable en tmp_path, `open_writer` detourne.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (doublure) (l.71)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_db_path  # noqa: E402
import forge_fts_repair as repair  # noqa: E402

TEXTES = [
    "PlansTab autonomous plan execution ownpilot",
    "litellm router provider fallback",
    "bge m3 embedding vectorisation lexicale",
]


def _base(tmp_path: Path, n: int = 60, indexer: int = 10) -> Path:
    """Base jetable : n chunks, dont seuls les `indexer` premiers sont indexes."""
    chemin = tmp_path / "embeddings.db"
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
                 "source TEXT, domain TEXT)")
    conn.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, "
                 "content='rag_chunks', content_rowid='rowid')")
    for i in range(n):
        conn.execute("INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
                     (f"c{i}", TEXTES[i % len(TEXTES)] + f" chunk{i}",
                      f"src/{i}.py", "veille_code"))
    conn.commit()
    # Seuls les premiers entrent dans l'index : on fabrique la derive a reparer.
    conn.execute("INSERT INTO rag_chunks_fts(rowid, text, source, domain) "
                 "SELECT rowid, text, source, domain FROM rag_chunks WHERE rowid <= ?",
                 (indexer,))
    conn.commit()
    conn.close()
    return chemin


def _brancher(monkeypatch, chemin: Path):
    monkeypatch.setattr(forge_db_path, "open_writer",
                        lambda timeout=30.0: sqlite3.connect(chemin, timeout=timeout,
                                                             isolation_level=None))
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(chemin))
    monkeypatch.setattr(repair, "ingestion_active", lambda: [])


def _match(chemin: Path, terme: str) -> int:
    conn = sqlite3.connect(chemin)
    try:
        return conn.execute("SELECT count(*) FROM rag_chunks_fts "
                            "WHERE rag_chunks_fts MATCH ?", (terme,)).fetchone()[0]
    finally:
        conn.close()


def test_un_chunk_non_indexe_devient_retrouvable(monkeypatch, tmp_path):
    """L'effet, c'est de pouvoir CHERCHER le texte -- pas qu'un compteur monte."""
    chemin = _base(tmp_path)
    _brancher(monkeypatch, chemin)
    assert _match(chemin, "chunk55") == 0, "temoin mal construit : deja indexe"

    res = repair.rattraper_incremental(taille_lot=7, budget_s=60.0, journal=lambda *_: None)

    assert _match(chemin, "chunk55") == 1
    assert res["ecart_apres"] == 0
    assert res["verdict"] == "RESORBE"
    assert res["inseres"] == 50


def test_ingestion_en_cours_de_route_arrete_le_rattrapage(monkeypatch, tmp_path):
    """La garde est re-consultee A CHAQUE LOT : un controle d'entree ne suffit pas."""
    chemin = _base(tmp_path)
    _brancher(monkeypatch, chemin)
    appels = {"n": 0}

    def _ingestion():
        appels["n"] += 1
        return [] if appels["n"] <= 2 else ["veille_run(pid 999)"]

    monkeypatch.setattr(repair, "ingestion_active", _ingestion)
    res = repair.rattraper_incremental(taille_lot=7, budget_s=60.0, journal=lambda *_: None)

    assert res["arret"].startswith("ingestion demarree")
    assert res["lots"] == 2, "le rattrapage a continue malgre l'ingestion"
    assert res["ecart_apres"] > 0
    assert res["verdict"] == "PARTIEL"


def test_dry_run_n_ecrit_rien(monkeypatch, tmp_path):
    chemin = _base(tmp_path)
    _brancher(monkeypatch, chemin)

    res = repair.rattraper_incremental(taille_lot=7, budget_s=60.0, dry_run=True,
                                       journal=lambda *_: None)

    assert res["dry_run"] is True
    assert res["ecart_apres"] == res["ecart_avant"] == 50
    assert _match(chemin, "chunk55") == 0, "le dry-run a ecrit dans l'index"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
