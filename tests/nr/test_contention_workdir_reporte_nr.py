"""NR -- une tache qui trouve le workdir d'AGY TENU est REPORTEE chez le meme agent, pas close en echec (17/10).

Mesure 17/10 : la matrice d'AGY (job_723fe078) a ete close ERR_INTERNAL « workdir agy deja tenu : tenu par AGY_M2M --
holder VIVANT » parce qu'une tache WORKER_CODE relayee a AGY tenait le verrou (commit ade344478 a 13:47:09). Le verrou a
fait son travail (deux agy n'ont pas ecrit dans le meme repertoire) ; c'est la tache PERDANTE qui etait mal traitee : une
contention passagere n'est pas un echec. Boucle BORNEE : au-dela de _MAX_REPORTS reports, la tache est reaffectee
(_reaffecter, existant) -- jamais d'attente infinie derriere un verrou qui ne se libere pas.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def _base(tmp_path, monkeypatch, statut="running"):
    chemin = tmp_path / "tasks.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, result TEXT)")
    con.execute("INSERT INTO tasks VALUES ('t1', 'ANTIGRAVITY', ?, 'x', NULL)", (statut,))
    con.commit()
    con.close()
    monkeypatch.setattr(E, "_db", lambda: sqlite3.connect(chemin))
    return chemin


def _ligne(chemin):
    con = sqlite3.connect(chemin)
    try:
        return con.execute("SELECT agent, status, reports FROM tasks WHERE id='t1'").fetchone()
    finally:
        con.close()


def test_un_workdir_tenu_reporte_la_tache_chez_le_meme_agent(tmp_path, monkeypatch):
    chemin = _base(tmp_path, monkeypatch)
    monkeypatch.setattr(E, "_reaffecter", lambda task, motif: (_ for _ in ()).throw(AssertionError("pas de reaffectation")))
    assert E._reporter({"id": "t1", "agent": "ANTIGRAVITY"}, "workdir agy deja tenu") == "REPORTEE"
    assert _ligne(chemin) == ("ANTIGRAVITY", "pending", 1)


def test_au_dela_de_la_borne_la_tache_est_reaffectee(tmp_path, monkeypatch):
    chemin = _base(tmp_path, monkeypatch)
    vus = []
    monkeypatch.setattr(E, "_reaffecter", lambda task, motif: vus.append(motif) or "MISTRAL")
    for _ in range(E._MAX_REPORTS):
        assert E._reporter({"id": "t1", "agent": "ANTIGRAVITY"}, "workdir agy deja tenu") == "REPORTEE"
    assert E._reporter({"id": "t1", "agent": "ANTIGRAVITY"}, "workdir agy deja tenu") == "MISTRAL"
    assert vus and "deja tenu" in vus[0]


def test_une_tache_deja_close_n_est_pas_rouverte(tmp_path, monkeypatch):
    chemin = _base(tmp_path, monkeypatch, statut="done")
    assert E._reporter({"id": "t1", "agent": "ANTIGRAVITY"}, "workdir agy deja tenu") is None
    assert _ligne(chemin)[1] == "done"


def test_la_branche_de_contention_reporte_au_lieu_de_clore():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fn = next(n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "_delegate_to_agy")
    corps = ast.get_source_segment(src, fn)
    i = corps.find("if not _jeton_wd:")
    assert i >= 0, "branche de contention introuvable"
    branche = corps[i:corps.find("except", i)]
    assert "_reporter(" in branche and "_fin(False" not in branche, branche
