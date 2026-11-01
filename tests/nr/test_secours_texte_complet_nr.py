"""NR -- secours automatique : consigne en LECTURE SEULE, texte COMPLET de la tache, verdict JSON jamais integre.

Recette reelle 29/10 12 h 30 (cli_swarm_ptr_20261029_114347.json) : la tache deposee par SWARM_LANCEUR est jugee
ERR_INTERNAL « commits produits : 0 » (la consigne contenait « fichier » -> livrable attendu, sans « lecture seule ») ; le
lanceur a integre le `result_summary` (200 car. de JSON du verdict) comme SYNTHESE. tmp_path, faux tasks.db, aucun hub."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402
from tools import forge_secours_lanceur as lz  # noqa: E402

LONG = "- mecanisme A : source x.md, aucun desaccord\n" * 6


def test_consigne_de_demande_est_en_lecture_seule():
    """La consigne deposee se declare en lecture seule (le juge de l'executeur n'attend alors aucun commit)."""
    c = S._consigne_secours("C:/x y/swarm_synthese_1.json")
    assert "lecture seule" in c.lower() and "ne committe rien" in c.lower()


def test_texte_complet_lu_par_cle_primaire(tmp_path, monkeypatch):
    """Le texte integre est le champ result COMPLET (sortie claude JSON), pas le result_summary."""
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, result TEXT)")
    brut = "[effet observe] ...\n" + json.dumps({"type": "result", "result": LONG + '\n{"intent":"OK_DONE"}',
                                                  "ttft_ms": 1})
    con.execute("INSERT INTO tasks VALUES (?, ?)", ("T1", brut))
    con.commit()
    con.close()
    monkeypatch.setattr(lz, "TASKS_DB", db)
    t = lz._texte_complet("T1")
    assert t.strip() == LONG.strip()


def test_verdict_json_jamais_integre(monkeypatch, tmp_path):
    """Un texte qui n'est qu'un verdict JSON (« {"intent": ... ») n'est pas une synthese : rien ecrit."""
    res = tmp_path / "r.json"
    res.write_text(json.dumps({"task": "c", "answers": []}), encoding="utf-8")
    txt = tmp_path / "t.txt"
    txt.write_text('{"intent": "ERR_INTERNAL", "status_code": "FAILURE", "detail": "commits produits : 0"}' + " " * 150,
                   encoding="utf-8")
    assert S._integrer_secours(str(res), "t", "CLAUDE_HEADLESS", texte=str(txt)) != 0
    assert "synthesis" not in json.loads(res.read_text(encoding="utf-8"))


def test_texte_sans_substance_jamais_integre(tmp_path):
    """26 car. (« We need to fetch the file. ») : rien ecrit, meme garde que la cascade."""
    res = tmp_path / "r.json"
    res.write_text(json.dumps({"task": "c", "answers": []}), encoding="utf-8")
    txt = tmp_path / "t.txt"
    txt.write_text("We need to fetch the file.", encoding="utf-8")
    assert S._integrer_secours(str(res), "t", "CLAUDE_HEADLESS", texte=str(txt)) != 0
    assert "synthesis" not in json.loads(res.read_text(encoding="utf-8"))
