# -*- coding: utf-8 -*-
"""NR — l'ingestion de veille S'ARRETE avant de saturer le disque de la base RAG.

Incident du 2026-09-01 : une campagne a 408 325 chunks a porte le WAL a 53 Go et
sature V:, jusqu'a `disk I/O error` sur TOUTE ecriture RAG. Le checkpoint entre
deux depots borne le WAL, pas la croissance de la base ni un gros depot seul.
Decision owner du 2026-09-23 : campagne par phases, ARRET a 30 Go libres.

Le garde passe AVANT chaque depot ingere, sur le volume REEL de la base (la
jonction RAG/ -> V: resolue), et l'arret rend un code DISTINCT (5) qui le dit.
Exerce par `main()` -- le chemin reel -- en `--ingest-only`.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
V = importlib.import_module("forge_veille_clone_ingest")


def _monter(monkeypatch, tmp_path, libre_go):
    cible = {"nom_dump": "x", "ordinal": 1}
    monkeypatch.setattr(V, "charger_cibles", lambda *a, **k: {"x": cible})
    monkeypatch.setattr(V, "calcul_generation_id", lambda c: "g")
    monkeypatch.setattr(V, "selectionner", lambda c, a, ordre_fige=None: ["x"])
    monkeypatch.setattr(V, "etat_dump", lambda *a: (V.READY, "ok"))
    monkeypatch.setattr(V, "DOCS", tmp_path)
    monkeypatch.setattr(V, "_libre_go", lambda chemin: libre_go)
    monkeypatch.setattr(sys, "argv", ["forge_veille_clone_ingest.py", "--ingest-only", "x"])


def test_sous_le_seuil_ARRETE_avant_toute_ingestion(monkeypatch, tmp_path, capsys):
    _monter(monkeypatch, tmp_path, libre_go=12.0)
    monkeypatch.setenv("NOKIDO_VEILLE_DISQUE_MIN_GO", "30")
    assert V.main() == 5
    out = capsys.readouterr().out
    assert "ARRET" in out and "12" in out and "30" in out


def test_le_seuil_par_defaut_est_30_go():
    assert V.seuil_disque_go() == 30.0


def test_espace_illisible_ARRETE_aussi(monkeypatch, tmp_path, capsys):
    """UNKNOWN != NO : un volume illisible n'est pas un volume libre."""
    _monter(monkeypatch, tmp_path, libre_go=None)
    assert V.main() == 5
    assert "ILLISIBLE" in capsys.readouterr().out


def test_libre_go_mesure_le_volume_reel(tmp_path):
    assert V._libre_go(tmp_path) > 0
