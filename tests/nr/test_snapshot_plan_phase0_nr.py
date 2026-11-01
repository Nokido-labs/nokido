"""NR -- `forge_snapshot.plan_phase0` : simulation pure, aucun effet, NO-GO dit.

Bases temporaires seulement ; aucune base vivante n'est ouverte.
"""
import collections
import os
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_snapshot as fs  # noqa: E402


def _base(chemin: Path, n=50):
    con = sqlite3.connect(str(chemin))
    con.execute("create table t(a)")
    con.executemany("insert into t values(?)", [("x" * 100,)] * n)
    con.commit()
    con.close()


def _src(chemin):
    return dict(a=dict(chemin=str(chemin), alias=[]))


def _instantane(dossier: Path):
    return sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in dossier.rglob("*"))


def test_go_sans_rien_ecrire(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "E").mkdir()
    _base(tmp_path / "src" / "a.db")
    avant = _instantane(tmp_path)
    plan = fs.plan_phase0(_src(tmp_path / "src" / "a.db"), cible=str(tmp_path / "E"))
    assert plan["verdict"] == "GO" and plan["ecrit"] is False
    assert plan["sources"][0]["octets"] == (tmp_path / "src" / "a.db").stat().st_size
    assert plan["libre_octets"] > plan["requis_octets"] > 0
    assert plan["duree_estimee_s"] is not None
    assert "backup" in plan["methode"] and "mode=ro" in plan["methode"]
    assert any("empreinte" in v for v in plan["verification"])
    assert _instantane(tmp_path) == avant  # ni -wal/-shm, ni dossier cree


def test_cible_absente_no_go_et_non_creee(tmp_path):
    _base(tmp_path / "a.db")
    cible = tmp_path / "E_absent"
    plan = fs.plan_phase0(_src(tmp_path / "a.db"), cible=str(cible))
    assert plan["verdict"] == "NO-GO"
    assert plan["libre_octets"] is None
    assert any("cible absente" in r for r in plan["raisons"])
    assert not cible.exists()


def test_espace_insuffisant_no_go(tmp_path, monkeypatch):
    _base(tmp_path / "a.db")
    (tmp_path / "E").mkdir()
    du = collections.namedtuple("du", "total used free")
    monkeypatch.setattr(fs.shutil, "disk_usage", lambda p: du(10, 10, 1))
    plan = fs.plan_phase0(_src(tmp_path / "a.db"), cible=str(tmp_path / "E"))
    assert plan["verdict"] == "NO-GO"
    assert any("insuffisant" in r for r in plan["raisons"])


def test_source_absente_no_go_jamais_zero(tmp_path):
    (tmp_path / "E").mkdir()
    plan = fs.plan_phase0(_src(tmp_path / "nope.db"), cible=str(tmp_path / "E"))
    assert plan["verdict"] == "NO-GO"
    assert plan["sources"][0]["octets"] is None


def test_aucune_ouverture_de_base(tmp_path, monkeypatch):
    _base(tmp_path / "a.db")
    (tmp_path / "E").mkdir()

    def interdit(*a, **k):
        raise AssertionError("plan_phase0 ne doit ouvrir aucune base")

    monkeypatch.setattr(fs.sqlite3, "connect", interdit)
    plan = fs.plan_phase0(_src(tmp_path / "a.db"), cible=str(tmp_path / "E"))
    assert plan["verdict"] == "GO"


def test_sources_via_forge_db_path_dedoublonnees(tmp_path, monkeypatch):
    _base(tmp_path / "rag.db")
    monkeypatch.setenv("LAFORGE_DB", str(tmp_path / "rag.db"))
    src = fs.phase0_sources()
    assert src["rag"]["chemin"] == os.path.realpath(str(tmp_path / "rag.db"))
    chemins = [v["chemin"] for v in src.values()]
    assert len(chemins) == len(set(chemins))
