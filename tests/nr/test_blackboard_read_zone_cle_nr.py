"""NR : blackboard_read_zone trouve un fait par sa cle, meme hors des `limit` plus recents.

Defaut mesure le 25/10 : l'outil ignorait `key` et `limit` ; une zone de plus de 200
faits ne rendait que les plus recents et un fait ancien paraissait ABSENT.
"""
import sqlite3
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_swarm_blackboard as bb  # noqa: E402


def _base(monkeypatch, tmp_path):
    db = tmp_path / "bb.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE swarm_blackboard (zone TEXT, key TEXT, value TEXT, category TEXT,"
              " trust REAL, worker_id TEXT, updated_at REAL, PRIMARY KEY (zone, key))")
    rows = [("z", "ancien_P1_x", "vieux", None, 0.5, "w", 1.0)]
    rows += [("z", f"recent_{i}", "v", None, 0.5, "w", 100.0 + i) for i in range(5)]
    rows += [("z", "P1_a%b", "joker", None, 0.5, "w", 50.0), ("z", "P1zz", "hors", None, 0.5, "w", 60.0)]
    c.executemany("INSERT INTO swarm_blackboard VALUES (?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    monkeypatch.setattr(bb, "_DB", db)


def test_cle_exacte_hors_des_plus_recents(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    assert [r["key"] for r in bb.read_zone("z", limit=3)] == ["recent_4", "recent_3", "recent_2"]
    assert [r["value"] for r in bb.read_zone("z", limit=3, key="ancien_P1_x")] == ["vieux"]


def test_prefixe_litteral_sans_joker(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    assert [r["key"] for r in bb.read_zone("z", key_prefix="P1_")] == ["P1_a%b"]
    assert [r["key"] for r in bb.read_zone("z", key_prefix="P1_a%")] == ["P1_a%b"]


def test_le_schema_mcp_annonce_cle_prefixe_et_limit():
    src = (_R / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    bloc = src[src.index('"name": "blackboard_read_zone"'):]
    bloc = bloc[:bloc.index('"name": "blackboard_propose_fact"')]
    for champ in ('"key":', '"key_prefix":', '"limit":'):
        assert champ in bloc
