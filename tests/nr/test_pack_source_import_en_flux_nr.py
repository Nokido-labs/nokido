"""NR -- un pack par source (tar `nokido-pack-source/1`) s'importe, EN FLUX, par le meme chemin d'ecriture (20/10).

Mesure du 20/10 : `forge_knowledge_pack_import` ne lisait que l'ancien format NPZ (`nokido-knowledge-pack/2`, charge
EN ENTIER en RAM). Les packs par source (decisions owner du 20/10 : un pack par licence, tout telecharge par defaut)
n'avaient AUCUN lecteur : rien ne pouvait les installer. Et le manifeste du tar ne disait pas le domaine des fragments
(physiologie...).

Contrat :
  * l'exporteur ecrit le `domaine` dans le manifeste du tar ;
  * `lire_pack_source(tar)` -> (manifeste, iterateur de (id, source, domaine, texte, vecteur float32)) : un GENERATEUR
    qui lit l'en-tete npy puis les lignes de vecteurs une a une et `textes.jsonl.xz` en flux -- jamais le tableau
    entier en memoire (Docker : ~350 Mo de vecteurs) ; format inconnu = refus ;
  * `import_pack(<tar>)` ecrit par la MEME boucle que le NPZ (rag_chunks + rag_fts, jamais d'ecrasement).
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sqlite3
import tarfile
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
PHYSIO = "github:openstax/osbooks-anatomy-physiology"
TEXTE = "Le systeme respiratoire assure les echanges gazeux ; les chemorecepteurs reglent la ventilation, section "


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _vec(i):
    v = np.zeros(1024, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


def _tar(tmp_path):
    ex = _charger("tools/forge_knowledge_pack_export.py", "pack_flux_export_nr")
    base = tmp_path / "src.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", [
        ("p1", PHYSIO + "/modules/m1/index.cnxml", "physiologie", TEXTE + "un", _vec(1), 1),
        ("p2", PHYSIO + "/modules/m2/index.cnxml", "physiologie", TEXTE + "deux", _vec(2), 1)])
    con.commit()
    con.close()
    comp = {"id": "knowledge-physio", "description": "x", "source": "construit", "construit": "rag_pack_source",
            "sha256": "au_build", "taille": "au_build", "licence": "CC-BY-4.0", "obligatoire": True, "famille": PHYSIO,
            "domaine": "physiologie", "conditions": "attribution OpenStax ; texte modifie",
            "preuve": "https://github.com/openstax/osbooks-anatomy-physiology/blob/b0058a743b/LICENSE"}
    return Path(ex.exporter_sources(base, [comp], tmp_path / "out", "9.9.9")[PHYSIO]["out_path"])


def _destination(tmp_path):
    dst = tmp_path / "dst.db"
    con = sqlite3.connect(dst)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, embedding BLOB)")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    con.commit()
    con.close()
    return dst


def test_le_manifeste_du_tar_dit_le_domaine(tmp_path):
    with tarfile.open(_tar(tmp_path)) as t:
        man = json.loads(t.extractfile("manifest.json").read().decode("utf-8"))
    assert man["domaine"] == "physiologie", man


def test_la_lecture_d_un_pack_source_est_un_flux(tmp_path):
    im = _charger("tools/forge_knowledge_pack_import.py", "pack_flux_import_nr")
    man, lignes = im.lire_pack_source(_tar(tmp_path))
    assert man["famille"] == PHYSIO and inspect.isgenerator(lignes), type(lignes)
    rangs = list(lignes)
    assert [r[0] for r in rangs] == ["p1", "p2"] and all(r[2] == "physiologie" for r in rangs), rangs
    v = rangs[1][4]
    assert v.dtype == np.float32 and v.shape == (1024,) and int(np.argmax(v)) == 2


def test_un_tar_au_format_inconnu_est_refuse(tmp_path):
    im = _charger("tools/forge_knowledge_pack_import.py", "pack_flux_refus_nr")
    faux = tmp_path / "faux.tar"
    with tarfile.open(faux, "w") as t:
        octets = json.dumps({"format": "autre/9"}).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(octets)
        import io
        t.addfile(info, io.BytesIO(octets))
    with pytest.raises(ValueError):
        man, lignes = im.lire_pack_source(faux)
        list(lignes)


def test_l_import_d_un_tar_ecrit_rag_chunks_et_rag_fts(tmp_path, monkeypatch):
    im = _charger("tools/forge_knowledge_pack_import.py", "pack_flux_ecrit_nr")
    tar = _tar(tmp_path)
    dst = _destination(tmp_path)
    monkeypatch.setattr(im, "DB", dst)

    def _sans_hub(*_a, **_k):
        raise OSError("pas de hub dans un NR")

    monkeypatch.setattr(im.urllib.request, "urlopen", _sans_hub)
    st = im.import_pack(tar)
    assert st["inserted"] == 2 and st["errors"] == 0, st
    con = sqlite3.connect(dst)
    rangs = con.execute("SELECT id, domain, embedding FROM rag_chunks ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rangs] == [("p1", "physiologie"), ("p2", "physiologie")]
    assert np.frombuffer(rangs[0][2], dtype=np.float32).shape == (1024,)
    assert con.execute("SELECT count(*) FROM rag_fts").fetchone()[0] == 2
    st2 = im.import_pack(tar)
    assert st2["inserted"] == 0 and st2["skipped_overwrite_forbidden"] == 2, "jamais d'ecrasement par defaut"
