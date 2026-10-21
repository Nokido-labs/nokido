# -*- coding: utf-8 -*-
"""NR (anti faux-calme) : tant que result_bytes n'est PAS mesure, le profileur ne classe pas de « resultats vides ».

Lecon du 2026-10-18 : un compte « vides lents » (ok=1, result_bytes=0, > 60 s) a fait conclure que les 21 appels
`rag` lents etaient de FAUX SUCCES. Faux : le decorateur de mesure de forge_mcp_registry appelle record() avec
payload_bytes SEULEMENT -- result_bytes vaut 0 pour TOUS les appels (80/80 appels `hub` > 10 s, 82/82 `introspect`,
qui avaient pourtant bien rendu un resultat). Un capteur qui ne mesure rien ne doit rien affirmer : UNKNOWN != NO.

Le jour ou le decorateur mesure la taille du resultat, ce garde s'eteint de lui-meme (premiere assertion).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_promcp_profiler as P  # noqa: E402


def _decorateur_mesure_la_taille() -> bool:
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8", errors="replace")
    i = src.find("forge_promcp_profiler import record as _rec")
    return i >= 0 and "result_bytes" in src[i:i + 600]


def test_sans_mesure_de_la_taille_le_profileur_ne_classe_pas_de_vides(tmp_path, monkeypatch):
    if _decorateur_mesure_la_taille():
        return                                   # la taille est mesuree : le classement redevient legitime
    db = tmp_path / "m.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE promcp_tool_metrics (id INTEGER PRIMARY KEY, tool TEXT, ts REAL, duration_ms REAL, "
              "ok INTEGER, payload_bytes INTEGER, result_bytes INTEGER)")
    c.execute("INSERT INTO promcp_tool_metrics (tool, ts, duration_ms, ok, payload_bytes, result_bytes) "
              "VALUES ('rag', ?, 70000, 1, 300, 0)", (time.time(),))
    c.commit()
    c.close()
    monkeypatch.setattr(P, "_conn", lambda: sqlite3.connect(str(db)))
    r = P.stats(since_hours=1)["tools"]["rag"]
    assert not any("vide" in k for k in r), (
        "stats classe des resultats « vides » alors que result_bytes n'est pas mesure : %s" % sorted(r))
