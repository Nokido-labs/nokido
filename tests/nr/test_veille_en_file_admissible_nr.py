# -*- coding: utf-8 -*-
"""NR (owner 3/11 23 h 30 « pourquoi tu coupes docker entre chaque veille ? », choix « file admissible = intention ») :
Docker coupe puis relance 3 fois en 15 min (keeper : 23:12, 23:20, 23:28) -- entre deux vagues de veilles, les chaines
en file (entierement `pending`) ne comptaient pas, donc Docker etait « sans intention ». La regle du 2/11 reste (en
satiete RAM, une veille en file ne retient RIEN : interblocage wj_851500cc12) ; HORS satiete, une VEILLE en file
(chain_id wj_*) est une intention -- elle demarrera bientot et aura besoin de Docker. Admissibilite illisible : rien
n'est compte (comportement du 2/11)."""
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

    def remplir(lignes):
        k = sqlite3.connect(p)
        k.executemany("INSERT INTO agent_chain_nodes (id, chain_id, step_index, status) VALUES (?,?,?,?)", lignes)
        k.commit()
        k.close()
    return remplir


def _chaine(cid, statuts):
    return [("%s_%d" % (cid, i), cid, i, s) for i, s in enumerate(statuts)]


def test_veille_en_file_admissible_retient_docker(base, monkeypatch):
    monkeypatch.setattr(RM, "_veilles_admissibles", lambda: True)
    base(_chaine("wj_attente", ["pending"] * 7))
    assert RM.get_active_intents()["chains_active"] > 0


def test_en_satiete_la_regle_du_2_11_tient(base, monkeypatch):
    monkeypatch.setattr(RM, "_veilles_admissibles", lambda: False)
    base(_chaine("wj_attente", ["pending"] * 7))
    assert RM.get_active_intents()["chains_active"] == 0


def test_une_chaine_en_file_qui_n_est_pas_une_veille_ne_compte_pas(base, monkeypatch):
    monkeypatch.setattr(RM, "_veilles_admissibles", lambda: True)
    base(_chaine("goap_x", ["pending"] * 3))
    assert RM.get_active_intents()["chains_active"] == 0


def test_admissibilite_illisible_ne_compte_rien(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_chain_executor",
                        types.SimpleNamespace(_ram_en_satiete=lambda: (_ for _ in ()).throw(RuntimeError("x"))))
    assert RM._veilles_admissibles() is False
