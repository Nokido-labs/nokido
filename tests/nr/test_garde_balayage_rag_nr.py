"""Un script `run` ne peut plus balayer la base RAG en entier (owner 24/10).

CE QUI A ETE PAYE (2026-10-24). « Les balayages massifs du RAG sont inadmissibles, il
y a des index pour ca. » Regle deja donnee, deja ecrite -- et violee deux fois le meme
jour : un script `run python` d'un executant (consigne « mesure la latence ») a lance
`SELECT id FROM rag_chunks WHERE embedding IS NULL` sur %NOKIDO_DATA%\embeddings.db (45 Go) et
sature le NVMe a 80 Mo/s. Une regle qui ne vit que dans un texte se re-paie : celle-ci
vit desormais dans le preambule WorkspaceGuard injecte dans chaque script `run`.

Contrat : toute connexion sqlite3 vers une base `embeddings.db` recoit un budget
d'etapes PAR REQUETE ; au-dela, la requete est interrompue et le garde dit pourquoi.
Une requete indexee (quelques centaines d'etapes) passe ; une autre base n'est pas
touchee. On eprouve dans un SOUS-PROCESSUS : `sys.addaudithook` est irreversible.
"""

from __future__ import annotations

import pathlib
import sqlite3
import subprocess
import sys

import pytest

pytestmark = pytest.mark.timeout(120)

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "app") not in sys.path:
    sys.path.insert(0, str(RACINE / "app"))

BUDGET = 200_000


@pytest.fixture()
def fwg():
    import forge_workspace_guard
    return forge_workspace_guard


def _base(chemin: pathlib.Path) -> pathlib.Path:
    cx = sqlite3.connect(str(chemin))
    cx.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, embedding BLOB, active INT)")
    cx.executemany("INSERT INTO rag_chunks VALUES (?, ?, 1)",
                   (("c%06d" % i, None if i % 7 else b"x") for i in range(60_000)))
    cx.commit()
    cx.close()
    return chemin


def _sous_garde(fwg, zone, code: str):
    src = fwg.build_run_guard_header([str(zone)], budget_rag=BUDGET) + "\n" + code
    p = subprocess.run([sys.executable, "-c", src], capture_output=True,
                       text=True, errors="replace", timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _requete(db, sql):
    return ("import sqlite3\n"
            "cx = sqlite3.connect(%r)\n"
            "print('LIGNES', len(cx.execute(%r).fetchall()))\n" % (str(db), sql))


def test_un_balayage_complet_de_la_base_RAG_est_interrompu(fwg, tmp_path):
    db = _base(tmp_path / "embeddings.db")
    rc, sortie = _sous_garde(fwg, tmp_path, _requete(db, "SELECT id FROM rag_chunks WHERE embedding IS NULL"))
    assert rc != 0, "balayage complet laisse passer : %s" % sortie[-400:]
    assert "WORKSPACE_GUARD" in sortie and "EXPLAIN" in sortie, sortie[-500:]


def test_le_garde_vaut_aussi_en_lecture_seule_par_uri(fwg, tmp_path):
    db = _base(tmp_path / "embeddings.db")
    code = ("import sqlite3\n"
            "cx = sqlite3.connect('file:' + %r + '?mode=ro', uri=True)\n"
            "cx.execute('SELECT count(*) FROM rag_chunks WHERE embedding IS NULL').fetchall()\n"
            % db.as_posix())
    rc, sortie = _sous_garde(fwg, tmp_path, code)
    assert rc != 0 and "WORKSPACE_GUARD" in sortie, sortie[-500:]


def test_une_requete_indexee_passe(fwg, tmp_path):
    """CONTRE-EPREUVE : un garde qui couperait tout casserait la lecture legitime."""
    db = _base(tmp_path / "embeddings.db")
    rc, sortie = _sous_garde(fwg, tmp_path, _requete(db, "SELECT id FROM rag_chunks WHERE id = 'c000042'"))
    assert rc == 0 and "LIGNES 1" in sortie, sortie[-500:]


def test_le_budget_est_par_requete_pas_par_connexion(fwg, tmp_path):
    """Mille petites requetes indexees ne doivent pas epuiser un budget cumule."""
    db = _base(tmp_path / "embeddings.db")
    code = ("import sqlite3\n"
            "cx = sqlite3.connect(%r)\n"
            "for i in range(3000):\n"
            "    cx.execute(\"SELECT id FROM rag_chunks WHERE id = ?\", ('c%%06d' %% i,)).fetchall()\n"
            "print('FINI')\n" % str(db))
    rc, sortie = _sous_garde(fwg, tmp_path, code)
    assert rc == 0 and "FINI" in sortie, sortie[-500:]


def test_une_autre_base_n_est_pas_touchee(fwg, tmp_path):
    db = _base(tmp_path / "autre.db")
    rc, sortie = _sous_garde(fwg, tmp_path, _requete(db, "SELECT id FROM rag_chunks WHERE embedding IS NULL"))
    assert rc == 0 and "LIGNES" in sortie, sortie[-500:]


def test_le_header_par_defaut_porte_le_garde(fwg):
    """Chemin reel : le header que le hub injecte (sans argument) arme le garde."""
    hdr = fwg.build_run_guard_header(["C:/zone"])
    assert "_gz_rag_garde" in hdr and "__BUDGET_RAG__" not in hdr
