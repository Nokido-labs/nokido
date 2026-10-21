"""NR -- le traceur d'import laisse un TEMOIN POSITIF d'armement, distinct de la trace des imports.

CI de reference e6642dcf1 (19/10, --trace-import pyarrow) : aucun sandbox/trace_import.jsonl. Sans temoin on ne
distinguait pas « pyarrow jamais importe » de « traceur jamais arme » -- une absence ne prouve rien (UNKNOWN != NO).
Le temoin vit a cote (`<sortie>.armement.jsonl`) : la trace garde son contrat (une ligne par module trace).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_trace_import as TI  # noqa: E402


def test_armer_ecrit_un_temoin_sans_toucher_la_trace(tmp_path):
    sortie = tmp_path / "trace_import.jsonl"
    finder = TI.armer(["module_jamais_importe_nr_19"], sortie)
    try:
        temoin = tmp_path / "trace_import.armement.jsonl"
        assert temoin.exists(), "aucun temoin d'armement"
        ligne = json.loads(temoin.read_text(encoding="utf-8").splitlines()[-1])
        assert ligne["modules"] == ["module_jamais_importe_nr_19"]
        assert ligne["session"] == finder.session and isinstance(ligne["pid"], int)
        assert not sortie.exists(), "la trace des imports ne doit contenir que des imports traces"
    finally:
        TI.desarmer(finder)
