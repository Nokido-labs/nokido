"""NR -- Knowledge Pack PAR SOURCE = PAR LICENCE (decision owner du 2026-10-20).

Mesure du 20/10 (inventaire_reference_par_famille_20261020) : le domaine `reference` est a 98,5 % des docsets
(Docker, NodeJS, Django, Python...), chacun sous SA licence ; le plus gros (Docker) fait ~350 Mo de vecteurs fp16.
Decisions owner : un pack par source, chacun avec sa NOTICE ; tout telecharge par defaut ; GitHub + SourceForge + HF.
Le pack monolithique `.npz` (savez_compressed) est charge EN ENTIER en RAM a l'import et deflate ne gagne rien sur du
float16 : le pack par source est un tar NON compresse dont les vecteurs se lisent en mmap.

Ce qui est garde :
  * le compositeur de release connait le constructeur `rag_pack_source` et ses champs (famille, conditions, preuve) ;
  * un composant tiers redistribue porte famille, licence AFFIRMEE (ni NOASSERTION ni INCONNU), conditions et une
    preuve https : sinon le manifeste est refuse (fail-closed) ;
  * le manifeste reel declare les docsets du lot 1 de l'audit des licences, obligatoires (tout par defaut) ;
  * l'export d'une source : liste blanche (refus de ce qui n'est pas declare redistribuable), memes filtres que le
    pack essentiel (secret, trop court, vecteur), doublons de TEXTE ecartes et comptes, tar = vecteurs.npy (float16,
    mmap) + textes.jsonl.xz + NOTICE.txt + manifest.json, somme sha256 du tar rendue.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import lzma
import sqlite3
import tarfile
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
LOT1 = {"docset:Django": "BSD-3-Clause", "docset:Flask": "BSD-3-Clause", "docset:Python": "PSF-2.0",
        "docset:JavaScript": "CC-BY-SA-2.5"}


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ra():
    return _charger("tools/forge_release_assets.py", "release_assets_source_nr")


def _composant(**modif):
    c = {"id": "knowledge-docset-flask", "description": "documentation Flask", "source": "construit",
         "construit": "rag_pack_source", "sha256": "au_build", "taille": "au_build", "licence": "BSD-3-Clause",
         "obligatoire": True, "famille": "docset:Flask",
         "conditions": "attribution, notice de copyright et clause de non-garantie conservees",
         "preuve": "https://flask.palletsprojects.com/en/latest/license/"}
    c.update(modif)
    return {k: v for k, v in c.items() if v is not None}


def test_le_compositeur_connait_le_constructeur_par_source():
    ra = _ra()
    gabarit = ra.BUILDERS["rag_pack_source"]
    assert "{famille}" in gabarit and "{version}" in gabarit and gabarit.endswith(".tar")
    assert {"famille", "conditions", "preuve"} <= ra._CLES_COMPOSANT


@pytest.mark.parametrize("modif, motif", [
    ({}, None),
    ({"preuve": None}, "preuve"),
    ({"preuve": "http://exemple.org/licence"}, "preuve"),
    ({"famille": None}, "famille"),
    ({"conditions": None}, "conditions"),
    ({"licence": "NOASSERTION"}, "licence"),
    ({"licence": "INCONNU"}, "licence"),
])
def test_un_pack_tiers_porte_famille_licence_conditions_et_preuve(modif, motif):
    erreurs, avert = [], []
    _ra()._valider_composant(_composant(**modif), "t", RACINE, erreurs, avert)
    if motif is None:
        assert erreurs == [], erreurs
    else:
        # l'erreur doit NOMMER le champ fautif, pas seulement le citer dans un refus de schema (faux vert du RED)
        assert any(motif in e and "hors schema" not in e for e in erreurs), erreurs


def test_le_manifeste_reel_declare_le_lot1_audite_et_se_valide():
    v = _ra().valider_manifeste()
    assert v["ok"], v["erreurs"]
    familles = {c["famille"]: c for c in v["packs"]["knowledge"]["composants"]
                if c.get("construit") == "rag_pack_source"}
    for f, lic in LOT1.items():
        assert f in familles, "%s absent du manifeste" % f
        assert familles[f]["licence"] == lic and familles[f]["preuve"].startswith("https://")
        assert familles[f]["obligatoire"] is True, "owner 20/10 : tout est telecharge par defaut"
    assert not {"claude_docs", "claude_code_docs"} & set(familles), "non redistribuable"


def _vec(i):
    v = np.zeros(1024, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


def _base(tmp_path, lignes):
    chemin = tmp_path / "rag.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    return chemin


TEXTE = "Flask est un micro-cadre web ecrit en Python ; documentation de reference, section "


def test_export_d_une_source_en_tar_mmap_avec_notice_et_doublons_comptes(tmp_path):
    m = _charger("tools/forge_knowledge_pack_export.py", "export_source_nr")
    secret = "jeton " + "sk" + "-" + "a" * 24 + " dans un exemple de la documentation Flask, a ne pas livrer"
    base = _base(tmp_path, [
        ("f1", "docset:Flask#Quickstart", "reference", TEXTE + "un", _vec(1), 1),
        ("f2", "docset:Flask#Quickstart", "reference", TEXTE + "un", _vec(2), 1),
        ("f3", "docset:Flask#Routing", "reference", TEXTE + "deux", _vec(3), 1),
        ("f4", "docset:Flask#Secrets", "reference", secret, _vec(4), 1),
        ("f5", "docset:Flask#Court", "reference", "court", _vec(5), 1),
        ("f6", "docset:Flask#Inactif", "reference", TEXTE + "trois", _vec(6), 0),
        ("d1", "docset:Django#Intro", "reference", TEXTE + "django", _vec(7), 1),
    ])
    st = m.exporter_source(base, _composant(), tmp_path / "out", "9.9.9")
    assert st["retenus"] == 2 and st["doublons"] == 1, st
    assert st["ecartes"]["secret"] == 1 and st["ecartes"]["trop_court"] == 1, st
    assert m.slug_famille("docset:Flask") == "docset-flask"
    tar = Path(st["out_path"])
    assert tar.name == _ra().BUILDERS["rag_pack_source"].format(famille="docset-flask", version="9.9.9")
    assert st["sha256"] == hashlib.sha256(tar.read_bytes()).hexdigest()
    with tarfile.open(tar) as t:
        assert sorted(t.getnames()) == ["NOTICE.txt", "manifest.json", "textes.jsonl.xz", "vecteurs.npy"]
        t.extractall(tmp_path / "x", filter="data")
    x = tmp_path / "x"
    vec = np.load(x / "vecteurs.npy", mmap_mode="r")
    assert vec.shape == (2, 1024) and vec.dtype == np.float16
    with lzma.open(x / "textes.jsonl.xz", "rt", encoding="utf-8") as fh:
        docs = [json.loads(l) for l in fh if l.strip()]
    assert [d["id"] for d in docs] == ["f1", "f3"] and all(d["source"].startswith("docset:Flask") for d in docs)
    notice = (x / "NOTICE.txt").read_text(encoding="utf-8")
    assert "BSD-3-Clause" in notice and "https://flask.palletsprojects.com" in notice and "attribution" in notice
    man = json.loads((x / "manifest.json").read_text(encoding="utf-8"))
    assert man["format"] == "nokido-pack-source/1" and man["famille"] == "docset:Flask" and man["count"] == 2
    assert man["licence"] == "BSD-3-Clause" and man["dtype"] == "float16" and man["dim"] == 1024


@pytest.mark.parametrize("modif", [{"construit": "rag_pack"}, {"licence": "NOASSERTION"}, {"licence": "INCONNU"},
                                   {"preuve": None}, {"famille": None}])
def test_l_export_refuse_une_source_non_declaree_redistribuable(tmp_path, modif):
    m = _charger("tools/forge_knowledge_pack_export.py", "export_source_refus_nr")
    base = _base(tmp_path, [("f1", "docset:Flask#Quickstart", "reference", TEXTE + "un", _vec(1), 1)])
    with pytest.raises(ValueError):
        m.exporter_source(base, _composant(**modif), tmp_path / "out", "1.0.0")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir()), "rien n'est ecrit"
