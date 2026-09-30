"""NR — le hook post-commit ne balaie plus la grosse base (P0 WAL, 2026-09-23).

Ecrit ROUGE avant correctif.

LE DEFAUT, PROUVE DEUX FOIS. Le piege SYSTEM `Nokido-WalPiege` a capture l'episode
17:55:03 -> 17:59:11 : deux `forge_post_commit` (un par commit) lisaient 19,4 et
10,2 Go, vus pour la derniere fois a 17:58:09 ; le WAL est tombe de 2,27 Go a 2,5 Mo
dans la minute. EXPLAIN QUERY PLAN sur la base reelle : la purge
`source = ? OR source LIKE ?` rend `SCAN rag_chunks` (33 Go) — `LIKE` est insensible
a la casse, donc `idx_rag_source` n'est pas utilisable — et ce, PAR FICHIER commite.
La purge `rag_fts` idem (`SCAN ... INDEX 0:`), et deux COUNT du README a chaque commit.
Un lecteur de cette duree interdit le checkpoint : c'est la famine du WAL.

CE QUE LE NR VERROUILLE, SUR LE CHEMIN REEL. `_index_doctrine` est execute sur une
base temporaire au MEME schema (index `idx_rag_source`, `rag_fts` aux colonnes
UNINDEXED) ; chaque instruction emise est rejouee en EXPLAIN QUERY PLAN. Aucune ne
doit balayer `rag_chunks` en entier, ni `rag_fts` sans contrainte d'index.

`rag_fts` a `chunk_id` et `source` UNINDEXED : on ne peut PAS purger « par id » sans
balayer. La seule voie indexee est MATCH sur `text` ; les ids servent de filtre exact.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

fpc = pytest.importorskip("forge_post_commit")
REL = "docs/temoin.md"


def _base(tmp_path) -> Path:
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL,"
        " domain TEXT DEFAULT 'general', embedding BLOB);"
        "CREATE INDEX idx_rag_source ON rag_chunks(source);"
        "CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED,"
        " domain UNINDEXED);"
    )
    anciens = [("v1", f"{REL}#chunk0", "ancienne doctrine alpha bravo charlie"),
               ("v2", f"{REL}#chunk1", "ancienne doctrine delta echo foxtrot"),
               ("aut", "docs/autre.md#chunk0", "doctrine voisine qui doit survivre alpha")]
    for cid, src, txt in anciens:
        con.execute("INSERT INTO rag_chunks (id, text, source, domain) VALUES (?,?,?,?)",
                    (cid, txt, src, "doctrine"))
        con.execute("INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?,?,?,?)",
                    (cid, txt, src, "doctrine"))
    con.commit()
    con.close()
    return db


def _executer(tmp_path, monkeypatch):
    """Execute `_index_doctrine` sur la base temoin et rend (db, instructions emises)."""
    db = _base(tmp_path)
    emises: list = []

    class _Enregistreuse(sqlite3.Connection):
        def execute(self, sql, params=(), /):
            emises.append((sql, tuple(params)))
            return super().execute(sql, params)

    vrai_connect = sqlite3.connect
    monkeypatch.setattr(fpc.sqlite3, "connect",
                        lambda *a, **k: vrai_connect(str(db), factory=_Enregistreuse, timeout=5))
    import nokido_agent.app.forge_db_path as dbp
    monkeypatch.setattr(dbp, "db_path", lambda: str(db))
    faux = types.ModuleType("nokido_agent.app.forge_embed_router")
    faux.embed_batch_fast = lambda textes: []  # aucun embedder : jamais de reseau en NR
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_embed_router", faux)

    texte = "# Temoin\n\nNouvelle doctrine golf hotel india, assez longue pour un chunk.\n"
    assert fpc._index_doctrine(ROOT / REL, REL, texte, dry_run=False)
    return db, emises


def _plans(db, emises):
    con = sqlite3.connect(db)
    out = []
    for sql, params in emises:
        s = sql.strip().upper()
        if not s.startswith(("SELECT", "DELETE", "UPDATE")):
            continue
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
        out.append((" ".join(sql.split())[:120], plan))
    con.close()
    return out


def test_aucune_instruction_ne_balaie_rag_chunks(tmp_path, monkeypatch):
    db, emises = _executer(tmp_path, monkeypatch)
    fautives = [(s, p) for s, p in _plans(db, emises)
                if any(l.startswith("SCAN rag_chunks") for l in p)]
    assert not fautives, "balayage complet de rag_chunks (33 Go en prod) : %s" % fautives


def test_aucune_instruction_ne_balaie_rag_fts_sans_index(tmp_path, monkeypatch):
    """FTS5 : `INDEX 0:` suivi de RIEN = aucune contrainte = table entiere."""
    db, emises = _executer(tmp_path, monkeypatch)
    fautives = [(s, p) for s, p in _plans(db, emises)
                if any(l.startswith("SCAN rag_fts") and l.rstrip().endswith("INDEX 0:") for l in p)]
    assert not fautives, "balayage complet de rag_fts : %s" % fautives


def test_la_purge_reste_exacte(tmp_path, monkeypatch):
    """Le correctif change le CHEMIN d'acces, pas le resultat : l'ancienne version du
    fichier disparait des deux tables, la voisine survit, la nouvelle est la."""
    db, _ = _executer(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    ids = {r[0] for r in con.execute("SELECT id FROM rag_chunks")}
    fts = {r[0] for r in con.execute("SELECT chunk_id FROM rag_fts")}
    sources = {r[0] for r in con.execute("SELECT source FROM rag_chunks")}
    con.close()
    assert "v1" not in ids and "v2" not in ids, ids
    assert "v1" not in fts and "v2" not in fts, "ligne FTS obsolete restee : %s" % fts
    assert "aut" in ids and "aut" in fts, "la doctrine voisine a ete emportee"
    assert any(s.startswith(REL + "#chunk") for s in sources), "la nouvelle version manque"


# ── Option 1 validee par l'owner (2026-09-23) : le rejeu de 24f6b1c5e a montre que le
# hook restait un lecteur long (4,9 Go en 90 s) — via `guarded_change` -> `_light_health`
# -> `forge_health_diagnostic.audit_rag_chunks`, l'instrument deja accuse le 04/09.
# Le hook passe a `guarded_change` un `post_check` de liveness (parametre PREVU par
# l'interface) : meme propriete critique — tables critiques non videes — sans balayage.

def _base_critique(tmp_path, vide=None, lignes=50_000) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "crit.db"
    con = sqlite3.connect(db)
    for t in ("rag_chunks", "biblio_raw", "forge_entities"):
        con.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, x TEXT)")
        if t != vide:
            con.executemany(f"INSERT INTO {t} (x) VALUES (?)", [("v" * 40,)] * lignes)
    con.commit()
    con.close()
    return db


def _vie(monkeypatch, db):
    if not hasattr(fpc, "_vie_legere"):
        pytest.fail("_vie_legere absent : le hook passe encore par audit_rag_chunks")
    import nokido_agent.app.forge_guarded_change as gc
    monkeypatch.setattr(gc, "_DB", db)
    return fpc._vie_legere()


def test_le_post_check_du_hook_voit_une_table_critique_videe(tmp_path, monkeypatch):
    """Condition owner n°2 : la liveness verifie TOUJOURS que les tables critiques ne
    sont pas vides — alleger le controle ne doit pas le rendre aveugle."""
    assert _vie(monkeypatch, _base_critique(tmp_path))["ok"] is True
    r = _vie(monkeypatch, _base_critique(tmp_path / "v", vide="rag_chunks"))
    assert r["ok"] is False and "rag_chunks" in r["reason"], r


def test_le_post_check_du_hook_est_borne(tmp_path, monkeypatch):
    """Condition owner n°3, mesure equivalente a EXPLAIN : `SELECT 1 ... LIMIT 1` montre
    un plan SCAN mais s'arrete a la premiere ligne. On compte les instructions de la VM
    SQLite sur 3 tables de 50 000 lignes : elles doivent rester bornees, pas lineaires."""
    db = _base_critique(tmp_path)
    pas = {"n": 0}
    vrai_connect = sqlite3.connect

    def connect_compte(*a, **k):
        con = vrai_connect(*a, **k)
        con.set_progress_handler(lambda: pas.__setitem__("n", pas["n"] + 1) or 0, 100)
        return con

    monkeypatch.setattr(fpc.sqlite3, "connect", connect_compte)
    assert _vie(monkeypatch, db)["ok"] is True
    assert pas["n"] < 50, "post_check lineaire en taille de table : %d x 100 instructions" % pas["n"]


def test_le_hook_n_appelle_plus_audit_rag_chunks(tmp_path, monkeypatch):
    """Condition owner n°1, sur le chemin REEL : `guarded_change` tel que le hook
    l'appelle ne doit plus atteindre `audit_rag_chunks`."""
    import nokido_agent.app.forge_guarded_change as gc
    import nokido_agent.app.forge_health_diagnostic as hd

    appels = []
    monkeypatch.setattr(hd, "audit_rag_chunks", lambda *a, **k: appels.append(1) or {})
    monkeypatch.setattr(gc, "_DB", _base_critique(tmp_path))
    src = Path(fpc.__file__).read_text(encoding="utf-8", errors="replace")
    main = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    appel_gc = [n for n in ast.walk(main) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "guarded_change"]
    assert appel_gc, "main() n'appelle plus guarded_change : le garde a disparu"
    kw = {k.arg: ast.unparse(k.value) for k in appel_gc[0].keywords}
    assert kw.get("post_check") == "_vie_legere", "le hook ne passe pas son post_check : %s" % kw
    with gc.guarded_change("nr", db_snapshot=False, post_check=fpc._vie_legere) as res:
        pass
    assert not appels, "audit_rag_chunks encore appele depuis le chemin du hook"
    assert not res.regressed, res.reason


def test_les_comptages_du_readme_sortent_du_chemin_de_chaque_commit():
    """Deux COUNT sur rag_chunks = deux balayages a CHAQUE commit. `main()` ne doit plus
    appeler `update_readme_stats` sans demande explicite."""
    src = Path(fpc.__file__).read_text(encoding="utf-8", errors="replace")
    main = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    appels_nus = []

    def visite(noeud, garde):
        for enfant in ast.iter_child_nodes(noeud):
            g = garde or (isinstance(enfant, ast.If) and "readme_stats" in ast.unparse(enfant.test))
            if isinstance(enfant, ast.Call) and getattr(enfant.func, "id", "") == "update_readme_stats" and not garde:
                appels_nus.append(enfant.lineno)
            visite(enfant, g)

    visite(main, False)
    assert not appels_nus, "update_readme_stats appele a chaque commit (lignes %s)" % appels_nus
