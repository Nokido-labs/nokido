"""NR -- MemoryConsolidator : garde CIBLE, pas de cycle au reveil avant l'intervalle (decision owner 20/10).

Mesure du 20/10 : le regulateur endort puis reveille NokidoMemoryConsolidator toutes les 10 a 30 min
(POST /supervisor/sleep|wake). A chaque reveil le daemon relancait un cycle complet ; son garde
`guarded_change(db_snapshot=True)` faisait un cold_backup de toute la base (%NOKIDO_DATA%\embeddings.db, 50 Go) et commencait par
un PRAGMA integrity_check -- ~47 min de lecture disque (17:05 -> 17:52) -- qui echouait (FTS5 rag_fts « malformed »).
`last_consolidated_ts` n'avancant qu'en cas de succes, chaque reveil retrouvait les memes 5000 traces : boucle qui
s'entretient (~49,5 Mo/s de lecture). Or le cycle n'ecrit que des chunks a identifiant DETERMINISTE.

Decision owner (AskUserQuestion) « Garde cible » :
  * plus de cold_backup de la base : le retour arriere retire les SEULS chunks que le cycle a CREES (un chunk identique
    deja present n'est jamais retire) ;
  * le debut du cycle est sauve AVANT le travail lourd ; au demarrage du daemon, pas de cycle avant la fin de
    l'intervalle (`_attente_avant_cycle`).
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import sqlite3
import sys
from hashlib import sha256
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Arret(Exception):
    pass


def _mod(monkeypatch, tmp_path):
    m = importlib.import_module("forge_memory_consolidator")
    db = tmp_path / "emb.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT)")
    con.execute("INSERT INTO rag_chunks VALUES ('autre', 'x', 'un chunk qui n est pas a nous')")
    con.commit()
    con.close()
    monkeypatch.setattr(m, "EMBEDDINGS_DB", db)
    monkeypatch.setattr(m, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(m, "HEARTBEAT", tmp_path / "hb.json")
    # Le VRAI guarded_change ne tourne jamais dans ce NR : avec db_snapshot=True il sauvegarderait la base vivante
    # (1re version de ce RED : refus de snapshot leve avant toute insertion -> faux vert du retour arriere).
    vus = []

    @contextlib.contextmanager
    def faux_garde(label, **kw):
        vus.append(kw)
        yield None

    monkeypatch.setattr(m, "guarded_change", faux_garde)
    m._gardes_vus = vus
    return m, db


def _ids(db):
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT id FROM rag_chunks")}
    finally:
        con.close()


def _id_de(task_type, resume, n):
    source = f"experience/consolidated/{task_type}"
    text = f"[{task_type}] {resume} (consolidated from {n} traces)"
    return sha256((source + text).encode()).hexdigest()[:16]


def test_le_cycle_ne_sauvegarde_plus_toute_la_base(monkeypatch, tmp_path):
    m, db = _mod(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_fetch_high_value_traces", lambda ts: {"t": [{}] * 5})
    monkeypatch.setattr(m, "_summarise_group", lambda tt, tr: "resume")
    m.run_consolidation_cycle({"last_consolidated_ts": 0})
    vus = m._gardes_vus
    assert vus and not any(k.get("db_snapshot") for k in vus), vus
    assert _id_de("t", "resume", 5) in _ids(db)


def test_le_retour_arriere_ne_retire_que_ce_que_le_cycle_a_cree(monkeypatch, tmp_path):
    m, db = _mod(monkeypatch, tmp_path)
    deja = _id_de("b", "resume b", 5)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO rag_chunks VALUES (?, ?, ?)", (deja, "experience/consolidated/b", "identique"))
    con.commit()
    con.close()

    def resume(tt, tr):
        if tt == "c":
            raise RuntimeError("panne du resumeur au 3e groupe")
        return "resume %s" % tt

    monkeypatch.setattr(m, "_fetch_high_value_traces", lambda ts: {"a": [{}] * 5, "b": [{}] * 5, "c": [{}] * 5})
    monkeypatch.setattr(m, "_summarise_group", resume)
    with pytest.raises(RuntimeError):
        m.run_consolidation_cycle({"last_consolidated_ts": 0})
    ids = _ids(db)
    assert _id_de("a", "resume a", 5) not in ids, "le chunk CREE par le cycle avorte est retire"
    assert deja in ids and "autre" in ids, "jamais un chunk qui existait deja"


def test_le_debut_du_cycle_est_sauve_avant_le_travail_lourd(monkeypatch, tmp_path):
    m, _db = _mod(monkeypatch, tmp_path)

    def lourd(ts):
        raise _Arret("endormi par le regulateur pendant la lecture")

    monkeypatch.setattr(m, "_fetch_high_value_traces", lourd)
    with pytest.raises(_Arret):
        m.run_consolidation_cycle({"last_consolidated_ts": 0})
    etat = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert etat.get("dernier_cycle_debut"), etat


def test_l_attente_avant_cycle_respecte_l_intervalle(monkeypatch, tmp_path):
    m, _db = _mod(monkeypatch, tmp_path)
    assert m._attente_avant_cycle({}, 10_000.0) == 0
    assert m._attente_avant_cycle({"dernier_cycle_debut": 10_000.0 - 100}, 10_000.0) == pytest.approx(m.INTERVAL_S - 100)
    assert m._attente_avant_cycle({"dernier_cycle_debut": 10_000.0 - m.INTERVAL_S - 1}, 10_000.0) == 0


def test_le_daemon_reveille_attend_au_lieu_de_relancer(monkeypatch, tmp_path):
    """Chemin reel : `main --daemon`, reveille 100 s apres le debut du dernier cycle."""
    m, _db = _mod(monkeypatch, tmp_path)
    maintenant = 50_000.0
    (tmp_path / "state.json").write_text(json.dumps({"last_consolidated_ts": 0,
                                                     "dernier_cycle_debut": maintenant - 100}), encoding="utf-8")
    monkeypatch.setattr(m.time, "time", lambda: maintenant)
    cycles, sommeils = [], []
    monkeypatch.setattr(m, "run_consolidation_cycle", lambda st: cycles.append(1) or {})

    def dormir(s):
        sommeils.append(s)
        raise _Arret()

    monkeypatch.setattr(m.time, "sleep", dormir)
    monkeypatch.setattr(sys, "argv", ["forge_memory_consolidator.py", "--daemon"])
    monkeypatch.setattr(sys, "stdout", io.StringIO())   # main() reemballe stdout.buffer : pas sous la capture pytest
    with pytest.raises(_Arret):
        m.main()
    assert cycles == [], "aucun cycle avant la fin de l'intervalle"
    assert sommeils and sommeils[0] == pytest.approx(m.INTERVAL_S - 100), sommeils
