"""NR — l'audit RAG periodique ne balaie plus la base, et ne se relance pas sur lui-meme (2026-09-23).

Ecrit ROUGE avant correctif. Derogation owner : `app/forge_health_diagnostic.py` seul.

LE DEFAUT. Second lecteur long du 23/09 : pendant l'ingestion 6f, `forge_homeostasis_orchestrator`
a lu 18,9 Go en 4 min et le WAL a gonfle de 2,5 a 18,3 Go. La phase `health` appelle
`audit_rag_chunks`, dont DEUX requetes font `SCAN rag_chunks` sur 38 Go (EXPLAIN reel) :
`GROUP BY hash HAVING COUNT(*) > 1` (doublons) et `AVG(quality_score)`. La phase depasse son delai
de 90 s et est « abandonnee » ; or le cache n'est ecrit qu'en FIN de mesure : le tick suivant
relance une mesure complete, possiblement pendant que la precedente lit encore.

CONTRAT OWNER. Aucun controle profond n'existe vers lequel les deplacer (le CLI appelle le meme
`run_cycle`) : ces deux grandeurs deviennent un ECHANTILLON explicitement declare — jamais une
mesure partielle qui garderait le nom ou le verdict d'une mesure exhaustive.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

hd = pytest.importorskip("nokido_agent.app.forge_health_diagnostic")


def _base(tmp_path, n=300, doublon_en_fin=True):
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT,"
        " embedding BLOB, hash TEXT, quality_score REAL, meta TEXT);"
        "CREATE INDEX idx_domain ON rag_chunks(domain);"
        # Fidelite au schema de production (EXPLAIN reel : `no_vec` passe par un index
        # PARTIEL) — sans lui, le temoin accuserait une requete saine.
        "CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;"
    )
    for i in range(n):
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?,?,?)",
                    (f"c{i}", "t", "s", "d%d" % (i % 3), b"x" * 16, f"h{i}", 0.5, "{}"))
    if doublon_en_fin:
        for k in ("dA", "dB"):
            con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?,?,?)",
                        (k, "t", "s", "d0", b"x" * 16, "h_double", 0.9, "{}"))
    con.commit()
    return con


class _Enregistreuse:
    def __init__(self, con):
        self.con, self.sql = con, []

    def execute(self, sql, params=()):
        self.sql.append((sql, tuple(params)))
        return self.con.execute(sql, params)


def test_aucune_lecture_complete_de_rag_chunks(tmp_path):
    con = _base(tmp_path)
    rec = _Enregistreuse(con)
    hd._audit_rag_chunks_mesure(rec)
    fautives = []
    for sql, params in rec.sql:
        if not sql.strip().upper().startswith("SELECT") or "LIMIT" in sql.upper():
            continue
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
        if any(l.startswith("SCAN rag_chunks") and "INDEX" not in l for l in plan):
            fautives.append((" ".join(sql.split())[:100], plan))
    assert not fautives, "lecture complete de rag_chunks (38 Go en prod) : %s" % fautives


def test_echantillon_declare_et_jamais_nomme_comme_exhaustif(tmp_path):
    r = hd._audit_rag_chunks_mesure(_base(tmp_path))
    assert str(r.get("doublons_statut", "")).startswith("ECHANTILLON"), r.get("doublons_statut")
    assert str(r["quality_score_echantillon"].get("statut", "")).startswith("ECHANTILLON")
    # Contrat owner : une mesure devenue partielle ne garde PAS le nom de l'exhaustive.
    anciens = {"duplicate_hashes", "duplicate_rows_total", "quality_score"} & set(r)
    assert not anciens, "noms d'une mesure exhaustive conserves sur un echantillon : %s" % anciens


def test_les_doublons_de_l_echantillon_sont_vus(tmp_path):
    r = hd._audit_rag_chunks_mesure(_base(tmp_path))
    assert r["duplicate_hashes_echantillon"] >= 1, "le doublon recent n'est plus detecte"


def test_aucune_valeur_de_qualite_n_est_pas_une_qualite_nulle(tmp_path):
    """Mesure du 23/09 sur la vraie base : les 10 000 derniers chunks n'ont PAS de quality_score,
    et l'ancien `round(None or 0)` affichait avg=0 — un faux zero."""
    con = _base(tmp_path, doublon_en_fin=False)
    con.execute("UPDATE rag_chunks SET quality_score = NULL")
    con.commit()
    q = hd._audit_rag_chunks_mesure(con)["quality_score_echantillon"]
    assert q["avg"] is None and q["n"] == 0, q
    assert "NON MESURE" in q["statut"], q


def test_pas_de_relance_pendant_une_mesure_en_cours(tmp_path, monkeypatch):
    """Une mesure longue en cours : le tick suivant ne doit PAS en relancer une seconde."""
    appels, feu = [], threading.Event()

    def mesure_lente(conn):
        appels.append(1)
        feu.wait(5)
        return {"total": 1, "duplicate_hashes": 0}

    monkeypatch.setattr(hd, "_audit_rag_chunks_mesure", mesure_lente)
    monkeypatch.setattr(hd, "_ventiler_la_dette", lambda r: None)
    monkeypatch.setattr(hd, "_RAG_CACHE", {"ts": time.time() - 10_000, "valeur": {"total": 7, "duplicate_hashes": 0}})
    t = threading.Thread(target=hd.audit_rag_chunks, args=(None,), kwargs={"force": True})
    t.start()
    time.sleep(0.3)
    second = hd.audit_rag_chunks(None, force=True)
    feu.set()
    t.join(5)
    assert len(appels) == 1, "une seconde mesure a ete relancee pendant la premiere"
    assert second.get("mesure_en_cours") is True and second.get("total") == 7, second
