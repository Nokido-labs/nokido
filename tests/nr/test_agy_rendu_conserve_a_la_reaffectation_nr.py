"""NR -- le rendu d'une surface qui echoue SURVIT a la reaffectation, et un print_timeout d'agy se NOMME.

Autopsie 31/10 (etude UI OmniRoute, job_add2906f + job_b2738b35) : la cause etait jugee « ILLISIBLE » parce que
(1) le journal de l'executeur n'ecrivait que `len(detail)` (« AGY KO (176 chars) ») ; (2) `_reaffecter` sortait AVANT
`_fin` : le detail d'AGY n'atteignait jamais tasks.db, et le receveur (MISTRAL) ecrivait ensuite SON resultat. La
sortie brute existait pourtant (sandbox/jobs/agy_<tache>.json) : rien ne pointait vers elle. Vraies causes, lues
apres coup : job_add2906f = `finished_reason: print_timeout` apres 24 min 30 (classe « REPONSE VIDE », le timeout
masque) ; job_b2738b35 = read_file refuse en headless.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


@pytest.fixture
def base(monkeypatch, tmp_path):
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
              " updated_at TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'x', 'ANTIGRAVITY', 'running', NULL, NULL)")
    c.commit()
    c.close()
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(chemin))
    monkeypatch.setattr(T, "_lire_registre", lambda: {"agents": {}})
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent == "MISTRAL")
    return chemin


def _trace(chemin):
    c = sqlite3.connect(chemin)
    return json.loads(c.execute("SELECT reaffectations FROM tasks WHERE id='t1'").fetchone()[0])


def test_le_rendu_de_la_surface_est_garde_dans_la_trace(base):
    rendu = "[REPONSE VIDE] agy SUCCESS sans reponse ; actions refusees par le bac : read_file\n" \
            "[executeur] sortie brute agy : sandbox/jobs/agy_t1.json"
    assert T._reaffecter({"id": "t1", "agent": "ANTIGRAVITY"}, "[RIEN PRODUIT]", rendu=rendu) == "MISTRAL"
    t = _trace(base)[-1]
    assert "read_file" in t["rendu"] and "agy_t1.json" in t["rendu"]


def test_le_rendu_est_borne(base):
    T._reaffecter({"id": "t1", "agent": "ANTIGRAVITY"}, "[RIEN PRODUIT]", rendu="x" * 5000)
    assert len(_trace(base)[-1]["rendu"]) <= T._RENDU_MAX


def test_sans_rendu_la_trace_reste_compatible(base):
    T._reaffecter({"id": "t1", "agent": "ANTIGRAVITY"}, "quota")
    assert "rendu" not in _trace(base)[-1]


def test_le_journal_porte_la_tete_du_rendu_sur_une_ligne():
    tete = T._tete_rendu("ligne 1\nligne 2\t" + "y" * 2000)
    assert "\n" not in tete and tete.startswith("ligne 1 ligne 2") and len(tete) <= T._RENDU_MAX


def test_le_pointeur_de_sortie_brute_survit_a_la_troncature():
    detail = "[REPONSE VIDE] x\n[executeur] sortie brute agy : C:/n/sandbox/jobs/agy_t1.json\n[executeur] " + "z" * 3000
    tete = T._tete_rendu(detail)
    assert "agy_t1.json" in tete and len(tete) <= T._RENDU_MAX


def test_toute_ligne_de_verdict_d_executeur_porte_la_tete_du_rendu():
    """31/10 09:30 : CLAUDE_HEADLESS KO en 5 s, journal = effet seul ; 0956596b0 n'avait corrige que la ligne AGY.
    Chaque ligne « DELEGATE ... {'OK' if ok else 'KO'} » de l'executeur doit ecrire _tete_rendu sur un KO."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    lignes = src.splitlines()
    sites = [i for i, l in enumerate(lignes) if "{'OK' if ok else 'KO'}" in l and "DELEGATE" in l]
    assert len(sites) >= 5
    for i in sites:
        bloc = " ".join(lignes[i:i + 3])
        assert "_tete_rendu" in bloc, "ligne %d sans tete du rendu : %s" % (i + 1, lignes[i].strip()[:90])


def test_print_timeout_se_nomme_au_lieu_de_reponse_vide():
    raw = json.dumps({"status": "SUCCESS", "response": "", "duration_seconds": 1366.06,
                      "finished_reason": "print_timeout"})
    ok, detail = T.lire_sortie_agy(raw)
    assert ok is False and "[TIMEOUT]" in detail and "print_timeout" in detail and "1366" in detail
