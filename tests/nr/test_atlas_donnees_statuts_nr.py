"""NR — atlas des donnees : statuts DISTINCTS par magasin, sur bases temporaires."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("census_atlas", ROOT / "tools" / "forge_savoir_census.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _base(p, index=True):
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, source TEXT)")
    if index:
        c.execute("CREATE INDEX ix ON t(source)")
    c.execute("INSERT INTO t(source) VALUES('a')")
    c.commit()
    c.close()


def _decl(p):
    return {"nom": "x", "chemin": str(p), "declare_par": "test", "requete": ("t", "source")}


def test_saine(tmp_path):
    p = tmp_path / "ok.db"
    _base(p)
    f = C.evaluer_magasin(_decl(p))
    assert f["declare"].startswith("declare")
    assert f["localise"] == "present"
    assert f["ouvert"].startswith("oui")
    assert f["requete"] == "verifiee (index)"
    assert f["integrite"] == "integrite controlee: ok"
    assert f["fraicheur"].startswith("frais")
    assert f["lacunes"] == []


def test_absente(tmp_path):
    f = C.evaluer_magasin(_decl(tmp_path / "nope.db"))
    assert f["localise"] == "absent"
    assert f["integrite"] == "non controlee" and f["requete"] == "non verifiee"
    assert any("absent" in x for x in f["lacunes"])


def test_illisible(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"ceci n'est pas une base sqlite" * 50)
    f = C.evaluer_magasin(_decl(p))
    assert f["localise"] == "present"
    assert f["ouvert"].startswith("NON")
    assert "non controlee" in f["integrite"]
    assert f["lacunes"]


def test_sans_index(tmp_path):
    p = tmp_path / "noix.db"
    _base(p, index=False)
    f = C.evaluer_magasin(_decl(p))
    assert f["requete"].startswith("SANS INDEX")
    assert any("SANS INDEX" in x for x in f["lacunes"])
    assert f["integrite"] == "integrite controlee: ok"  # statuts non fusionnes


def test_gros_fichier_pas_de_controle(tmp_path, monkeypatch):
    p = tmp_path / "gros.db"
    _base(p)
    monkeypatch.setattr(C, "SEUIL_INTEGRITE_OCTETS", 1)
    f = C.evaluer_magasin(_decl(p))
    assert f["integrite"] == C.NON_CONTROLEE_GROS
    assert "fenetre de maintenance" in f["integrite"]


def test_lecture_seule_et_aucun_index_cree(tmp_path):
    p = tmp_path / "ro.db"
    _base(p, index=False)
    avant = (p.stat().st_mtime_ns, p.read_bytes())
    C.evaluer_magasin(_decl(p))
    assert (p.stat().st_mtime_ns, p.read_bytes()) == avant
    c = sqlite3.connect(str(p))
    assert [r[0] for r in c.execute("select name from sqlite_master where type='index'")] == []
    c.close()


def test_perime(tmp_path):
    p = tmp_path / "old.db"
    _base(p)
    f = C.evaluer_magasin(_decl(p), maintenant=p.stat().st_mtime + 90 * 86400)
    assert f["fraicheur"].startswith("PERIME")
    assert any("fraicheur" in x for x in f["lacunes"])


def test_atlas_liste_les_lacunes(tmp_path):
    a = C.atlas_donnees([_decl(tmp_path / "absent.db")])
    assert len(a["magasins"]) == 1 and a["lacunes"]


def test_pas_de_integrity_check_ni_like_dans_atlas():
    src = (ROOT / "tools" / "forge_savoir_census.py").read_text(encoding="utf-8")
    bloc = src[src.index("ATLAS DES DONNEES"):src.index("def main(")]
    code = "\n".join(x for x in bloc.splitlines() if not x.lstrip().startswith("#"))
    assert "PRAGMA integrity_check" not in code
    assert " LIKE " not in code.upper()
