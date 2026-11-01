"""NR : forge_retrieval_sweep --couverture (mesure seule, aucune ecriture RAG).

Base temoin + arborescence temporaire : 2 dossiers de veille, un fichier petit
(<2 Ko, ignore), un fichier deja au RAG (source exacte), un jamais ingere.
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "sweep_cov", ROOT / "tools" / "forge_retrieval_sweep.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _monde(tmp_path):
    e = tmp_path / "E"
    (e / "nokido_veille_dumps_v3").mkdir(parents=True)
    (e / "nokido_veille_rsi" / "sous").mkdir(parents=True)
    (e / "autre_dossier").mkdir()
    gros = "x" * 3000
    (e / "nokido_veille_dumps_v3" / "a.md").write_text(gros)
    (e / "nokido_veille_dumps_v3" / "b.md").write_text(gros)
    (e / "nokido_veille_dumps_v3" / "petit.md").write_text("x")
    (e / "nokido_veille_rsi" / "sous" / "c.md").write_text(gros)
    (e / "autre_dossier" / "d.md").write_text(gros)
    (e / "deep-research-report.md").write_text(gros)
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rag_chunks (id INTEGER PRIMARY KEY, source TEXT,"
                " text TEXT)")
    con.execute("CREATE INDEX idx_rag_source ON rag_chunks(source)")
    src = (e / "nokido_veille_dumps_v3" / "a.md").as_posix()
    con.execute("INSERT INTO rag_chunks(source,text) VALUES (?,?)", (src, "t"))
    con.commit()
    con.close()
    return e, db


def test_couverture_par_dossier(tmp_path):
    e, db = _monde(tmp_path)
    r = _mod().couverture_veilles(e, db=db, dir_config=str(e / "nokido_veille_dumps"))
    d = r["dossiers"]
    assert set(d) == {"nokido_veille_dumps_v3", "nokido_veille_rsi", "(racine)"}
    v3 = d["nokido_veille_dumps_v3"]
    assert v3["fichiers"] == 2 and v3["au_rag"] == 1 and v3["jamais_ingeres"] == 1
    assert v3["exemples_jamais_ingeres"][0].endswith("b.md")
    assert d["nokido_veille_rsi"]["fichiers"] == 1
    assert d["(racine)"]["fichiers"] == 1
    assert r["total"] == {"fichiers": 4, "au_rag": 1, "jamais_ingeres": 3}
    # config pointe vers v1 de dumps, pas v3 : l'ecart est dit
    assert r["veille_dumps_dir"]["pointe_vers_v3"] is False


def test_base_illisible_n_est_pas_jamais_ingere(tmp_path):
    e, _ = _monde(tmp_path)
    r = _mod().couverture_veilles(e, db=tmp_path / "absente.db")
    assert r["etat_rag"] == "illisible"
    assert r["total"]["jamais_ingeres"] is None
    assert r["total"]["fichiers"] == 4


def test_lecture_seule_aucune_ecriture(tmp_path):
    e, db = _monde(tmp_path)
    avant = db.read_bytes()
    out = tmp_path / "out.json"
    _mod().couverture_veilles(e, db=db, sortie=out)
    assert db.read_bytes() == avant
    assert json.loads(out.read_text())["total"]["fichiers"] == 4
