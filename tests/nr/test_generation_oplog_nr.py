"""NR: le registre des REUSSITES (op-log de forge_generation) -- invariants PURS,
sans git ni rejeu de suite. Couvre lock_sha256 (hermeticity S14), l'empreinte des
capacites, le gain-delta et l'append-only de l'op-log. Consolider les victoires, pas
l'archeologie des pertes (2026-08-28)."""
import json
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gen_oplog", ROOT / "app" / "forge_generation.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_lock_hash_est_deterministe_et_ordre_independant():
    a = gen._lock_hash({"x": "1", "y": "2"})
    b = gen._lock_hash({"y": "2", "x": "1"})
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_empreinte_a_les_deux_compteurs():
    e = gen._empreinte_capacites()
    assert set(e) == {"modules_forge", "tests_nr"}
    assert e["modules_forge"] > 0
    assert e["tests_nr"] > 0


def test_gain_premiere_generation_signale_premiere(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "DOSSIER", tmp_path)
    g = gen._gain_vs_precedente({"modules_forge": 5, "tests_nr": 3})
    assert g["premiere"] is True
    assert g["vs"] is None
    assert g["modules_forge"] == 5
    assert g["tests_nr"] == 3


def test_oplog_est_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "DOSSIER", tmp_path)
    gen._append_oplog({"generation": "GEN-A", "gain": {"modules_forge": 1}})
    gen._append_oplog({"generation": "GEN-B", "gain": {"modules_forge": 2}})
    lignes = (tmp_path / "oplog.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["generation"] == "GEN-A"
    assert json.loads(lignes[1])["generation"] == "GEN-B"
