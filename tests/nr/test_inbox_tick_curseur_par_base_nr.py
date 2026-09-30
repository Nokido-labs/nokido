# -*- coding: utf-8 -*-
"""NR - le curseur de l'inbox Claude est lie a SA base (2026-09-06).

`claude_inbox_tick._inbox` lit les M2M de agt_claude par curseur de rowid (un status
'unread' pouvait etre vole par un autre drain, mesure 2026-08-28). Or un rowid n'a de
sens que dans sa base : a la bascule M2M (sandbox/m2m.switch), la base change et ses
rowids avec elle -- un curseur de l'ancienne base (ex. 25 000) applique a la nouvelle
(19 434 lignes) aurait saute en silence tout message jusqu'a ce que la nouvelle
depasse 25 000 lignes.

Contrats :
  1. un curseur memorise pour une AUTRE base est ignore : rebase sur MAX(rowid) de la
     base courante, et le curseur reecrit porte cette base ;
  2. apres rebase, le message suivant est livre et le curseur avance ;
  3. un curseur de la MEME base est honore (pas de rejeu).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for d in ("tools", "app"):
    if str(ROOT / d) not in sys.path:
        sys.path.insert(0, str(ROOT / d))

T = pytest.importorskip("claude_inbox_tick")


def _base(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE agent_messages(id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, result TEXT, status TEXT, "
              "created_at TEXT, read_at TEXT)")
    c.commit()
    return c


def _msg(c, mid, texte):
    c.execute("INSERT INTO agent_messages(id,from_agent,to_agent,method,payload,status,created_at) "
              "VALUES(?,?,?,?,?,?,?)", (mid, "agt_gemini", T.AGENT, "notify",
                                        json.dumps({"text": texte}), "unread", "2026-09-06 04:00:00"))
    c.commit()


def test_un_curseur_d_une_autre_base_est_rebase(tmp_path, monkeypatch):
    db = tmp_path / "m2m.db"
    monkeypatch.setattr(T, "DB_PATH", db)
    monkeypatch.setattr(T, "CURSOR_M2M", tmp_path / "cursor.json")
    c = _base(db)
    _msg(c, "m1", "ancien")
    # curseur herite de l'ancienne base, tres au-dessus des rowids de la nouvelle
    (tmp_path / "cursor.json").write_text(json.dumps({"last_rowid": 25000, "db": "%NOKIDO_DATA%\ancienne.db"}), encoding="utf-8")
    assert T._inbox(c) == [], "rebase : on repart du dernier message, sans rejouer l'historique"
    cj = json.loads((tmp_path / "cursor.json").read_text(encoding="utf-8"))
    assert cj["db"] == str(db) and cj["last_rowid"] == 1, cj
    _msg(c, "m2", "nouveau apres la bascule")
    lignes = T._inbox(c)   # en-tete + 1 ligne par message + pied
    assert "1 message(s)" in lignes[0] and "nouveau apres la bascule" in "\n".join(lignes), lignes
    assert json.loads((tmp_path / "cursor.json").read_text(encoding="utf-8"))["last_rowid"] == 2


def test_un_curseur_de_la_meme_base_est_honore(tmp_path, monkeypatch):
    db = tmp_path / "m2m.db"
    monkeypatch.setattr(T, "DB_PATH", db)
    monkeypatch.setattr(T, "CURSOR_M2M", tmp_path / "cursor.json")
    c = _base(db)
    _msg(c, "m1", "un"); _msg(c, "m2", "deux")
    (tmp_path / "cursor.json").write_text(json.dumps({"last_rowid": 1, "db": str(db)}), encoding="utf-8")
    lignes = T._inbox(c)
    assert "1 message(s)" in lignes[0] and "deux" in "\n".join(lignes) and "'un'" not in "\n".join(lignes), lignes
