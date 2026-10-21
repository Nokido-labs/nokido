# -*- coding: utf-8 -*-
"""NR -- une delegation OpenCode refusee faute de jeton est REAFFECTEE, pas perdue (owner : « aucune demande ne doit se perdre »).

Mesure du 19/10 ~00 h : 4 taches assignees a OPENCODE_DEFAUT2-5 (worktrees crees par l'owner, jetons pas encore
frappes) ont ete closes « done / ERR_INTERNAL : delegation refusee : jeton FORGE_TOKEN_OPENCODE_DEFAUTn absent ou
illisible au coffre », colonne reaffectations VIDE : quatre demandes tombees en silence. Le chemin Codex (L~1860)
reaffecte deja sur un motif de non-livraison ; celui-ci clotait directement.

Contrat : jeton absent -> `_reaffecter(..., ordre=palier ecrit)` ; reaffectee -> la delegation n'est PAS close ;
aucun receveur -> close en echec comme avant (le motif est dit).
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as X  # noqa: E402


@pytest.fixture()
def sans_jeton(monkeypatch, tmp_path):
    appels = {"reaffecter": [], "clore": []}
    monkeypatch.setattr(X, "_jeton_opencode_instance", lambda inst: "")
    monkeypatch.setattr(X, "_workdir_opencode", lambda inst: tmp_path)
    monkeypatch.setattr(X, "_etat_git", lambda wt: {})
    monkeypatch.setattr(X, "_chemins_status", lambda wt: frozenset())
    monkeypatch.setattr(X, "_clore_delegation", lambda *a, **k: appels["clore"].append(a))
    return appels


def test_jeton_absent_la_tache_est_reaffectee_pas_close(sans_jeton, monkeypatch):
    monkeypatch.setattr(X, "_reaffecter", lambda task, motif, ordre=None:
                        sans_jeton["reaffecter"].append((motif, ordre)) or "OPENCODE_GLM")
    X._delegate_to_opencode({"id": "t1", "agent": "OPENCODE_DEFAUT2", "description": "x"}, "jeton")
    assert len(sans_jeton["reaffecter"]) == 1 and "FORGE_TOKEN_OPENCODE_DEFAUT2" in sans_jeton["reaffecter"][0][0]
    assert "ANTIGRAVITY" not in (sans_jeton["reaffecter"][0][1] or ())
    assert sans_jeton["clore"] == []


def test_sans_receveur_la_tache_est_close_en_echec(sans_jeton, monkeypatch):
    monkeypatch.setattr(X, "_reaffecter", lambda task, motif, ordre=None: None)
    X._delegate_to_opencode({"id": "t2", "agent": "OPENCODE_DEFAUT3", "description": "x"}, "jeton")
    assert len(sans_jeton["clore"]) == 1 and sans_jeton["clore"][0][2] is False
