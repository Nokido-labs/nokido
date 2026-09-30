# -*- coding: utf-8 -*-
"""NR — l'autorisation ne doit pas dependre du plus gros fichier concurrent.

CAUSE MESUREE le 2026-09-05, trois chutes du hub en une heure. `access_switches`
-- lue a CHAQUE appel de tool, gate FAIL-CLOSED -- vivait dans `embeddings.db`,
la base de 24,9 Go que le RAG, l'ingestion, le backfill, l'embed daemon et pytest
ecrivent tous. Chaine OBSERVEE, pas deduite :

    verrou sur embeddings.db
      -> GATE_DENIED sur TOUS les tools   (hub vivant, totalement inutilisable)
      -> Unable to connect                 (hub mort, tue par son healthcheck)

Disproportion mesuree : **19 regles / 20 Ko** contre **23,2 Go**.

Ce que ce correctif a de particulier : **il ne depend pas d'identifier qui
verrouille**. SQLite ne nomme jamais le tenant d'un verrou -- un remede qui
l'exigerait ne serait jamais applicable. On coupe la PROPAGATION.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


def _module(monkeypatch, chemin: str | None):
    import importlib

    if chemin is None:
        monkeypatch.delenv("LAFORGE_SWITCHES_DB_PATH", raising=False)
    else:
        monkeypatch.setenv("LAFORGE_SWITCHES_DB_PATH", chemin)
    import forge_access_switches as fas

    return importlib.reload(fas)


def test_sans_la_variable_le_comportement_est_INCHANGE(monkeypatch):
    """Une bascule de gate ne doit JAMAIS arriver par effet de bord : c'est un
    geste owner, parce qu'un gate mal migre ouvre ou ferme TOUT."""
    fas = _module(monkeypatch, None)
    assert fas.DEFAULT_DB_PATH.endswith("embeddings.db")


def test_la_variable_isole_la_table(monkeypatch, tmp_path):
    cible = tmp_path / "sw.db"
    fas = _module(monkeypatch, str(cible))
    assert fas.DEFAULT_DB_PATH == str(cible)
    assert "embeddings.db" not in fas.DEFAULT_DB_PATH


@pytest.fixture
def source_fabriquee(tmp_path):
    """Base SOURCE fabriquee : ces cas testent l'outil, pas le corpus reel. Les
    faire dependre de la vraie base les rendrait sensibles a l'etat global du
    module (mesure : trois echecs par `reload` anterieur) et les ferait ecrire
    a cote du fichier de 23,2 Go qu'on cherche precisement a ne plus toucher."""
    import forge_access_switches as fas

    src = tmp_path / "src.db"
    conn = sqlite3.connect(str(src), isolation_level=None)
    try:
        conn.executescript(fas.DDL)
        conn.execute(
            "INSERT INTO access_switches (id, agent_pattern, resource_pattern, "
            "action, allowed, granted_by, created_at, updated_at, version) "
            "VALUES ('r1','agt_test','app/*','read',1,'nr','2026-09-05','2026-09-05',1)")
    finally:
        conn.close()
    return str(src)


def test_la_copie_est_idempotente(source_fabriquee, tmp_path):
    """Rejouable apres une modification de regle, sans dupliquer ni perdre."""
    split = pytest.importorskip("forge_switches_db_split")
    cible = tmp_path / "sw.db"
    a = split.copier(cible, appliquer=True, source=source_fabriquee)
    b = split.copier(cible, appliquer=True, source=source_fabriquee)
    assert a["regles_lues"] == b["regles_lues"] >= 1
    conn = sqlite3.connect(str(cible))
    try:
        n = conn.execute("SELECT COUNT(*) FROM access_switches").fetchone()[0]
    finally:
        conn.close()
    assert n == a["regles_lues"], "la seconde passe a duplique des regles"


def test_le_dry_run_n_ecrit_RIEN(source_fabriquee, tmp_path):
    split = pytest.importorskip("forge_switches_db_split")
    cible = tmp_path / "sw.db"
    r = split.copier(cible, appliquer=False, source=source_fabriquee)
    assert r["applique"] is False
    assert not cible.exists(), "le dry-run a cree la base"


def test_base_ABSENTE_n_est_pas_base_VIDE(tmp_path):
    """Le gate etant fail-closed, une base vide REFUSE tout -- le hub devient
    inutilisable exactement comme sous verrou. La verification doit donc
    distinguer « pas encore copiee » de « copiee et conforme »."""
    split = pytest.importorskip("forge_switches_db_split")
    r = split.verifier(tmp_path / "jamais_creee.db")
    assert r["ok"] is False
    assert "ABSENTE" in r["raison"]


def test_la_verification_compare_REGLE_A_REGLE(source_fabriquee, tmp_path):
    """Un COUNT identique ne prouve rien : deux tables peuvent avoir le meme
    nombre de lignes et des contenus differents."""
    split = pytest.importorskip("forge_switches_db_split")
    cible = tmp_path / "sw.db"
    split.copier(cible, appliquer=True, source=source_fabriquee)
    assert split.verifier(cible, source=source_fabriquee)["ok"] is True
    conn = sqlite3.connect(str(cible), isolation_level=None)
    try:
        conn.execute("UPDATE access_switches SET allowed = 1 - allowed")
    finally:
        conn.close()
    r = split.verifier(cible, source=source_fabriquee)
    assert r["ok"] is False, "une regle ALTEREE est passee pour conforme"


def test_l_outil_ne_peut_pas_ecrire_dans_la_base_du_RAG():
    """C'est elle qu'on fuit : l'ouverture doit etre `mode=ro`, pas une promesse."""
    src = (ROOT / "tools" / "forge_switches_db_split.py").read_text(
        encoding="utf-8", errors="replace")
    assert "mode=ro" in src and "query_only" in src


def test_la_dependance_critique_est_DOCUMENTEE_a_la_source():
    """Sans la trace, un futur lecteur remettra la table dans la grosse base --
    le chemin par defaut y mene toujours."""
    src = (ROOT / "app" / "forge_access_switches.py").read_text(
        encoding="utf-8", errors="replace")
    assert "FAIL-CLOSED" in src and "LAFORGE_SWITCHES_DB_PATH" in src
