"""NR -- un pack par source peut venir d'un AUTRE domaine que `reference` (20/10).

La veille physiologie (OpenStax Anatomy and Physiology 2e, CC BY 4.0) est en base dans le domaine `physiologie`,
vectorisee le 20/10 (vague DeportEmbed de 17 h 05). `exporter_sources` ne lisait QUE le domaine `reference` : un
composant physiologie serait sorti vide, en silence. Un composant porte desormais son `domaine` (defaut `reference`) ;
l'export lit chaque domaine declare (index `domain`, un passage par domaine) et le compositeur de release accepte le
champ.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
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


def _base(tmp_path, lignes):
    chemin = tmp_path / "rag.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    return chemin


def _composant(famille, domaine=None, **modif):
    c = {"id": "knowledge-x", "description": "x", "source": "construit", "construit": "rag_pack_source",
         "sha256": "au_build", "taille": "au_build", "licence": "CC-BY-4.0", "obligatoire": True, "famille": famille,
         "conditions": "attribution conservee", "preuve": "https://openstax.org/license"}
    if domaine is not None:
        c["domaine"] = domaine
    c.update(modif)
    return c


def test_un_composant_d_un_autre_domaine_s_exporte(tmp_path):
    m = _charger("tools/forge_knowledge_pack_export.py", "pack_hors_reference_nr")
    physio = "github:openstax/osbooks-anatomy-physiology"
    base = _base(tmp_path, [
        ("p1", physio + "/modules/m46545/index.cnxml", "physiologie", TEXTE + "un", _vec(1), 1),
        ("f1", "docset:Flask#Quickstart", "reference", "Flask est un micro-cadre web ecrit en Python, section un",
         _vec(2), 1),
    ])
    st = m.exporter_sources(base, [_composant(physio, "physiologie"), _composant("docset:Flask", licence="BSD-3-Clause")],
                            tmp_path / "out", "9.9.9", dry_run=True)
    assert st[physio]["retenus"] == 1, st
    assert st["docset:Flask"]["retenus"] == 1, "le domaine par defaut reste reference : %s" % st


def test_l_export_garde_l_index_domain():
    """Livraison MISTRAL d4980130b... d54955bef (20/10) : `+active=1` reecrit en `active=1` -- sur rag_chunks (46 Go),
    sans le `+` SQLite peut quitter l'index `domain` pour un balayage (piege paye, memoire index_chaud_routeur). La base
    minuscule des NR ne le voit pas : on garde la forme."""
    import inspect
    m = _charger("tools/forge_knowledge_pack_export.py", "pack_hors_reference_index_nr")
    src = inspect.getsource(m.exporter_sources)
    assert "+active=1" in src and " active=1" not in src.replace("+active=1", ""), "index domain detourne"


def test_le_compositeur_accepte_le_domaine_d_un_composant():
    ra = _charger("tools/forge_release_assets.py", "release_hors_reference_nr")
    erreurs, avert = [], []
    ra._valider_composant(_composant("github:openstax/osbooks-anatomy-physiology", "physiologie"), "t", RACINE,
                          erreurs, avert)
    assert erreurs == [], erreurs
