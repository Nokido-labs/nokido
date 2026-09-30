# -*- coding: utf-8 -*-
"""NR - les balayeurs LISENT le producteur, ils ne recomptent pas (2026-09-06).

Cinq services ont ete coupes le 05/09 (mode sauvegarde) parce qu'ils lisaient la base
de 24,9 Go en boucle : OrganPulse (COUNT(*) du backlog toutes les 600 s, 107 Mo/s),
ParietalFusion (appelle le pouls), Homeostasis (via la proprioception : 2 COUNT +
GROUP BY domain + AVG, puis un COUNT(*) par table, a chaque cycle). Regle du corps :
« ne jamais reconstruire un etat que son producteur connait ».

Contrats :
  1. `forge_organ_pulse._check_embed_backlog` lit `forge_memory_availability.snapshot`
     : perime/absent -> WARN avec « INCONNU » (ni zero ni embolie) ; frais -> seuils ;
  2. `forge_proprioception.measure_knowledge` n'emet AUCUN SQL (tout vient du
     snapshot) ; absent -> None partout et `mesure` INCONNUE ;
  3. `forge_proprioception.measure_storage` n'emet aucun COUNT(*) : MAX(rowid), et
     la note dit que c'est une borne.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : os.walk racine (code appele)
#   (l.93)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for d in ("app", "tools"):
    if str(ROOT / d) not in sys.path:
        sys.path.insert(0, str(ROOT / d))

MA = pytest.importorskip("forge_memory_availability")
P = pytest.importorskip("forge_proprioception")
OP = pytest.importorskip("forge_organ_pulse")


class _Espion:
    """Connexion factice : enregistre chaque SQL, rend des valeurs plausibles."""

    def __init__(self, tables=("rag_chunks", "agent_messages")):
        self.sql: list[str] = []
        self._tables = tables

    def execute(self, sql, *a):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return (7,)

    def fetchall(self):
        return [(t,) for t in self._tables]

    def close(self):
        pass


def test_le_pouls_lit_le_snapshot_et_dit_l_inconnu(monkeypatch):
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: {"frais": False, "vector_pending": None,
                                                         "raison": "aucun snapshot"})
    etat, raison = OP._check_embed_backlog()
    assert etat == OP.WARN and "INCONNU" in raison, (etat, raison)
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: {"frais": True, "vector_pending": 12, "age_s": 30})
    assert OP._check_embed_backlog()[0] == OP.CLEAR
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: {"frais": True, "vector_pending": OP.EMBED_BACKLOG, "age_s": 30})
    assert OP._check_embed_backlog()[0] == OP.EMBOLIE


def test_measure_knowledge_n_emet_aucun_sql(monkeypatch):
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: {
        "frais": True, "age_s": 100, "total": 1000, "vector_available": 250,
        "by_domain": [["code", 600], ["doc", 400]], "avg_quality": 0.8})
    esp = _Espion()
    r = P.measure_knowledge(esp)
    assert esp.sql == [], f"measure_knowledge a recompte : {esp.sql}"
    assert r["chunks_total"] == 1000 and r["vectorized_pct"] == 25.0 and r["avg_quality"] == 0.8
    assert r["domains_top"][0] == {"domain": "code", "n": 600}
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: {"frais": False, "vector_pending": None,
                                                         "raison": "aucun snapshot"})
    r2 = P.measure_knowledge(esp)
    assert r2["score"] is None and r2["chunks_total"] is None and "INCONNUE" in r2["mesure"]
    assert esp.sql == []


def test_measure_storage_ne_compte_jamais_par_count(tmp_path, monkeypatch):
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(str(m2m))
    c.execute("CREATE TABLE agent_messages(id TEXT PRIMARY KEY, status TEXT)")
    c.execute("INSERT INTO agent_messages VALUES('a','unread')")
    c.commit(); c.close()
    import forge_db_path as dbp
    monkeypatch.setattr(dbp, "m2m_path", lambda: str(m2m))
    esp = _Espion(tables=("rag_chunks", "biblio_raw"))
    r = P.measure_storage(esp)
    scans = [s for s in esp.sql if "COUNT(*)" in s.upper() and "rag_chunks" in s]
    assert not scans, f"COUNT(*) sur rag_chunks emis par measure_storage : {scans}"
    assert all("MAX(rowid)" in s for s in esp.sql if 'FROM "' in s), esp.sql
    assert "borne" in r["db_rows_note"]
