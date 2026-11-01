"""NR -- l'ecrivain STATS du README mesure de facon BORNEE et dit son echec (P1_readme_affirmations_verifiees_ci).

Reste de l'item (19/10) : « ecrivain STATS (tools/forge_post_commit.update_readme_stats, fige depuis le 23/09, COUNT
sur rag_chunks 46 Go) reecrit par MESURE bornee ». Lu le 21/10 : deux balayages complets (`COUNT(*)` puis
`length(embedding)` sur chaque ligne) ; `timeout=5` ne borne que l'attente du verrou, pas la requete ; et
`except Exception: return` -- une mesure ratee se tait, d'ou des chiffres figes sans que personne le sache.
(L'item disait aussi « a chaque commit » : PERIME, l'appel est derriere `--readme-stats` depuis une correction anterieure.)

Contrats :
  1. aucune requete `COUNT(` sur rag_chunks : le volume se lit par `MAX(rowid)` (O(log n)) et s'ecrit `rag_chunks≈N` ;
     les embeddings, sans mesure bornee connue, s'ecrivent `embeddings=non_mesure` -- jamais un balayage ;
  2. la fonction rend {etat: ECRIT | DRY | ILLISIBLE, ...} ; base illisible -> ILLISIBLE, motif journalise en
     WARNING, README INCHANGE (une absence de mesure n'efface pas la derniere mesure, et elle se DIT).
"""
import logging
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_post_commit as M  # noqa: E402


def _base(tmp_path, n=7):
    db = tmp_path / "rag.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, embedding BLOB)")
        c.executemany("INSERT INTO rag_chunks VALUES (?, ?, ?)", [("k%d" % i, "t", b"x" * 20) for i in range(n)])
    return db


def test_mesure_bornee_sans_count(tmp_path, monkeypatch):
    db = _base(tmp_path)
    (tmp_path / "README.md").write_text("# Nokido\n\n<!-- STATS:old:2026-09-23 modules=1 -->\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "forge_a.py").write_text("", encoding="utf-8")
    vues = []
    vrai_connect = sqlite3.connect

    def connect(*a, **kw):
        c = vrai_connect(*a, **kw)
        c.set_trace_callback(vues.append)
        return c

    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "DB", db)
    monkeypatch.setattr(M, "_get_commit_sha", lambda: "abc1234")
    monkeypatch.setattr(M.sqlite3, "connect", connect)
    r = M.update_readme_stats()
    assert r["etat"] == "ECRIT"
    assert not [q for q in vues if "COUNT(" in q.upper()], vues
    texte = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "rag_chunks≈7" in texte and "embeddings=non_mesure" in texte and "modules=1" in texte
    assert "STATS:old" not in texte


def test_base_illisible_le_dit_et_ne_touche_pas_au_readme(tmp_path, monkeypatch, caplog):
    avant = "# Nokido\n\n<!-- STATS:old:2026-09-23 modules=1 -->\n"
    (tmp_path / "README.md").write_text(avant, encoding="utf-8")
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "DB", tmp_path / "absente" / "rag.db")
    monkeypatch.setattr(M, "_get_commit_sha", lambda: "abc1234")
    with caplog.at_level(logging.WARNING):
        r = M.update_readme_stats()
    assert r["etat"] == "ILLISIBLE"
    assert any("ILLISIBLE" in rec.getMessage() for rec in caplog.records)
    # 24/10 : l'illisibilite s'ECRIT dans la zone stats (jamais 0, jamais la vieille mesure presentee comme fraiche)
    apres = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "ILLISIBLE" in apres and "rag_chunks≈0" not in apres and apres.startswith("# Nokido")
