# -*- coding: utf-8 -*-
"""NR — l'instrument AVANT/APRES du switch journaux compte sur une FENETRE, en trois etats.

Contrat owner du 2026-09-19 : « on retire des ecrivains du verrou RAG » ; le
critere est que la grosse base CESSE DE RECEVOIR. Mesure exigee : frequence
d'ecriture par COMPTAGE SUR FENETRE, jamais une moyenne all-time.
  * l'ecart de MAX(rowid) entre deux instantanes compte les insertions ;
  * une table ABSENTE ou une base ILLISIBLE ne vaut JAMAIS 0 (UNKNOWN != NO) ;
  * ce qui n'est pas mesure est DECLARE, pas tu.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
M = importlib.import_module("forge_mesure_journaux")


def _base(p, tables=("token_usage", "inspector_log", "conversation_log")):
    c = sqlite3.connect(str(p))
    for t in tables:
        c.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY, v TEXT)" % t)
    c.commit()
    return c


def test_ecart_de_fenetre_compte_les_insertions(tmp_path):
    p = tmp_path / "rag.db"
    c = _base(p)
    avant = M.compter(str(p))
    for _ in range(7):
        c.execute("INSERT INTO token_usage (v) VALUES ('x')")
    c.execute("INSERT INTO inspector_log (v) VALUES ('y')")
    c.commit()
    apres = M.compter(str(p))
    d = M.ecarts(avant, apres)
    assert d["token_usage"] == 7 and d["inspector_log"] == 1 and d["conversation_log"] == 0


def test_table_absente_n_est_pas_zero(tmp_path):
    p = tmp_path / "rag.db"
    _base(p, tables=("token_usage",))
    n = M.compter(str(p))
    assert n["inspector_log"] == "ABSENTE"
    assert M.ecarts(n, n)["inspector_log"] == "ABSENTE"


def test_base_illisible_n_est_pas_zero(tmp_path):
    n = M.compter(str(tmp_path / "inexistante.db"))
    assert all(v == "ILLISIBLE" for v in n.values()), n


def test_la_mesure_n_ecrit_rien_dans_la_base(tmp_path):
    """Un instrument qui ecrit dans la base qu'il mesure fausse sa propre mesure."""
    p = tmp_path / "rag.db"
    _base(p).close()
    avant = p.stat().st_mtime_ns
    M.compter(str(p))
    assert p.stat().st_mtime_ns == avant


def test_le_point_d_entree_CLI_produit_le_rapport(tmp_path, monkeypatch):
    """Chemin reel : `main(--label --fenetre)`, chemins demandes a l'accesseur (simule)."""
    p = tmp_path / "rag.db"
    _base(p).close()
    monkeypatch.setattr(M, "_chemins_reels", lambda: (str(p), {}, {"interrupteur_pose": False}))
    monkeypatch.setattr(M, "ROOT", tmp_path)
    assert M.main(["--label", "CLI", "--fenetre", "0"]) == 0
    assert list((tmp_path / "sandbox").glob("mesure_journaux_CLI_*.json"))


def test_le_rapport_declare_ce_qu_il_ne_mesure_pas(tmp_path):
    p = tmp_path / "rag.db"
    _base(p).close()
    r = M.fenetre(0, label="TEST", base_rag=str(p), cibles={}, sortie=tmp_path / "o.json")
    assert r["label"] == "TEST" and "non_mesure" in r and r["non_mesure"]
    assert (tmp_path / "o.json").exists()
