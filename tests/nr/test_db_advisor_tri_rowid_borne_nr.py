"""NR -- le chasseur ne crie pas a tort : `ORDER BY <rowid> DESC LIMIT n` sans WHERE est BORNE (21/10).

Passage reel du 21/10 (job_234b87467d7a) : `SELECT ts, channel, agent, tool, status FROM network_log ORDER BY id DESC
LIMIT 10` (forge_mcp_registry.py:6347) et `... inspector_log ORDER BY rowid DESC LIMIT 1` (forge_vitals_channels.py:743)
sortaient en `SCAN` sur des tables de 2,1 M et 177 k lignes. Or SQLite parcourt le b-tree de la table A REBOURS et
s'arrete au n-ieme enregistrement : O(n), pas O(table). Les corriger serait du travail perdu ; les garder dans la liste
ferait desarmer le chasseur (un garde qui crie a faux se fait desarmer).

Contrats :
  1. sans WHERE, ORDER BY sur l'alias de rowid (`rowid` ou colonne INTEGER PRIMARY KEY seule) et LIMIT -> ni scans
     ni index_complets, mais fiche["bornes"] = [{table, origine, sql}] (DIT, jamais cache) ;
  2. ORDER BY sur une colonne NON indexee + LIMIT -> reste un balayage (tri sur toute la table) ;
  3. un WHERE + ORDER BY rowid DESC LIMIT -> reste un balayage (le filtre peut parcourir loin).
"""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_index_advisor as A  # noqa: E402


def test_tri_rowid_desc_limit_est_borne(tmp_path, monkeypatch):
    db = tmp_path / "logs.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("CREATE TABLE network_log (id INTEGER PRIMARY KEY, ts TEXT, tool TEXT)")
        c.executemany("INSERT INTO network_log (ts, tool) VALUES (?, ?)", [("t%d" % i, "x") for i in range(40)])
    requetes = [("SELECT ts, tool FROM network_log ORDER BY id DESC LIMIT 10", "reg.py", 1, True),
                ("SELECT ts FROM network_log ORDER BY rowid DESC LIMIT 1", "vit.py", 2, True),
                ("SELECT ts FROM network_log ORDER BY ts DESC LIMIT 10", "tri.py", 3, True),
                ("SELECT ts FROM network_log WHERE tool = 'y' ORDER BY id DESC LIMIT 5", "filtre.py", 4, True)]
    monkeypatch.setattr(A, "_requetes_du_code", lambda: requetes)
    monkeypatch.setattr(A, "_bases", lambda: [db])
    monkeypatch.setattr(A, "_hors_depot", lambda: ([], []))  # le parcours reel des disques est teste a part
    fiche = A.auditer(seuil=1)["bases"][0]
    bornes = {e["origine"] for e in fiche["bornes"]}
    assert bornes == {"reg.py:1", "vit.py:2"}
    balayes = {o for s in fiche["scans"] for o in s["origines"]} | {e["origine"] for e in fiche["index_complets"]}
    assert "reg.py:1" not in balayes and "vit.py:2" not in balayes
    assert {"tri.py:3", "filtre.py:4"} <= balayes
