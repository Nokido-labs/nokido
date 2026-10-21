"""NR 18/10 -- le guet des jobs lisait « rc=0 sans ligne de bilan » sur les 3 ingestions GitHub du jour alors que la
sortie de tools/forge_ingest_github_repo.py porte son bilan en JSON (`"index": {"inserted": 1652, ...}`). Un bilan
ecrit et non lu vaut un silence : le guet doit le reconnaitre (DECLARE avec le compte), et 0 insere = VIDE.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_job_watch_cli as guet  # noqa: E402

SORTIE = """{
  "repo": "nimbalyst/nimbalyst",
  "index": {
    "chunks": 1652,
    "inserted": 1652,
    "skipped_dedup": 0
  }
}"""


def test_le_bilan_json_de_l_ingestion_est_lu():
    b = guet.lire_bilan(SORTIE, "0")
    assert b["etat"] == "DECLARE" and b.get("chunks") == 1652, b


def test_zero_insere_est_vide():
    b = guet.lire_bilan(SORTIE.replace('"inserted": 1652', '"inserted": 0'), "0")
    assert b["etat"] == "VIDE", b
