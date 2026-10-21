"""NR 18/10 -- boucle A (nociceptive/metabolique, GO owner 18/10) : premiere metrique MESURABLE AUJOURD'HUI.

Metrique du debat anatomie : « refus suivis d'un repli reussi / refus ». La cartographie GLM (fbd3d7391) la disait
« partielle » faute de lien refus -> repli ; il existe pourtant un domaine ou le lien est trace : tasks.db, colonne
`reaffectations` ([{de, vers, motif, quand}]) + le resultat final de la tache. Un refus = une tache reaffectee au
moins une fois ; un repli REUSSI = cette tache finit `done` AVEC une livraison constatee (« commits produits : N »,
N >= 1, sans « [NON LIVRE] »). Illisible (JSON casse) = compte a part, jamais un succes ni un echec.
Portee dite : ce n'est QUE le domaine executeurs ; les autres refus (admission, routeur) restent a relier.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_regulation_efficacy as fre  # noqa: E402

R1 = [{"de": "OPENCODE_GLM", "vers": "OPENCODE_NEMOTRON", "motif": "NON LIVRE", "quand": "2026-10-18T15:00:00"}]


def _base(tmp_path):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, result TEXT, reaffectations TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,?,?,?,?)", [
        ("t1", "OPENCODE_NEMOTRON", "done", "[effet observe] commits produits : 1 (a..b)", json.dumps(R1)),
        ("t2", "OPENCODE_GPTOSS", "done", "[effet observe] commits produits : 0 (a..a) ; [NON LIVRE] x", json.dumps(R1)),
        ("t3", "OPENCODE_GPTOSS", "pending", None, json.dumps(R1)),
        ("t4", "OPENCODE_GPTOSS", "done", "[effet observe] commits produits : 2 (a..c)", None),   # jamais refusee
        ("t5", "OPENCODE_GPTOSS", "done", "commits produits : 1", "{pas du json"),
    ])
    c.commit()
    c.close()
    return db


def test_taux_de_repli_reussi_apres_refus(tmp_path):
    m = fre.taux_repli_apres_refus(_base(tmp_path))
    assert m["refus"] == 3, m            # t1, t2, t3 (t4 jamais refusee, t5 illisible)
    assert m["replis_reussis"] == 1, m   # seule t1 a livre apres reaffectation
    assert m["en_cours"] == 1, m         # t3 : pas encore de verdict, ni succes ni echec
    assert m["illisibles"] == 1, m
    assert abs(m["taux"] - 0.5) < 1e-9, m   # 1 reussi / 2 refus TERMINES


def test_base_absente_est_illisible_pas_zero(tmp_path):
    m = fre.taux_repli_apres_refus(tmp_path / "absente.db")
    assert m["taux"] is None and m.get("etat") == "ILLISIBLE", m
