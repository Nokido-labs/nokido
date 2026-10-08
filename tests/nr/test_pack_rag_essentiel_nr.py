"""NR -- le Knowledge Pack ESSENTIEL ne contient que des fragments PROUVES publics (2026-10-07).

Critere : le texte d'un fragment (espaces normalises) se retrouve mot pour mot dans un fichier PUBLIE du dist, lu a
son commit. Ce NR construit un dist et une base jetables et verifie chaque motif d'ecart (non rattache, non prouve,
trop court, vecteur invalide, secret, juge ROUGE, fragment inactif), l'aller-retour export -> import SANS pickle,
le refus de l'ancien format a objets pickle, et le chemin reel (`__main__` + drapeaux).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(90)

RACINE = Path(__file__).resolve().parents[2]
EXPORT = RACINE / "tools" / "forge_knowledge_pack_export.py"
IMPORT = RACINE / "tools" / "forge_knowledge_pack_import.py"
PARA = "Le hub verifie chaque ecriture avant de la laisser partir vers le depot partage."
CODE = "def ouvrir_session(nom):\n    return {'nom': nom, 'etat': 'ouverte'}"
# fausse cle ASSEMBLEE a l'execution : aucun litteral de secret dans la source (le scanner le refuserait, a raison)
CLE = "Exemple de cle a ne jamais publier : " + "sk" + "-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + "0123456789" + " dans la doc."


def _charger(chemin, nom):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(depot, *a):
    subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=nr", "-c", "user.email=nr@example.invalid",
                    "-c", "commit.gpgsign=false", "-C", str(depot), *a], check=True, capture_output=True)


def _vec(graine, dim=1024):
    v = np.random.default_rng(graine).standard_normal(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def monde(tmp_path):
    dist = tmp_path / "dist"
    (dist / "docs").mkdir(parents=True)
    (dist / "tools").mkdir()
    (dist / "docs" / "guide.md").write_text("# Guide\n\n" + PARA.replace(" chaque ", "  chaque\n") + "\n\n" + CLE + "\n",
                                            encoding="utf-8")
    (dist / "tools" / "x.py").write_text(CODE + "\n", encoding="utf-8")
    _git(dist, "init", "-q")
    _git(dist, "add", "-A")
    _git(dist, "commit", "-q", "-m", "init")
    base = tmp_path / "rag.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, embedding BLOB, "
                "active INTEGER)")
    lignes = [
        ("prouve_doc", "docs\\guide.md#chunk0", "nokido_doc", PARA, _vec(1).tobytes(), 1),
        ("prouve_code", "untracked:tools/x.py", "forge_core", CODE, _vec(2).tobytes(), 1),
        ("prive", "docs/guide.md", "nokido_doc", "Note privee de session qui n'existe dans aucun fichier publie.",
         _vec(3).tobytes(), 1),
        ("conv", "conv://session/abc", "nokido_doc", PARA, _vec(4).tobytes(), 1),
        ("court", "docs/guide.md", "nokido_doc", "Le hub", _vec(5).tobytes(), 1),
        ("dim", "docs/guide.md", "nokido_doc", PARA, _vec(6, 10).tobytes(), 1),
        ("secret", "docs/guide.md", "nokido_doc", CLE, _vec(7).tobytes(), 1),
        ("inactif", "docs/guide.md", "nokido_doc", PARA, _vec(8).tobytes(), 0),
        ("hors_domaine", "docs/guide.md", "veille_code", PARA, _vec(9).tobytes(), 1),
        # formats REELS de la base (essai du 2026-10-07) : vecteur en JSON, et blob brut mal aligne
        ("json", "tools/x.py", "doctrine", CODE, "[" + ",".join("%.6f" % x for x in _vec(10)) + "]", 1),
        ("mal_aligne", "docs/guide.md", "doctrine", PARA, _vec(11).tobytes()[:-2], 1),
        # 26 vecteurs de norme infinie dans la base reelle (debordaient en float16) : ecartes, jamais renormalises
        ("enorme", "tools/x.py", "forge_core", CODE, (_vec(12) * 1e30).astype(np.float32).tobytes(), 1),
    ]
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    return dist, base


def test_seuls_les_fragments_prouves_publics_sont_retenus(monde):
    m = _charger(EXPORT, "kpe_nr")
    dist, base = monde
    retenus, cr = m.selectionner(m._lignes(base, m.DOMAINES), m.Dist(dist), lambda chemin, texte: False)
    assert sorted(r[0] for r in retenus) == ["json", "prouve_code", "prouve_doc"]
    assert {r[2] for r in retenus} == {"docs/guide.md", "tools/x.py"}, "la source publiee est le chemin du dist"
    doc = cr["nokido_doc"]
    assert doc["non_prouve"] == 1 and doc["non_rattache"] == 1 and doc["trop_court"] == 1
    assert doc["vecteur_invalide"] == 1 and doc["secret"] == 1
    assert "veille_code" not in cr and doc["lus"] == 6, "inactif et hors domaine ne sont meme pas lus"
    assert cr["doctrine"] == {"lus": 2, "retenus": 1, "vecteur_invalide": 1}, cr["doctrine"]
    assert cr["forge_core"] == {"lus": 2, "retenus": 1, "vecteur_non_norme": 1}, cr["forge_core"]


def test_le_juge_rouge_ecarte_un_fragment_prouve(monde):
    m = _charger(EXPORT, "kpe_nr2")
    dist, base = monde
    retenus, cr = m.selectionner(m._lignes(base, m.DOMAINES), m.Dist(dist), lambda chemin, texte: "hub" in texte)
    assert sorted(r[0] for r in retenus) == ["json", "prouve_code"] and cr["nokido_doc"]["juge_rouge"] == 1


def test_aller_retour_sans_pickle_par_le_point_d_entree(monde, tmp_path):
    dist, base = monde
    sortie = tmp_path / "pack.npz"
    r = subprocess.run([sys.executable, str(EXPORT), "--dist", str(dist), "--base", str(base), "--version", "9.9.9",
                        "--output", str(sortie)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=80)
    assert r.returncode == 0, r.stdout + r.stderr
    with np.load(sortie, allow_pickle=False) as z:
        assert set(z.files) == {"embeddings", "meta", "texts"} and z["embeddings"].dtype == np.float16
    pack = _charger(IMPORT, "kpi_nr").lire_pack(sortie)
    assert pack["manifest"]["format"] == "nokido-knowledge-pack/2" and pack["manifest"]["license"] == "AGPL-3.0-or-later"
    assert sorted(pack["chunk_ids"]) == ["json", "prouve_code", "prouve_doc"]
    i = pack["chunk_ids"].index("prouve_doc")
    assert pack["texts"][i] == PARA and pack["embeddings"].dtype == np.float32
    assert np.allclose(pack["embeddings"][i], _vec(1), atol=2e-3)


def test_l_ancien_format_a_objets_pickle_est_refuse(tmp_path):
    ancien = tmp_path / "ancien.npz"
    np.savez_compressed(ancien, chunk_ids=np.array(["a"], dtype=object), texts=np.array(["t"], dtype=object),
                        embeddings=np.zeros((1, 1024), np.float32), manifest=np.array(["{}"], dtype=object))
    with pytest.raises(ValueError, match="pickle"):
        _charger(IMPORT, "kpi_nr2").lire_pack(ancien)
