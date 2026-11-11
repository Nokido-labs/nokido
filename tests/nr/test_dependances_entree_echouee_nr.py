"""NR 7/11 : une entree `done` avec cause_echec n'est pas livree (job_2d93b0a1 / job_56e078fb)."""
import sqlite3
import pytest
from tools import forge_task_executor as ex


def _base(entree):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE tasks (id TEXT, status TEXT, depend_de TEXT, cause_echec TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t3','pending','[\"e\"]',NULL)")
    c.execute("INSERT INTO tasks VALUES ('e',?,NULL,?)", entree)
    return c


@pytest.mark.parametrize("cause", ["QUOTA", "INCONNU", "NON_LIVRE", "SESSION_EXPIREE", "zzz"])
def test_entree_echouee_bloque(cause):
    ok, motif = ex._dependances_pretes(_base(("done", cause)), "t3")
    assert not ok and motif.startswith("BLOQUE_PAR_DEPENDANCE") and cause in motif


@pytest.mark.parametrize("cause", [None, "", "FAUX_VERT"])
def test_entree_livree_prete(cause):
    assert ex._dependances_pretes(_base(("done", cause)), "t3") == (True, "")


def test_entree_en_cours_bloque():
    assert not ex._dependances_pretes(_base(("pending", None)), "t3")[0]
