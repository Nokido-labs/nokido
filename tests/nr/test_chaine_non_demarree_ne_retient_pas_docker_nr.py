"""NR 2/11 -- interblocage satiete RAM x relache Docker.

Mesure du 2/11 15 h 10 : la veille wj_851500cc12 restait `pending keywords` (aucun noeud demarre) parce que
`_etaler_veilles` n'en demarre aucune au-dessus du seuil de satiete RAM (~80 %). Or `get_active_intents()` comptait
TOUS les noeuds `pending` : cette chaine jamais demarree interdisait donc la relache de Docker (vmmem 2,55 Go), ce
qui maintenait la RAM au-dessus du seuil -- la veille attendait la RAM, la RAM attendait la veille.

Regle : une chaine retient les ressources des qu'elle a DEMARRE (un noeud running / retry_pending / termine). Une
chaine entierement `pending` attend son admission : elle ne retient rien, et redemandera Docker elle-meme
(`_ensure_searxng` pose docker.wanted a la recherche).
"""
import sqlite3

import pytest

from nokido_agent.app import forge_db_path as DBP
from nokido_agent.app import forge_resource_manager as RM


@pytest.fixture
def base(tmp_path, monkeypatch):
    p = tmp_path / "m2m.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE agent_chain_nodes (id TEXT PRIMARY KEY, chain_id TEXT, step_index INTEGER, "
              "status TEXT DEFAULT 'pending')")
    c.commit()
    c.close()
    monkeypatch.setattr(DBP, "db_path", lambda *a, **k: str(p))
    # 3/11 : la condition de l'incident est FIGEE (RAM en satiete -> aucune veille admissible). Sans elle, ce NR
    # dependrait de la RAM reelle depuis la regle « file admissible = intention » (test_veille_en_file_admissible_nr).
    monkeypatch.setattr(RM, "_veilles_admissibles", lambda: False)

    def remplir(lignes):
        k = sqlite3.connect(p)
        k.executemany("INSERT INTO agent_chain_nodes (id, chain_id, step_index, status) VALUES (?,?,?,?)", lignes)
        k.commit()
        k.close()
    return remplir


def _chaine(cid, statuts):
    return [("%s_%d" % (cid, i), cid, i, s) for i, s in enumerate(statuts)]


def test_chaine_jamais_demarree_ne_retient_rien(base):
    base(_chaine("wj_attente", ["pending"] * 7))
    assert RM.get_active_intents()["chains_active"] == 0


def test_chaine_en_cours_retient(base):
    base(_chaine("wj_cours", ["done", "running"] + ["pending"] * 5))
    assert RM.get_active_intents()["chains_active"] > 0


def test_chaine_entre_deux_etapes_retient(base):
    # keywords fini, search pas encore pris : la chaine a DEMARRE, Docker ne doit pas tomber entre deux noeuds
    base(_chaine("wj_entre", ["done", "done"] + ["pending"] * 5))
    assert RM.get_active_intents()["chains_active"] > 0


def test_retry_retient(base):
    base(_chaine("wj_retry", ["retry_pending"] + ["pending"] * 6))
    assert RM.get_active_intents()["chains_active"] > 0


def test_melange_ne_compte_que_les_chaines_demarrees(base):
    base(_chaine("wj_attente", ["pending"] * 7) + _chaine("wj_cours", ["done", "running"] + ["pending"] * 5))
    n = RM.get_active_intents()["chains_active"]
    assert n == 6, n  # les 6 noeuds vivants de wj_cours, aucun de wj_attente


def test_chaine_terminee_ne_retient_rien(base):
    base(_chaine("wj_fini", ["done"] * 7))
    assert RM.get_active_intents()["chains_active"] == 0
