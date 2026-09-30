# -*- coding: utf-8 -*-
"""NR — le detecteur d'ingestion lit TOUTES les surfaces de clone, pas une seule.

Defaut mesure le 2026-09-05 : `_ingere_clone` n'interrogeait que `sdk_gitingest`
et ne reconnaissait que les 12 entrees du dict `REPOS`. Consequence, `BerriAI/litellm`
etait imprime **ABSENT** dans le rapport de retard alors que **92 682 chunks** de ce
depot etaient en base sous le prefixe `berriai_litellm`. Un rapport de retard qui
declare absent ce qui est present envoie re-ingerer des depots deja ingeres : c'est
la meme famille que « conclure d'une source qui se tait », mais en pire, parce que
l'instrument avait bien regarde — au mauvais endroit.

Le test est HERMETIQUE : base SQLite en memoire, aucune lecture de la base de prod.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

mod = pytest.importorskip("forge_veille_backlog_github")


def _base(lignes):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (source TEXT, domain TEXT)")
    conn.executemany("INSERT INTO rag_chunks (source, domain) VALUES (?, ?)", lignes)
    return conn


def test_les_deux_domaines_de_clone_sont_lus():
    """`veille_code` porte la meme convention que `sdk_gitingest` — mesure du 05/09."""
    assert "sdk_gitingest" in mod.DOMAINES_CLONE
    assert "veille_code" in mod.DOMAINES_CLONE


def test_depot_present_dans_veille_code_n_est_pas_absent():
    """Le cas exact du defaut : present sous `veille_code`, declare ABSENT."""
    conn = _base([("berriai_litellm/a.py", "veille_code"),
                  ("berriai_litellm/b.py", "veille_code")])
    res = mod._ingere_clone(conn, ["BerriAI/litellm"])
    conn.close()
    assert "berriai/litellm" in res, "depot present en base rendu ABSENT"
    n, voie = res["berriai/litellm"]
    assert n == 2
    assert voie == "structure"


def test_correspondance_par_nom_seul_reste_indeterminee():
    """Sans l'owner, deux depots homonymes sont indiscernables : pas de verdict INGERE."""
    conn = _base([("skills/a.md", "sdk_gitingest")])
    res = mod._ingere_clone(conn, ["openclaw/skills"])
    conn.close()
    assert res["openclaw/skills"][1] == "ambigu"


def test_la_table_repos_reste_la_voie_forte():
    """Un nom local sans rapport avec le nom GitHub ne se retrouve QUE par REPOS."""
    conn = _base([("scalesim/x.py", "sdk_gitingest")])
    res = mod._ingere_clone(conn, ["scalesim-project/SCALE-Sim"])
    conn.close()
    assert res.get("scalesim-project/scale-sim", (0, ""))[1] == "table"


def test_un_depot_absent_le_reste():
    """Le detecteur elargi ne doit pas fabriquer de presence : pas de faux positif."""
    conn = _base([("berriai_litellm/a.py", "veille_code")])
    res = mod._ingere_clone(conn, ["HeyPuter/firefox"])
    conn.close()
    assert "heyputer/firefox" not in res
