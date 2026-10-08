"""NR -- sur machine VIERGE, l'amorcage cree la base et le Knowledge Pack s'y importe (2026-10-07).

Paye au test d'installation sur runners GitHub : aucune etape du chemin documente ne creait rag_chunks (Linux « base
absente », Windows fichier vide), et l'import du pack mourait sur « Table rag_chunks missing ». forge_db_bootstrap
applique desormais seed/schema_base.sql (copie de la base de reference). Ce NR garde : creation sur dossier vide,
rejouabilite, mecanismes du poste ecartes (snapshots, qdrant), import d'un pack au format 2, index plein texte
alimente par les triggers, colonnes calculees. Le chemin reel est emprunte : main() de l'amorcage par sys.argv.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _amorcer(tmp_path, monkeypatch):
    boot = _charger("tools/forge_db_bootstrap.py", "boot_nr")
    graines = tmp_path / "seed"
    graines.mkdir()
    db = tmp_path / "RAG" / "embeddings.db"
    monkeypatch.setattr(boot, "DB", db)
    monkeypatch.setattr(sys, "argv", ["forge_db_bootstrap.py", "--seed-dir", str(graines)])
    return boot, db


def _objets(db):
    con = sqlite3.connect(db)
    try:
        return {(t, n) for t, n in con.execute("SELECT type, name FROM sqlite_master")}
    finally:
        con.close()


def test_l_amorcage_cree_la_base_et_son_schema_sur_dossier_vide(tmp_path, monkeypatch):
    boot, db = _amorcer(tmp_path, monkeypatch)
    assert not db.exists()
    assert boot.main() == 0
    o = _objets(db)
    for t in ("rag_chunks", "rag_fts", "rag_chunks_fts", "biblio_raw", "biblio_topics", "forge_entities",
              "system_rules", "trajectories"):
        assert ("table", t) in o, t
    for trig in ("rag_chunks_fts_ai", "rag_chunks_fts_ad", "rag_chunks_fts_au", "rag_chunks_fts_bi", "forge_tier_guard"):
        assert ("trigger", trig) in o, trig
    assert not any(n.startswith(("auto_snapshot", "qdrant_sync")) for _, n in o), (
        "les mecanismes du poste de reference exigent des tables absentes d'une machine neuve")
    assert boot.main() == 0, "l'amorcage se rejoue sans risque (IF NOT EXISTS)"


def test_le_pack_s_importe_et_l_index_plein_texte_suit(tmp_path, monkeypatch):
    boot, db = _amorcer(tmp_path, monkeypatch)
    assert boot.main() == 0
    exp = _charger("tools/forge_knowledge_pack_export.py", "kpe_boot_nr")
    imp = _charger("tools/forge_knowledge_pack_import.py", "kpi_boot_nr")
    v = np.random.default_rng(3).standard_normal(1024).astype(np.float32)
    v /= np.linalg.norm(v)
    pack = tmp_path / "pack.npz"
    texte = "Le hub verifie chaque ecriture gouvernee avant le depot partage."
    exp.ecrire_pack(pack, [("c1", texte, "tools/forge_x.py", "forge_core", v)],
                    {"format": exp.FORMAT, "count": 1, "dim": 1024})
    monkeypatch.setattr(imp, "DB", db)
    stats = imp.import_pack(pack)
    assert stats["inserted"] == 1 and stats["errors"] == 0, stats
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT origin, ext FROM rag_chunks WHERE id='c1'").fetchone() == ("laforge-code", "py")
        assert con.execute("SELECT count(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH 'gouvernee'").fetchone()[0] == 1
        assert con.execute("SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH 'gouvernee'").fetchall() == [("c1",)], (
            "rag_fts (lu par /api/rag/stream du hub) doit suivre l'import, regle d'or")
    finally:
        con.close()
    # ecrasement (--overwrite) : l'entree lexicale suit le NOUVEAU texte, via purger_fts (jamais une purge par balayage)
    exp.ecrire_pack(pack, [("c1", "Texte remplace par une nouvelle version publiee.", "tools/forge_x.py", "forge_core", v)],
                    {"format": exp.FORMAT, "count": 1, "dim": 1024})
    stats = imp.import_pack(pack, overwrite_existing=True)
    assert stats["updated_embedding"] == 1 and stats["errors"] == 0 and not stats.get("rag_fts_laissees"), stats
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT count(*) FROM rag_fts WHERE rag_fts MATCH 'gouvernee'").fetchone()[0] == 0
        assert con.execute("SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH 'remplace'").fetchall() == [("c1",)]
    finally:
        con.close()


def test_doctor_connait_les_emplacements_d_installation():
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
    from app import forge_install_prerequis as P  # meme forme que test_prerequis_surface_complete_nr
    usuels = {e["cle"]: e.get("chemins_usuels", ()) for e in P.PREREQUIS}
    assert any(c.replace("\\", "/").endswith("runtime/llama/llama-server") for c in usuels["llama_server"])
    assert any(c.replace("\\", "/").endswith(".deno/bin/deno.exe") for c in usuels["deno"])
    assert json.dumps(sorted(P.PROFILS["dev"]["prerequis"])) == json.dumps(["deno", "git", "llama_server", "python"])
