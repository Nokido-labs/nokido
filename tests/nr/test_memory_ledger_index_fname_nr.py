# -*- coding: utf-8 -*-
"""NR — les requetes PAR FICHIER du ledger memoire passent par un index.

Mesure du 2026-09-26 : le hook SessionStart `forge_memory_compactor.py --auto` etait
TUE a son delai de 8 s a CHAQUE demarrage de Claude Code (47 fois sur 47 dans les
transcripts, aucun succes). Cause : `memory_ledger` n'avait aucun index sur `fname`.
`sync()` (via `_last`) et `prune()` lancent UNE requete `WHERE fname=?` par fichier
memoire, soit 975 balayages complets d'une table qui porte les textes entiers :
1,9 s + 3,2 s au calme, davantage au demarrage quand les autres hooks tournent.

Deux degats, pas un :
  - la reingestion de MEMORY.md, placee APRES le ledger, n'etait jamais atteinte :
    le lexical servait une version perimee de l'index (4 chunks a ecrire et 9
    anciens a retirer le jour de la mesure) — le defaut repare le 2026-09-04,
    revenu par un autre chemin ;
  - `prune()` ne commit qu'a la FIN : tue avant, il repartait de zero a chaque
    demarrage et n'avancait jamais.

Ce NR traverse les VRAIES fonctions (`sync`, `prune`) et capte le SQL qu'elles
emettent, plutot que de recopier leurs requetes : une requete ajoutee demain sans
index doit le faire tomber aussi.
"""
# pylint: disable=protected-access
#   `_conn` est le seul endroit ou le schema est pose : le verifier est l'objet du NR.
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_memory_ledger as ml  # noqa: E402

_ANCIEN_SCHEMA = (
    "CREATE TABLE memory_ledger ("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, fname TEXT, name TEXT, mtype TEXT, "
    "description TEXT, sha256 TEXT, size INTEGER, event TEXT, content TEXT, "
    "prev_hash TEXT, chain_hash TEXT)"
)


def _dossier_memoire(tmp_path: Path, versions: int = 3) -> Path:
    """Trois fiches, chacune reecrite `versions` fois : prune a du contenu a vider."""
    d = tmp_path / "memory"
    d.mkdir()
    for v in range(versions):
        for nom in ("a.md", "b.md", "c.md"):
            (d / nom).write_text("---\nname: %s\n---\nversion %d\n" % (nom, v), encoding="utf-8")
        ml.sync(d)
    return d


@pytest.fixture
def sql_emis(monkeypatch):
    """Capte chaque instruction SQL emise par le module, telle qu'executee."""
    capte = []
    connect_reel = sqlite3.connect

    def espion(*a, **k):
        c = connect_reel(*a, **k)
        c.set_trace_callback(capte.append)
        return c

    monkeypatch.setattr(ml.sqlite3, "connect", espion)
    return capte


def _plans_par_fichier(db: Path, instructions) -> dict:
    requetes = {s for s in instructions if s.lstrip().upper().startswith("SELECT") and "fname=" in s}
    assert requetes, "aucune requete par fichier captee : le NR ne mesure plus rien"
    c = sqlite3.connect(str(db))
    try:
        return {q: [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + q)] for q in requetes}
    finally:
        c.close()


def test_sync_et_prune_ne_balaient_pas_la_table(tmp_path, monkeypatch, sql_emis):
    d = _dossier_memoire(tmp_path)
    db = d / "_memory_ledger.db"
    monkeypatch.setattr(ml, "DB", db)  # prune() ouvre la base par defaut
    ml.sync(d)
    ml.prune()
    balayages = {q: p for q, p in _plans_par_fichier(db, sql_emis).items()
                 if any(ligne.startswith("SCAN memory_ledger") for ligne in p)}
    assert not balayages, "requete(s) par fichier sans index : %s" % balayages


def test_un_ledger_d_avant_le_correctif_recoit_l_index(tmp_path):
    """Le ledger reel existe deja : l'index doit se poser sur lui, pas seulement sur une base neuve."""
    d = tmp_path / "memory"
    d.mkdir()
    db = d / "_memory_ledger.db"
    c = sqlite3.connect(str(db))
    c.execute(_ANCIEN_SCHEMA)
    c.commit()
    c.close()
    (d / "a.md").write_text("---\nname: a\n---\nx\n", encoding="utf-8")
    ml.sync(d)
    c = sqlite3.connect(str(db))
    try:
        index = [r[0] for r in c.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='memory_ledger'")]
    finally:
        c.close()
    assert any(s and "fname" in s for s in index), "aucun index sur fname : %s" % index


def test_la_chaine_reste_intacte_et_prune_vide_l_ancien(tmp_path, monkeypatch):
    """L'index ne touche pas aux lignes : chaine verifiee, et prune garde 2 versions par fichier."""
    d = _dossier_memoire(tmp_path, versions=4)
    monkeypatch.setattr(ml, "DB", d / "_memory_ledger.db")
    r = ml.prune()
    assert r["pruned_content"] == 3 * 2, r  # 4 versions - 2 gardees, pour 3 fichiers
    v = ml.verify()
    assert v["ok"] and v["entries"] == 12, v
