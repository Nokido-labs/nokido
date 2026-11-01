# -*- coding: utf-8 -*-
"""NR — le gate firehose ignore le Markdown.

Mesure du 26/10 : docs/specs/01_SCHEMA.md CITE du DDL genere et le gate rendait
85 faux avertissements « CREATE TABLE ... non referencee ». Le Markdown decrit
un schema, il ne cree aucune table : il doit etre saute AVANT lecture, sans
toucher au reste du scan.
"""

import sys
from pathlib import Path

ROOT_TEST = Path(__file__).resolve().parents[2]
for _p in (str(ROOT_TEST), str(ROOT_TEST / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_firehose_guard as guard

DDL = "CREATE TABLE x (id INT);\n"


def _isoler(monkeypatch, tmp_path):
    retention = tmp_path / "forge_log_retention.py"
    retention.write_text("", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "RETENTION", retention, raising=False)
    return tmp_path


def test_markdown_avec_ddl_ne_produit_aucun_avertissement_create_table(monkeypatch, tmp_path):
    root = _isoler(monkeypatch, tmp_path)
    (root / "01_SCHEMA.md").write_text(DDL, encoding="utf-8")
    warns = guard.scan(["01_SCHEMA.md"])
    assert isinstance(warns, list)
    assert not [w for w in warns if "CREATE TABLE" in w]


def test_meme_texte_en_py_produit_un_avertissement(monkeypatch, tmp_path):
    root = _isoler(monkeypatch, tmp_path)
    (root / "schema.py").write_text(DDL, encoding="utf-8")
    warns = guard.scan(["schema.py"])
    assert isinstance(warns, list)
    assert [w for w in warns if "CREATE TABLE x" in w]


def test_scan_rend_toujours_une_liste(monkeypatch, tmp_path):
    _isoler(monkeypatch, tmp_path)
    assert isinstance(guard.scan([]), list)
