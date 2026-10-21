"""NR 18/10 -- lot 1 de migration des ecrivains RAG NUS de app/ (decision owner C_06 : cliquet + migrer app/).

Quatre modules non critiques (8 instructions INSERT nues mesurees par le cliquet eb4f52c9f) doivent ecrire par le
chemin gouverne : `forge_db_path.write_retry(lambda c: ...)` (et `ecrire_chunk` pour rag_chunks, id canonique).
Ce test reutilise l'instrument du cliquet (meme definition de « nu ») ; au GREEN, le plafond app du cliquet descend
de 40 a 32 dans le meme commit.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOT1 = ("app/forge_conversation_logger.py", "app/forge_git_historian.py",
        "app/forge_skill_curator.py", "app/forge_extern_patterns.py")


def _cliquet():
    spec = importlib.util.spec_from_file_location(
        "cliquet_ecrivains_nr", ROOT / "tests" / "nr" / "test_cliquet_ecrivains_rag_nus_nr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_lot1_n_a_plus_aucun_ecrivain_nu():
    nus = [s for s in _cliquet()._nus("app") if s.rsplit(":", 1)[0] in LOT1]
    assert not nus, "ecrivain(s) RAG encore nu(s) dans le lot 1 : %s" % nus


def test_le_plafond_du_cliquet_suit_la_migration():
    assert _cliquet().PLAFOND["app"] <= 32, "lot 1 migre : abaisser PLAFOND['app'] a 32 dans le cliquet"
