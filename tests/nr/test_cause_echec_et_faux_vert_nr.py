# -*- coding: utf-8 -*-
"""NR (owner 3/11 « vois-tu et diagnostiques-tu au moins les raisons des echecs de delegations ? ») : le CORPS classe la
cause de chaque echec, et un faux vert n'est plus un succes.

Ce soir, chaque cause a ete trouvee a la main en lisant tasks.db. Les rendus REELS ci-dessous sont ceux de ce soir.
Faux vert : GPT-OSS (74f27169f) et GLM (395d83b16) ont livre du code faux avec « preuve RED INDETERMINEE (RED NON
OBSERVE : preuve vide) », compte SUCCESS.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402

RENDUS = {
    "QUOTA": "ERROR: You've hit your usage limit. ... try again at Nov 17th, 2026 1:38 PM.",
    "OUTIL_REFUSE": '"error": {"message": "Tool execution denied by approval policy", "code": "tool_denied"}',
    "RING": '{"intent": "ERR_INTERNAL", "commit_message": "security: refuse l\'edition de forge_lane_admission.py '
            '(sandbox=console requiert ring=0)"}',
    "DELAI": '{"status":"SUCCESS","response":"","duration_seconds":1465.9,"finished_reason":"print_timeout"}',
    "NON_LIVRE": "[effet observe] commits produits : 0 ; [RIEN PRODUIT] (RIEN_PRODUIT) ni commit ni fichier",
}


@pytest.mark.parametrize("cause", sorted(RENDUS))
def test_la_cause_est_classee_depuis_le_rendu_reel(cause):
    assert T.classer_cause_echec(RENDUS[cause]) == cause


def test_le_quota_prime_sur_le_non_livre():
    # Codex : « RIEN PRODUIT » ET « usage limit » dans le meme rendu -> la cause est le quota, pas l'absence de livraison
    assert T.classer_cause_echec(RENDUS["NON_LIVRE"] + "\n" + RENDUS["QUOTA"]) == "QUOTA"


def test_cause_inconnue_est_dite():
    assert T.classer_cause_echec("AssertionError: assert 2 == 3") == "INCONNU"


def test_faux_vert_passe_a_revoir():
    effet = ("[effet observe] commits produits : 2 ; preuve RED INDETERMINEE (RED NON OBSERVE : preuve vide) "
             "[commit RED 1579739cd]")
    assert T._statut_livraison(True, effet) == "A_REVOIR"
    assert T._statut_livraison(True, "[effet observe] commits produits : 2 (a..b)") == "SUCCESS"


def test_la_cause_est_ecrite_en_base(tmp_path):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'running')")
    T._noter_cause_echec(c, "t1", "OUTIL_REFUSE")
    assert c.execute("SELECT cause_echec FROM tasks WHERE id='t1'").fetchone()[0] == "OUTIL_REFUSE"
    T._noter_cause_echec(c, "t1", None)                                      # pas d'echec : rien d'ecrit
    assert c.execute("SELECT cause_echec FROM tasks WHERE id='t1'").fetchone()[0] == "OUTIL_REFUSE"


def test_la_cloture_classe_l_echec(monkeypatch):
    vus = []
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(":memory:"))
    monkeypatch.setattr(T, "_mark_done", lambda *a, **k: None)
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_noter_cause_echec", lambda conn, tid, cause: vus.append((tid, cause)))
    T._clore_delegation("t9", "jeton", False, RENDUS["OUTIL_REFUSE"])
    T._clore_delegation("t8", "jeton", True, "[effet observe] commits produits : 1 ; RED INDETERMINEE")
    T._clore_delegation("t7", "jeton", True, "[effet observe] commits produits : 1 (a..b)")
    assert vus == [("t9", "OUTIL_REFUSE"), ("t8", "FAUX_VERT"), ("t7", None)]


_EXPIREE = ("[effet observe] commits produits : 1 (a..b)\n[executeur] travail INACHEVE preserve : commit abc "
            "| print timeout after 24m30s with the turn still in progress")


def _cloture(monkeypatch, ok, detail):
    vus, marques = [], []
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(":memory:"))
    # 7/11 (7aa64ee12) : `_mark_done` recoit aussi `workdir=` (juge sur le worktree de la tache) ; la doublure l'accepte.
    monkeypatch.setattr(T, "_mark_done", lambda conn, tid, res, o, workdir=None: marques.append(o))
    monkeypatch.setattr(T, "_hub_call", lambda *a, **k: {})
    monkeypatch.setattr(T, "_noter_cause_echec", lambda conn, tid, cause: vus.append(cause))
    T._clore_delegation("t1", "jeton", ok, detail)
    return vus, marques


def test_session_expiree_avec_commit_inacheve_n_est_jamais_done_sans_cause(monkeypatch):
    for ok in (True, False):
        vus, marques = _cloture(monkeypatch, ok, _EXPIREE)
        assert vus == ["SESSION_EXPIREE"] and marques == [False]


def test_session_expiree_sans_commit_inchangee(monkeypatch):
    vus, marques = _cloture(monkeypatch, False, "print timeout after 24m30s with the turn still in progress")
    assert vus == ["INCONNU"] and marques == [False]      # comportement actuel conserve
