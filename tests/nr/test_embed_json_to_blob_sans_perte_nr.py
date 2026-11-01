"""NR conversion A (GO owner 29/10, « pas de perte de donnees utiles ») : tools/forge_embed_json_to_blob.py convertit
les vecteurs JSON (TEXT ET BLOB) en float32 binaire SANS balayage (plages de rowid), en verifiant chaque ligne, sans
toucher au JSON illisible, sans supprimer de trigger, en respectant forge_tier_guard (refus COMPTES), et en ne
laissant dans qdrant_sync_pending que les entrees qui y etaient deja (le vecteur ne change pas)."""
import importlib.util
import json
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    nom = "forge_embed_json_to_blob_nr"
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "forge_embed_json_to_blob.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def _base(tmp_path):
    db = tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, meta TEXT, embedding BLOB);
    CREATE TABLE rag_snapshots (chunk_id TEXT, op TEXT);
    CREATE TABLE qdrant_sync_pending (chunk_id TEXT PRIMARY KEY, queued_at INTEGER);
    CREATE TRIGGER auto_snapshot_before_update BEFORE UPDATE OF text, source, domain, meta ON rag_chunks
      BEGIN INSERT INTO rag_snapshots VALUES (OLD.id, 'update'); END;
    CREATE TRIGGER forge_tier_guard BEFORE UPDATE OF embedding ON rag_chunks FOR EACH ROW
      WHEN NEW.embedding IS NOT NULL AND NEW.domain = 'sdk_gitingest' BEGIN SELECT RAISE(IGNORE); END;
    CREATE TRIGGER qdrant_sync_on_embed_update AFTER UPDATE OF embedding ON rag_chunks FOR EACH ROW
      WHEN NEW.embedding IS NOT NULL BEGIN INSERT OR IGNORE INTO qdrant_sync_pending VALUES (NEW.id, 0); END;
    """)
    v = [0.5, -0.25, 0.125, 1.0]
    rows = [("a", "t", "s", "hot", json.dumps(v)),                       # JSON TEXT -> converti
            ("b", "t", "s", "hot", json.dumps(v).encode()),              # JSON BLOB -> converti
            ("c", "t", "s", "hot", struct.pack("4f", *v)),               # deja binaire -> intact
            ("d", "t", "s", "hot", "[0.1, pas du json"),                  # illisible -> intact, compte
            ("e", "t", "s", "sdk_gitingest", json.dumps(v)),             # tier froid -> refuse par la garde, compte
            ("f", "t", "s", "hot", None)]                                # sans vecteur -> intact
    c.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,?)", rows)
    c.execute("INSERT INTO qdrant_sync_pending VALUES ('b', 1)")         # deja en file AVANT : doit rester
    c.commit()
    c.close()
    return db, v


def test_anomalies_journalisees_par_id_dans_un_fichier_frere(tmp_path):
    """29/10 : la passe complete a laisse 3 077 illisibles et 3 refus SANS leur id -- les retrouver aurait demande un
    parcours complet de la base (interdit). Chaque anomalie est journalisee par id + rowid, a cote du journal."""
    m = _mod()
    db, _v = _base(tmp_path)
    m.convertir(db, lot=2, journal=tmp_path / "journal.jsonl")
    lignes = (tmp_path / "journal.jsonl.anomalies.jsonl").read_text(encoding="utf-8").splitlines()
    par_id = {json.loads(x)["id"]: json.loads(x) for x in lignes}
    assert set(par_id) == {"d", "e"}
    assert par_id["d"]["anomalie"] == "ILLISIBLE" and par_id["e"]["anomalie"] == "REFUS_TIER_GUARD"
    assert all(isinstance(x["rowid"], int) for x in par_id.values())


def test_conversion_sans_perte_et_gardes_respectees(tmp_path):
    m = _mod()
    db, v = _base(tmp_path)
    bilan = m.convertir(db, lot=2, journal=tmp_path / "journal.jsonl")
    c = sqlite3.connect(db)
    emb = dict(c.execute("SELECT id, embedding FROM rag_chunks"))
    assert struct.unpack("4f", emb["a"]) == tuple(v) and struct.unpack("4f", emb["b"]) == tuple(v)
    assert emb["d"] == "[0.1, pas du json" and isinstance(emb["e"], str) and emb["f"] is None
    assert bilan["convertis"] == 2 and bilan["illisibles"] == 1 and bilan["refuses_tier_guard"] == 1
    assert bilan["ecart_max"] == 0.0
    assert [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")] == [
        "auto_snapshot_before_update", "forge_tier_guard", "qdrant_sync_on_embed_update"]
    assert sorted(r[0] for r in c.execute("SELECT chunk_id FROM qdrant_sync_pending")) == ["b"]
    assert c.execute("SELECT count(*) FROM rag_snapshots").fetchone()[0] == 0
    lignes = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(x)["id"] for x in lignes} == {"a", "b"}


def test_dry_run_n_ecrit_rien(tmp_path):
    m = _mod()
    db, _ = _base(tmp_path)
    avant = sqlite3.connect(db).execute("SELECT id, embedding FROM rag_chunks ORDER BY id").fetchall()
    bilan = m.convertir(db, lot=2, journal=tmp_path / "j.jsonl", dry_run=True)
    assert bilan["a_convertir"] == 3 and bilan["convertis"] == 0
    assert sqlite3.connect(db).execute("SELECT id, embedding FROM rag_chunks ORDER BY id").fetchall() == avant


def test_aucun_balayage_plan_par_rowid():
    src = (ROOT / "tools" / "forge_embed_json_to_blob.py").read_text(encoding="utf-8")
    assert "typeof(embedding)='text'" not in src.replace(" ", "")
    assert "rowid BETWEEN" in src
