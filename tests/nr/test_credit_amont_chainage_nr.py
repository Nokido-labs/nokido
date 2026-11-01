"""NR 31/10 (owner : « go le 1 ») -- un travail aval REUSSI credite les agents dont il a consomme les livrables.

Reflexion owner (incubation -> saillance -> renforcement) branchee sur l'EXISTANT : le routage hedoniste mesure
(forge_motivation.ordre_hedoniste_mesure, arme dans la reaffectation) ne voyait que la livraison PROPRE de chaque agent.
Depuis le chainage depend_de (ca6defd6b, prouve en vrai le 31/10), une sequence d'agents qui a mene a un succes se
renforce : chaque entree d'une tache aval LIVREE vaut un credit d'1/2 livraison a son agent. Un echec aval ne punit
PAS l'amont (la cause peut etre l'aval : dans le doute, on s'abstient). Base tasks.db factice.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from nokido_agent.app import forge_motivation as M

LIVRE = "[effet observe] commits produits : 1 (a1..b2) ; fichiers non commites : 0"
NOW = datetime(2026, 10, 31, 9, 30)


def _base(avec_dep=True, aval_ok=True):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
              " created_at TEXT, updated_at TEXT, job_id TEXT, reaffectations TEXT"
              + (", depend_de TEXT" if avec_dep else "") + ")")
    q = "2026-10-31T09:00:00"
    lignes = [("t1", "ANTIGRAVITY", "done", LIVRE, None), ("t2", "MISTRAL", "done", LIVRE, None),
              ("t3", "CLAUDE_HEADLESS", "done" if aval_ok else "failed",
               LIVRE if aval_ok else "NON LIVRE apres delegation", json.dumps(["t1", "t2"]))]
    for tid, ag, st, res, dep in lignes:
        if avec_dep:
            c.execute("INSERT INTO tasks (id, agent, status, result, created_at, updated_at, job_id, depend_de)"
                      " VALUES (?,?,?,?,?,?,?,?)", (tid, ag, st, res, q, q, tid, dep))
        else:
            c.execute("INSERT INTO tasks (id, agent, status, result, created_at, updated_at, job_id)"
                      " VALUES (?,?,?,?,?,?,?)", (tid, ag, st, res, q, q, tid))
    return c


def test_aval_livre_credite_l_amont():
    cpt = M._compter_livraisons(_base(), NOW)
    assert cpt["ANTIGRAVITY"] == {"livrees": 1.5, "touches": 1.5}
    assert cpt["MISTRAL"] == {"livrees": 1.5, "touches": 1.5}
    assert cpt["CLAUDE_HEADLESS"] == {"livrees": 1, "touches": 1}  # l'aval n'est pas credite de lui-meme


def test_aval_echoue_ne_punit_pas_l_amont():
    cpt = M._compter_livraisons(_base(aval_ok=False), NOW)
    assert cpt["ANTIGRAVITY"] == {"livrees": 1, "touches": 1} and cpt["MISTRAL"] == {"livrees": 1, "touches": 1}


def test_base_d_avant_sans_colonne_inchangee():
    cpt = M._compter_livraisons(_base(avec_dep=False), NOW)
    assert cpt["ANTIGRAVITY"] == {"livrees": 1, "touches": 1}


def test_le_credit_change_le_score_dans_le_bon_sens():
    avec = M.scores_hedonistes_mesure(["ANTIGRAVITY"], _base(), now=NOW, resultats=[])["ANTIGRAVITY"]["valeur"]
    sans = M.scores_hedonistes_mesure(["ANTIGRAVITY"], _base(aval_ok=False), now=NOW, resultats=[])["ANTIGRAVITY"]["valeur"]
    assert avec > sans
